# Offline tests for crawler.py + fetcher.needs_browser (zero network: the
# crawl tests inject a fake fetch). Run: python3 -m src.contact_scraper.test_crawler

import os
import threading

from .crawler import (FIRST_WAVE_MAX, MAX_PAGES, classify_page_weight,
                      crawl_site, keyword_score, normalize_url,
                      registrable_domain, score_link)
from .fetcher import needs_browser

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


def read_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name), encoding='utf-8') as f:
        return f.read()


def make_result(html, status=200, final_url='https://acme.com', error=None,
                mode_used='requests'):
    return {'final_url': final_url, 'status': status, 'html': html,
            'mode_used': mode_used, 'error': error}


def make_fake_fetch(site, log):
    # site: {normalized_url: {'html': ..., 'final_url': ..., 'status': ...}}
    # Called from the crawler's executor threads (seed probes + waves run
    # concurrently): log.append is GIL-atomic, but entries within one wave
    # land in arbitrary order — assert on membership/counts, not positions
    # (the two seed probes normalize to the same key, so log[0] is stable).
    def fetch(url, mode='requests', blocked=False):
        key = normalize_url(url)
        log.append((key, mode))
        entry = site.get(key)
        if entry is None:
            return {'final_url': url, 'status': None, 'html': '',
                    'mode_used': mode, 'error': 'ConnectionError: refused'}
        return {'final_url': entry.get('final_url', url),
                'status': entry.get('status', 200),
                'html': entry['html'], 'mode_used': mode, 'error': None,
                'headers': entry.get('headers', {})}
    return fetch


def test_score_link():
    contact = score_link('/contact', 'Contact', False, False, 1)
    impressum = score_link('/impressum', 'Impressum', False, False, 1)
    about = score_link('/about', 'About us', False, False, 1)
    careers = score_link('/careers', 'Careers', False, False, 1)
    support = score_link('/support', 'Support', False, False, 1)
    privacy = score_link('/privacy', 'Privacy Policy', False, False, 1)
    generic = score_link('/products/widget-a', 'Read more', False, False, 1)
    assert contact > impressum > about > careers > support > privacy > generic

    # anchor text alone can trigger a category
    assert score_link('/de/seite-7', 'Kontakt aufnehmen', False, False, 1) == contact

    assert score_link('/contact', 'Contact', True, False, 1) == contact + 20   # footer
    assert score_link('/contact', 'Contact', False, True, 1) == contact + 10   # nav
    assert score_link('/contact', 'Contact', True, True, 1) == contact + 30
    assert score_link('/contact', 'Contact', False, False, 2) == contact - 10  # depth


def test_keyword_buckets_tech_pages():
    # careers/jobs/blog/news score exactly 70: a depth-1 plain link lands at
    # 70-10 = 60 = FIRST_WAVE_MIN_SCORE (guaranteed wave-1 fetch) while
    # staying below the 'about' weight class in classify_page_weight.
    for path in ('/careers', '/career', '/jobs', '/blog', '/news',
                 '/blog/post1', '/en/careers'):
        assert keyword_score(path, '') == 70, path
    assert keyword_score('/x', 'Careers') == 70  # anchor label alone
    assert classify_page_weight(70, False) == 'other'
    assert keyword_score('/products/widget-a', 'Read more') == 10


def test_normalize_url():
    n = normalize_url('https://www.Acme.com/Contact/?utm_source=nl&b=2&a=1#team')
    assert n == 'https://acme.com/Contact?a=1&b=2', n
    assert normalize_url(n) == n  # idempotent

    assert normalize_url('acme.com') == 'https://acme.com'
    assert normalize_url('http://www.acme.com/') == 'https://acme.com'
    assert normalize_url('https://acme.com/x#frag') == 'https://acme.com/x'
    stripped = normalize_url('https://acme.com/x?ref=partner&fbclid=abc&gclid=1&page=2')
    assert stripped == 'https://acme.com/x?page=2', stripped
    assert normalize_url('https://acme.com/x?utm_campaign=a&utm_medium=b') == 'https://acme.com/x'
    # same page, different shapes -> one visited-set key
    assert normalize_url('http://www.acme.com/contact/') == normalize_url('https://acme.com/contact')


def test_registrable_domain():
    assert registrable_domain('https://blog.acme.co.uk/about') == 'acme.co.uk'
    assert registrable_domain('acme.co.uk') == 'acme.co.uk'
    assert registrable_domain('www.acme.com') == 'acme.com'
    assert registrable_domain('https://shop.acme.com/x') == 'acme.com'
    assert (registrable_domain('https://blog.acme.co.uk')
            == registrable_domain('https://www.acme.co.uk'))


def test_classify_page_weight():
    assert classify_page_weight(0, True) == 'homepage'
    assert classify_page_weight(100, True) == 'homepage'
    assert classify_page_weight(100, False) == 'contact'
    assert classify_page_weight(90, False) == 'contact'
    assert classify_page_weight(85, False) == 'about'
    assert classify_page_weight(80, False) == 'about'
    assert classify_page_weight(79, False) == 'other'
    assert classify_page_weight(0, False) == 'other'


def test_needs_browser():
    spa = read_fixture('spa_shell.html')
    assert len(spa) < 5000  # fixture must stay a small app shell
    assert needs_browser(make_result(spa)) == 'csr'

    normal = ('<html><body><h1>Contact us</h1>'
              '<p>Email info@acme.com or call +1 415 555 2671.</p>'
              '<a href="/">Home</a><a href="/about">About</a>'
              '<a href="/team">Team</a><a href="/privacy">Privacy</a>'
              '<a href="/terms">Terms</a></body></html>')
    assert needs_browser(make_result(normal)) is False

    assert needs_browser(make_result(normal, status=403)) == 'blocked'
    assert needs_browser(make_result('', status=None, error='ConnectionError')) is False

    script_only = ('<html><head><script>' + 'var chunk_a1 = 9;' * 1600
                   + '</script></head><body><div></div></body></html>')
    assert len(script_only) > 20000
    assert needs_browser(make_result(script_only)) == 'csr'

    challenge = '<html><head><title>Just a moment...</title></head><body></body></html>'
    assert needs_browser(make_result(challenge)) == 'blocked'

    # Akamai Bot Manager interstitial (tesla.com): status 200, so only the
    # challenge-container marker catches it.
    akamai = ('<html><body>'
              '<div id="sec-if-cpt-container" role="main" style="display: none">'
              '<p>Powered and protected by</p></div></body></html>')
    assert needs_browser(make_result(akamai)) == 'blocked'


SMALL_SITE = {
    'https://acme.com': {'html': """
        <html><body>
        <nav><a href="/contact">Contact Us</a> <a href="/about">About</a></nav>
        <main>
          <p>Welcome to Acme. We build fine widgets and ship them worldwide.</p>
          <a href="/blog/post1">Read our launch story</a>
          <a href="https://other.com/partners">Partner site</a>
          <a href="/contact?utm_source=footer">Get in touch</a>
          <a href="/login">Login</a>
        </main>
        </body></html>""",
        'headers': {'Server': 'nginx'}},
    'https://acme.com/contact': {'html': '<html><body><h1>Contact</h1>'
                                         '<p>Email info@acme.com any time.</p></body></html>'},
    'https://acme.com/about': {'html': '<html><body><h1>About Acme</h1>'
                                       '<p>Founded 2001 by widget lovers.</p></body></html>'},
    'https://acme.com/blog/post1': {'html': '<html><body><h1>Launch</h1>'
                                            '<p>We launched a widget.</p></body></html>'},
    'https://other.com/partners': {'html': '<html><body>external</body></html>'},
    'https://acme.com/login': {'html': '<html><body>login form</body></html>'},
}


def test_crawl_small_site():
    log = []
    result = crawl_site('acme.com', fetch=make_fake_fetch(SMALL_SITE, log))

    assert result['domain'] == 'acme.com'
    assert result['browser_used'] is False

    fetched = [url for url, _ in log]
    assert fetched[0] == 'https://acme.com'
    # duplicate /contact?utm_source=footer deduped via normalize_url
    assert fetched.count('https://acme.com/contact') == 1
    # external + noise-path links never fetched
    assert all('other.com' not in url for url in fetched)
    assert all('/login' not in url for url in fetched)

    # pages land in score order regardless of wave fetch completion order
    urls = [entry['page'].url for entry in result['pages']]
    assert urls == ['https://acme.com', 'https://acme.com/contact',
                    'https://acme.com/about', 'https://acme.com/blog/post1'], urls
    # contact (score 100) processed before blog (score 70)
    assert urls.index('https://acme.com/contact') < urls.index('https://acme.com/blog/post1')

    classes = [entry['weight_class'] for entry in result['pages']]
    assert classes == ['homepage', 'contact', 'about', 'other'], classes
    assert [entry['is_homepage'] for entry in result['pages']] == [True, False, False, False]
    assert [entry['depth'] for entry in result['pages']] == [0, 1, 1, 1]


def make_big_site(n_links=30):
    links = ''.join(f'<a href="/p{i}">Page {i}</a> ' for i in range(1, n_links + 1))
    site = {'https://big.com': {'html': f'<html><body><p>hub</p>{links}</body></html>'}}
    for i in range(1, n_links + 1):
        site[f'https://big.com/p{i}'] = {
            'html': f'<html><body><p>page {i} content about widgets</p></body></html>'}
    return site


def test_crawl_max_pages():
    log = []
    result = crawl_site('big.com', fetch=make_fake_fetch(make_big_site(), log))
    assert len(result['pages']) == MAX_PAGES, len(result['pages'])
    # Up to 2 concurrent seed probes (bare + www-flip) + 19 children: waves
    # are budget-capped, so children never over-fetch past MAX_PAGES. The
    # flip probe may be cancelled before it runs (the bare host answered
    # first), so the exact count is racy by one.
    assert MAX_PAGES <= len(log) <= MAX_PAGES + 1, len(log)


def test_crawl_no_early_exit():
    # The signal-based early exit was removed entirely: even a site whose
    # homepage already has contacts crawls to its full budget.
    site = {
        'https://acme.com': {'html': """
            <html><body>
            <p>Home. Mail hi@acme.com or dial tel:+14155552671.</p>
            <a href="/p1">One</a><a href="/p2">Two</a><a href="/p3">Three</a>
            </body></html>"""},
        'https://acme.com/p1': {'html': '<html><body><p>one</p></body></html>'},
        'https://acme.com/p2': {'html': '<html><body><p>two</p></body></html>'},
        'https://acme.com/p3': {'html': '<html><body><p>three</p></body></html>'},
    }
    log = []
    result = crawl_site('acme.com', fetch=make_fake_fetch(site, log))
    urls = [entry['page'].url for entry in result['pages']]
    assert len(urls) == 4, urls  # homepage + every generic link, none skipped


def test_crawl_seed_redirect_adopts_domain():
    site = {
        # seed 301s to the rebranded domain; crawl domain must follow it
        'https://oldbrand.com': {
            'html': """<html><body><p>Welcome to Newbrand (formerly Oldbrand).</p>
                       <a href="/contact">Contact</a>
                       <a href="https://oldbrand.com/legacy">Legacy page</a>
                       </body></html>""",
            'final_url': 'https://www.newbrand.com/'},
        # fake-fetch keys are normalized, but the crawler itself must request
        # the ORIGINAL resolved link (www. kept) - normalize_url is only the
        # dedupe key, hence the www. page url assertion below
        'https://newbrand.com/contact': {'html': '<html><body><p>Mail us at hi@newbrand.com.'
                                                 '</p></body></html>'},
        'https://oldbrand.com/legacy': {'html': '<html><body>old</body></html>'},
    }
    log = []
    result = crawl_site('oldbrand.com', fetch=make_fake_fetch(site, log))

    # reported domain = final resolved HOST of the homepage (www. kept)
    assert result['domain'] == 'www.newbrand.com'
    urls = [entry['page'].url for entry in result['pages']]
    assert urls == ['https://www.newbrand.com/', 'https://www.newbrand.com/contact'], urls
    # oldbrand links are now cross-domain and never fetched
    assert all('oldbrand.com/legacy' not in url for url, _ in log)
    assert result['pages'][1]['weight_class'] == 'contact'


def test_crawl_seed_www_retry():
    # bare host refuses connections; www. works (both probe concurrently and
    # the earliest-listed success is preferred, so www wins only here)
    site = {'https://www.onlywww.com': {'html': '<html><body><p>hello world</p></body></html>',
                                        'final_url': 'https://www.onlywww.com/'}}

    def fetch(url, mode='requests', blocked=False):
        if url == 'https://onlywww.com':
            return {'final_url': url, 'status': None, 'html': '',
                    'mode_used': mode, 'error': 'ConnectionError: refused'}
        entry = site.get(url)
        if entry is None:
            return {'final_url': url, 'status': None, 'html': '',
                    'mode_used': mode, 'error': 'ConnectionError: refused'}
        return {'final_url': entry['final_url'], 'status': 200,
                'html': entry['html'], 'mode_used': mode, 'error': None}

    result = crawl_site('onlywww.com', fetch=fetch)
    # the www-variant answered, so the resolved host (with www.) is reported
    assert result['domain'] == 'www.onlywww.com'
    assert len(result['pages']) == 1


def test_crawl_unreachable():
    def fetch(url, mode='requests', blocked=False):
        return {'final_url': url, 'status': None, 'html': '',
                'mode_used': mode, 'error': 'ConnectionError: refused'}

    result = crawl_site('dead.example', fetch=fetch)
    assert result == {'domain': 'dead.example',
                      'pages': [], 'browser_used': False,
                      'homepage_headers': {},
                      'error': 'ConnectionError: refused'}


def test_crawl_sticky_csr():
    spa = read_fixture('spa_shell.html')
    rendered_home = """<html><body><nav><a href="/contact">Contact</a></nav>
                       <p>Rendered app content with plenty of visible text.</p>
                       </body></html>"""
    modes_by_call = []

    def fetch(url, mode='requests', blocked=False):
        modes_by_call.append((normalize_url(url), mode))
        if mode == 'requests':
            return {'final_url': url, 'status': 200, 'html': spa,
                    'mode_used': mode, 'error': None}
        html = rendered_home if normalize_url(url) == 'https://spa.com' else \
            '<html><body><p>Contact page: hello@spa.com</p></body></html>'
        return {'final_url': url, 'status': 200, 'html': html,
                'mode_used': mode, 'error': None}

    result = crawl_site('spa.com', fetch=fetch)
    assert result['browser_used'] is True
    # both concurrent seed probes go through requests mode first
    assert modes_by_call[0][1] == 'requests'
    first_csr = next(i for i, (_, m) in enumerate(modes_by_call) if m == 'csr')
    # the homepage is the first csr refetch, and once CSR mode sticks
    # every subsequent fetch is a full csr navigation
    assert modes_by_call[first_csr][0] == 'https://spa.com'
    assert all(m == 'csr' for _, m in modes_by_call[first_csr:])
    assert len(result['pages']) == 2


def test_wave_concurrency():
    # The two score>=60 homepage links must be IN FLIGHT at the same time:
    # each blocks on a shared barrier that only releases when both arrived.
    # Sequential fetching would deadlock the barrier (5s timeout -> error).
    barrier = threading.Barrier(2, timeout=5)
    site_html = {
        'https://acme.com': """
            <html><body><nav>
            <a href="/contact">Contact</a><a href="/about">About</a>
            </nav><p>Welcome to Acme widgets.</p></body></html>""",
        'https://acme.com/contact': '<html><body><p>mail hi@acme.com</p></body></html>',
        'https://acme.com/about': '<html><body><p>About Acme.</p></body></html>',
    }

    def fetch(url, mode='requests', blocked=False):
        key = normalize_url(url)
        if key in ('https://acme.com/contact', 'https://acme.com/about'):
            barrier.wait()  # raises BrokenBarrierError if fetched sequentially
        html = site_html.get(key)
        if html is None:
            return {'final_url': url, 'status': None, 'html': '',
                    'mode_used': mode, 'error': 'ConnectionError: refused'}
        return {'final_url': url, 'status': 200, 'html': html,
                'mode_used': mode, 'error': None}

    result = crawl_site('acme.com', fetch=fetch)
    urls = [entry['page'].url for entry in result['pages']]
    assert 'https://acme.com/contact' in urls and 'https://acme.com/about' in urls, urls


def test_fetch_many_wave():
    # Once a blocked seed flips the crawl to blocked mode, multi-URL waves
    # must go through the injected fetch_many (the driver.get_many path)
    # and its results must feed the normal pipeline.
    normal_home = """<html><body><nav>
        <a href="/contact">Contact</a><a href="/about">About</a></nav>
        <p>Plenty of real homepage text to keep needs_browser quiet.</p>
        </body></html>"""
    pages = {
        'https://shield.com/contact': '<html><body><p>mail hi@shield.com</p></body></html>',
        'https://shield.com/about': '<html><body><p>About Shield Co.</p></body></html>',
    }
    many_calls = []

    def fetch(url, mode='requests', blocked=False):
        if mode == 'requests':
            # challenged seed: real 403 with an interstitial marker
            return {'final_url': url, 'status': 403,
                    'html': '<html><head><title>Just a moment...</title></head></html>',
                    'mode_used': mode, 'error': None}
        # the csr refetch of the homepage earns the cookies
        return {'final_url': 'https://shield.com/', 'status': 200,
                'html': normal_home, 'mode_used': 'csr', 'error': None}

    def fetch_many(urls):
        many_calls.append(list(urls))
        return [{'final_url': u, 'status': 200,
                 'html': pages[normalize_url(u)],
                 'mode_used': 'blocked', 'error': None} for u in urls]

    result = crawl_site('shield.com', fetch=fetch, fetch_many=fetch_many)
    assert result['browser_used'] is True
    assert len(many_calls) == 1 and len(many_calls[0]) == 2, many_calls
    urls = [entry['page'].url for entry in result['pages']]
    assert urls == ['https://shield.com/', 'https://shield.com/contact',
                    'https://shield.com/about'], urls


def test_on_page_kept_receives_record():
    seen = []

    def on_page_kept(result, rec):
        seen.append((result['final_url'], rec['weight_class'],
                     rec['is_homepage'], result.get('headers')))

    log = []
    crawl_site('acme.com', fetch=make_fake_fetch(SMALL_SITE, log),
               on_page_kept=on_page_kept)
    assert seen[0][2] is True and seen[0][1] == 'homepage'
    # the homepage callback sees the merged homepage headers (tech detection's
    # HTTP-level signal), enriched by the crawler before the callback fires
    assert seen[0][3] == {'Server': 'nginx'}, seen[0]
    by_class = {weight for _, weight, _, _ in seen}
    assert 'contact' in by_class, seen


def test_crawl_mode_homepage():
    seen = []
    log = []
    result = crawl_site('acme.com', fetch=make_fake_fetch(SMALL_SITE, log),
                        on_page_kept=lambda r, rec: seen.append(rec),
                        mode='homepage')
    urls = [entry['page'].url for entry in result['pages']]
    assert urls == ['https://acme.com'], urls
    # only the concurrent seed probes hit the network (bare + www-flip, and
    # the flip may be cancelled before it runs) - never any child link
    assert 1 <= len(log) <= 2, log
    assert all(url == 'https://acme.com' for url, _ in log), log
    assert len(seen) == 1 and seen[0]['is_homepage'] is True


def test_crawl_mode_homepage_blocked():
    # A challenged homepage still escalates to the browser in homepage mode;
    # the rendered page's links must still not be crawled.
    calls = []

    def fetch(url, mode='requests', blocked=False):
        calls.append((normalize_url(url), mode))
        if mode == 'requests':
            return {'final_url': url, 'status': 403,
                    'html': '<html><head><title>Just a moment...</title></head></html>',
                    'mode_used': mode, 'error': None}
        return {'final_url': 'https://shield.com/', 'status': 200,
                'html': '<html><body><nav><a href="/contact">Contact</a></nav>'
                        '<p>Real content after the challenge cleared.</p></body></html>',
                'mode_used': 'csr', 'error': None}

    result = crawl_site('shield.com', fetch=fetch, mode='homepage')
    assert result['browser_used'] is True
    urls = [entry['page'].url for entry in result['pages']]
    assert urls == ['https://shield.com/'], urls
    assert all(key != 'https://shield.com/contact' for key, _ in calls), calls


STANDARD_SITE = {
    # homepage links score 90/70/60 (all wave-1) plus two sub-60 generic
    # links that only a deep crawl fetches
    'https://acme.com': {'html': """
        <html><body>
        <a href="/contact">Contact</a> <a href="/about">About</a>
        <a href="/careers">Careers</a>
        <a href="/products/widget-a">Widget A</a> <a href="/pricing">Pricing</a>
        <p>Welcome to Acme widgets.</p>
        </body></html>"""},
    # a wave-1 page linking onward to a fresh high scorer: deep fetches it
    # in wave 2, key_pages must not
    'https://acme.com/contact': {'html': '<html><body><p>mail hi@acme.com</p>'
                                         '<a href="/impressum">Impressum</a></body></html>'},
    'https://acme.com/about': {'html': '<html><body><p>About Acme.</p></body></html>'},
    'https://acme.com/careers': {'html': '<html><body><p>Join us!</p></body></html>'},
    'https://acme.com/impressum': {'html': '<html><body><p>Acme GmbH</p></body></html>'},
    'https://acme.com/products/widget-a': {'html': '<html><body><p>widget</p></body></html>'},
    'https://acme.com/pricing': {'html': '<html><body><p>prices</p></body></html>'},
}


def test_crawl_mode_key_pages_stops_after_wave1():
    log = []
    result = crawl_site('acme.com', fetch=make_fake_fetch(STANDARD_SITE, log),
                        mode='key_pages')
    urls = sorted(entry['page'].url for entry in result['pages'])
    assert urls == ['https://acme.com', 'https://acme.com/about',
                    'https://acme.com/careers', 'https://acme.com/contact'], urls
    fetched = {url for url, _ in log}
    assert 'https://acme.com/impressum' not in fetched, fetched
    assert 'https://acme.com/products/widget-a' not in fetched, fetched
    assert 'https://acme.com/pricing' not in fetched, fetched

    # the same site in (default) deep mode keeps crawling past wave 1
    deep = crawl_site('acme.com', fetch=make_fake_fetch(STANDARD_SITE, []))
    deep_urls = {entry['page'].url for entry in deep['pages']}
    assert 'https://acme.com/impressum' in deep_urls, deep_urls
    assert 'https://acme.com/pricing' in deep_urls, deep_urls


def test_crawl_mode_key_pages_caps_at_first_wave_max():
    # more qualifying (>=60) links than FIRST_WAVE_MAX: the cap wins
    paths = ['contact', 'about', 'team', 'impressum',
             'careers', 'jobs', 'blog', 'news']
    links = ''.join(f'<a href="/{p}">{p}</a> ' for p in paths)
    site = {'https://big.com': {'html': f'<html><body>{links}<p>hub</p></body></html>'}}
    for p in paths:
        site[f'https://big.com/{p}'] = {
            'html': f'<html><body><p>{p} page</p></body></html>'}
    log = []
    result = crawl_site('big.com', fetch=make_fake_fetch(site, log), mode='key_pages')
    assert len(result['pages']) == 1 + FIRST_WAVE_MAX, len(result['pages'])
    child_fetches = [url for url, _ in log if url != 'https://big.com']
    assert len(child_fetches) == FIRST_WAVE_MAX, child_fetches


def test_crawl_mode_key_pages_csr():
    # A csr transport spreads wave 1 over sequential one-page iterations:
    # key_pages mode keeps iterating while >=60 links remain, then stops at
    # the score floor instead of draining the frontier.
    spa = read_fixture('spa_shell.html')
    rendered_home = """<html><body><nav>
        <a href="/contact">Contact</a><a href="/about">About</a>
        <a href="/pricing">Pricing</a></nav>
        <p>Rendered app content with plenty of visible text.</p></body></html>"""
    log = []

    def fetch(url, mode='requests', blocked=False):
        key = normalize_url(url)
        log.append((key, mode))
        if mode == 'requests':
            return {'final_url': url, 'status': 200, 'html': spa,
                    'mode_used': mode, 'error': None}
        html = rendered_home if key == 'https://spa.com' else \
            '<html><body><p>Some rendered subpage text.</p></body></html>'
        return {'final_url': url, 'status': 200, 'html': html,
                'mode_used': 'csr', 'error': None}

    result = crawl_site('spa.com', fetch=fetch, mode='key_pages')
    urls = sorted(entry['page'].url for entry in result['pages'])
    assert urls == ['https://spa.com', 'https://spa.com/about',
                    'https://spa.com/contact'], urls
    assert all(key != 'https://spa.com/pricing' for key, _ in log), log


def test_crawl_mode_invalid():
    try:
        crawl_site('acme.com', fetch=lambda *a, **k: None, mode='quick')
    except ValueError as e:
        assert 'mode' in str(e), e
    else:
        raise AssertionError('invalid mode must raise ValueError')


def main():
    test_score_link()
    test_keyword_buckets_tech_pages()
    test_normalize_url()
    test_registrable_domain()
    test_classify_page_weight()
    test_needs_browser()
    test_crawl_small_site()
    test_crawl_max_pages()
    test_crawl_no_early_exit()
    test_crawl_seed_redirect_adopts_domain()
    test_crawl_seed_www_retry()
    test_crawl_unreachable()
    test_crawl_sticky_csr()
    test_wave_concurrency()
    test_fetch_many_wave()
    test_on_page_kept_receives_record()
    test_crawl_mode_homepage()
    test_crawl_mode_homepage_blocked()
    test_crawl_mode_key_pages_stops_after_wave1()
    test_crawl_mode_key_pages_caps_at_first_wave_max()
    test_crawl_mode_key_pages_csr()
    test_crawl_mode_invalid()


if __name__ == '__main__':
    main()
    print('contact_scraper crawler tests OK')
