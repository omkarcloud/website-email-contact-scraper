# Standalone unit tests for extract_emails (zero network):
#   python3 -m contact_scraper.test_emails

import os

from .extract_emails import decode_cfemail, deobfuscate_text, extract_emails
from .html_text import build_page

_FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')

# Same payloads as in fixtures/cloudflare_email.html.
_HEX_DAVE = '73171205163312101e165e071600075d101c1e'
_HEX_EVE = '214457446140424c440c554452550f424e4c'


def _load_page(fixture_name):
    with open(os.path.join(_FIXTURES_DIR, fixture_name), encoding='utf-8') as f:
        return build_page('https://acme-test.com/contact', f.read())


def _encode_cfemail(email, key):
    return format(key, '02x') + ''.join(format(ord(c) ^ key, '02x') for c in email)


def test_decode_cfemail():
    assert decode_cfemail(_HEX_DAVE) == 'dave@acme-test.com'
    assert decode_cfemail(_HEX_EVE) == 'eve@acme-test.com'
    # round trip with an arbitrary key
    assert decode_cfemail(_encode_cfemail('x.y-z@sub.acme-test.co.uk', 0xa5)) == 'x.y-z@sub.acme-test.co.uk'


def test_deobfuscate_text():
    # bracketed forms
    assert deobfuscate_text('info [at] acme-test [dot] com') == 'info@acme-test.com'
    assert deobfuscate_text('press(at)acme-test(dot)com') == 'press@acme-test.com'
    assert deobfuscate_text('jean {arobase} acme-test {punkt} com') == 'jean@acme-test.com'
    # unicode lookalikes
    assert deobfuscate_text('sales＠acme-test．com') == 'sales@acme-test.com'
    assert deobfuscate_text('ops﹫acme-test。com') == 'ops@acme-test.com'
    assert deobfuscate_text('x․y') == 'x.y'
    # defensive entity decoding
    assert deobfuscate_text('a&#64;b.com') == 'a@b.com'
    # spaced words commit only when the result is email-shaped
    assert deobfuscate_text('write to hr at acme-test dot com today') == 'write to hr@acme-test.com today'
    assert deobfuscate_text('we met at the office') == 'we met at the office'
    assert deobfuscate_text('reach us at info for help') == 'reach us at info for help'


def test_obfuscated_emails_fixture():
    page = _load_page('obfuscated_emails.html')
    hits = extract_emails(page)
    values = [h['value'] for h in hits]
    # discovery order: mailto pass, then raw-text pass, then de-obfuscated pass
    assert values == [
        'support@acme-test.com',
        'john@acme-test.com',
        'info@acme-test.com',
        'press@acme-test.com',
        'sales@acme-test.com',
        'hr@acme-test.com',
    ], values

    by_value = {h['value']: h for h in hits}
    support = by_value['support@acme-test.com']
    assert support['from_href'] and support['in_footer'], support
    john = by_value['john@acme-test.com']
    assert not john['from_href'] and not john['in_footer'], john

    # false positives never survive
    for dropped in ('logo@2x.png', 'user@example.com', 'foo@mail.example.com',
                    '3f2a9c81b4d05e67a1b2c3d4@logs.acme-test.com'):
        assert dropped not in values, dropped


def test_cloudflare_fixture():
    page = _load_page('cloudflare_email.html')
    hits = extract_emails(page)
    values = [h['value'] for h in hits]
    assert sorted(values) == ['dave@acme-test.com', 'eve@acme-test.com'], values
    # the literal placeholder shown in static HTML must never be extracted
    assert '[email protected]' not in values
    assert not any('protected' in v for v in values)

    by_value = {h['value']: h for h in hits}
    dave = by_value['dave@acme-test.com']  # data-cfemail span inside <footer>
    assert dave['in_footer'] and not dave['from_href'], dave
    eve = by_value['eve@acme-test.com']  # /cdn-cgi/ fragment anchor in <main>
    assert eve['from_href'] and not eve['in_footer'], eve


def test_hostile_pages():
    import time

    # 50k-char digit/word runs used to take ~30s per regex pass; the long-token
    # guard must keep extraction fast without losing nearby real contacts.
    hostile = ('<html><body><p>' + '1' * 50000 + ' ' + 'a' * 50000 + '@ '
               + '12.34.' * 8000 + '</p><p>mail hello@acme.com</p></body></html>')
    started = time.monotonic()
    hits = extract_emails(build_page('https://acme.com/', hostile))
    assert time.monotonic() - started < 5
    assert any(h['value'] == 'hello@acme.com' for h in hits)

    # Malformed pages nest thousands of tags deep; must not RecursionError.
    deep = ('<html><body>' + '<div>' * 3000 + 'hello@acme.com'
            + '</div>' * 3000 + '</body></html>')
    hits = extract_emails(build_page('https://acme.com/', deep))
    assert any(h['value'] == 'hello@acme.com' for h in hits)


def main():
    test_decode_cfemail()
    test_deobfuscate_text()
    test_obfuscated_emails_fixture()
    test_cloudflare_fixture()
    test_hostile_pages()


if __name__ == '__main__':
    main()
    print('extract_emails tests OK')
