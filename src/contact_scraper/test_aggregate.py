# Standalone unit checks for aggregate.py (synthetic page records, no network,
# no fixtures): python3 -m contact_scraper.test_aggregate

from .aggregate import OUTPUT_KEYS, build_output, empty_output
from .html_text import html_to_soup, page_meta

EXPECTED_KEYS = [
    'domain', 'title', 'description',
    'emails', 'phones', 'phones_uncertain',
    'linkedins', 'twitters', 'instagrams', 'facebooks', 'youtubes',
    'tiktoks', 'pinterests', 'discords', 'snapchats', 'threads',
    'telegrams', 'reddits', 'whatsapps',
    'githubs', 'blueskys', 'mediums',
    'calendlys',
    'technologies',
    'error',   # always last; None on success, reason string on failure
]

DATA_KEYS = EXPECTED_KEYS[:-1]
LIST_KEYS = EXPECTED_KEYS[3:-1]   # everything after the scalar identity keys


def page(url, weight_class='other', is_homepage=False, emails=None,
         phones=None, phones_uncertain=None, socials=None):
    return {
        'url': url,
        'is_homepage': is_homepage,
        'weight_class': weight_class,
        'emails': emails or [],
        'phones': phones or [],
        'phones_uncertain': phones_uncertain or [],
        'socials': socials or [],
    }


def email_hit(value, from_href=False, in_footer=False):
    return {'value': value, 'from_href': from_href, 'in_footer': in_footer}


def phone_hit(value, from_href=False, in_footer=False, region_match=False):
    return {'value': value, 'key': value, 'from_href': from_href,
            'in_footer': in_footer, 'region_match': region_match}


def social_hit(platform, value, key, handle, from_href=False, in_footer=False):
    return {'platform': platform, 'value': value, 'key': key, 'handle': handle,
            'from_href': from_href, 'in_footer': in_footer}


def test_empty_output():
    out = empty_output('acme.com')
    assert list(out.keys()) == EXPECTED_KEYS
    assert OUTPUT_KEYS == DATA_KEYS
    assert out['domain'] == 'acme.com'
    assert out['title'] is None
    assert out['description'] is None
    for key in LIST_KEYS:
        assert out[key] == []
    assert out['error'] is None
    assert build_output('acme.com', []) == out
    failed = empty_output('dead.com', error='dns: no such host: dead.com')
    assert list(failed.keys())[-1] == 'error'
    assert failed['error'] == 'dns: no such host: dead.com'


def test_three_page_scenario():
    home = page(
        'https://acme.com/', 'homepage', is_homepage=True,
        emails=[email_hit('info@acme.com', from_href=True, in_footer=True)],
        phones=[phone_hit('+14155552671', from_href=True, in_footer=True,
                          region_match=True)],
        socials=[
            social_hit('twitters', 'https://x.com/acme', 'acme', 'acme',
                       from_href=True, in_footer=True),
            social_hit('linkedins', 'https://www.linkedin.com/company/acme',
                       'company/acme', 'acme', from_href=True, in_footer=True),
        ])
    blog = page(
        'https://acme.com/blog/post', 'other',
        emails=[email_hit('info@acme.com')],
        phones_uncertain=[phone_hit('12345678')],
        socials=[social_hit('twitters', 'https://x.com/randomguy',
                            'randomguy', 'randomguy')])
    contact = page(
        'https://acme.com/contact', 'contact',
        emails=[email_hit('info@acme.com', from_href=True),
                email_hit('sales@acme.com', from_href=True)],
        phones=[phone_hit('+14155552671', region_match=True)])

    # blog crawled before contact: sources must still order by weight first
    out = build_output('acme.com', [home, blog, contact])

    assert list(out.keys()) == EXPECTED_KEYS

    # email seen on all 3 pages merges into one entry, homepage-weight first
    assert [e['value'] for e in out['emails']] == ['info@acme.com', 'sales@acme.com']
    assert out['emails'][0]['sources'] == [
        'https://acme.com/', 'https://acme.com/contact', 'https://acme.com/blog/post']
    assert out['emails'][0]['is_likely_official'] is True
    assert out['emails'][1]['is_likely_official'] is False

    assert [e['value'] for e in out['twitters']] == [
        'https://x.com/acme', 'https://x.com/randomguy']
    assert [e['is_likely_official'] for e in out['twitters']] == [True, False]

    # single-entry list still carries exactly one flag
    assert len(out['linkedins']) == 1
    assert out['linkedins'][0]['is_likely_official'] is True

    # same phone key on two pages merges; sources ordered by weight
    assert len(out['phones']) == 1
    assert out['phones'][0]['value'] == '+14155552671'
    assert out['phones'][0]['sources'] == [
        'https://acme.com/', 'https://acme.com/contact']
    assert out['phones'][0]['is_likely_official'] is True

    # phones_uncertain entries never carry the flag
    assert out['phones_uncertain'] == [
        {'value': '12345678', 'sources': ['https://acme.com/blog/post']}]
    assert set(out['phones_uncertain'][0].keys()) == {'value', 'sources'}

    assert out['error'] is None

    # exactly one is_likely_official=True per non-empty flagged list
    for key in LIST_KEYS:
        if key == 'phones_uncertain':
            continue
        entries = out[key]
        if entries:
            assert [e['is_likely_official'] for e in entries].count(True) == 1
            assert entries[0]['is_likely_official'] is True
        else:
            assert entries == []


def test_footer_social_outranks_blog_social():
    # 5-source text-only blog account vs 2-source footer account whose handle
    # matches the domain label: prominence + similarity must win
    pages = [
        page(f'https://acme.com/blog/{i}', 'other',
             socials=[social_hit('instagrams',
                                 'https://www.instagram.com/coolblogger',
                                 'coolblogger', 'coolblogger')])
        for i in range(5)
    ]
    pages.append(page(
        'https://acme.com/', 'homepage', is_homepage=True,
        socials=[social_hit('instagrams', 'https://www.instagram.com/acme',
                            'acme', 'acme', from_href=True, in_footer=True)]))
    pages.append(page(
        'https://acme.com/contact', 'contact',
        socials=[social_hit('instagrams', 'https://www.instagram.com/acme',
                            'acme', 'acme', from_href=True, in_footer=True)]))

    out = build_output('acme.com', pages)
    assert [e['value'] for e in out['instagrams']] == [
        'https://www.instagram.com/acme', 'https://www.instagram.com/coolblogger']
    assert len(out['instagrams'][0]['sources']) == 2
    assert len(out['instagrams'][1]['sources']) == 5
    assert [e['is_likely_official'] for e in out['instagrams']] == [True, False]


def test_sources_capped_at_ten():
    # x on 12 pages, y on the first 10 and always first-seen: if the score
    # were computed AFTER capping both would tie at 10 and y would win the
    # first-seen tie-break, so x ranking first proves score-before-cap
    pages = []
    for i in range(1, 13):
        hits = [email_hit('x@othercorp.com')]
        if i <= 10:
            hits.insert(0, email_hit('y@othercorp.com'))
        pages.append(page(f'https://acme.com/p{i}', 'other', emails=hits))

    out = build_output('acme.com', pages)
    assert [e['value'] for e in out['emails']] == ['x@othercorp.com', 'y@othercorp.com']
    assert len(out['emails'][0]['sources']) == 10
    assert len(out['emails'][1]['sources']) == 10
    assert out['emails'][0]['sources'] == [
        f'https://acme.com/p{i}' for i in range(1, 11)]
    assert [e['is_likely_official'] for e in out['emails']] == [True, False]


def test_free_mail_penalty():
    # equal prominence for all three; gmail is first-seen yet must sink below
    # the neutral third-party address (-2) and the site-domain address (+4)
    p = page('https://acme.com/team', 'about',
             emails=[email_hit('john@gmail.com'),
                     email_hit('john@othercorp.com'),
                     email_hit('contact@acme.com')])
    out = build_output('acme.com', [p])
    assert [e['value'] for e in out['emails']] == [
        'contact@acme.com', 'john@othercorp.com', 'john@gmail.com']
    assert [e['is_likely_official'] for e in out['emails']] == [True, False, False]


def test_cross_page_uncertain_suppression():
    # A number validated via tel: on one page must not resurface as uncertain
    # from another page's prose; its sources merge into the valid entry.
    records = [
        page('https://acme.com/contact', weight_class='contact',
             phones=[phone_hit('+14155552671', from_href=True)]),
        page('https://acme.com/about', weight_class='about',
             phones_uncertain=[phone_hit('415.555.2671')]),
        page('https://acme.com/blog',
             phones_uncertain=[phone_hit('84591203')]),
    ]
    out = build_output('acme.com', records)
    assert [p['value'] for p in out['phones']] == ['+14155552671']
    assert set(out['phones'][0]['sources']) == {
        'https://acme.com/contact', 'https://acme.com/about'}
    assert [p['value'] for p in out['phones_uncertain']] == ['84591203']


def test_phone_semantic_merge():
    # A bare digit-suffix coincidence must NOT merge two different numbers:
    # Danish '52 33 12 34' is a suffix of the US +14152331234 but parses to a
    # different E164 in region US.
    records = [
        page('https://a.com/contact', weight_class='contact',
             phones=[phone_hit('+14152331234', from_href=True)]),
        page('https://a.com/about', weight_class='about',
             phones_uncertain=[{'value': '52 33 12 34', 'key': '52331234',
                                'from_href': False, 'in_footer': False,
                                'region_match': False}]),
    ]
    out = build_output('a.com', records)
    assert [p['value'] for p in out['phones_uncertain']] == ['52 33 12 34']

    # ...while the genuine Danish owner of that number DOES merge
    records[0]['phones'] = [phone_hit('+4552331234', from_href=True)]
    out = build_output('a.com', records)
    assert out['phones_uncertain'] == []
    assert len(out['phones'][0]['sources']) == 2

    # national tel: digits entry and the E164 form of the same number fold
    # into one E164-valued entry across pages
    records = [
        page('https://a.com/contact', weight_class='contact',
             phones=[phone_hit('02031234567', from_href=True)]),
        page('https://a.com/about', weight_class='about',
             phones=[phone_hit('+442031234567')]),
    ]
    out = build_output('a.com', records)
    assert [p['value'] for p in out['phones']] == ['+442031234567']
    assert len(out['phones'][0]['sources']) == 2


def test_tie_break_first_seen():
    p = page('https://acme.com/x', 'other',
             emails=[email_hit('a@othercorp.com'), email_hit('b@othercorp.com')])
    out = build_output('acme.com', [p])
    assert [e['value'] for e in out['emails']] == [
        'a@othercorp.com', 'b@othercorp.com']


def test_page_meta():
    soup = html_to_soup(
        '<html><head><title>  Acme \n Corp  </title>'
        '<meta NAME="Description" content=" Best   widgets  since 1999 ">'
        '</head><body></body></html>')
    assert page_meta(soup) == ('Acme Corp', 'Best widgets since 1999')

    og_only = html_to_soup(
        '<html><head><title></title>'
        '<meta property="og:title" content="Acme">'
        '<meta property="og:description" content="Widgets"></head></html>')
    assert page_meta(og_only) == ('Acme', 'Widgets')

    assert page_meta(html_to_soup('<html><body>hi</body></html>')) == (None, None)


    out = build_output('acme.com', [],
                       title='Acme Corp', description='Widgets')
    assert out['title'] == 'Acme Corp' and out['description'] == 'Widgets'
    assert list(out.keys()) == EXPECTED_KEYS


def main():
    test_empty_output()
    test_page_meta()
    test_three_page_scenario()
    test_footer_social_outranks_blog_social()
    test_sources_capped_at_ten()
    test_free_mail_penalty()
    test_cross_page_uncertain_suppression()
    test_phone_semantic_merge()
    test_tie_break_first_seen()


if __name__ == '__main__':
    main()
    print('contact_scraper.test_aggregate tests OK')
