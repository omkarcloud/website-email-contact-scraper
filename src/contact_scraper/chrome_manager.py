"""Chrome pool manager for the contact scraper.

The "contact" pool holds warmed Chrome drivers shared by every crawl:

  min   warmed browsers kept alive at ALL times. "Alive" counts ready + leased
        + warming — a leased browser is alive and warm, and a warming one is
        being brought alive (requiring ready >= min would make min drivers
        unusable for concurrency). Defaults to 0: Chrome is built LAZILY, the
        first browser-mode fetch spawns a warmer and requests-only crawls
        never launch Chrome at all.
  max   hard cap on live Chromes for the pool.

Request lifecycle (`acquire(key)` / `with_chrome(key)`):
  - Take the least-recently-used ready driver (FIFO deque -> round-robin
    rotation, so no single browser is bombarded).
  - If none is ready and the pool is below max, spawn a BACKGROUND warmer and
    wait for whichever comes first: a busy driver being released or the warm
    completing. Request threads never construct drivers inline.
  - On success the driver returns to the FIFO tail. On failure it is closed
    and discarded; the next acquire (or `ensure_min` when min > 0) warms a
    replacement, so a crashed Chrome can never re-enter the ready pool.

Warm-up is per-pool (register_warmup) and must prove the driver end-to-end
with a real navigation. A driver only enters the ready pool if the warm-up
didn't raise.

Drivers are created through botasaurus's own Driver class with the same
options the @browser decorator would pass, so fingerprint/proxy behavior is
unchanged. Construction is serialized by a global lock (first-time display/
profile setup races otherwise); navigation + validation run concurrently.

Env knobs: CONTACT_SCRAPER_CHROMES_MIN (0), CONTACT_SCRAPER_CHROMES_MAX (2),
CONTACT_SCRAPER_PROXY (direct connection when unset).
"""
import itertools
import os
import threading
import time
from collections import deque
from contextlib import contextmanager
from traceback import format_exc

from botasaurus.decorators_common import evaluate_proxy, save_error_logs
from botasaurus.env import IS_DOCKER
from botasaurus_driver.driver import Driver

CHROME_POOLS = {
    "contact": {
        # min=0 -> lazy: no Chrome exists until a crawl's first browser-mode
        # fetch. Set CONTACT_SCRAPER_CHROMES_MIN=1 to keep one pre-warmed.
        "min": int(os.environ.get("CONTACT_SCRAPER_CHROMES_MIN", 0)),
        "max": int(os.environ.get("CONTACT_SCRAPER_CHROMES_MAX", 2)),
        # None means direct connection: crawling arbitrary small sites
        # through residential exits buys nothing.
        "proxy": os.environ.get("CONTACT_SCRAPER_PROXY") or None,
    },
}

MAX_RETRIES = 3          # run_with_chrome attempts before giving up
WARMUP_ATTEMPTS = 3            # create+warm+validate tries per warmer thread
WARMUP_BACKOFF = [5, 15, 30]   # seconds between warmer attempts
ACQUIRE_TIMEOUT = 90           # seconds a request waits for a Chrome
ENSURE_MIN_INTERVAL = 60       # janitor period re-asserting pool minimums


class ChromeUnavailable(Exception):
    """No warm Chrome became available within ACQUIRE_TIMEOUT. Not retried —
    retrying would just re-wait on the same exhausted pool."""


class ContentError(Exception):
    """The scraped content itself was the problem (e.g. item does not exist) —
    the driver is healthy. Subclass this in scrapers so the pool returns the
    driver for reuse instead of destroying it, and run_with_chrome re-raises
    immediately instead of retrying."""


_warmups = {}


def register_warmup(key, fn):
    """Register the warm-up (a real validation navigation) run once on every new
    driver of a pool. The driver joins the ready pool only if fn didn't raise."""
    _warmups[key] = fn


# Serializes Driver(...) construction only (~seconds): two first-time creations
# race on display/profile setup. Never held together with a pool condition.
_create_lock = threading.Lock()


class ChromePool:
    """One keyed pool.

    All state lives under one Condition. Invariant: every +1 to
    total = len(_ready) + leased + warming is guarded by `total < max` inside
    the same locked section, so live Chromes never exceed `max`.
    """

    def __init__(self, key, settings):
        self.key = key
        self.settings = settings
        self.min = int(settings.get("min", 0))
        self.max = int(settings["max"])
        if not 0 <= self.min <= self.max:
            raise ValueError(f"{key}: need 0 <= min({self.min}) <= max({self.max})")
        self._cond = threading.Condition()
        self._ready = deque()   # FIFO: popleft to lease, append on release/warm
        self.leased = 0
        self.warming = 0
        self.queued = 0
        self.warm_failures = 0  # monotonic, for observability
        self._seq = itertools.count(1)

    def _total_locked(self):
        return len(self._ready) + self.leased + self.warming

    def acquire(self, timeout=None) -> Driver:
        timeout = ACQUIRE_TIMEOUT if timeout is None else timeout
        deadline = (time.monotonic() + timeout) if timeout else None
        with self._cond:
            while True:
                if self._ready:
                    driver = self._ready.popleft()
                    self.leased += 1
                    print(f"{self.key}: lease driver#{getattr(driver, '_pool_seq', '?')} "
                          f"(ready={len(self._ready)} leased={self.leased} warming={self.warming})")
                    return driver
                if self._total_locked() < self.max:
                    self._spawn_warmer_locked()
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise ChromeUnavailable(
                        f"{self.key}: no Chrome available within {timeout}s "
                        f"(leased={self.leased} warming={self.warming})")
                self.queued += 1
                try:
                    self._cond.wait(remaining)  # woken by release OR warmer; first wins
                finally:
                    self.queued -= 1

    def release(self, driver, ok):
        if not ok:
            # Close BEFORE decrementing leased: the OS Chrome count stays within
            # the accounted total, so a replacement warmer can't overlap the
            # dying Chrome and momentarily exceed `max` real processes.
            _close_quietly(driver)
        with self._cond:
            self.leased -= 1
            if ok:
                self._ready.append(driver)  # FIFO tail -> round-robin rotation
            else:
                self._ensure_min_locked()   # background replacement (min > 0)
            self._cond.notify_all()

    def _spawn_warmer_locked(self):
        self.warming += 1  # reserve capacity before the thread exists
        t = threading.Thread(target=_warmer_main, args=(self,), daemon=True,
                             name=f"warmup-{self.key}")
        try:
            t.start()
        except BaseException:
            self.warming -= 1
            raise

    def _ensure_min_locked(self):
        while self._total_locked() < self.min:
            self._spawn_warmer_locked()

    def serviceable(self):
        with self._cond:
            return len(self._ready) + self.leased >= 1

    def stats(self):
        with self._cond:
            return {
                "ready": len(self._ready),
                "leased": self.leased,
                "warming": self.warming,
                "queued": self.queued,
                "min": self.min,
                "max": self.max,
                "warm_failures": self.warm_failures,
            }


_pools = {}
_pools_mutex = threading.Lock()
_janitor_started = False


def _pool(key) -> ChromePool:
    with _pools_mutex:
        pool = _pools.get(key)
        if pool is None:
            if key not in CHROME_POOLS:
                raise KeyError(f"unknown chrome pool {key!r}; add it to CHROME_POOLS")
            pool = ChromePool(key, CHROME_POOLS[key])
            _pools[key] = pool
        return pool


def _close_quietly(driver):
    try:
        driver.close()
    except Exception:
        pass


def _build_driver(settings):
    # An explicit "proxy": None (the default) means direct connection.
    driver = Driver(
        headless=False,
        proxy=evaluate_proxy(settings.get("proxy")),
        block_images=True,
        lang=settings.get("lang", "en-US"),
        wait_for_complete_page_load=False,
        enable_xvfb_virtual_display=IS_DOCKER,
    )
    if settings.get("locale") or settings.get("timezone"):
        driver.set_locale_and_timezone(settings.get("locale"), settings.get("timezone"))
    return driver


def _warmer_main(pool):
    """Background warmer: create + warm + validate one driver, with backoff.
    Decrements `warming` exactly once: on publish, or in the final failure path."""
    published = False
    try:
        for attempt in range(1, WARMUP_ATTEMPTS + 1):
            driver = None
            started = time.monotonic()
            try:
                with _create_lock:
                    driver = _build_driver(pool.settings)
                warmup = _warmups.get(pool.key)
                if warmup is not None:
                    warmup(driver)
                with pool._cond:
                    pool.warming -= 1
                    driver._pool_seq = next(pool._seq)
                    pool._ready.append(driver)
                    pool._cond.notify_all()
                published = True
                print(f"{pool.key}: driver#{driver._pool_seq} warmed+validated "
                      f"in {time.monotonic() - started:.1f}s")
                return
            except Exception as e:
                print(f"{pool.key}: warm-up attempt {attempt}/{WARMUP_ATTEMPTS} "
                      f"failed: {e}")
                try:
                    save_error_logs(format_exc(),
                                    driver if isinstance(driver, Driver) else None)
                except Exception:
                    pass
                if driver is not None:
                    _close_quietly(driver)
                if attempt < WARMUP_ATTEMPTS:
                    time.sleep(WARMUP_BACKOFF[attempt - 1])
    finally:
        if not published:
            with pool._cond:
                pool.warming -= 1
                pool.warm_failures += 1
                pool._cond.notify_all()  # waiters recheck; next acquire re-triggers


def acquire(key, timeout=None):
    """Lease a warmed driver WITHOUT the with_chrome scope — for callers that
    hold one driver across a larger unit of work (a contact crawl keeps its
    challenge cookies on one Chrome) and release() it themselves. Raises
    ChromeUnavailable after `timeout` (default ACQUIRE_TIMEOUT)."""
    return _pool(key).acquire(timeout)


def release(key, driver, ok=True):
    """Return a driver leased via acquire(). ok=False destroys it (the next
    acquire warms a replacement)."""
    _pool(key).release(driver, ok)


@contextmanager
def with_chrome(key):
    """Borrow a warmed Chrome from the pool; waits (FIFO) when none is ready.
    Raises ChromeUnavailable after ACQUIRE_TIMEOUT."""
    pool = _pool(key)
    driver = pool.acquire()
    try:
        yield driver
    except ContentError:
        pool.release(driver, ok=True)  # healthy driver; the content was the problem
        raise
    except BaseException:
        pool.release(driver, ok=False)
        raise
    else:
        pool.release(driver, ok=True)


def run_with_chrome(key, fn, data, retries=None):
    """Run fn(driver, data) on a pooled Chrome. A failed attempt destroys its
    driver and retries immediately on another warm one."""
    attempts = MAX_RETRIES if retries is None else retries
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            with with_chrome(key) as driver:
                try:
                    return fn(driver, data)
                except ContentError:
                    raise
                except Exception:
                    save_error_logs(format_exc(),
                                    driver if isinstance(driver, Driver) else None)
                    raise
        except (ContentError, ChromeUnavailable):
            raise
        except Exception as error:
            last_error = error
            print(f"{key} attempt {attempt}/{attempts} failed: {error}")
    raise last_error


def ensure_min(key):
    """Bring the pool up to its min floor via background warmers (no-op for
    the lazy default min=0)."""
    pool = _pool(key)
    with pool._cond:
        pool._ensure_min_locked()


def wait_until_ready(timeout):
    """Block until every pool with a warm floor (min >= 1) has >= 1 live driver
    (ready or leased). A min=0 pool warms only on demand, so waiting on it would
    always burn the whole timeout. Returns False on timeout."""
    deadline = time.monotonic() + timeout
    for key in CHROME_POOLS:
        pool = _pool(key)
        if pool.min == 0:
            continue
        with pool._cond:
            while not (pool._ready or pool.leased):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                pool._cond.wait(remaining)
    return True


def all_serviceable():
    return all(_pool(key).serviceable() for key in CHROME_POOLS)


def start_janitor():
    """Idempotent: one daemon thread re-asserting every pool's min floor.
    Only useful when CONTACT_SCRAPER_CHROMES_MIN > 0."""
    global _janitor_started
    with _pools_mutex:
        if _janitor_started:
            return
        _janitor_started = True

    def _janitor_main():
        while True:
            time.sleep(ENSURE_MIN_INTERVAL)
            for key in CHROME_POOLS:
                try:
                    ensure_min(key)
                except Exception as e:
                    print(f"janitor: ensure_min({key}) failed: {e}")

    threading.Thread(target=_janitor_main, daemon=True, name="pool-janitor").start()


def shutdown_all():
    """Best-effort cleanup: close every ready driver."""
    for key in list(_pools):
        pool = _pools[key]
        with pool._cond:
            drivers = list(pool._ready)
            pool._ready.clear()
        for driver in drivers:
            _close_quietly(driver)


def status():
    """Gauges for every configured pool."""
    return {key: _pool(key).stats() for key in CHROME_POOLS}
