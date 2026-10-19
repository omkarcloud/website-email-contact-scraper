# Offline tests for fetcher.py's browser path: how a nav() challenge outcome
# turns into a fetch result, the light-fetch fallbacks on a Cloudflare
# re-challenge, and is_cloudflare() - the gate that keeps every
# Cloudflare-specific step off non-Cloudflare sites.
# Zero network, no browser: a fake driver stands in for PatchrightDriver.
# Run: python3 -m src.contact_scraper.test_fetcher

from .fetcher import (ERR_CHALLENGE_REFUSED, ERR_CHALLENGE_TIMEOUT,
                      _browser_light_get, _fetch_page_browser,
                      fetch_pages_light, is_cloudflare,
                      is_cloudflare_challenge_html, needs_browser)

INTERSTITIAL = ('<html><head><title>Just a moment...</title></head><body>'
                '<script>(function(){window._cf_chl_opt = {cvId: "3"};})();</script></body></html>')
CF_BLOCK = ('<html><head><title>Attention Required! | Cloudflare</title></head><body>'
            '<div id="cf-error-details"><h1>Sorry, you have been blocked</h1></div></body></html>')
CF_PROXIED = ('<html><head><title>Shield Co</title></head><body><p>mail hi@shield.com</p>'
              '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script></body></html>')
PERIMETERX = '<html><body><p>Please verify you are a human</p></body></html>'
REAL = '<html><head><title>Shield Co</title></head><body><p>mail hi@shield.com</p></body></html>'
ABOUT = '<html><body><p>About Shield Co.</p></body></html>'


class FakeResp:
    def __init__(self, text, ok=True, status_code=200, url=''):
        self.ok, self.status_code, self.url, self.text = ok, status_code, url, text
        self.headers = {'content-type': 'text/html; charset=utf-8'}
        self.error = None if ok else 'TypeError: Failed to fetch'


def nav_result(url, html, status=200, challenge=None, title='', clicks=0, headers=None):
    return {'url': url, 'status': status, 'ok': status < 400,
            'headers': headers or {}, 'html': html, 'challenge': challenge,
            'challenge_title': title, 'challenge_clicks': clicks}


class FakeDriver:
    def __init__(self, navs=(), light=None):
        self._navs = list(navs)
        self._light = light or {}
        self.nav_calls = []
        self.cleared = []

    def nav(self, url, referer=None, mode='csr', challenge_markers=()):
        self.nav_calls.append((url, mode))
        return self._navs.pop(0)

    def get(self, url, timeout_ms=0):
        return self._light[url]

    def get_many(self, urls, timeout_ms=0):
        return [self._light[u] for u in urls]

    def clear_cookies(self, url=None):
        self.cleared.append(url)


class FakeSession:
    def __init__(self, driver):
        self.driver = driver
        self.dirty = False

    def lease(self):
        return self.driver


def r(html='', status=200, error=None, headers=None):
    return {'final_url': 'https://shield.com/', 'status': status, 'html': html,
            'mode_used': 'requests', 'error': error, 'headers': headers or {}}


def test_is_cloudflare_gate():
    assert is_cloudflare(r(INTERSTITIAL, 403))
    assert is_cloudflare(r('', 403, headers={'CF-Mitigated': 'challenge'}))
    assert is_cloudflare(r(CF_BLOCK, 403))
    assert is_cloudflare(r('', None, error=ERR_CHALLENGE_TIMEOUT))
    assert is_cloudflare(r('', 403, error=ERR_CHALLENGE_REFUSED))
    assert not is_cloudflare(r(REAL))
    assert not is_cloudflare(r(CF_PROXIED))                       # beacon only
    assert not is_cloudflare(r(PERIMETERX, 403))                   # other vendor
    assert not is_cloudflare(r('<html>Forbidden</html>', 403))     # plain 403
    assert not is_cloudflare(r('', 403, headers={'server': 'cloudflare'}))  # proxied, not challenged
    assert not is_cloudflare(r('', None, error='browser busy: no warm chrome'))
    # escalation still fires for the non-Cloudflare blocks (unchanged)
    assert needs_browser(r(PERIMETERX, 403)) == 'blocked'
    assert not is_cloudflare_challenge_html(CF_PROXIED)


def test_browser_timeout_drops_interstitial():
    url = 'https://shield.com/'
    driver = FakeDriver(navs=[nav_result(url, INTERSTITIAL, status=403, challenge='timeout',
                                         title='just a moment...', clicks=2,
                                         headers={'cf-mitigated': 'challenge'})])
    result = _fetch_page_browser(driver, url, light=False, is_blocked=True)
    assert result['html'] == '', result
    assert result['error'] == ERR_CHALLENGE_TIMEOUT, result['error']
    assert result['status'] == 403 and result['mode_used'] == 'csr', result
    assert result['headers'] == {'cf-mitigated': 'challenge'}
    assert driver.cleared == []
    assert needs_browser(result) == 'blocked' and is_cloudflare(result)


def test_browser_refused_clears_host_cookies():
    url = 'https://shield.com/'
    driver = FakeDriver(navs=[nav_result(url, CF_BLOCK, status=403, challenge='refused',
                                         title='attention required! | cloudflare')])
    result = _fetch_page_browser(driver, url, light=False, is_blocked=True)
    assert result['error'] == ERR_CHALLENGE_REFUSED, result
    assert result['html'] == ''
    assert driver.cleared == [url], driver.cleared


def test_browser_cleared_is_a_normal_page():
    url = 'https://shield.com/'
    driver = FakeDriver(navs=[nav_result(url, REAL, status=200, challenge='cleared',
                                         title='shield co', clicks=1)])
    result = _fetch_page_browser(driver, url, light=False, is_blocked=True)
    assert result['error'] is None and result['html'] == REAL, result
    assert result['status'] == 200 and needs_browser(result) is False


def test_browser_non_cloudflare_block_passes_through():
    # Another vendor's interstitial in the browser: challenge None, the html
    # is returned as before (the crawler decides what to do with it).
    url = 'https://shield.com/'
    driver = FakeDriver(navs=[nav_result(url, PERIMETERX, status=403)])
    result = _fetch_page_browser(driver, url, light=False, is_blocked=True)
    assert result['error'] is None and result['html'] == PERIMETERX, result
    assert driver.cleared == []


def test_light_get_cloudflare_rechallenge_returns_none():
    driver = FakeDriver(light={
        'https://shield.com/contact': FakeResp(INTERSTITIAL, url='https://shield.com/contact'),
        'https://shield.com/about': FakeResp(ABOUT, url='https://shield.com/about'),
        'https://shield.com/px': FakeResp(PERIMETERX, status_code=403, url='https://shield.com/px'),
    })
    assert _browser_light_get(driver, 'https://shield.com/contact') is None
    about = _browser_light_get(driver, 'https://shield.com/about')
    assert about['html'] == ABOUT and about['mode_used'] == 'blocked', about
    # other vendors: returned as-is, exactly like before
    px = _browser_light_get(driver, 'https://shield.com/px')
    assert px['html'] == PERIMETERX and px['status'] == 403, px


def test_fetch_pages_light_cloudflare_rechallenge_falls_back():
    contact, about, px = ('https://shield.com/contact', 'https://shield.com/about',
                          'https://shield.com/px')
    driver = FakeDriver(
        navs=[nav_result(contact, REAL, status=200, challenge='cleared', title='shield co', clicks=1)],
        light={contact: FakeResp(INTERSTITIAL, url=contact), about: FakeResp(ABOUT, url=about),
               px: FakeResp(PERIMETERX, status_code=403, url=px)})
    session = FakeSession(driver)
    out = fetch_pages_light([contact, about, px], session)
    assert driver.nav_calls == [(contact, 'blocked')], driver.nav_calls   # px NOT navigated
    assert out[0]['html'] == REAL and out[0]['mode_used'] == 'csr' and out[0]['error'] is None, out[0]
    assert out[1]['html'] == ABOUT and out[1]['mode_used'] == 'blocked', out[1]
    assert out[2]['html'] == PERIMETERX and out[2]['mode_used'] == 'blocked', out[2]
    assert session.dirty is False


def test_fetch_pages_light_transport_failure_still_falls_back():
    contact = 'https://shield.com/contact'
    driver = FakeDriver(navs=[nav_result(contact, REAL, status=200)],
                        light={contact: FakeResp('', ok=False, status_code=0, url=contact)})
    out = fetch_pages_light([contact], FakeSession(driver))
    assert driver.nav_calls == [(contact, 'blocked')], driver.nav_calls
    assert out[0]['html'] == REAL and out[0]['mode_used'] == 'csr', out[0]


def main():
    test_is_cloudflare_gate()
    test_browser_timeout_drops_interstitial()
    test_browser_refused_clears_host_cookies()
    test_browser_cleared_is_a_normal_page()
    test_browser_non_cloudflare_block_passes_through()
    test_light_get_cloudflare_rechallenge_returns_none()
    test_fetch_pages_light_cloudflare_rechallenge_falls_back()
    test_fetch_pages_light_transport_failure_still_falls_back()


if __name__ == '__main__':
    main()
    print('contact_scraper fetcher tests OK')
