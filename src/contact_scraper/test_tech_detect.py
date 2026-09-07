# Standalone offline checks for tech_detect.py (no network):
# python3 -m src.contact_scraper.test_tech_detect

from .tech_detect import _engines_created, detect_technologies, merge_technologies

WORDPRESS_HTML = ('<html><head>'
                  '<meta name="generator" content="WordPress 5.4.2">'
                  '</head><body>hi</body></html>')


def test_wordpress_detection():
    result = detect_technologies('https://wp-example.com/', WORDPRESS_HTML, {})
    by_name = {entry['name']: entry for entry in result}
    assert 'WordPress' in by_name, result
    assert 'CMS' in by_name['WordPress']['categories'], by_name['WordPress']
    assert by_name['WordPress']['versions'] == ['5.4.2'], by_name['WordPress']
    for entry in result:
        assert set(entry) == {'name', 'versions', 'categories'}, entry


def test_headers_only_signal():
    # No HTML signal at all: detection must come from the response headers.
    result = detect_technologies('https://nginx-example.com/', '<html></html>',
                                 {'Server': 'nginx'})
    assert any(entry['name'] == 'Nginx' for entry in result), result


def test_list_valued_headers():
    # botasaurus_requests reports duplicate headers as lists; detection must
    # not silently die on them (regression: vercel.com returned [] live).
    result = detect_technologies(
        'https://nginx-example.com/', '<html></html>',
        {'Server': 'nginx', 'Set-Cookie': ['a=1; Path=/', 'b=2; Path=/']})
    assert any(entry['name'] == 'Nginx' for entry in result), result


def test_junk_input_returns_empty():
    assert detect_technologies('https://x.com/', None, None) == []
    assert detect_technologies(None, None, None) == []
    # Non-dict headers must be swallowed, not raise.
    assert detect_technologies('https://x.com/', '<html></html>', 'bogus') == []


def test_merge_technologies():
    merged = merge_technologies([
        [{'name': 'WordPress', 'versions': ['5.4.2'], 'categories': ['CMS']},
         {'name': 'Nginx', 'versions': [], 'categories': []}],
        None,   # a failed/timed-out detection contributes nothing
        [],
        [{'name': 'WordPress', 'versions': ['5.4.2', '6.0'], 'categories': ['CMS', 'Blogs']},
         {'name': 'Nginx', 'versions': ['1.19'], 'categories': ['Web servers']},
         {'name': 'React', 'versions': [], 'categories': ['JavaScript frameworks']}],
    ])
    assert [e['name'] for e in merged] == ['Nginx', 'React', 'WordPress'], merged
    by_name = {e['name']: e for e in merged}
    assert by_name['WordPress']['versions'] == ['5.4.2', '6.0']      # union, first-seen order
    assert by_name['WordPress']['categories'] == ['CMS']             # first non-empty wins
    assert by_name['Nginx']['versions'] == ['1.19']
    assert by_name['Nginx']['categories'] == ['Web servers']
    assert merge_technologies([]) == []
    assert merge_technologies([None, []]) == []


def test_stable_and_leak_free():
    first = detect_technologies('https://wp-example.com/', WORDPRESS_HTML, {})
    second = detect_technologies('https://wp-example.com/', WORDPRESS_HTML, {})
    assert first == second
    assert first == sorted(first, key=lambda e: e['name'])
    # The per-URL cache must be drained after every call or a long-running
    # worker grows without bound - checked on every engine the pool built.
    assert _engines_created, 'detections above must have built an engine'
    assert all(e.detected_technologies == {} for e in _engines_created)


# python -m contact_scraper.test_tech_detect
if __name__ == '__main__':
    test_wordpress_detection()
    test_headers_only_signal()
    test_list_valued_headers()
    test_junk_input_returns_empty()
    test_merge_technologies()
    test_stable_and_leak_free()
    print('tech_detect OK')
