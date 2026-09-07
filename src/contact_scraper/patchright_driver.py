"""Patchright (patched Playwright Chrome) driver for chrome_manager pools.

Real Chrome (channel="chrome", headed) passes Cloudflare and similar
challenge walls where plain headless Chrome gets challenged, which is why
the crawler's blocked-mode fallback runs on it.

Patchright wraps Playwright's *sync* API, which is greenlet-bound: every object
must be used from the thread that created it. chrome_manager builds drivers on
warmer threads and serves them to request/crawl threads, so each
PatchrightDriver owns a dedicated daemon thread that launches the browser and
executes every page operation; the public methods marshal callables onto that
thread and wait for the result.

The browser runs headed by default (Cloudflare flags headless Chrome). On
Linux without a DISPLAY, one process-wide Xvfb virtual display is started
lazily and shared by every driver (pyvirtualdisplay, the same mechanism
botasaurus uses) — it lives for the process lifetime, so a driver restart
never yanks the display out from under live browsers. Pools that face no
anti-bot (the contact-csr renderer) can opt into headless=True and
block_resources=[...] so client-side apps render without images/CSS/fonts/
media: image and font are Chrome flags (never requested at all), stylesheet
and media are aborted through a URL-pattern route (see _BLOCK_URL_PATTERNS).

Each driver gets a throwaway profile dir (fresh identity per driver); close()
removes it. A wedged page op (call() timeout) leaves the owner thread stuck
inside Playwright, so close() force-kills the driver's OS process tree (the
playwright node driver; Chrome runs under it), recorded by pid-diff around
the launch. kill_orphan_browsers() lets the pool janitor reap any tree that
still slips through — identified by the playwright run-driver cmdline of the
tree root.
"""
import json
from botasaurus.env import IS_IN_KUBERNETES, IS_DOCKER, get_os
import os
import queue
import re
import shutil
import sys
import tempfile
import threading
import time
from urllib.parse import urlparse

import psutil
from patchright.sync_api import sync_playwright

STARTUP_TIMEOUT = 120    # browser launch + first page
CALL_TIMEOUT = 90        # hard ceiling per marshalled op
GOTO_TIMEOUT_MS = 60000  # residential exits are slow
FETCH_TIMEOUT_MS = 30000  # per in-page fetch (AbortSignal), under CALL_TIMEOUT

# nav() settle budgets. IDLE is the networkidle fast-exit cap (most pages go
# idle well under 1s; chatty analytics/websocket pages exit at the cap).
# BUDGET is the total deadline for the smart paths: the csr empty-shell
# stability poll and the blocked challenge-clear poll.
SETTLE_IDLE_MS = 2000
SETTLE_BUDGET_MS = 8000

# In-page fetch run from the loaded page, so it inherits the page's cookies,
# Cloudflare clearance and TLS fingerprint. The browser attaches the forbidden
# headers (sec-ch-ua*, sec-fetch-*, referer via the referrer option) itself.
# Never throws across the evaluate bridge: returns a structured object so the
# Python side gets a clean error taxonomy.
_FETCH_JS = """async ({url, method, headers, body, referrer, timeoutMs}) => {
    try {
        const r = await fetch(url, {
            method: method || 'GET',
            credentials: 'include',
            headers: headers || {},
            body: body || undefined,
            referrer: referrer || undefined,
            referrerPolicy: 'strict-origin-when-cross-origin',
            signal: AbortSignal.timeout(timeoutMs),
        });
        return { ok: true, status: r.status, url: r.url, body: await r.text(),
                 headers: Object.fromEntries(r.headers.entries()) };
    } catch (e) {
        return { ok: false, status: 0, url: '', body: '', headers: {}, error: String(e) };
    }
}"""

# Batched variant of _FETCH_JS: N fetches launched from one evaluate() call,
# each after i*staggerMs (like a page firing its subresource requests), all
# awaited together. Per-request failures are contained — the array always
# comes back with one structured result per input, in input order.
_FETCH_MANY_JS = """async ({requests, timeoutMs, staggerMs}) => {
    const one = async ({url, method, headers, body, referrer}, i) => {
        try {
            if (i && staggerMs)
                await new Promise(res => setTimeout(res, i * staggerMs));
            const r = await fetch(url, {
                method: method || 'GET',
                credentials: 'include',
                headers: headers || {},
                body: body || undefined,
                referrer: referrer || undefined,
                referrerPolicy: 'strict-origin-when-cross-origin',
                signal: AbortSignal.timeout(timeoutMs),
            });
            return { ok: true, status: r.status, url: r.url, body: await r.text(),
                     headers: Object.fromEntries(r.headers.entries()) };
        } catch (e) {
            return { ok: false, status: 0, url: '', body: '', headers: {}, error: String(e) };
        }
    };
    return Promise.all(requests.map(one));
}"""

# Inter-launch spacing inside one get_many batch. Zero: stress runs showed
# no Cloudflare blocks without it.
FETCH_STAGGER_MS = 0

DEFAULT_FETCH_HEADERS = {
    "accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,image/apng,*/*;q=0.8"),
    "accept-language": "en-US,en;q=0.6",
}

# Live (unclosed) drivers, so kill_orphan_browsers() knows which OS processes
# are legitimately owned. Guarded by _drivers_lock.
_drivers = set()
_drivers_lock = threading.Lock()

# One shared Xvfb for every patchright driver (Linux containers only).
_display = None
_display_lock = threading.Lock()


def _ensure_display():
    """Start the process-wide virtual display once (Linux, no DISPLAY).
    pyvirtualdisplay exports DISPLAY into os.environ, which the Chrome
    processes inherit at launch."""
    global _display
    if not sys.platform.startswith("linux") or os.environ.get("DISPLAY"):
        return
    with _display_lock:
        if _display is not None:
            return
        from pyvirtualdisplay import Display
        _display = Display(visible=False, size=(1920, 1080))
        _display.start()
        print("patchright: started shared Xvfb virtual display")


def _children_since(pre_launch_pids):
    """Direct children of this process spawned since the snapshot — the OS
    processes of the driver being launched (playwright node driver; Chrome and
    its helpers live under it). Valid because chrome_manager serializes
    construction (_create_lock)."""
    kids = []
    for p in psutil.Process().children():
        if p.pid in pre_launch_pids:
            continue
        try:
            if "resource_tracker" in " ".join(p.cmdline()):
                continue
        except psutil.Error:
            pass
        kids.append(p)
    return kids


def _kill_tree(root):
    """SIGKILL a process and all its descendants. psutil checks creation time
    before signalling, so a recycled pid is a no-op, not a stray kill."""
    try:
        procs = [root] + root.children(recursive=True)
    except psutil.NoSuchProcess:
        return
    for p in procs:
        try:
            p.kill()
        except psutil.Error:
            pass


def _is_playwright_root(proc):
    """True when proc is a playwright/patchright node driver — the root of a
    patchright browser tree."""
    try:
        cmd = " ".join(proc.cmdline())
    except psutil.Error:
        return False
    return "run-driver" in cmd and ("playwright" in cmd or "patchright" in cmd)


def kill_orphan_browsers():
    """Janitor safety net: SIGKILL every patchright browser tree no live driver
    owns. MUST be called with chrome_manager's _create_lock held so no launch
    is mid-flight — otherwise a half-launched browser has processes no driver
    owns yet and would be reaped as an orphan."""
    with _drivers_lock:
        owned = {p.pid for d in _drivers for p in d._procs}
    killed = 0
    for child in psutil.Process().children():
        if child.pid in owned or not _is_playwright_root(child):
            continue
        try:
            tree_len = len(child.children(recursive=True)) + 1
        except psutil.Error:
            tree_len = 1
        _kill_tree(child)
        killed += 1
        print(f"patchright: killed orphaned browser tree "
              f"(root pid {child.pid}, {tree_len} procs)")
    return killed


class FetchResponse:
    """Minimal requests-like result from an in-page fetch. NOT raised on
    HTTP/network errors — inspect `.ok`, `.status_code`, `.error`.

      ok           False only for transport failures (network error / abort
                   timeout / bridge miss), NOT for HTTP 4xx/5xx.
      status_code  HTTP status (0 when the fetch never completed).
      url          final URL after redirects ('' when the fetch never completed).
      text         response body as text.
      headers      response headers, lowercase keys ({} when the fetch never
                   completed; Set-Cookie and cross-origin headers are withheld
                   by the browser's fetch API).
      error        transport error string when ok is False, else None.
    """

    def __init__(self, ok, status_code, url, text, error=None, headers=None):
        self.ok = ok
        self.status_code = status_code
        self.url = url
        self.text = text
        self.headers = headers or {}
        self.error = error

    def json(self):
        return json.loads(self.text)

    def __repr__(self):
        return (f"<FetchResponse ok={self.ok} status={self.status_code} "
                f"bytes={len(self.text)}>")


# page.content() serializes the ENTIRE DOM. A runaway page (infinite-scroll
# feed, a JS append loop) makes that a multi-GB string in BOTH the renderer
# and Python - and the csr settle poll re-serializes it every 300ms; observed
# OOM-killing contact crawls at 5-12GB anon-rss. Slicing inside the page keeps
# every copy under the cap; 20MB is far above any legitimate page this stack
# parses (callers apply their own tighter caps downstream).
_MAX_CONTENT_CHARS = 20_000_000

_CAPPED_CONTENT_JS = """n => {
    const dt = document.doctype
        ? new XMLSerializer().serializeToString(document.doctype) + '\\n' : '';
    const el = document.documentElement;
    return dt + (el ? el.outerHTML.slice(0, n) : '');
}"""


def _capped_content(page):
    """content()-equivalent snapshot, sliced in-page to _MAX_CONTENT_CHARS.
    Raises like page.content() while a navigation is in flight."""
    return page.evaluate(_CAPPED_CONTENT_JS, _MAX_CONTENT_CHARS)


def _page_content(page):
    """_capped_content that returns None instead of raising while a navigation
    is in flight (Cloudflare's clearance reload destroys the execution
    context mid-poll)."""
    try:
        return _capped_content(page)
    except Exception:
        return None


def _settle_csr(page):
    """networkidle fast-exit, then a content-length stability poll ONLY when
    the page still looks like an unrendered app shell — fast pages pay the
    old <=2s wait, slow SPAs get up to SETTLE_BUDGET_MS to render.

    Every probe is deadline-checked. A page whose JS never stops working
    (SPA render loop, runaway allocation) makes each individual probe block
    for its own timeout: unchecked, a handful of them serialize past the
    driver's CALL_TIMEOUT and the caller sees a "wedged" driver rather than
    the partial page that was already renderable. The budget is the whole
    settle phase, not per probe."""
    start = time.monotonic()

    def left_ms(cap):
        # Remaining settle budget, clamped to `cap`; 0 when spent.
        return max(0, min(cap, int(SETTLE_BUDGET_MS - (time.monotonic() - start) * 1000)))

    try:
        page.wait_for_load_state("networkidle", timeout=min(SETTLE_IDLE_MS, SETTLE_BUDGET_MS))
    except Exception:
        pass
    probe_ms = left_ms(1000)
    if probe_ms:
        try:
            innertxt = page.inner_text("body", timeout=probe_ms) or ""
            if len(innertxt) >= 200 and page.evaluate("document.querySelectorAll('a').length") >= 5:
                return
        except Exception:
            # body not queryable yet (blank shell, or the execution context was
            # destroyed by a mid-render navigation) - exactly the pages the
            # stability poll below exists for, so fall through to it.
            pass
    prev = None
    while left_ms(SETTLE_BUDGET_MS):
        page.wait_for_timeout(min(300, left_ms(300)) or 1)
        html = _page_content(page)
        cur = len(html) if html is not None else None
        if cur is not None and cur == prev:
            return
        prev = cur


def _settle_blocked(page, markers):
    """Challenge-clear poll: return immediately when no challenge markup is
    on the page (plain 403s never had one, nothing to wait for); otherwise
    poll until the interstitial swaps itself out for the real page, capped
    at SETTLE_BUDGET_MS."""
    html = _page_content(page)
    if html is not None and not any(m in html for m in markers):
        return
    deadline = time.monotonic() + SETTLE_BUDGET_MS / 1000
    while time.monotonic() < deadline:
        page.wait_for_timeout(400)
        html = _page_content(page)
        if html is None:
            continue  # mid-reload: the challenge is clearing right now
        if not any(m in html for m in markers):
            # Cleared - give the real page a moment to finish loading.
            try:
                page.wait_for_load_state("networkidle", timeout=1000)
            except Exception:
                pass
            return


def _proxy_dict(proxy_url):
    """http://user:pass@host:port -> playwright proxy dict."""
    u = urlparse(proxy_url)
    return {
        "server": f"http://{u.hostname}:{u.port}",
        "username": u.username,
        "password": u.password,
    }


# block_resources types aborted through a URL-pattern route, keyed by resource
# type -> the URL shapes that carry it ("image" and "font" are Chrome flags
# instead, see PatchrightDriver.__init__). The compiled union is handed to
# context.route(): playwright ships a string/regex route pattern to its driver
# as the interception pattern, so non-matching requests are continued inside
# the driver process and only the requests to abort ever cross the pipe into
# Python. URL matching is deliberately loose (extension-less assets and blob:
# media slip through) - the goal is bandwidth and renderer memory, not an
# airtight block.
_BLOCK_URL_PATTERNS = {
    "stylesheet": r"\.css(?:[?#]|$)|//fonts\.googleapis\.com/",
    "media": r"\.(?:mp4|webm|m4v|mov|mp3|m4a|ogg|oga|wav|flac|aac)(?:[?#]|$)",
}


def _in_container():
    """True inside docker/compose or a Kubernetes pod (botasaurus's IS_DOCKER
    plus the k8s service env, which containerd-based GKE nodes always set)."""
    return bool(IS_DOCKER or IS_IN_KUBERNETES)


class PatchrightDriver:
    def __init__(self, proxy_url, headless=False, block_resources=None,
                 reset_on_release=False, browserforge=False, timezone=None):
        self._headless = bool(headless)
        # browserforge / timezone are PER-DRIVER browser-identity knobs set by
        # the pool settings (chrome_manager.CHROME_POOLS) — never process-wide
        # env, so pools with different anti-bot needs coexist in one process.
        # timezone: Chrome's JS-visible Intl timezone (playwright timezone_id)
        # for scrapers whose proxy exit country differs from the container TZ;
        # None keeps the system TZ.
        self._browserforge = bool(browserforge)
        self._timezone = timezone or None
        block = frozenset(block_resources or ())
        # "image" and "font" in block_resources are honored at the Chrome
        # level (--blink-settings=imagesEnabled=false, --disable-remote-fonts)
        # instead of route interception: those requests are then never issued,
        # so no bandwidth is spent and - unlike aborting them via a route,
        # which wedged some SPAs into stalling every later page op on the
        # driver - no load-error paths ever fire. Detectable by WAFs
        # (naturalWidth 0, missing web fonts), so only pools that never face
        # anti-bot sites should list them.
        self._block_images = "image" in block
        self._block_fonts = "font" in block
        # The remaining types (stylesheet/media) are aborted by a URL-pattern
        # route - see _BLOCK_URL_PATTERNS. JS/XHR/document always load.
        patterns = [_BLOCK_URL_PATTERNS[t] for t in sorted(block)
                    if t in _BLOCK_URL_PATTERNS]
        self._block_url_re = (re.compile("|".join(patterns), re.IGNORECASE)
                              if patterns else None)
        # reset_on_release: chrome_manager parks this driver on about:blank
        # when it returns to the pool, so an idle driver never keeps a huge
        # rendered page (and its renderer memory) alive.
        self.reset_on_release = bool(reset_on_release)
        if not self._headless:
            _ensure_display()
        self._jobs = queue.Queue()
        self._started = threading.Event()
        self._start_error = None
        self._closed = False
        self._profile_dir = tempfile.mkdtemp(prefix="patchright-profile-")
        # OS processes backing this browser, recorded by pid-diff around the
        # launch (construction is serialized by chrome_manager's _create_lock).
        self._procs = []
        pre_launch = {p.pid for p in psutil.Process().children()}
        self._thread = threading.Thread(
            target=self._main,
            args=(_proxy_dict(proxy_url) if proxy_url else None,),
            daemon=True, name="patchright-driver")
        self._thread.start()
        started = self._started.wait(STARTUP_TIMEOUT)
        self._procs = _children_since(pre_launch)
        if not started or self._start_error is not None:
            # Hung or failed launch: the owner thread may be stuck inside the
            # launch with processes already spawned — reap everything ourselves,
            # re-diffing for processes that appeared after the snapshot above.
            self.close()
            self._procs = _children_since(pre_launch)
            self._force_kill()
            if not started:
                raise RuntimeError(f"patchright startup timed out after {STARTUP_TIMEOUT}s")
            raise RuntimeError(f"patchright startup failed: {self._start_error}")
        with _drivers_lock:
            _drivers.add(self)

    # ---- owner thread ---------------------------------------------------
    def _main(self, proxy):
        pw = None
        browser = None
        page = None
        try:
            pw = sync_playwright().start()
            # launch_persistent_context + headed. The channel is real Chrome
            # BY DEFAULT, everywhere: in a container that is decided here
            # rather than by deployment env (the botasaurus image ships
            # google-chrome but NO ms-playwright cache, so patchright's
            # bundled Chromium cannot launch there at all). On a host
            # PATCHRIGHT_CHANNEL overrides the channel; PATCHRIGHT_CHANNEL=""
            # (empty) opts out of channels entirely (PATCHRIGHT_EXECUTABLE,
            # else the Opera/Brave probe list, else bundled Chromium).
            channel = "chrome" if _in_container() else os.environ.get("PATCHRIGHT_CHANNEL", "chrome")
            exe = None if channel else (os.environ.get("PATCHRIGHT_EXECUTABLE") or next(
                (p for p in (
                    "/Applications/Opera.app/Contents/MacOS/Opera",
                    "/usr/bin/opera",
                    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
                    "/usr/bin/brave-browser",
                ) if os.path.exists(p)), None))
            # PATCHRIGHT_LANG (unset by default) pins the browser
            # UI/Accept-Language so navigator.language(s) agree with the
            # injected fingerprint's locale on every platform (Linux Chrome
            # otherwise derives it from LANG). Set it to match the proxy exit
            # country, e.g. en-IN for India, en-GB for the UK; when unset the
            # browser keeps its own default and no --lang arg is passed.
            lang = os.environ.get("PATCHRIGHT_LANG")
            launch_args = [f"--lang={lang}"] if lang else []
            if self._block_images:
                launch_args.append("--blink-settings=imagesEnabled=false")
            if self._block_fonts:
                launch_args.append("--disable-remote-fonts")
            browser = pw.chromium.launch_persistent_context(
                user_data_dir=self._profile_dir,
                headless=self._headless,
                proxy=proxy,
                **({"args": launch_args} if launch_args else {}),
                **({"timezone_id": self._timezone} if self._timezone else {}),
                **({"channel": channel,
                    "no_viewport":True,
                    } if channel else {}),
                **({"executable_path": exe} if exe else {}),
            )
            # browserforge=True: overlay a fresh, statistically-real
            # browserforge fingerprint (navigator/screen/WebGL/fonts) per
            # driver via an init script (optional dependency; the contact
            # pools leave it off). The fingerprint OS must match the real
            # platform: linux in containers, macos on the Mac host;
            # PATCHRIGHT_BROWSERFORGE_OS overrides.
            if self._browserforge:
                from browserforge.fingerprints import FingerprintGenerator
                from browserforge.injectors.utils import InjectFunction
                bf_os_map = {"windows": "windows", "mac": "macos", "linux": "linux"}
                bf_os = (os.environ.get("PATCHRIGHT_BROWSERFORGE_OS")
                         or bf_os_map.get(get_os(), "linux"))
                try:
                    fp = FingerprintGenerator().generate(
                        browser="chrome", os=bf_os,
                         device="desktop",
                        **({"locale": (lang, "en")} if lang else {})
                        )
                except Exception:
                    # Locale absent from browserforge's dataset: drop it so
                    # injection never silently disables itself.
                    fp = FingerprintGenerator().generate(
                        browser="chrome", os=bf_os, device="desktop")
                browser.add_init_script(InjectFunction(fp))
            if self._block_url_re is not None:
                # Route ONLY the URLs to abort (abort is the sole action, so
                # there is no continue/fallback path at all). The old handler
                # routed "**/*" and decided per request in Python, so EVERY
                # request round-tripped over the playwright pipe; a page that
                # keeps issuing requests (SPA polling, analytics beacons)
                # saturated that pipe and starved the driver's own page ops
                # until they hit CALL_TIMEOUT - the "page wedged" timeouts,
                # with the backed-up requests showing up as multi-GB renderer
                # memory. (fallback() vs continue_() never mattered: an
                # unhandled fallback is continued from Python as well.)
                browser.route(self._block_url_re, lambda route: route.abort())
            page = browser.new_page()
            page.set_default_timeout(30000)
        except Exception as e:
            self._start_error = e
            self._started.set()
            for closer in (browser, pw):
                if closer is not None:
                    try:
                        closer.close() if closer is browser else closer.stop()
                    except Exception:
                        pass
            return
        self._started.set()
        while True:
            job = self._jobs.get()
            if job is None:
                break
            fn, done, box = job
            try:
                box["result"] = fn(page)
            except BaseException as e:
                box["error"] = e
            done.set()
        try:
            browser.close()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass

    # ---- calling threads ------------------------------------------------
    def call(self, fn, timeout=CALL_TIMEOUT):
        """Run fn(page) on the owner thread; raise whatever it raised.
        A timeout means the page is wedged — the driver is unusable and the
        caller/pool should close it (the wedged op keeps the daemon thread)."""
        if self._closed:
            raise RuntimeError("patchright driver is closed")
        done = threading.Event()
        box = {}
        self._jobs.put((fn, done, box))
        if not done.wait(timeout):
            raise TimeoutError(f"patchright op timed out after {timeout}s (page wedged)")
        if "error" in box:
            raise box["error"]
        return box.get("result")

    def goto(self, url, referer=None):
        return self.call(lambda page: page.goto(
            url, referer=referer, wait_until="domcontentloaded",
            timeout=GOTO_TIMEOUT_MS))

    def nav(self, url, referer=None, mode='csr', challenge_markers=()):
        """Navigate + mode-aware settle + snapshot as ONE owner-thread op.
        Returns plain data {'url','status','ok','headers','html'} that is safe
        to hand across threads (goto()'s playwright Response is greenlet-bound
        to the owner thread and must never leave it). status/headers are
        None/{} when playwright returns no response (same-document
        navigation). Raises on navigation failure (net::ERR_*, goto timeout)
        exactly like goto().

        mode picks the settle strategy (budgets are module constants):
          'csr'      networkidle capped at SETTLE_IDLE_MS; if the body is
                     still an empty app shell afterwards, a content-length
                     stability poll runs up to SETTLE_BUDGET_MS.
          'blocked'  returns immediately unless one of challenge_markers is
                     on the page; otherwise polls until the interstitial
                     clears (capped at SETTLE_BUDGET_MS).
        status/ok/headers come from the LAST main-frame document response
        seen — a challenge that clears during the settle reports the real
        page's status, not the interstitial's 403."""
        def _do(page):
            docs = []

            def _on_response(resp):
                try:
                    if (resp.request.resource_type == "document"
                            and resp.frame == page.main_frame):
                        docs.append(resp)
                except Exception:
                    pass

            page.on("response", _on_response)
            try:
                resp = page.goto(url, referer=referer,
                                 wait_until="domcontentloaded",
                                 timeout=GOTO_TIMEOUT_MS)
                # print(mode)
                if mode == 'blocked':
                    # _settle_blocked(page, challenge_markers)
                    # csr seems better for tesla.com
                    _settle_csr(page)
                else:
                    _settle_csr(page)
                final = docs[-1] if docs else resp
            finally:
                page.remove_listener("response", _on_response)
            try:
                html = _capped_content(page)
            except Exception:
                # Snapshot raced a navigation (challenge still reloading at
                # the deadline): let it land, then read once more.
                page.wait_for_timeout(500)
                html = _capped_content(page)
            return {"url": page.url,
                    "status": final.status if final is not None else None,
                    "ok": final.ok if final is not None else True,
                    "headers": dict(final.headers) if final is not None else {},
                    "html": html}
        return self.call(_do)

    def evaluate(self, js, arg=None):
        return self.call(lambda page: page.evaluate(js, arg))

    def title(self):
        return self.call(lambda page: page.title())

    def content(self):
        return self.call(_capped_content)

    def blank(self):
        """Park on about:blank, releasing the current page's renderer memory."""
        self.call(lambda page: page.goto("about:blank"))

    def content_frames(self):
        """HTML of every frame (main first, then iframes) as one owner-thread
        op. Some challenge vendors render their block/captcha verdict inside
        an iframe that page.content() (main frame only) never shows. Frames
        that are mid-navigation or unreadable yield ""."""
        def _do(page):
            out = []
            for f in page.frames:
                try:
                    out.append(f.evaluate(_CAPPED_CONTENT_JS,
                                          _MAX_CONTENT_CHARS) or "")
                except Exception:
                    out.append("")
            return out
        return self.call(_do)

    @property
    def current_url(self):
        return self.call(lambda page: page.url)

    def get(self, url, headers=None, referrer=None,
            timeout_ms=FETCH_TIMEOUT_MS, call_timeout=CALL_TIMEOUT):
        """requests-like GET run as an in-page fetch (inherits the page's
        cookies, Cloudflare clearance and TLS fingerprint). Returns a
        FetchResponse; never raises on HTTP/network errors — check .ok /
        .status_code. `call_timeout` is the hard owner-thread ceiling."""
        res = self.call(
            lambda page: page.evaluate(_FETCH_JS, {
                "url": url,
                "method": "GET",
                "headers": headers if headers is not None else DEFAULT_FETCH_HEADERS,
                "body": None,
                "referrer": referrer,
                "timeoutMs": timeout_ms,
            }),
            timeout=call_timeout,
        ) or {}
        return FetchResponse(
            ok=bool(res.get("ok")),
            status_code=int(res.get("status") or 0),
            url=res.get("url") or "",
            text=res.get("body") or "",
            error=res.get("error"),
            headers=res.get("headers") or {},
        )

    def get_many(self, urls, headers=None, referrer=None,
                 timeout_ms=FETCH_TIMEOUT_MS, stagger_ms=FETCH_STAGGER_MS,
                 call_timeout=CALL_TIMEOUT):
        """Concurrent in-page GETs: one marshalled evaluate() runs every fetch
        via Promise.all, each launched i*stagger_ms apart — the browser fires
        them in parallel like a page loading its subresources. Returns a list
        of FetchResponse in input order; like get(), never raises on
        HTTP/network errors."""
        if not urls:
            return []
        results = self.call(
            lambda page: page.evaluate(_FETCH_MANY_JS, {
                "requests": [{
                    "url": url,
                    "method": "GET",
                    "headers": headers if headers is not None else DEFAULT_FETCH_HEADERS,
                    "body": None,
                    "referrer": referrer,
                } for url in urls],
                "timeoutMs": timeout_ms,
                "staggerMs": stagger_ms,
            }),
            timeout=call_timeout,
        ) or []
        results += [{}] * (len(urls) - len(results))  # bridge miss -> transport error
        return [FetchResponse(
            ok=bool(res.get("ok")),
            status_code=int(res.get("status") or 0),
            url=res.get("url") or "",
            text=res.get("body") or "",
            error=res.get("error"),
            headers=res.get("headers") or {},
        ) for res in results]

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._jobs.put(None)
        self._thread.join(timeout=30)
        # A wedged page op keeps the owner thread stuck inside Playwright: it
        # never reaches the sentinel and the join above times out — kill the
        # browser's process trees directly.
        self._force_kill()
        shutil.rmtree(self._profile_dir, ignore_errors=True)
        with _drivers_lock:
            _drivers.discard(self)

    def _force_kill(self):
        """SIGKILL whatever of this driver's OS processes survived a clean
        shutdown. No-op when the owner thread already shut down cleanly."""
        for proc in self._procs:
            _kill_tree(proc)
