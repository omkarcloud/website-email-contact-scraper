# Public entrypoint: scrape_contacts(urls) -> one dict per input URL/domain.
# Each item is a bare URL string or {'query': url, 'mode': 'homepage'|
# 'key_pages'|'deep'} to pick the crawl depth (default 'key_pages').
# python3 -m src.contact_scraper.api   runs a manual live self-test.

import gc
import os
import re
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from botasaurus.task import task

from . import chrome_manager
from . import crawler
from .aggregate import build_output, empty_output
from .extract_emails import extract_emails
from .extract_phones import extract_phones, region_from_domain
from .extract_socials import extract_socials
from .fetcher import POOL_KEY, POOL_KEY_CSR
from .html_text import page_meta
from .tech_detect import detect_technologies, merge_technologies


def _warm_contact_driver(driver):
    return


# api is the contact scraper's startup entrypoint (routes -> contact_scraper.api),
# imported before the contact pools warm. Register the driver warm-up here so
# the pools' startup warmers validate each driver before it enters the ready pool.
chrome_manager.register_warmup(POOL_KEY, _warm_contact_driver)
chrome_manager.register_warmup(POOL_KEY_CSR, _warm_contact_driver)

# Soft cap for the per-page extraction pass; a pathological page must not
# stall the whole crawl (the phone regex alternation can backtrack heavily).
PAGE_EXTRACT_BUDGET_SECONDS = 10

# Per-page extraction is pure regex/parsing CPU. On a free-threaded build
# (PEP 703, python3.14t) a crawl's pages extract in parallel across cores;
# on GIL builds threads would only interleave the same core, so the
# sequential path is kept there.
_FREE_THREADED = not getattr(sys, '_is_gil_enabled', lambda: True)()
_extract_pool = (ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 1),
                                    thread_name_prefix='contact-extract')
                 if _FREE_THREADED else None)

# Technology-detection page slots beyond homepage/contact: careers and blog
# pages run the classic "different stack" (Greenhouse/Lever embeds, a
# separate blog CMS, newsletter widgets).
_TECH_PATH_RE = re.compile(r'/(careers?|jobs|blog|news)(/|$)', re.IGNORECASE)
MAX_TECH_PAGES = 4
TECH_WAIT_SECONDS = 30


class _TechPipeline:
    """Wappalyzer detections kicked off AS PAGES ARRIVE, overlapping the
    crawl's network wait (detection is GIL/lock-serialized regex CPU, so it
    runs essentially free while crawl threads block on fetches). Slots:
    homepage (always, with the merged homepage headers), first contact page,
    first careers/jobs page, first blog/news page; if neither careers nor
    blog was crawled, the largest remaining page is submitted post-crawl.
    One worker on purpose: detections are serialized process-wide by the
    engine lock anyway, and a per-crawl worker means finish() only ever
    waits on this crawl's own <= MAX_TECH_PAGES jobs."""

    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=1,
                                            thread_name_prefix='contact-tech')
        self._futures = []
        self._slots = set()
        self._urls = set()

    def _slot_for(self, result, rec):
        if rec['is_homepage']:
            return 'homepage'
        if rec['weight_class'] == 'contact':
            return 'contact'
        match = _TECH_PATH_RE.search(urlsplit(result['final_url']).path)
        if match:
            label = match.group(1).lower()
            return 'careers' if label.startswith(('career', 'job')) else 'blog'
        return None

    def _submit(self, url, html, headers):
        self._urls.add(url)
        self._futures.append(self._executor.submit(
            detect_technologies, url, html, headers))

    def offer(self, result, rec):
        # Called from the crawl thread (on_page_kept): cheap slot resolution
        # only, the detection itself runs on the worker.
        if len(self._futures) >= MAX_TECH_PAGES:
            return
        slot = self._slot_for(result, rec)
        if slot is None or slot in self._slots:
            return
        self._slots.add(slot)
        self._submit(result['final_url'], result.get('html') or '',
                     result.get('headers') or {})

    def finish(self, crawl_pages):
        # Largest-HTML fallback: no careers/blog page was crawled, so the
        # biggest not-yet-scanned page stands in as the "most distinct
        # template" candidate.
        if (not self._slots & {'careers', 'blog'}
                and len(self._futures) < MAX_TECH_PAGES):
            candidates = [rec['page'] for rec in crawl_pages
                          if rec['page'].url not in self._urls]
            if candidates:
                biggest = max(candidates, key=lambda p: len(p.html or ''))
                self._submit(biggest.url, biggest.html or '', {})
        deadline = time.monotonic() + TECH_WAIT_SECONDS
        collected = []
        for future in self._futures:
            try:
                collected.append(future.result(
                    timeout=max(0.1, deadline - time.monotonic())))
            except Exception:
                pass  # timeout or detection crash: keep what completed
        return merge_technologies(collected)

    def shutdown(self):
        # cancel_futures: detections still QUEUED when the crawl ends (finish
        # timed out or the crawl raised) must not keep burning the process-wide
        # engine lock that live crawls' pipelines are waiting on.
        self._executor.shutdown(wait=False, cancel_futures=True)


def _extract_page_record(rec, region):
    page = rec['page']
    started = time.monotonic()
    record = {
        'url': page.url,
        'is_homepage': rec['is_homepage'],
        'weight_class': rec['weight_class'],
        'emails': [],
        'phones': [],
        'socials': [],
    }
    socials, whatsapp_candidates = extract_socials(page)
    record['socials'] = socials
    if time.monotonic() - started < PAGE_EXTRACT_BUDGET_SECONDS:
        record['emails'] = extract_emails(page)
    if time.monotonic() - started < PAGE_EXTRACT_BUDGET_SECONDS:
        record['phones'] = extract_phones(
            page, region, extra_candidates=whatsapp_candidates)
    return record


# Soup trees are cycle-heavy (parent/child backrefs), so a finished crawl's
# ~20 BeautifulSoup documents are reclaimed only by the cyclic GC, never by
# refcounting. On the free-threaded build the automatic GC cannot keep pace
# with concurrent crawls' allocation rate and multi-GB garbage backlogs
# accumulate until the container OOMs, so finished crawls trigger a manual
# collection — throttled, because each collect stops the world.
_GC_MIN_INTERVAL_SECONDS = 8
_gc_lock = threading.Lock()
_last_gc = [0.0]


def _collect_garbage_throttled():
    now = time.monotonic()
    if now - _last_gc[0] < _GC_MIN_INTERVAL_SECONDS:
        return
    with _gc_lock:
        if time.monotonic() - _last_gc[0] < _GC_MIN_INTERVAL_SECONDS:
            return
        gc.collect()
        _last_gc[0] = time.monotonic()


def _scrape_single(query, mode):
    # Every crawl runs to its mode's page / attempts / wall-clock budgets (the
    # signal-based early exit was removed by design); the kept-page callback
    # only feeds the tech-detection pipeline as pages arrive.
    pipeline = _TechPipeline()

    def on_page_kept(result, rec):
        pipeline.offer(result, rec)

    try:
        crawl = crawler.crawl_site(query, on_page_kept=on_page_kept, mode=mode)
        domain = crawl['domain'] or crawler.registrable_domain(query)
        if not crawl['pages']:
            return empty_output(domain,
                                error=crawl.get('error') or 'unreachable: no pages fetched')

        region = region_from_domain(domain)
        if _extract_pool is not None:
            page_records = list(_extract_pool.map(
                lambda rec: _extract_page_record(rec, region), crawl['pages']))
        else:
            page_records = [_extract_page_record(rec, region) for rec in crawl['pages']]
        home = crawl['pages'][0]['page']  # crawler always appends the homepage first
        technologies = pipeline.finish(crawl['pages'])
        title, description = page_meta(home.soup)
        return build_output(domain, page_records, technologies=technologies,
                            title=title, description=description)
    finally:
        pipeline.shutdown()
        _collect_garbage_throttled()


@task(cache=False, close_on_crash=True, create_error_logs=False,
      max_retry=2)
def scrape_contacts(data):
    # botasaurus maps list inputs over this function sequentially, so `data`
    # is a single item here: a URL/domain string (mode defaults to
    # 'key_pages') or a {'query', 'mode'} dict (what the dashboard sends);
    # scrape_contacts(list) returns list of dicts. Concurrency comes from
    # each crawl's own wave fetching (and, under the dashboard server, from
    # its task workers).
    if isinstance(data, dict):
        query = (data.get('query') or '').strip()
        mode = (data.get('mode') or 'key_pages').strip().lower()
    else:
        query, mode = data, 'key_pages'
    try:
        return _scrape_single(query, mode)
    except Exception as e:
        # Fixed output schema even for unreachable/broken sites. No crawl
        # happened, so the reported domain is the host as the caller gave it.
        traceback.print_exc()
        try:
            domain = crawler._seed_host(query)
        except Exception:
            domain = query
        return empty_output(domain, error=f'{type(e).__name__}: {e}'[:200])


if __name__ == '__main__':
    import json
    result = scrape_contacts('vercel.com')
    print(json.dumps(result, indent=2))
