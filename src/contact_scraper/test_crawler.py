# Offline tests for crawler.py + fetcher.needs_browser (zero network: the
# crawl tests inject a fake fetch). Run: python3 -m contact_scraper.test_crawler

import os

from .crawler import (MAX_PAGES, EARLY_EXIT_MIN_PAGES, classify_page_weight,
                      crawl_site, normalize_url, registrable_domain, score_link)
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
    def fetch(url, mode='requests'):
        key = normalize_url(url)
        log.append((key, mode))
        entry = site.get(key)
        if entry is None:
            return {'final_url': url, 'status': None, 'html': '',
                    'mode_used': mode, 'error': 'ConnectionError: refused'}
        return {'final_url': entry.get('final_url', url),
                'status': entry.get('status', 200),
                'html': entry['html'], 'mode_used': mode, 'error': None}
    return fetch


def test_score_link():
    contact = score_link('/contact', 'Contact', False, False, 1)
    impressum = score_link('/impressum', 'Impressum', False, False, 1)
    about = score_link('/about', 'About us', False, False, 1)
    support = score_link('/support', 'Support', False, False, 1)
    privacy = score_link('/privacy', 'Privacy Policy', False, False, 1)
    generic = score_link('/blog/post1', 'Read more', False, False, 1)
    assert contact > impressum > about > support > privacy > generic

    # anchor text alone can trigger a category
    assert score_link('/de/seite-7', 'Kontakt aufnehmen', False, False, 1) == contact

    assert score_link('/contact', 'Contact', True, False, 1) == contact + 20   # footer
    assert score_link('/contact', 'Contact', False, True, 1) == contact + 10   # nav
    assert score_link('/contact', 'Contact', True, True, 1) == contact + 30
    assert score_link('/contact', 'Contact', False, False, 2) == contact - 10  # depth


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
        </body></html>"""},
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

    urls = [entry['page'].url for entry in result['pages']]
    assert urls == ['https://acme.com', 'https://acme.com/contact',
                    'https://acme.com/about', 'https://acme.com/blog/post1'], urls
    # contact (score 100) fetched before blog (score 0)
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
    assert len(log) == MAX_PAGES  # 1 homepage + 19 children, no over-fetch


def test_crawl_early_exit():
    log = []
    result = crawl_site('big.com', fetch=make_fake_fetch(make_big_site(), log),
                        early_exit_check=lambda count, best_score: True)
    assert len(result['pages']) == EARLY_EXIT_MIN_PAGES, len(result['pages'])


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
    # bare host refuses connections; www. works
    site = {'https://www.onlywww.com': {'html': '<html><body><p>hello world</p></body></html>',
                                        'final_url': 'https://www.onlywww.com/'}}

    def fetch(url, mode='requests'):
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
    def fetch(url, mode='requests'):
        return {'final_url': url, 'status': None, 'html': '',
                'mode_used': mode, 'error': 'ConnectionError: refused'}

    result = crawl_site('dead.example', fetch=fetch)
    assert result == {'domain': 'dead.example',
                      'pages': [], 'browser_used': False,
                      'homepage_headers': {},
                      'error': 'ConnectionError: refused'}


def test_crawl_sticky_browser():
    spa = read_fixture('spa_shell.html')
    rendered_home = """<html><body><nav><a href="/contact">Contact</a></nav>
                       <p>Rendered app content with plenty of visible text.</p>
                       </body></html>"""
    modes_by_call = []

    def fetch(url, mode='requests'):
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
    # seed via requests, refetched via browser, children browser-only
    assert modes_by_call[0] == ('https://spa.com', 'requests')
    assert modes_by_call[1] == ('https://spa.com', 'browser')
    assert all(mode == 'browser' for _, mode in modes_by_call[1:])
    assert len(result['pages']) == 2


def main():
    test_score_link()
    test_normalize_url()
    test_registrable_domain()
    test_classify_page_weight()
    test_needs_browser()
    test_crawl_small_site()
    test_crawl_max_pages()
    test_crawl_early_exit()
    test_crawl_seed_redirect_adopts_domain()
    test_crawl_seed_www_retry()
    test_crawl_unreachable()
    test_crawl_sticky_browser()


if __name__ == '__main__':
    main()
    print('contact_scraper crawler tests OK')
