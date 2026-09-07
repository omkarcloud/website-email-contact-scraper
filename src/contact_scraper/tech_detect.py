# Technology detection via the wappalyzer-python3 library.
#
# detect_technologies() returns [{'name', 'versions', 'categories'}, ...]
# sorted by name, and [] on ANY failure - tech detection must never fail a
# scrape. Engines are pooled: building one parses the 484KB bundled
# technologies.json and compiles thousands of regexes, far too costly per
# site, and analyze() mutates engine state (detected_technologies keyed by
# URL), so an engine serves ONE detection at a time. On GIL builds the pool
# holds a single engine (threads couldn't overlap the regex CPU anyway -
# extra engines would only burn RAM); on free-threaded builds it grows to
# min(4, cores) so concurrent crawls' detections run truly in parallel.

import os
import queue
import sys
import threading

# Wappalyzer regexes run over the raw HTML; cap the input so a pathological
# minified blob can't stall a scrape.
# Wappalyzer's fingerprint regexes backtrack catastrophically on large
# documents: measured on a 1.09MB page, 500KB analyzed in 0.6s while 800KB
# had not finished after 45s (and the FULL page never returned - it hung the
# crawl's tech worker, and with it the whole scrape, past every deadline).
# Detections are identical at every size tried (the fingerprints live in
# <head> markup, script src/globals and headers, not deep in the body), so
# the truncation costs no accuracy.
MAX_TECH_HTML_CHARS = 400_000


def _default_pool_size():
    if getattr(sys, '_is_gil_enabled', lambda: True)():
        return 1
    return min(4, os.cpu_count() or 1)


_POOL_SIZE = _default_pool_size()

_idle_engines = queue.Queue()
_engines_created = []  # every engine ever built (introspection/tests)
_create_lock = threading.Lock()


def _acquire_engine():
    try:
        return _idle_engines.get_nowait()
    except queue.Empty:
        pass
    with _create_lock:
        if len(_engines_created) < _POOL_SIZE:
            from Wappalyzer import Wappalyzer
            # Bundled fingerprints only: update=True pulls a newer-schema
            # file whose scriptSrc keys the engine silently ignores.
            engine = Wappalyzer.latest()
            _engines_created.append(engine)
            return engine
    # Pool at capacity: wait for a release. The timeout guards the per-crawl
    # tech workers against a leaked engine wedging them forever - a timeout
    # surfaces as a failed (empty) detection, never a hang.
    return _idle_engines.get(timeout=60)


def _release_engine(engine):
    _idle_engines.put(engine)


def _normalize_headers(headers):
    # Duplicate headers (Set-Cookie & co.) may arrive as list values; the
    # Wappalyzer engine regex-searches each value and requires str.
    try:
        items = (headers or {}).items()
    except AttributeError:
        return {}
    norm = {}
    for key, value in items:
        if isinstance(value, (list, tuple)):
            value = ', '.join(str(v) for v in value)
        norm[str(key)] = str(value)
    return norm


def detect_technologies(url, html, headers):
    try:
        from Wappalyzer import WebPage
        webpage = WebPage(url, (html or '')[:MAX_TECH_HTML_CHARS],
                          _normalize_headers(headers))
        engine = _acquire_engine()
        try:
            try:
                results = engine.analyze_with_versions_and_categories(webpage)
            finally:
                # The engine caches detections per URL forever; drop this
                # site's entry or a long-running worker grows without bound.
                engine.detected_technologies.pop(url, None)
        finally:
            _release_engine(engine)
        return [{'name': name,
                 'versions': info.get('versions', []),
                 'categories': info.get('categories', [])}
                for name, info in sorted(results.items())]
    except Exception:
        return []


def merge_technologies(result_lists):
    """Merge per-page detect_technologies() outputs into one list: versions
    are unioned in first-seen order, categories come from the first page that
    reported any (they are fixed per technology in the fingerprint file), and
    the result is name-sorted like single-page output. None/empty inputs are
    tolerated."""
    merged = {}
    for results in result_lists:
        for entry in results or []:
            cur = merged.get(entry['name'])
            if cur is None:
                merged[entry['name']] = {
                    'name': entry['name'],
                    'versions': list(entry.get('versions') or []),
                    'categories': list(entry.get('categories') or []),
                }
                continue
            for version in entry.get('versions') or []:
                if version not in cur['versions']:
                    cur['versions'].append(version)
            if not cur['categories']:
                cur['categories'] = list(entry.get('categories') or [])
    return [merged[name] for name in sorted(merged)]
