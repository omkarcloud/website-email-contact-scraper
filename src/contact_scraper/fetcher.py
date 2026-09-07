# Page fetching: curl_cffi (Chrome-impersonating TLS with keep-alive) first,
# pooled patchright Chrome fallback.
#
# Both fetchers return the same result shape so the crawler can treat them
# interchangeably: {"final_url", "status", "html", "mode_used", "headers", "error"}.
# error is None on success; on failure html == "" and error is a short string.
# headers is {} when the transport exposes none. needs_browser() is the
# escalation heuristic (plan section 6); the crawler makes csr/blocked mode sticky
# for the rest of the domain once it fires.
#
# Browsers come from two chrome_manager pools:
#   "contact"      headed patchright Chrome, full fidelity — challenge-blocked
#                  sites. The challenge cookies earned by the first full page
#                  load live on the leased driver; blocked-mode reuses them
#                  for in-page fetches (batched via get_many in
#                  fetch_pages_light).
#   "contact-csr"  headless patchright Chrome with image/media/font/stylesheet
#                  requests aborted — client-side-rendered sites, where there
#                  is no anti-bot to fool and subresources are dead weight.
# Each crawl leases at most ONE driver via BrowserSession on its first
# csr/blocked-mode fetch and holds it until the crawl ends. The pool is pinned by
# the first escalation reason; a challenge seen while on the CSR pool upgrades
# (once) to the headed pool.

import functools
import os
import re
import socket
import threading
from urllib.parse import urlsplit

from . import chrome_manager
from .html_text import html_to_soup, soup_to_text

POOL_KEY = 'contact'
POOL_KEY_CSR = 'contact-csr'
# Bounded wait for a pooled Chrome: when both drivers are held by other
# crawls, degrading to a fetch error beats queueing behind them for minutes.
BROWSER_ACQUIRE_TIMEOUT = 180

REQUESTS_TIMEOUT = 15
MAX_HTML_BYTES = 3_000_000

# curl_cffi impersonation target: resolves to the newest Chrome profile the
# installed curl_cffi ships. The Referer default mirrors what the previous
# botasaurus_requests client sent on every request.
IMPERSONATE = 'chrome'
DEFAULT_HEADERS = {'Referer': 'https://www.google.com/'}

BLOCK_STATUSES = {403, 429, 503}

# Challenge interstitials identify themselves through markup the vendors emit
# with exact casing - searched in the RAW html, case-sensitive. Lowercased
# vendor-name matching ('perimeterx', 'just a moment') misfired on pages that
# merely TALK about bot protection, e.g. scraping-tool docs and blogs.
CHALLENGE_MARKERS = (
    '<title>Just a moment...',        # Cloudflare interstitial
    'Please verify you are a human',  # PerimeterX
    '_Incapsula_',
    'sec-if-cpt-container',           # Akamai Bot Manager (served with 200)
    "var dd={'rt':",                  # DataDome interstitial (seen on g2.com)
)

# App-shell mounts: a tiny html body with only one of these and almost no links
# means the real content is rendered client-side.
APP_SHELL_MARKERS = (
    'id="root"', "id='root'", 'id="__next"', "id='__next'",
    'id="app"', "id='app'", 'data-reactroot', 'ng-app',
)

# "Enable JavaScript" noscript banners are the CSR frameworks' own admission
# that the real content renders client-side.
_NOSCRIPT_CSR_RE = re.compile(
    r"(enable\s+javascript|javascript\s+is\s+(required|disabled)|"
    r"you need to enable javascript)", re.I,
)

# Driver-is-dead markers in playwright exception text: these poison the
# session (the driver is destroyed on release); any other navigation error
# leaves the driver in the pool.
_FATAL_DRIVER_RE = re.compile(
    r'(target closed|browser has been closed|'
    r'context or browser has been closed|crashed)', re.IGNORECASE)


def _result(final_url, status, html, mode_used, error=None, headers=None):
    return {'final_url': final_url, 'status': status, 'html': html,
            'mode_used': mode_used, 'headers': headers or {}, 'error': error}


@functools.lru_cache(maxsize=2048)
def _resolve_host(host):
    # Cached for the process lifetime, negative results included - fine for
    # scraper workers, add a TTL before reusing this in a long-lived server.
    try:
        socket.getaddrinfo(host, None)
    except OSError:
        return f'dns: no such host: {host}'
    return None


def _dns_error(url):
    # Cheap cached pre-check: dead hosts are rejected before any transport
    # sees them, and repeated lookups across a crawl's pages are free.
    host = urlsplit(url).hostname
    if not host:
        return 'invalid url: no host'
    return _resolve_host(host)


def _guard_html(response_text, content_type):
    # Non-HTML payloads are blanked (nothing extractable); huge ones truncated.
    if content_type:
        ct = content_type.lower()
        if 'text/html' not in ct and 'application/xhtml' not in ct:
            return '', 'non-html content-type: ' + ct.split(';')[0].strip()
    return response_text[:MAX_HTML_BYTES], None


def _curl_error_string(e, url):
    # Stable, greppable prefixes for log triage; <= 200 chars.
    host = urlsplit(url).hostname or url
    code = getattr(e, 'code', None)
    try:
        code = int(code)
    except (TypeError, ValueError):
        code = None
    if code == 28:
        return f'timeout: no response in {REQUESTS_TIMEOUT}s'
    if code == 6:
        return f'dns: no such host: {host}'
    if code == 7:
        return f'connection refused: {host}'
    if code in (35, 51, 58, 60):
        return f'ssl: {str(e)[:160]}'
    if code == 47:
        return 'too many redirects'
    if code in (52, 56):
        return 'connection reset'
    if code is not None:
        return f'curl{code}: {str(e)[:160]}'
    return f'{type(e).__name__}: {e}'[:200]


def _new_session():
    from curl_cffi import requests as curl_requests
    return curl_requests.Session(impersonate=IMPERSONATE,
                                 headers=dict(DEFAULT_HEADERS))


class RequestsSessionBundle:
    """curl_cffi sessions for ONE crawl, one per calling thread (a curl handle
    must not be used concurrently; wave fetches for one crawl run on multiple
    shared-executor threads). Keyed by thread ident so keep-alive holds within
    the crawl while cookies never leak across crawls — close_all() runs when
    the crawl ends."""

    def __init__(self):
        self._sessions = {}
        self._lock = threading.Lock()

    def session(self):
        ident = threading.get_ident()
        sess = self._sessions.get(ident)
        if sess is None:
            sess = _new_session()
            with self._lock:
                self._sessions[ident] = sess
        return sess

    def close_all(self):
        with self._lock:
            sessions, self._sessions = list(self._sessions.values()), {}
        for sess in sessions:
            try:
                sess.close()
            except Exception:
                pass


def fetch_page_requests(url, http=None):
    # http is the crawl's RequestsSessionBundle; without one (direct callers,
    # __main__ probes) a throwaway session is built and closed per call.
    sess = http.session() if http is not None else _new_session()
    try:
        try:
            response = sess.get(url, timeout=REQUESTS_TIMEOUT, allow_redirects=True)
        except Exception as e:
            return _result(url, None, '', 'requests', _curl_error_string(e, url))
        html, error = _guard_html(response.text or '',
                                  response.headers.get('Content-Type'))
        return _result(str(response.url) or url, response.status_code, html,
                       'requests', error, headers=dict(response.headers))
    finally:
        if http is None:
            try:
                sess.close()
            except Exception:
                pass


def _browser_light_get(driver, url):
    # In-page window.fetch on the leased patchright driver: reuses whatever
    # challenge cookies the full page load earned, without navigation or
    # settle waits. Same-origin only - cross-origin fetches raise (CORS) and
    # fall back. Returns None on transport failure so the caller falls back to
    # navigation (FetchResponse.ok is False only for transport failures, never
    # for HTTP 4xx/5xx - those are real results and pass through).
    try:
        resp = driver.get(url, timeout_ms=REQUESTS_TIMEOUT * 1000)
    except TimeoutError:
        raise  # call() ceiling: page wedged, driver unusable
    except Exception:
        return None
    if not resp.ok:
        return None
    html, error = _guard_html(resp.text or '', resp.headers.get('content-type'))
    return _result(resp.url or url, resp.status_code, html, 'blocked',
                   error, headers=resp.headers)


def _fetch_page_browser(driver, url, light, is_blocked=False):
    if light:
        result = _browser_light_get(driver, url)
        if result is not None:
            return result
        # In-page fetch failed (cross-origin redirect, network error): fall
        # back to real navigation for this one page.
    try:
        # The driver picks the settle strategy from the mode: blocked polls
        # for the challenge markers to clear, csr extends the wait only while
        # the page is still an unrendered app shell.
        nav = driver.nav(url, mode='blocked' if is_blocked else 'csr',
                         challenge_markers=CHALLENGE_MARKERS)
    except TimeoutError:
        # call() ceiling: the page op wedged and the owner thread is stuck -
        # the driver is unusable. Propagate so the session is poisoned.
        raise
    except Exception as e:
        if _FATAL_DRIVER_RE.search(str(e)):
            raise  # dead Chrome - poison the session
        # Ordinary navigation failure (net::ERR_*, goto timeout): the driver
        # is healthy - degrade to a fetch error without burning it.
        return _result(url, None, '', 'csr', f'csr nav: {str(e)[:160]}')
    final_url = nav['url'] or url
    # Chrome error pages render as chrome-error://chromewebdata/ - that is a
    # failed fetch, not a page (its "domain" would poison the crawl).
    if final_url.startswith(('chrome-error://', 'about:', 'data:')):
        return _result(url, None, '', 'csr', f'csr error page: {final_url[:80]}')
    # Real HTTP status when playwright exposes one (used by needs_browser);
    # same-document navigations expose none and count as 200.
    status = nav['status'] if nav['status'] is not None else 200
    return _result(final_url, status, (nav['html'] or '')[:MAX_HTML_BYTES],
                   'csr', None, headers=nav.get('headers') or {})


class BrowserSession:
    """One crawl's pooled patchright Chrome. Nothing is leased until the
    crawl's first csr/blocked-mode fetch (pure-requests crawls never touch a
    pool); the driver is then held until close() so its challenge cookies
    keep serving blocked-mode fetches. The pool is pinned by the first
    escalation reason: 'csr' -> the headless resource-blocked "contact-csr"
    renderer, anything else -> the headed stealth "contact" pool. A challenge
    seen while on the CSR pool upgrades (once) to the headed pool; the
    reverse never happens - a headed driver renders CSR fine, only the sticky
    crawl mode flips. A navigation exception marks the session dirty: close()
    destroys that driver instead of returning it, so a crashed Chrome can
    never re-enter the ready pool (a background warmer replaces it)."""

    def __init__(self):
        self.driver = None
        self.dirty = False
        self.pool_key = None
        self._upgraded = False

    def ensure_pool(self, reason):
        # Pin on the first escalation only; never re-point while a driver is
        # held (a stealth driver must not be downgraded mid-crawl).
        if self.driver is None and self.pool_key is None:
            self.pool_key = POOL_KEY_CSR if reason == 'csr' else POOL_KEY

    def upgrade_for_block(self):
        """Mixed signals, blocked wins: a challenge seen on the CSR pool swaps
        to the headed stealth pool (once per crawl). Returns True when the
        caller should refetch on the new pool."""
        if self._upgraded or self.pool_key != POOL_KEY_CSR:
            return False
        self._upgraded = True
        if self.driver is not None:
            chrome_manager.release(POOL_KEY_CSR, self.driver, ok=not self.dirty)
            self.driver = None
            self.dirty = False
        self.pool_key = POOL_KEY
        return True

    def lease(self):
        if self.driver is None:
            self.driver = chrome_manager.acquire(self.pool_key or POOL_KEY,
                                                 timeout=BROWSER_ACQUIRE_TIMEOUT)
        return self.driver

    def close(self):
        if self.driver is not None:
            chrome_manager.release(self.pool_key or POOL_KEY, self.driver,
                                   ok=not self.dirty)
            self.driver = None


def fetch_pages_light(urls, session):
    """Wave of same-site in-page fetches on the crawl's ONE leased driver:
    a single get_many marshals every URL into one Promise.all inside the page
    (the pattern g2 uses), so challenge cookies serve all of them at once.
    Per-URL transport failures fall back to sequential full navigation on the
    same driver. Returns result dicts in input order."""
    try:
        driver = session.lease()
    except chrome_manager.ChromeUnavailable as e:
        err = f'browser busy: {e}'[:200]
        return [_result(u, None, '', 'csr', err) for u in urls]
    try:
        responses = driver.get_many(urls, timeout_ms=REQUESTS_TIMEOUT * 1000)
    except Exception as e:
        session.dirty = True
        err = f'browser: {type(e).__name__}: {e}'[:200]
        return [_result(u, None, '', 'csr', err) for u in urls]
    out = []
    for url, resp in zip(urls, responses):
        if resp.ok:
            html, error = _guard_html(resp.text or '',
                                      resp.headers.get('content-type'))
            out.append(_result(resp.url or url, resp.status_code, html,
                               'blocked', error, headers=resp.headers))
            continue
        try:
            # Transport failure (CORS, network): navigation fallback, same
            # semantics as the single-URL blocked path.
            out.append(_fetch_page_browser(driver, url, light=False,
                                           is_blocked=True))
        except Exception as e:
            session.dirty = True
            out.append(_result(url, None, '', 'csr',
                               f'csr: {type(e).__name__}: {e}'[:200]))
    return out


def fetch_page(url, mode='requests', session=None, http=None, blocked=False):
    # blocked=True asks a full-navigation (csr-mode) fetch to use the blocked
    # settle strategy anyway - the crawler's escalation refetch of a
    # challenged page navigates for real to earn the challenge cookies, but
    # still needs the interstitial-clear wait.
    error = _dns_error(url)
    if error:
        return _result(url, None, '', mode, error)
    if mode in ('csr', 'blocked'):
        if session is None:
            return _result(url, None, '', 'csr', 'browser unavailable: no session')
        try:
            driver = session.lease()
        except chrome_manager.ChromeUnavailable as e:
            return _result(url, None, '', 'csr', f'browser busy: {e}'[:200])
        try:
            result = _fetch_page_browser(driver, url, light=mode == 'blocked',
                                         is_blocked=blocked or mode == 'blocked')
        except Exception as e:
            # Wedged page or dead Chrome: degrade to a fetch error, not a
            # crawl abort, and poison the session - the pool warms a
            # replacement in the background and this crawl keeps its driver
            # until close().
            session.dirty = True
            return _result(url, None, '', 'csr',
                           f'csr: {type(e).__name__}: {e}'[:200])
    else:
        result = fetch_page_requests(url, http=http)
    return result or _result(url, None, '', mode, 'fetch layer returned None')


def needs_browser(result, text=None, soup=None):
    # Returns the escalation reason (truthy) or False. 'blocked' means the
    # browser's cookies unlock the site, so in-page fetches suffice afterwards;
    # 'csr' means the content is rendered client-side and every page needs a
    # real page load. Pass the already-built page soup/text to skip re-parsing;
    # otherwise the html is parsed at most once, shared by both CSR checks.
    if result.get('status') in BLOCK_STATUSES:
        return 'blocked'
    html = result.get('html') or ''
    if any(marker in html for marker in CHALLENGE_MARKERS):
        return 'blocked'
    lowered = html.lower()
    if (len(html) < 5000
            and any(marker in lowered for marker in APP_SHELL_MARKERS)
            and lowered.count('<a ') < 5):
        return 'csr'
    if '<noscript' in lowered:
        if soup is None:
            soup = html_to_soup(html)
        for ns in soup.find_all('noscript'):
            if _NOSCRIPT_CSR_RE.search(ns.get_text(' ', strip=True) or ''):
                # "Enable JavaScript" banners ship as boilerplate on plenty
                # of fully server-rendered sites (Drupal puts one on every
                # page): only trust the banner when the page has no real
                # content to go with it.
                if text is None:
                    text = soup_to_text(soup)
                if len(text) < 200:
                    return 'csr'
                break
    # Text-empty pages: >20k of markup with no text is the classic hydrated
    # SPA. Smaller script-driven shells (AEM prerender apps like shell.com's
    # 9KB homepage) dodge that floor - catch them by having scripts but
    # almost no links; the size floor alone stays for everything else so tiny
    # static pages (example.com: 559 bytes, ~170 chars) never escalate.
    if len(html) > 20000 or ('<script' in lowered and lowered.count('<a ') < 3):
        if text is None:
            if soup is None:
                soup = html_to_soup(html)
            text = soup_to_text(soup)
        if len(text) < 200:
            return 'csr'
    return False


if __name__ == '__main__':
    # Manual live check (not part of the test suite): one static site via
    # curl_cffi, one SPA that should trip needs_browser, then the browser path
    # on the CSR pool. Run as:  python3 -m src.contact_scraper.fetcher
    # (Chrome is built lazily by the pool on the first browser-mode fetch.)
    static = fetch_page('https://example.com')
    print('static:', static['status'], len(static['html']), 'needs_browser =', needs_browser(static))

    spa = fetch_page('https://react.dev')
    reason = needs_browser(spa)
    print('spa (requests):', spa['status'], len(spa['html']), 'needs_browser =', reason)
    if reason:
        session = BrowserSession()
        session.ensure_pool(reason)
        try:
            rendered = fetch_page(spa['final_url'], mode='csr', session=session)
            pool_used = session.pool_key
        finally:
            session.close()
        print(f'spa (csr, pool={pool_used}):', rendered['status'],
              len(rendered['html']),
              'text chars =', len(soup_to_text(html_to_soup(rendered['html']))))
