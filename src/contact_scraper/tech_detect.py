# Homepage technology detection via the wappalyzer-python3 library.
#
# detect_technologies() returns [{'name', 'versions', 'categories'}, ...]
# sorted by name, and [] on ANY failure - tech detection must never fail a
# scrape. The engine is a lazy process-wide singleton: building it parses the
# 484KB bundled technologies.json and compiles thousands of regexes, far too
# costly per site. analyze() mutates the shared engine (detected_technologies
# keyed by URL), so calls are serialized with a lock - analysis is GIL-bound
# regex CPU, so the @task(parallel=5) threads couldn't overlap here anyway.

import threading

# Wappalyzer regexes run over the raw HTML; cap the input so a pathological
# minified blob can't stall a scrape (same philosophy as MAX_TEXT_SCAN_CHARS).
MAX_TECH_HTML_CHARS = 1_500_000

_engine = None
_lock = threading.Lock()


def _get_engine():
    global _engine
    if _engine is None:
        with _lock:
            if _engine is None:
                from Wappalyzer import Wappalyzer
                # Bundled fingerprints only: update=True pulls a newer-schema
                # file whose scriptSrc keys the engine silently ignores.
                _engine = Wappalyzer.latest()
    return _engine


def _normalize_headers(headers):
    # botasaurus_requests reports duplicate headers (Set-Cookie & co.) as list
    # values; the Wappalyzer engine regex-searches each value and requires str.
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
        engine = _get_engine()
        webpage = WebPage(url, (html or '')[:MAX_TECH_HTML_CHARS],
                          _normalize_headers(headers))
        with _lock:
            try:
                results = engine.analyze_with_versions_and_categories(webpage)
            finally:
                # The engine caches detections per URL forever; drop this
                # site's entry or a long-running worker grows without bound.
                engine.detected_technologies.pop(url, None)
        return [{'name': name,
                 'versions': info.get('versions', []),
                 'categories': info.get('categories', [])}
                for name, info in sorted(results.items())]
    except Exception:
        return []
