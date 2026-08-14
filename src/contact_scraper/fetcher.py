# Page fetching: botasaurus @request first, pooled-Chrome fallback.
#
# Both fetchers return the same result shape so the crawler can treat them
# interchangeably: {"final_url", "status", "html", "mode_used", "headers", "error"}.
# error is None on success; on failure html == "" and error is a short string.
# headers is {} when the transport exposes none (full browser navigation).
# needs_browser() is the escalation heuristic (plan section 6); the crawler
# makes browser mode sticky for the rest of the domain once it fires.
#
# The browser comes from the chrome_manager "contact" pool. Chrome is built
# LAZILY — no driver exists until the first browser-mode fetch — and pooled
# drivers are reused across crawls afterwards: each crawl leases at most one
# driver via BrowserSession on its first browser-mode fetch and holds it until
# the crawl ends, because the challenge cookies earned by the first full page
# load live on that driver (browser_light reuses them for in-page fetches).

import functools
import os
import re
import socket
from urllib.parse import urlsplit

from botasaurus.request import request, Request

from . import chrome_manager
from .html_text import html_to_soup, soup_to_text

POOL_KEY = 'contact'
# Bounded wait for a pooled Chrome: when both drivers are held by other
# crawls, degrading to a fetch error beats queueing behind them for minutes.
BROWSER_ACQUIRE_TIMEOUT = 60

REQUESTS_TIMEOUT = int(os.environ.get('CONTACT_SCRAPER_REQUESTS_TIMEOUT', 15))
MAX_HTML_BYTES = 3_000_000

BLOCK_STATUSES = {403, 429, 503}

# Challenge interstitials identify themselves through markup the vendors emit
# with exact casing - searched in the RAW html, case-sensitive. Lowercased
# vendor-name matching ('perimeterx', 'just a moment') misfired on pages that
# merely TALK about bot protection, e.g. scraping-tool docs and blogs.
CHALLENGE_MARKERS = (
    '<title>Just a moment...',        # Cloudflare interstitial
    'Please verify you are a human',  # PerimeterX
    '_Incapsula_',
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

CONSENT_SELECTOR = ('#onetrust-accept-btn-handler, '
                    '[id*=accept i][class*=cookie i], '
                    'button[class*=consent i]')


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
    # botasaurus_requests retries "no such host" errors FOREVER (20s sleeps in
    # retry_on_network_error), so a dead host must be rejected before the
    # request layer ever sees it.
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


@request(
    max_retry=1,
    output=None,
    close_on_crash=True,
    create_error_logs=False,
    raise_exception=False,
)
def fetch_page_requests(request: Request, url):
    try:
        response = request.get(url, timeout=REQUESTS_TIMEOUT, allow_redirects=True)
    except Exception as e:
        return _result(url, None, '', 'requests', f'{type(e).__name__}: {e}'[:200])
    html, error = _guard_html(response.text or '', response.headers.get('Content-Type'))
    return _result(str(response.url), response.status_code, html, 'requests', error,
                   headers=dict(response.headers))


def _browser_light_get(driver, url):
    # In-page window.fetch (driver.requests) reuses whatever challenge cookies
    # the full page load earned, without navigation or settle sleeps.
    # Same-origin only: the driver must already be parked on a page of the
    # crawled site - cross-origin fetches raise (CORS) and fall back.
    # Returns None on any failure so the caller falls back to navigation.
    try:
        response = driver.requests.get(url, timeout=REQUESTS_TIMEOUT)
    except Exception:
        return None
    html, error = _guard_html(response.text or '',
                              response.headers.get('Content-Type'))
    return _result(str(response.url), response.status_code, html,
                   'browser_light', error, headers=dict(response.headers))


def _fetch_page_browser(driver, url, light):
    if light:
        result = _browser_light_get(driver, url)
        if result is not None:
            return result
        # In-page fetch failed (cross-origin redirect, network error): fall
        # back to real navigation for this one page.
    driver.get(url)
    driver.sleep(2)  # settle: let client-side rendering finish
    html = driver.page_html or ''
    # try:
    #     # One cookie-consent dismissal attempt, then re-read the DOM.
    #     driver.click(CONSENT_SELECTOR, wait=2)
    #     driver.sleep(1)
    #     html = driver.page_html or html
    # except Exception:
    #     pass
    final_url = driver.current_url or url
    # Chrome error pages render as chrome-error://chromewebdata/ - that is a
    # failed fetch, not a page (its "domain" would poison the crawl).
    if final_url.startswith(('chrome-error://', 'about:', 'data:')):
        return _result(url, None, '', 'browser', f'browser error page: {final_url[:80]}')
    # No HTTP status is exposed by the driver; a rendered page counts as 200.
    return _result(final_url, 200, html[:MAX_HTML_BYTES], 'browser', None)


class BrowserSession:
    """One crawl's pooled Chrome. Nothing is leased until the crawl's first
    browser-mode fetch (pure-requests crawls never touch the pool — Chrome is
    built lazily by the pool's background warmer on the first lease, then
    reused by later crawls); the driver is then held until close() so its
    challenge cookies keep serving browser_light fetches. A navigation
    exception marks the session dirty: close() destroys that driver instead
    of returning it, so a crashed Chrome can never re-enter the ready pool
    (the next lease warms a replacement)."""

    def __init__(self):
        self.driver = None
        self.dirty = False

    def lease(self):
        if self.driver is None:
            self.driver = chrome_manager.acquire(POOL_KEY,
                                                 timeout=BROWSER_ACQUIRE_TIMEOUT)
        return self.driver

    def close(self):
        if self.driver is not None:
            chrome_manager.release(POOL_KEY, self.driver, ok=not self.dirty)
            self.driver = None


def fetch_page(url, mode='requests', session=None):
    error = _dns_error(url)
    if error:
        return _result(url, None, '', mode, error)
    if mode in ('browser', 'browser_light'):
        if session is None:
            return _result(url, None, '', 'browser', 'browser unavailable: no session')
        try:
            driver = session.lease()
        except chrome_manager.ChromeUnavailable as e:
            return _result(url, None, '', 'browser', f'browser busy: {e}'[:200])
        try:
            result = _fetch_page_browser(driver, url, light=mode == 'browser_light')
        except Exception as e:
            # Nav failure must degrade to a fetch error, not abort the crawl
            # and discard fetched pages. It may also mean the Chrome died, so
            # poison the session — the pool warms a replacement in the
            # background and this crawl keeps its driver until close().
            session.dirty = True
            return _result(url, None, '', 'browser',
                           f'browser: {type(e).__name__}: {e}'[:200])
    else:
        result = fetch_page_requests(url)
    # botasaurus decorators return None (not raise) on decorator-level crashes
    # when raise_exception=False
    return result or _result(url, None, '', mode, 'fetch layer returned None')


def _warm_contact_driver(driver):
    # Prove the driver end-to-end with a real navigation before it enters the
    # ready pool. Registered on the 'contact' pool at contact_scraper.api
    # import time, so it is in place before any lazy warmer can run.
    driver.get('https://example.com/')
    if 'Example Domain' not in (driver.page_html or ''):
        raise RuntimeError('contact warm-up: unexpected page content')


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
                return 'csr'
    if len(html) > 20000:
        if text is None:
            if soup is None:
                soup = html_to_soup(html)
            text = soup_to_text(soup)
        if len(text) < 200:
            return 'csr'
    return False


if __name__ == '__main__':
    # Manual live check (not part of the test suite): one static site via
    # requests, one SPA that should trip needs_browser, then the browser path.
    # Run as:  python3 -m src.contact_scraper.fetcher
    # (Chrome is built lazily by the pool on the first browser-mode fetch.)
    static = fetch_page('https://example.com')
    print('static:', static['status'], len(static['html']), 'needs_browser =', needs_browser(static))

    spa = fetch_page('https://react.dev')
    print('spa (requests):', spa['status'], len(spa['html']), 'needs_browser =', needs_browser(spa))
    if needs_browser(spa):
        session = BrowserSession()
        try:
            rendered = fetch_page(spa['final_url'], mode='browser', session=session)
        finally:
            session.close()
        print('spa (browser):', rendered['status'], len(rendered['html']),
              'text chars =', len(soup_to_text(html_to_soup(rendered['html']))))
