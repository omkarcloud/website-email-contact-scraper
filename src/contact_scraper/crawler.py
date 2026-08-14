# Site crawler: scored priority frontier (contact-like pages first) over the
# registrable domain of the seed, with sticky requests->browser escalation.

import functools
import heapq
import os
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import tldextract

from .html_text import build_page

MAX_PAGES = int(os.environ.get('CONTACT_SCRAPER_MAX_PAGES', 20))
MAX_DEPTH = 2
EARLY_EXIT_MIN_PAGES = 8
MAX_TEXT_SCAN_CHARS = 1_500_000
# A site that starts timing out must not stall the crawl for minutes: cap the
# total frontier pops and abort after this many back-to-back fetch failures.
MAX_FETCH_ATTEMPTS = 2 * MAX_PAGES
MAX_CONSECUTIVE_FAILURES = 5
# Hard wall-clock budget per site: sticky browser mode + slow hosts otherwise
# stretch a single crawl to 20+ minutes.
MAX_CRAWL_SECONDS = int(os.environ.get('CONTACT_SCRAPER_MAX_CRAWL_SECONDS', 120))

SKIP_EXT_RE = re.compile(
    r'\.(?:png|jpe?g|gif|svg|webp|ico|css|js|mjs|json|xml|pdf|zip|gz|mp3|mp4|webm|avi|woff2?|ttf|eot)(?:\?|$)',
    re.IGNORECASE)

NOISE_PATH_RE = re.compile(
    r'\/(wp-json|wp-admin|cart|checkout|login|signin|register|account|search|tag|category|page\/\d+|\d{4}\/\d{2})(\/|$)',
    re.IGNORECASE)

TRACKING_PARAM_RE = re.compile(
    r'^(utm_.*|fbclid|gclid|msclkid|dclid|yclid|igshid|igsh|si|ref|ref_src|ref_url|source|mc_cid|mc_eid|_ga|feature)$',
    re.IGNORECASE)

# Offline suffix snapshot only - never fetch the public suffix list.
_tld_extract = tldextract.TLDExtract(suffix_list_urls=())


# Whole path segments / whole nav labels only. Substring matching classified
# product pages like /google-maps-with-contact-details as contact pages, which
# both wasted crawl budget and inflated their page weight in ranking.
_KEYWORD_BUCKETS = [
    (100, re.compile(r'^(contact(-?(us|details|form|info|sales))?|kontakt(formular|-aufnehmen)?|contactos?|get-in-touch|reach-us)$')),
    (90,  re.compile(r'^(impressum|imprint|legal-notice|mentions-legales)$')),
    (80,  re.compile(r'^(about(-?us)?|team|our-team|meet-the-team|people|company|who-we-are|ueber-uns|uber-uns|ber-uns)$')),
    (60,  re.compile(r'^(support|help(-center)?|customer-service|locations?|stores?|offices?)$')),
    (40,  re.compile(r'^(privacy(-policy)?|terms(-of-(service|use))?|legal)$')),
]


_SEGMENT_EXT_RE = re.compile(r'\.(?:s?html?|php\d?|aspx?|jsp|cfm|cgi)$')


def keyword_score(url_path, anchor_text) -> int:
    # Pure page-kind bucket; classify_page_weight must see this, not the
    # frontier score, or footer/depth bonuses would misclassify pages.
    candidates = [
        stripped
        for seg in url_path.lower().split('/') if seg
        for stripped in (_SEGMENT_EXT_RE.sub('', seg),) if stripped  # contact.html
    ]
    label = re.sub(r'[^a-z0-9]+', '-', anchor_text.lower()).strip('-')
    if label and len(label) <= 30:
        candidates.append(label)
    for score, bucket in _KEYWORD_BUCKETS:
        if any(bucket.match(c) for c in candidates):
            return score
    return 10


def score_link(url_path, anchor_text, in_footer, in_nav, depth) -> int:
    s = keyword_score(url_path, anchor_text)
    if in_footer: s += 20
    if in_nav:    s += 10
    return s - 10 * depth


def normalize_url(url) -> str:
    # Canonical visited-set key; must be idempotent.
    if '://' not in url:
        url = 'https://' + url
    parts = urlsplit(url)
    host = (parts.netloc or '').lower()
    if host.startswith('www.'):
        host = host[4:]
    path = parts.path.rstrip('/')
    params = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
              if not TRACKING_PARAM_RE.match(k)]
    query = urlencode(sorted(params))
    return urlunsplit(('https', host, path, query, ''))


def registrable_domain(url_or_host) -> str:
    ext = _tld_extract(url_or_host)
    if ext.registered_domain:
        return ext.registered_domain
    # No known suffix (localhost, raw IPs): fall back to the bare host.
    host = urlsplit(url_or_host).netloc if '://' in url_or_host else url_or_host.split('/')[0]
    host = host.lower()
    return host[4:] if host.startswith('www.') else host


def classify_page_weight(link_score, is_homepage) -> str:
    if is_homepage:
        return 'homepage'
    if link_score >= 90:
        return 'contact'
    if link_score >= 80:
        return 'about'
    return 'other'


def _seed_host(query):
    q = query.strip()
    if '://' in q:
        host = urlsplit(q).netloc
    else:
        host = q.split('/')[0]
    return host.lower().strip('.')


def _enqueue_links(page, page_depth, domain, frontier, visited, seq):
    depth = page_depth + 1
    if depth > MAX_DEPTH:
        return seq
    for anchor in page.anchors:
        resolved = anchor['resolved']
        if not resolved:
            continue  # mailto:/tel:/javascript: and friends
        if SKIP_EXT_RE.search(resolved):
            continue
        parts = urlsplit(resolved)
        if parts.scheme not in ('http', 'https'):
            continue
        if NOISE_PATH_RE.search(parts.path):
            continue
        if registrable_domain(resolved) != domain:
            continue
        norm = normalize_url(resolved)
        if norm in visited:
            continue
        visited.add(norm)
        score = score_link(parts.path, anchor['text'], anchor['in_footer'],
                           anchor['in_nav'], depth)
        kw = keyword_score(parts.path, anchor['text'])
        # fetch the ORIGINAL url - normalize_url strips www., and www-only
        # hosts refuse the bare domain; norm is only the dedupe key
        heapq.heappush(frontier, (-score, seq, resolved, depth, kw))
        seq += 1
    return seq


def _flip_www(bare):
    # 'www.acme.com/path' <-> 'acme.com/path'
    hostpart, sep, rest = bare.partition('/')
    if hostpart.lower().startswith('www.'):
        hostpart = hostpart[4:]
    else:
        hostpart = 'www.' + hostpart
    return hostpart + sep + rest


def _seed_failed(result):
    if result['error'] and not result['html']:
        return True
    status = result['status']
    # A 5xx seed is a broken host variant (e.g. Cloudflare 525 when only the
    # www. origin's SSL is misconfigured) - its error page must not become
    # the homepage. 503 is excluded: needs_browser treats it as a challenge.
    return status is not None and status >= 500 and status != 503


def crawl_site(query, fetch=None, early_exit_check=None, on_page_kept=None):
    session = None
    if fetch is None:
        from .fetcher import BrowserSession, fetch_page
        # One pooled-Chrome session per crawl: leased on the first browser-mode
        # fetch, held so challenge cookies persist across the domain's pages,
        # released whenever the crawl returns. Injected fetches (tests) manage
        # no session.
        session = BrowserSession()
        fetch = functools.partial(fetch_page, session=session)
    try:
        return _crawl_site(query, fetch, early_exit_check, on_page_kept)
    finally:
        if session is not None:
            session.close()


def _crawl_site(query, fetch, early_exit_check, on_page_kept):
    from .fetcher import needs_browser

    started = time.monotonic()
    mode = 'requests'
    browser_used = False
    host = _seed_host(query)
    q = query.strip()
    # Seed with the full given URL so path inputs like "dpd.com/be" start on
    # the intended page; preserve an explicit http:// (http-only sites exist).
    scheme = 'https'
    if '://' in q and urlsplit(q).scheme.lower() in ('http', 'https'):
        scheme = urlsplit(q).scheme.lower()
    bare = q.split('://', 1)[-1].strip('/')
    # Broken host variants: the flipped www-form often works - www-only hosts
    # refuse the bare domain, and a misconfigured www. origin can 5xx while
    # the bare domain serves the real site. Hosts with broken TLS (handshake
    # failure, dead cert) often still answer plain http, typically redirecting
    # to the working site.
    seed_urls = [f'{scheme}://{bare}', f'{scheme}://{_flip_www(bare)}']
    if scheme == 'https':
        seed_urls += [f'http://{bare}', f'http://{_flip_www(bare)}']
    result = fetch(seed_urls[0], mode=mode)
    for seed_url in seed_urls[1:]:
        if not _seed_failed(result):
            break
        retry = fetch(seed_url, mode=mode)
        if not _seed_failed(retry):
            result = retry

    # The seed always goes through requests mode first, so its headers are the
    # most reliable HTTP-level signal for tech detection; a full-browser
    # refetch exposes no headers and falls back to these.
    seed_headers = result.get('headers') or {}

    out = {'domain': host, 'pages': [],
           'browser_used': False, 'homepage_headers': {}, 'error': None}
    if result['error'] and not result['html']:
        # Connection-level failure on the seed (after the www-flip retry):
        # the host is dead or refuses us outright - give up, no browser probe.
        out['error'] = result['error']
        return out

    reason = needs_browser(result)
    if reason:
        browser_used = True
        refetched = fetch(result['final_url'], mode='browser')
        if refetched['html']:
            result = refetched
        # The full page load above earned any challenge cookies, so blocked
        # sites can continue on cheap in-page fetches; client-side-rendered
        # sites still need a real page load per page.
        mode = 'browser' if reason == 'csr' else 'browser_light'

    out['homepage_headers'] = result.get('headers') or seed_headers

    # The final homepage URL decides the crawl domain (seed redirects to a
    # renamed/parked domain adopt it; later cross-domain redirects drop pages).
    # Scope stays registrable (subdomains crawl together); the REPORTED domain
    # is the final resolved host, e.g. docker.com -> www.docker.com.
    domain = registrable_domain(result['final_url'])
    out['domain'] = (urlsplit(result['final_url']).hostname or host).lower()

    visited = {normalize_url('https://' + host), normalize_url(result['final_url'])}
    fetched_finals = {normalize_url(result['final_url'])}
    frontier = []
    seq = 0

    homepage = build_page(result['final_url'], result['html'])
    out['pages'].append({'page': homepage, 'depth': 0,
                         'weight_class': 'homepage', 'is_homepage': True})
    if on_page_kept:
        on_page_kept(result)
    seq = _enqueue_links(homepage, 0, domain, frontier, visited, seq)

    attempts = 0
    consecutive_failures = 0
    while (frontier and len(out['pages']) < MAX_PAGES
           and attempts < MAX_FETCH_ATTEMPTS
           and time.monotonic() - started < MAX_CRAWL_SECONDS):
        attempts += 1
        neg_score, _, url, depth, kw = heapq.heappop(frontier)
        result = fetch(url, mode=mode)
        if result['error'] and not result['html']:
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                break  # site went dark mid-crawl; keep what we have
            continue
        consecutive_failures = 0
        if registrable_domain(result['final_url']) != domain:
            continue  # redirected off-site
        if normalize_url(result['final_url']) in fetched_finals:
            continue  # redirect landed on an already-fetched page

        page = build_page(result['final_url'], result['html'])
        if result['mode_used'] != 'browser':
            # Covers requests AND browser_light results: an in-page fetch
            # returns raw HTML without running JS, so a CSR page must escalate
            # too. Keyed on mode_used, not the crawl mode: a light fetch that
            # already fell back to full navigation internally (cross-origin
            # subdomain, fetch error) must not be fetched a second time.
            reason = needs_browser(result, text=page.text, soup=page.soup)
            if reason:
                browser_used = True
                refetched = fetch(url, mode='browser')
                if refetched['html']:
                    result = refetched
                    page = build_page(result['final_url'], result['html'])
                mode = 'browser' if reason == 'csr' else 'browser_light'

        # Re-check: the browser refetch may have redirected somewhere new.
        if registrable_domain(result['final_url']) != domain:
            continue
        final_norm = normalize_url(result['final_url'])
        if final_norm in fetched_finals:
            continue
        fetched_finals.add(final_norm)
        visited.add(final_norm)
        out['pages'].append({'page': page, 'depth': depth,
                             'weight_class': classify_page_weight(kw, False),
                             'is_homepage': False})
        if on_page_kept:
            on_page_kept(result)
        seq = _enqueue_links(page, depth, domain, frontier, visited, seq)

        if early_exit_check and len(out['pages']) >= EARLY_EXIT_MIN_PAGES:
            best_remaining = -frontier[0][0] if frontier else 0
            if early_exit_check(len(out['pages']), best_remaining):
                break

    out['browser_used'] = browser_used
    return out
