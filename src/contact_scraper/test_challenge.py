# Offline tests for the driver's Cloudflare challenge handling: detection
# (cloudflare_verdict), the Turnstile click geometry and the
# _settle_challenge loop, against a fake page with a fake clock (zero
# network, no browser). The rule under test: the loop runs on Cloudflare's
# own pages ONLY - every other page returns at once, untouched.
# Run: python3 -m src.contact_scraper.test_challenge

try:
    from . import patchright_driver as pd          # open-source layout
except ImportError:
    import patchright_driver as pd                 # omkar-apis layout

CF_FRAME_URL = 'https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/b/turnstile/if/ov2/av0/rcv/x'
INTERSTITIAL = ('<html><head><title>Just a moment...</title></head><body>'
                '<script>(function(){window._cf_chl_opt = {cvId: "3", cType: "managed"};'
                'var a=document.createElement("script");'
                'a.src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1?ray=8f";})();'
                '</script></body></html>')
REAL = '<html><head><title>Acme Inc</title></head><body><p>Welcome to Acme.</p></body></html>'
# An ordinary page behind Cloudflare Bot Management: the jsd beacon only.
CF_PROXIED = ('<html><head><title>Acme Inc</title></head><body><p>Welcome.</p>'
              '<script>(function(){var a=document.createElement("script");'
              'a.src="/cdn-cgi/challenge-platform/scripts/jsd/main.js";})();</script></body></html>')
# A contact form protected by a Turnstile widget - a normal page.
TURNSTILE_FORM = ('<html><head><title>Contact us | Acme</title>'
                  '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script></head>'
                  '<body><form><div class="cf-turnstile" data-sitekey="0x4AAA"></div>'
                  '<iframe src="' + CF_FRAME_URL + '"></iframe></form></body></html>')
CF_BLOCK = ('<html><head><title>Attention Required! | Cloudflare</title></head><body>'
            '<div id="cf-error-details"><h1>Sorry, you have been blocked</h1>'
            '<h2>You are unable to access acme.com</h2></div></body></html>')
CF_522 = ('<html><head><title>acme.com | 522: Connection timed out</title></head><body>'
          '<div id="cf-error-details"><h1>Connection timed out</h1></div></body></html>')
PERIMETERX = '<html><head><title>Access to this page has been denied</title></head><body><p>Please verify you are a human</p></body></html>'
DATADOME = "<html><head><title>acme.com</title></head><body><script>var dd={'rt':'c','cid':'x'}</script></body></html>"
AKAMAI_DENIED = '<html><head><title>Access Denied</title></head><body>You don\'t have permission to access "http://acme.com/". Reference #18.1</body></html>'
APP_LOADING = '<html><head><title>Just a moment...</title></head><body><div id="root"></div></body></html>'
BLOG_ABOUT_CF = ('<html><head><title>How Cloudflare challenges work</title></head><body>'
                 '<p>The "Just a moment..." page loads /cdn-cgi/challenge-platform/ scripts.</p></body></html>')


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeFrame:
    def __init__(self, url, box=None, raises=False):
        self.url, self.box, self.raises = url, box, raises

    def frame_element(self):
        if self.raises:
            raise RuntimeError('frame detached')
        return self

    def bounding_box(self):
        return self.box


class FakeMouse:
    def __init__(self, clock):
        self.clock = clock
        self.events = []

    def move(self, x, y, steps=1):
        self.events.append(('move', x, y, self.clock.t))

    def down(self):
        self.events.append(('down', self.clock.t))

    def up(self):
        self.events.append(('up', self.clock.t))


class FakePage:
    """title() / content snapshots are consumed one per poll from the given
    sequences (the last value sticks); an Exception entry is raised, which
    is how a mid-reload "execution context destroyed" looks to the loop."""

    def __init__(self, clock, frames=(), titles=('',), htmls=('',)):
        self.clock = clock
        self.frames = list(frames)
        self.mouse = FakeMouse(clock)
        self._titles = list(titles)
        self._htmls = list(htmls)
        self.waits = []

    @staticmethod
    def _next(seq):
        value = seq.pop(0) if len(seq) > 1 else seq[0]
        if isinstance(value, Exception):
            raise value
        return value

    def title(self):
        return self._next(self._titles)

    def evaluate(self, js, arg=None):
        if 'querySelectorAll' in js:
            return 10
        return self._next(self._htmls)

    def inner_text(self, selector, timeout=None):
        return 'x' * 300

    def wait_for_timeout(self, ms):
        self.waits.append(ms)
        self.clock.t += ms / 1000.0

    def wait_for_load_state(self, *args, **kwargs):
        pass


def _with_fake_clock(fn):
    clock = FakeClock()
    real_now = pd._now
    pd._now = clock
    try:
        return fn(clock)
    finally:
        pd._now = real_now


def _cf_widget():
    return FakeFrame(CF_FRAME_URL, {'x': 100, 'y': 200, 'width': 300, 'height': 65})


# ---- detection ---------------------------------------------------------------

def test_verdict_cloudflare_pages():
    v = pd.cloudflare_verdict
    assert v('just a moment...', INTERSTITIAL) == 'challenge'
    assert v('', INTERSTITIAL) == 'challenge'                         # config alone
    assert v('acme', '<html></html>', cf_mitigated=True) == 'challenge'  # header alone
    assert v('attention required! | cloudflare', CF_BLOCK) == 'refused'
    assert v('', CF_BLOCK) == 'refused'                                # html alone
    assert v('access denied | acme.com used cloudflare to restrict access', '<html></html>') == 'refused'


def test_verdict_everything_else_is_none():
    v = pd.cloudflare_verdict
    cases = [
        ('acme inc', REAL),
        ('acme inc', CF_PROXIED),                      # jsd beacon only
        ('contact us | acme', TURNSTILE_FORM),         # Turnstile form widget
        ('acme.com | 522: connection timed out', CF_522),   # CF origin error
        ('access to this page has been denied', PERIMETERX),
        ('acme.com', DATADOME),
        ('access denied', AKAMAI_DENIED),              # Akamai, not Cloudflare
        ('just a moment...', APP_LOADING),             # an app's own loading title
        ('how cloudflare challenges work', BLOG_ABOUT_CF),
        (None, None),
        ('', ''),
    ]
    for title, html in cases:
        assert v(title, html) is None, (title, (html or '')[:60])


def test_verdict_on_probe_output():
    # In the browser the loop sees _cf_markers' output - only the markers
    # present, newline-joined - not the document. Same verdicts.
    v = pd.cloudflare_verdict
    assert v('just a moment...', '_cf_chl_opt\nchallenge-platform') == 'challenge'
    assert v('verifying...', '_cf_chl_opt') == 'challenge'
    assert v('just a moment...', 'challenge-platform') == 'challenge'
    assert v('acme inc', 'challenge-platform') is None                 # jsd beacon
    assert v('just a moment...', '') is None                            # app loading title
    assert v('acme.com | 522: connection timed out', 'id="cf-error-details"') is None
    assert v('attention required! | cloudflare', '') == 'refused'
    assert v('', 'id="cf-error-details"\nSorry, you have been blocked') == 'refused'
    assert set(pd._CF_PROBE_MARKERS) >= set(pd.CF_CHALLENGE_HTML) | set(pd.CF_REFUSED_HTML)


# ---- click geometry ----------------------------------------------------------

def test_click_turnstile_clicks_cf_frame():
    clock = FakeClock()
    page = FakePage(clock, frames=[
        FakeFrame('https://www.google.com/recaptcha/api2/anchor', {'x': 0, 'y': 0, 'width': 300, 'height': 80}),
        _cf_widget(),
    ])
    assert pd.click_turnstile(page) is True
    kinds = [e[0] for e in page.mouse.events]
    assert kinds == ['move', 'down', 'up'], page.mouse.events
    _, x, y, _ = page.mouse.events[0]
    assert abs(x - (100 + 300 / 9)) <= 5.01, x
    assert abs(y - (200 + 65 / 2)) <= 5.01, y
    assert page.waits and all(50 <= w <= 300 for w in page.waits), page.waits


def test_click_turnstile_skips_non_cf_and_tiny():
    clock = FakeClock()
    page = FakePage(clock, frames=[
        FakeFrame('https://www.google.com/recaptcha/api2/anchor', {'x': 0, 'y': 0, 'width': 300, 'height': 80}),
        FakeFrame(CF_FRAME_URL, {'x': 0, 'y': 0, 'width': 20, 'height': 20}),   # collapsed widget
        FakeFrame(CF_FRAME_URL, raises=True),                                     # detached
        FakeFrame(CF_FRAME_URL, None),                                            # not laid out
    ])
    assert pd.click_turnstile(page) is False
    assert page.mouse.events == [], page.mouse.events


# ---- the loop runs ONLY on Cloudflare ----------------------------------------

def test_settle_non_cloudflare_pages_return_at_once():
    # Every non-Cloudflare page - including a contact form whose Turnstile
    # widget frame IS on the page - returns None with no wait and no click.
    pages = [('Acme Inc', REAL), ('Acme Inc', CF_PROXIED),
             ('Contact us | Acme', TURNSTILE_FORM), ('Access to this page has been denied', PERIMETERX),
             ('acme.com', DATADOME), ('Access Denied', AKAMAI_DENIED),
             ('Just a moment...', APP_LOADING), ('acme.com | 522: Connection timed out', CF_522)]
    for title, html in pages:
        def run(clock, title=title, html=html):
            page = FakePage(clock, frames=[_cf_widget()], titles=[title], htmls=[html])
            outcome = pd._settle_challenge(page, budget_ms=25000)
            assert outcome == (None, title.lower(), 0), (title, outcome)
            assert page.waits == [] and page.mouse.events == [], (title, page.waits, page.mouse.events)
        _with_fake_clock(run)


def test_settle_unreadable_page_without_cf_evidence_is_none():
    # A document that stays unreadable (mid-redirect) with no Cloudflare
    # header: three short reads, then hands back - never the 25 s loop.
    def run(clock):
        boom = RuntimeError('Execution context was destroyed')
        page = FakePage(clock, titles=[boom], htmls=[boom])
        outcome = pd._settle_challenge(page, budget_ms=25000)
        assert outcome[0] is None and outcome[2] == 0, outcome
        assert sum(page.waits) <= 1000, page.waits
        assert page.mouse.events == []
    _with_fake_clock(run)


def test_settle_cf_mitigated_header_enters_loop():
    # The header alone is Cloudflare evidence: even if the first snapshot is
    # unreadable, the loop runs and reports the page that lands.
    def run(clock):
        boom = RuntimeError('Execution context was destroyed')
        page = FakePage(clock, titles=[boom, boom, boom, boom, 'Acme Inc'],
                        htmls=[boom, boom, boom, boom, REAL])
        outcome = pd._settle_challenge(page, budget_ms=25000, cf_mitigated=True)
        assert outcome == ('cleared', 'acme inc', 0), outcome
    _with_fake_clock(run)


def test_settle_challenge_clears_after_click():
    def run(clock):
        start = clock.t
        page = FakePage(clock, frames=[_cf_widget()],
                        titles=['Just a moment...'] * 8 + ['Acme Inc'],
                        htmls=[INTERSTITIAL] * 8 + [REAL])
        outcome, title, clicks = pd._settle_challenge(page, budget_ms=25000)
        assert outcome == 'cleared', (outcome, title)
        assert title == 'acme inc', title
        assert clicks == 1, clicks
        downs = [e for e in page.mouse.events if e[0] == 'down']
        assert len(downs) == 1 and downs[0][1] - start >= 3.0, (downs, start)
    _with_fake_clock(run)


def test_settle_challenge_clears_without_click():
    # The common case on a clean IP: Cloudflare clears itself before the
    # first click is due.
    def run(clock):
        page = FakePage(clock, frames=[_cf_widget()],
                        titles=['Just a moment...'] * 3 + ['Acme Inc'],
                        htmls=[INTERSTITIAL] * 3 + [REAL])
        assert pd._settle_challenge(page, budget_ms=25000) == ('cleared', 'acme inc', 0)
        assert page.mouse.events == []
    _with_fake_clock(run)


def test_settle_challenge_clears_into_turnstile_form():
    # The real page behind the challenge happens to embed a Turnstile form:
    # that is "cleared", not "still challenged".
    def run(clock):
        page = FakePage(clock, frames=[_cf_widget()],
                        titles=['Just a moment...', 'Contact us | Acme'],
                        htmls=[INTERSTITIAL, TURNSTILE_FORM])
        assert pd._settle_challenge(page, budget_ms=25000)[0] == 'cleared'
    _with_fake_clock(run)


def test_settle_challenge_timeout():
    def run(clock):
        start = clock.t
        page = FakePage(clock, frames=[_cf_widget()],
                        titles=['Just a moment...'], htmls=[INTERSTITIAL])
        outcome, title, clicks = pd._settle_challenge(page, budget_ms=6000)
        assert outcome == 'timeout', outcome
        assert title == 'just a moment...', title
        assert 1 <= clicks <= pd.CHALLENGE_MAX_CLICKS, clicks
        assert clock.t - start >= 6.0, clock.t - start
    _with_fake_clock(run)


def test_settle_challenge_click_cadence_capped():
    def run(clock):
        page = FakePage(clock, frames=[_cf_widget()],
                        titles=['Just a moment...'], htmls=[INTERSTITIAL])
        outcome, _, clicks = pd._settle_challenge(page, budget_ms=60000)
        assert outcome == 'timeout'
        assert clicks == pd.CHALLENGE_MAX_CLICKS, clicks
        downs = [e[1] for e in page.mouse.events if e[0] == 'down']
        gaps = [b - a for a, b in zip(downs, downs[1:])]
        assert all(g >= pd.CHALLENGE_CLICK_EVERY_MS / 1000 for g in gaps), gaps
    _with_fake_clock(run)


def test_settle_challenge_refused():
    def run(clock):
        page = FakePage(clock, frames=[_cf_widget()],
                        titles=['Attention Required! | Cloudflare'], htmls=[CF_BLOCK])
        outcome = pd._settle_challenge(page, budget_ms=6000)
        assert outcome == ('refused', 'attention required! | cloudflare', 0), outcome
        assert page.mouse.events == [] and page.waits == []
    _with_fake_clock(run)


def test_settle_challenge_refused_mid_loop():
    def run(clock):
        page = FakePage(clock,
                        titles=['Just a moment...', 'Just a moment...',
                                'Access denied | acme.com used Cloudflare to restrict access'],
                        htmls=[INTERSTITIAL, INTERSTITIAL, '<html><body>blocked</body></html>'])
        outcome, title, clicks = pd._settle_challenge(page, budget_ms=6000)
        assert outcome == 'refused', (outcome, title)
        assert clicks == 0
    _with_fake_clock(run)


def test_settle_challenge_mid_reload_tolerated():
    # title()/content raise while Cloudflare's clearance reload is in
    # flight; the loop keeps polling and reports the page that lands.
    def run(clock):
        boom = RuntimeError('Execution context was destroyed')
        page = FakePage(clock,
                        titles=['Just a moment...', boom, boom, 'Acme Inc'],
                        htmls=[INTERSTITIAL, boom, boom, REAL])
        assert pd._settle_challenge(page, budget_ms=6000) == ('cleared', 'acme inc', 0)
    _with_fake_clock(run)


def test_settle_csr_zero_budget_returns_at_once():
    clock = FakeClock()
    page = FakePage(clock, titles=['x'], htmls=['<html></html>'])
    pd._settle_csr(page, budget_ms=0)
    assert page.waits == [], page.waits


def main():
    test_verdict_cloudflare_pages()
    test_verdict_everything_else_is_none()
    test_verdict_on_probe_output()
    test_click_turnstile_clicks_cf_frame()
    test_click_turnstile_skips_non_cf_and_tiny()
    test_settle_non_cloudflare_pages_return_at_once()
    test_settle_unreadable_page_without_cf_evidence_is_none()
    test_settle_cf_mitigated_header_enters_loop()
    test_settle_challenge_clears_after_click()
    test_settle_challenge_clears_without_click()
    test_settle_challenge_clears_into_turnstile_form()
    test_settle_challenge_timeout()
    test_settle_challenge_click_cadence_capped()
    test_settle_challenge_refused()
    test_settle_challenge_refused_mid_loop()
    test_settle_challenge_mid_reload_tolerated()
    test_settle_csr_zero_budget_returns_at_once()


if __name__ == '__main__':
    main()
    print('contact_scraper challenge tests OK')
