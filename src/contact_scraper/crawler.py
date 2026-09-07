# Site crawler: scored priority frontier (contact-like pages first) over the
# registrable domain of the seed, fetched in concurrent waves, with sticky
# requests->browser escalation.

import functools
import heapq
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import tldextract

from .html_text import build_page

MAX_PAGES = 20
MAX_DEPTH = 2
# A site that starts timing out must not stall the crawl for minutes: cap the
# total frontier pops and abort after this many back-to-back fetch failures.
MAX_FETCH_ATTEMPTS = 2 * MAX_PAGES
MAX_CONSECUTIVE_FAILURES = 5
# Hard wall-clock budget per site: sticky csr/blocked mode + slow hosts otherwise
# stretch a single crawl to 20+ minutes.
MAX_CRAWL_SECONDS = 120

# Wave fetching: frontier URLs fetch in concurrent batches through ONE
# process-wide executor shared by every crawl (per-crawl pools would explode
# under @task(parallel=40); saturation just serializes waves). The first wave
# takes every queued link scoring >= FIRST_WAVE_MIN_SCORE — contact, about,
# impressum, careers, blog — a deliberately modest burst that doubles as the
# escalation probe. Later waves take the WHOLE remaining page budget in one
# burst (there is no early exit, every queued page gets fetched anyway, so
# splitting them only adds round-trips). WAVE_MAX caps the burst for
# rate-limit-sensitive deployments; 1 reverts to sequential fetching.
# Crawl modes shrink this: 'key_pages' stops after the first wave, 'homepage'
# never reaches the loop at all.
FETCH_POOL_SIZE = 24
FIRST_WAVE_MAX = 6
WAVE_MAX = MAX_PAGES
FIRST_WAVE_MIN_SCORE = 60

# Browser escalations are the expensive path: each one is a real navigation
# on the crawl's single pooled Chrome (serialized on that driver's owner
# thread) and can burn up to the driver's CALL_TIMEOUT. An app-shell-looking
# site can want one for EVERY page, so a 20-page crawl blows minutes past
# MAX_CRAWL_SECONDS while holding a driver and its renderer memory - the
# stall behind the contact pods' liveness restarts and OOMs. Cap how many a
# single crawl may spend, and never start one the deadline cannot cover.
MAX_BROWSER_ESCALATIONS = 6
MIN_ESCALATION_SECONDS = 10

_fetch_pool = ThreadPoolExecutor(max_workers=FETCH_POOL_SIZE,
                                 thread_name_prefix='contact-fetch')

SKIP_EXT_RE = re.compile(
    r'\.(?:png|jpe?g|gif|svg|webp|ico|css|js|mjs|json|xml|pdf|zip|gz|mp3|mp4|webm|avi|woff2?|ttf|eot)(?:\?|$)',
    re.IGNORECASE)

NOISE_PATH_RE = re.compile(
    r'\/(wp-json|wp-admin|cart|checkout|oauth2|sign-up|sign-in|login|signin|register|account|search|tag|category|page\/\d+|\d{4}\/\d{2})(\/|$)',
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
    # 70 = the tech-detection targets (job boards, blog CMSes live there).
    # Exactly 70 on purpose: a depth-1 plain link scores 70-10 = 60 =
    # FIRST_WAVE_MIN_SCORE, so these are guaranteed wave-1 fetches; staying
    # below 80 keeps classify_page_weight at 'other'.
    (70,  re.compile(r'^(careers?|jobs|blog|news)$')),
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


def _collect(future, deadline, url, mode):
    # Wave fetches share the crawl's wall clock: a future that can't deliver
    # before the deadline is cancelled (if still queued behind a saturated
    # executor) and degraded to a fetch error, so MAX_CRAWL_SECONDS stays a
    # hard wall even when 40 crawls contend for the shared pool.
    try:
        return future.result(timeout=max(0.1, deadline - time.monotonic()))
    except FuturesTimeout:
        future.cancel()
        return {'final_url': url, 'status': None, 'html': '', 'mode_used': mode,
                'headers': {}, 'error': 'wave timeout: crawl budget exhausted'}


def _probe_seeds(fetch, urls, deadline):
    """Fetch every seed variant concurrently; prefer the earliest-listed
    success (the host as typed beats the www-flip). Collects in listed order
    and returns the moment the winner is known, so a hanging flip variant
    never delays an already-answered as-typed host; later variants only get
    waited on when every earlier one failed. Returns (chosen, first): chosen
    is None when every variant failed, first is variant #1's result."""
    futures = [_fetch_pool.submit(fetch, u, mode='requests') for u in urls]
    first = chosen = None
    for f, u in zip(futures, urls):
        result = _collect(f, deadline, u, 'requests')
        if first is None:
            first = result
        if not _seed_failed(result):
            chosen = result
            break
    for f in futures:
        f.cancel()  # a still-queued loser frees its shared-pool slot
    return chosen, first


def _pop_wave(frontier, first_wave, budget):
    # First wave: every immediately-known high-value link, so contact/about/
    # impressum/careers/blog all fetch concurrently; always at least one
    # entry so a low-scoring frontier still advances the crawl.
    cap = min(FIRST_WAVE_MAX if first_wave else WAVE_MAX, budget)
    wave = []
    while frontier and len(wave) < cap:
        if first_wave and wave and -frontier[0][0] < FIRST_WAVE_MIN_SCORE:
            break
        wave.append(heapq.heappop(frontier))
    return wave


def crawl_site(query, fetch=None, on_page_kept=None, fetch_many=None, mode='deep'):
    if mode not in ('homepage', 'key_pages', 'deep'):
        # Reject before any fetch: an unknown mode must not silently run the
        # most expensive (deep) crawl.
        raise ValueError(
            f"crawl mode must be one of ('homepage', 'key_pages', 'deep'), got {mode!r}")
    session = None
    http = None
    if fetch is None:
        from .fetcher import (BrowserSession, RequestsSessionBundle,
                              fetch_page, fetch_pages_light)
        # One pooled-Chrome session + one keep-alive HTTP bundle per crawl:
        # the driver is leased on the crawl's first browser-mode fetch and
        # held until the crawl returns (challenge cookies live on it); the
        # curl sessions hold keep-alive connections to the site. Injected
        # fetches (tests) manage neither — note they MUST tolerate concurrent
        # calls, since waves and seed probes run on executor threads.
        session = BrowserSession()
        http = RequestsSessionBundle()
        fetch = functools.partial(fetch_page, session=session, http=http)
        fetch_many = functools.partial(fetch_pages_light, session=session)
    try:
        return _crawl_site(query, fetch, on_page_kept, fetch_many, session, mode)
    finally:
        if session is not None:
            session.close()
        if http is not None:
            http.close_all()


def _crawl_site(query, fetch, on_page_kept, fetch_many=None, session=None,
                crawl_mode='deep'):
    """Crawl a site with one of three modes:
      - 'homepage':  homepage only — fetch the seed page and extract its details.
      - 'key_pages': homepage + first wave of high-value links (contact, about,
                     impressum, careers, blog). Stops after wave 1.
      - 'deep':      full site crawl (the default) — up to MAX_PAGES pages,
                     depth 2, with browser escalation.
    """
    from .fetcher import POOL_KEY_CSR, needs_browser

    started = time.monotonic()
    deadline = started + MAX_CRAWL_SECONDS
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
    # the bare domain serves the real site. Both variants probe concurrently;
    # hosts with broken TLS (handshake failure, dead cert) often still answer
    # plain http, so the http pair probes next when https yielded nothing.
    result, first = _probe_seeds(
        fetch, [f'{scheme}://{bare}', f'{scheme}://{_flip_www(bare)}'], deadline)
    if result is None and scheme == 'https':
        result, _ = _probe_seeds(
            fetch, [f'http://{bare}', f'http://{_flip_www(bare)}'], deadline)
    if result is None:
        result = first  # every variant failed: report variant #1's error

    # The seed always goes through requests mode first, so its headers are the
    # most reliable HTTP-level signal for tech detection; a full csr/blocked-mode
    # refetch exposes no headers and falls back to these.
    seed_headers = result.get('headers') or {}

    out = {'domain': host, 'pages': [],
           'browser_used': False, 'homepage_headers': {}, 'error': None}
    if result['error'] and not result['html']:
        # Connection-level failure on the seed (after every variant probe):
        # the host is dead or refuses us outright - give up, no browser probe.
        out['error'] = result['error']
        return out

    mode = 'requests'  # transport mode; escalation below flips it to csr/blocked
    reason = needs_browser(result)
    if reason:
        browser_used = True
        if session is not None:
            session.ensure_pool(reason)
        refetched = fetch(result['final_url'], mode='csr',
                          blocked=reason == 'blocked')
        if (session is not None and session.pool_key == POOL_KEY_CSR
                and refetched['html'] and needs_browser(refetched) == 'blocked'
                and session.upgrade_for_block()):
            # Mixed signals on the seed itself, blocked wins: the headless CSR
            # chrome was served a challenge page, and keeping it would poison
            # the homepage AND the frontier (a challenge page has no links) -
            # swap to the headed stealth pool and redo the full page load,
            # same rule as the mid-crawl upgrade below.
            refetched = fetch(result['final_url'], mode='csr', blocked=True)
        if refetched['html']:
            result = refetched
        # The full page load above earned any challenge cookies, so blocked
        # sites can continue on cheap in-page fetches; client-side-rendered
        # sites still need a real page load per page.
        mode = 'csr' if reason == 'csr' else 'blocked'

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
    homepage_rec = {'page': homepage, 'depth': 0,
                    'weight_class': 'homepage', 'is_homepage': True}
    out['pages'].append(homepage_rec)
    if on_page_kept:
        # The homepage callback must see the merged seed/browser headers -
        # they are tech detection's only reliable HTTP-level signal.
        result['headers'] = out['homepage_headers']
        on_page_kept(result, homepage_rec)
    if crawl_mode == 'homepage':
        out['browser_used'] = browser_used
        return out
    seq = _enqueue_links(homepage, 0, domain, frontier, visited, seq)

    # 'key_pages' = exactly the first wave: at most FIRST_WAVE_MAX high-value
    # fetches beyond the homepage, then stop (a csr transport spreads that
    # same selection over sequential one-page iterations).
    key_pages = crawl_mode == 'key_pages'
    attempts_cap = FIRST_WAVE_MAX if key_pages else MAX_FETCH_ATTEMPTS
    attempts = 0
    consecutive_failures = 0
    escalations = 0
    first_wave = True
    stop = False
    while (not stop and frontier and len(out['pages']) < MAX_PAGES
           and attempts < attempts_cap
           and time.monotonic() < deadline):
        if key_pages and not first_wave:
            if mode != 'csr':
                break  # wave 1 fetched and processed in one burst
            if -frontier[0][0] < FIRST_WAVE_MIN_SCORE:
                break  # csr pops wave-1 one page at a time; floor reached
        budget = min(MAX_PAGES - len(out['pages']), attempts_cap - attempts)
        if mode == 'csr':
            # Full-navigation (CSR) crawling stays strictly sequential: one
            # driver, one real page load at a time.
            wave = _pop_wave(frontier, False, min(budget, 1))
        else:
            wave = _pop_wave(frontier, first_wave, budget)
        first_wave = False
        attempts += len(wave)
        urls = [entry[2] for entry in wave]

        if mode == 'requests':
            futures = [_fetch_pool.submit(fetch, u, mode='requests') for u in urls]
            results = [_collect(f, deadline, u, 'requests')
                       for f, u in zip(futures, urls)]
        elif mode == 'blocked' and fetch_many is not None and len(urls) > 1:
            # One in-page Promise.all on the crawl's leased driver.
            results = fetch_many(urls)
        else:
            results = [fetch(u, mode=mode) for u in urls]

        # Process sequentially in score order (the wave is heap-ordered).
        for entry, result in zip(wave, results):
            neg_score, _entry_seq, url, depth, kw = entry
            if result['error'] and not result['html']:
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    stop = True  # site went dark mid-crawl; keep what we have
                    break
                continue
            consecutive_failures = 0
            if registrable_domain(result['final_url']) != domain:
                continue  # redirected off-site
            if normalize_url(result['final_url']) in fetched_finals:
                continue  # redirect landed on an already-fetched page

            page = build_page(result['final_url'], result['html'])
            if result['mode_used'] != 'csr':
                # Covers requests AND blocked results: an in-page fetch
                # returns raw HTML without running JS, so a CSR page must
                # escalate too. Keyed on mode_used, not the crawl mode: a
                # light fetch that already fell back to full navigation
                # internally (cross-origin subdomain, fetch error) must not
                # be fetched a second time.
                reason = needs_browser(result, text=page.text, soup=page.soup)
                if reason and (escalations >= MAX_BROWSER_ESCALATIONS
                               or deadline - time.monotonic() < MIN_ESCALATION_SECONDS):
                    # Budget spent (or too little time left to finish one):
                    # keep the raw-HTML result rather than stalling the crawl.
                    reason = None
                if reason:
                    escalations += 1
                    browser_used = True
                    if session is not None:
                        session.ensure_pool(reason)
                    refetched = fetch(url, mode='csr',
                                      blocked=reason == 'blocked')
                    if refetched['html']:
                        result = refetched
                        page = build_page(result['final_url'], result['html'])
                    mode = 'csr' if reason == 'csr' else 'blocked'
            elif (session is not None and session.pool_key == POOL_KEY_CSR
                    and escalations < MAX_BROWSER_ESCALATIONS
                    and deadline - time.monotonic() >= MIN_ESCALATION_SECONDS
                    and needs_browser(result, text=page.text, soup=page.soup) == 'blocked'
                    and session.upgrade_for_block()):
                escalations += 1
                # Mixed signals, blocked wins: a challenge served to the
                # headless CSR chrome swaps the session to the headed stealth
                # pool (once per crawl) and refetches this one page there.
                browser_used = True
                refetched = fetch(url, mode='csr', blocked=True)
                if refetched['html']:
                    result = refetched
                    page = build_page(result['final_url'], result['html'])

            # Re-check: the browser refetch may have redirected somewhere new.
            if registrable_domain(result['final_url']) != domain:
                continue
            final_norm = normalize_url(result['final_url'])
            if final_norm in fetched_finals:
                continue
            fetched_finals.add(final_norm)
            visited.add(final_norm)
            rec = {'page': page, 'depth': depth,
                   'weight_class': classify_page_weight(kw, False),
                   'is_homepage': False}
            out['pages'].append(rec)
            if on_page_kept:
                on_page_kept(result, rec)
            seq = _enqueue_links(page, depth, domain, frontier, visited, seq)

            if len(out['pages']) >= MAX_PAGES or time.monotonic() >= deadline:
                stop = True
                break

    out['browser_used'] = browser_used
    return out
