# Standalone test script: python3 -m contact_scraper.test_phones
# Zero network; fixture HTML only.

from pathlib import Path

from .extract_phones import extract_phones, region_from_domain
from .html_text import build_page

FIXTURES = Path(__file__).parent / 'fixtures'


def load_fixture_page():
    html = (FIXTURES / 'phones_intl.html').read_text(encoding='utf-8')
    return build_page('https://acme.de/contact', html)


def hits_by_key(hits):
    return {h['key']: h for h in hits}


def test_region_from_domain():
    assert region_from_domain('sub.example.co.uk') == 'GB'
    assert region_from_domain('example.com') is None
    assert region_from_domain('example.de') == 'DE'
    assert region_from_domain('shop.example.com.au') == 'AU'
    assert region_from_domain('example.us') == 'US'
    assert region_from_domain('example.fr') == 'FR'
    assert region_from_domain('example.io') is None
    assert region_from_domain('example.co') is None  # generic use of .co
    assert region_from_domain('https://www.example.co.uk/contact') == 'GB'
    assert region_from_domain('') is None


def test_tel_href_in_footer(result):
    phones = hits_by_key(result['phones'])
    hit = phones.get('+14155552671')
    assert hit is not None, phones
    assert hit['value'] == '+14155552671'
    assert hit['from_href'] is True
    assert hit['in_footer'] is True


def test_german_number_region(result):
    phones = hits_by_key(result['phones'])
    hit = phones.get('+49301234567')
    assert hit is not None, phones
    assert hit['value'] == '+49301234567'
    assert hit['region_match'] is True
    assert hit['from_href'] is False


def test_date_and_year_absent(result):
    all_hits = result['phones'] + result['phones_uncertain']
    for hit in all_hits:
        assert '20181110' not in hit['key'], hit          # date 2018-11-10
        assert '2018-11-10' not in hit['value'], hit
        assert hit['key'] != '2020' and hit['value'] != '2020', hit


def test_order_number_uncertain_only(result):
    uncertain = hits_by_key(result['phones_uncertain'])
    assert '84591203' in uncertain, uncertain
    assert uncertain['84591203']['value'] == '84591203'
    assert uncertain['84591203']['from_href'] is False
    for hit in result['phones']:
        assert '84591203' not in hit['key'], hit


def test_tel_and_text_merge_one_key(result):
    # tel:+14155552671 and the "(415) 555-2671" / "+1 (415) 555-2671" text
    # forms must collapse into exactly one phones entry, none uncertain.
    matching = [h for h in result['phones'] if '4155552671' in h['key']]
    assert len(matching) == 1, result['phones']
    assert matching[0]['key'] == '+14155552671'
    for hit in result['phones_uncertain']:
        assert '4155552671' not in hit['key'], hit


def test_extra_candidates():
    page = load_fixture_page()
    result = extract_phones(page, region='DE',
                            extra_candidates=('+14155550132',))
    phones = hits_by_key(result['phones'])
    hit = phones.get('+14155550132')
    assert hit is not None, phones
    assert hit['from_href'] is True
    assert hit['in_footer'] is False


def test_tel_href_union_when_phonenumbers_rejects():
    # tel: OR validated is a union: an href number phonenumbers rejects but
    # the phone-shape regex accepts still lands in phones, digits-only key.
    html = '<p><a href="tel:12-345-678-901234">call</a></p>'
    page = build_page('https://acme.com/', html)
    result = extract_phones(page, region=None)
    phones = hits_by_key(result['phones'])
    hit = phones.get('12345678901234')
    assert hit is not None, result
    assert hit['value'] == '12345678901234'
    assert hit['from_href'] is True
    assert hit['in_footer'] is False


def test_audit_precision_canary():
    # One page holding every audited junk class + one real number: the output
    # must be exactly that number (dates, registry ids and truncated
    # fragments of the number itself all filtered/merged away).
    from .aggregate import build_output
    from .html_text import build_page
    page_obj = build_page('https://a.dk/contact',
                          '<p>Stand: 31.07.2026. CVR no. 40596860. '
                          'Call +45 41 11 10 75.</p>')
    result = extract_phones(page_obj, 'DK')
    record = {'url': page_obj.url, 'is_homepage': False,
              'weight_class': 'contact', 'emails': [], 'socials': [],
              'phones': result['phones'],
              'phones_uncertain': result['phones_uncertain']}
    out = build_output('a.dk', [record])
    assert [p['value'] for p in out['phones']] == ['+4541111075'], out['phones']
    assert out['phones_uncertain'] == [], out['phones_uncertain']


def test_uncertain_noise_filters():
    from .html_text import build_page
    html = ('<p>Ducati 1200 2015, 950 2017. Ref 000123456, id 336359125457, '
            'server 49.36.137.230. Mobile 07911 123456.</p>')
    result = extract_phones(build_page('https://a.com/', html), None)
    values = [p['value'] for p in result['phones_uncertain']]
    for junk in ('1200 2015', '950 2017', '000123456', '336359125457', '49.36.137.230'):
        assert junk not in values, (junk, values)
    # the phone-like value survives (leading 0 lost to the space
    # pattern's 4-digit first group - JS-identical behavior)
    assert any('123456' in v for v in values), values


def main():
    test_region_from_domain()
    result = extract_phones(load_fixture_page(), region='DE')
    test_tel_href_in_footer(result)
    test_german_number_region(result)
    test_date_and_year_absent(result)
    test_order_number_uncertain_only(result)
    test_tel_and_text_merge_one_key(result)
    test_extra_candidates()
    test_uncertain_noise_filters()
    test_audit_precision_canary()
    test_tel_href_union_when_phonenumbers_rejects()


if __name__ == '__main__':
    main()
    print('contact_scraper.test_phones tests OK')
