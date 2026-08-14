# Standalone unit tests (no network): python3 -m contact_scraper.test_socials

import os

from .extract_socials import canonicalize, extract_socials
from .html_text import build_page

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


def load_page(name, url='https://www.acmeoffice.example/'):
    with open(os.path.join(FIXTURES_DIR, name), encoding='utf-8') as f:
        return build_page(url, f.read())


def value_of(result):
    assert result is not None
    return result['value']


def by_platform(hits):
    grouped = {}
    for hit in hits:
        grouped.setdefault(hit['platform'], []).append(hit)
    return grouped


def hit_by_value(hits, value):
    for hit in hits:
        if hit['value'] == value:
            return hit
    raise AssertionError('missing hit: ' + value)


def test_canonicalize_linkedin():
    r = canonicalize('linkedins', 'https://www.linkedin.com/company/acme-corp/?utm_source=nl&utm_campaign=x')
    assert value_of(r) == 'https://www.linkedin.com/company/acme-corp'
    assert r['key'] == 'company/acme-corp' and r['handle'] == 'acme-corp'
    assert value_of(canonicalize('linkedins', 'linkedin.com/in/john-doe-123')) == 'https://www.linkedin.com/in/john-doe-123'
    assert value_of(canonicalize('linkedins', 'https://linkedin.com/school/mit')) == 'https://www.linkedin.com/school/mit'
    assert canonicalize('linkedins', 'https://www.linkedin.com/shareArticle?mini=true&url=x') is None
    assert canonicalize('linkedins', 'https://www.linkedin.com/sharing/share-offsite/?url=x') is None
    assert canonicalize('linkedins', 'https://www.linkedin.com/feed/update/urn:li:activity:7123') is None
    assert canonicalize('linkedins', 'https://www.linkedin.com/posts/acme_something-activity-712') is None
    assert canonicalize('linkedins', 'https://www.linkedin.com/pulse/some-article-title') is None
    assert canonicalize('linkedins', 'https://www.linkedin.com/jobs/view/123') is None
    assert canonicalize('linkedins', 'https://www.linkedin.com/uas/login') is None
    assert canonicalize('linkedins', 'https://www.linkedin.com/legal/privacy-policy') is None
    assert canonicalize('linkedins', 'https://www.linkedin.com/login') is None


def test_canonicalize_twitter():
    r = canonicalize('twitters', 'https://twitter.com/AcmeCorp/status/123456?s=20&t=xyz')
    assert value_of(r) == 'https://x.com/AcmeCorp'
    assert r['key'] == 'acmecorp' and r['handle'] == 'AcmeCorp'
    assert value_of(canonicalize('twitters', 'mobile.twitter.com/acme')) == 'https://x.com/acme'
    assert value_of(canonicalize('twitters', 'https://x.com/acme/')) == 'https://x.com/acme'
    assert canonicalize('twitters', 'https://twitter.com/intent/tweet?url=x') is None
    assert canonicalize('twitters', 'https://x.com/i/flow/login') is None
    assert canonicalize('twitters', 'https://twitter.com/hashtag/desks') is None


def test_canonicalize_instagram():
    r = canonicalize('instagrams', 'https://www.instagram.com/acme?igshid=abc123')
    assert value_of(r) == 'https://www.instagram.com/acme'
    assert r['key'] == 'acme'
    assert value_of(canonicalize('instagrams', 'https://www.instagram.com/stories/acme.co/31415926535')) \
        == 'https://www.instagram.com/acme.co'
    assert value_of(canonicalize('instagrams', 'instagram.com/acme_shop/#bio')) == 'https://www.instagram.com/acme_shop'
    assert canonicalize('instagrams', 'https://www.instagram.com/p/Cabc123xyzQ/') is None
    assert canonicalize('instagrams', 'https://www.instagram.com/reel/Cabc123/') is None
    assert canonicalize('instagrams', 'https://www.instagram.com/tv/Cabc123/') is None
    assert canonicalize('instagrams', 'https://www.instagram.com/explore/tags/desks/') is None
    assert canonicalize('instagrams', 'https://www.instagram.com/accounts/login/') is None
    assert canonicalize('instagrams', 'https://www.instagram.com/direct/inbox/') is None


def test_canonicalize_facebook():
    assert value_of(canonicalize('facebooks', 'https://fb.com/acmecorp')) == 'https://www.facebook.com/acmecorp'
    r = canonicalize('facebooks', 'https://www.facebook.com/profile.php?id=100012345678&fbclid=IwAR123')
    assert value_of(r) == 'https://www.facebook.com/profile.php?id=100012345678'
    assert r['key'] == 'id/100012345678'
    r = canonicalize('facebooks', 'https://www.facebook.com/people/John-Doe/100044556677')
    assert value_of(r) == 'https://www.facebook.com/people/John-Doe/100044556677'
    assert r['key'] == 'people/100044556677' and r['handle'] == 'John-Doe'
    assert value_of(canonicalize('facebooks', 'https://www.facebook.com/pages/Acme-Corp/123456789012')) \
        == 'https://www.facebook.com/pages/Acme-Corp/123456789012'
    # l.facebook.com redirector unwrap
    assert value_of(canonicalize('facebooks', 'https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.facebook.com%2Facmecorp%2F&h=AT2abc')) \
        == 'https://www.facebook.com/acmecorp'
    assert canonicalize('facebooks', 'https://www.facebook.com/sharer/sharer.php?u=x') is None
    assert canonicalize('facebooks', 'https://www.facebook.com/sharer.php?u=x') is None
    assert canonicalize('facebooks', 'https://www.facebook.com/dialog/share?app_id=1') is None
    assert canonicalize('facebooks', 'https://www.facebook.com/story.php?story_fbid=1&id=2') is None
    assert canonicalize('facebooks', 'https://www.facebook.com/photo.php?fbid=123') is None
    assert canonicalize('facebooks', 'https://www.facebook.com/permalink.php?story_fbid=1&id=2') is None
    assert canonicalize('facebooks', 'https://www.facebook.com/groups/acmefans') is None
    assert canonicalize('facebooks', 'https://www.facebook.com/events/123456') is None
    assert canonicalize('facebooks', 'https://www.facebook.com/watch/?v=123') is None
    assert canonicalize('facebooks', 'https://www.facebook.com/hashtag/desks') is None
    assert canonicalize('facebooks', 'https://www.facebook.com/login.php') is None
    assert canonicalize('facebooks', 'https://www.facebook.com/plugins/like.php?href=x') is None


def test_canonicalize_youtube():
    r = canonicalize('youtubes', 'https://www.youtube.com/channel/UC1a2B3c4D5e6F7g8H9i0Jk?feature=share')
    assert value_of(r) == 'https://www.youtube.com/channel/UC1a2B3c4D5e6F7g8H9i0Jk'
    assert r['key'] == 'channel/UC1a2B3c4D5e6F7g8H9i0Jk'
    r = canonicalize('youtubes', 'https://www.youtube.com/@AcmeTube')
    assert value_of(r) == 'https://www.youtube.com/@AcmeTube'
    assert r['key'] == '@acmetube'
    assert value_of(canonicalize('youtubes', 'https://m.youtube.com/c/AcmeVideos')) == 'https://www.youtube.com/c/AcmeVideos'
    assert value_of(canonicalize('youtubes', 'youtube.com/user/acmevideos')) == 'https://www.youtube.com/user/acmevideos'
    assert canonicalize('youtubes', 'https://www.youtube.com/watch?v=dQw4w9WgXcQ') is None
    assert canonicalize('youtubes', 'https://www.youtube.com/shorts/abc123DEF45') is None
    assert canonicalize('youtubes', 'https://www.youtube.com/playlist?list=PL123abc') is None
    assert canonicalize('youtubes', 'https://www.youtube.com/embed/dQw4w9WgXcQ') is None
    assert canonicalize('youtubes', 'https://www.youtube.com/results?search_query=desks') is None
    assert canonicalize('youtubes', 'https://www.youtube.com/feed/subscriptions') is None
    assert canonicalize('youtubes', 'https://youtu.be/dQw4w9WgXcQ') is None


def test_canonicalize_tiktok():
    r = canonicalize('tiktoks', 'https://www.tiktok.com/@acme.shop/video/7012345678901234567')
    assert value_of(r) == 'https://www.tiktok.com/@acme.shop'
    assert r['key'] == 'acme.shop' and r['handle'] == 'acme.shop'
    assert value_of(canonicalize('tiktoks', 'tiktok.com/@acme')) == 'https://www.tiktok.com/@acme'
    assert canonicalize('tiktoks', 'https://www.tiktok.com/discover/standing-desks') is None
    assert canonicalize('tiktoks', 'https://www.tiktok.com/v/7012345678901234567') is None
    assert canonicalize('tiktoks', 'https://www.tiktok.com/trending/7012345678901234567') is None
    assert canonicalize('tiktoks', 'https://www.tiktok.com/tag/office') is None
    assert canonicalize('tiktoks', 'https://www.tiktok.com/live') is None


def test_canonicalize_pinterest():
    r = canonicalize('pinterests', 'https://www.pinterest.com/acmestudio/office-ideas/')
    assert value_of(r) == 'https://www.pinterest.com/acmestudio'  # board collapses to profile
    assert r['key'] == 'acmestudio'
    assert value_of(canonicalize('pinterests', 'https://cz.pinterest.com/acmestudio')) == 'https://www.pinterest.com/acmestudio'
    assert canonicalize('pinterests', 'https://www.pinterest.com/pin/123456789012/') is None
    assert canonicalize('pinterests', 'https://www.pinterest.com/search/pins/?q=desk') is None
    assert canonicalize('pinterests', 'https://www.pinterest.com/ideas/') is None
    assert canonicalize('pinterests', 'https://www.pinterest.com/login/') is None


def test_canonicalize_discord():
    r = canonicalize('discords', 'https://discord.com/invite/AbC123')
    assert value_of(r) == 'https://discord.gg/AbC123'
    assert r['key'] == 'invite/AbC123'
    assert value_of(canonicalize('discords', 'https://discordapp.com/invite/xyz12')) == 'https://discord.gg/xyz12'
    assert value_of(canonicalize('discords', 'discord.gg/acme')) == 'https://discord.gg/acme'
    r = canonicalize('discords', 'https://discord.com/users/80351110224678912')
    assert value_of(r) == 'https://discord.com/users/80351110224678912'
    assert canonicalize('discords', 'https://discord.com/channels/123456789/987654321') is None
    assert canonicalize('discords', 'https://discord.com/login') is None
    assert canonicalize('discords', 'https://discord.com/developers/docs') is None


def test_canonicalize_snapchat():
    r = canonicalize('snapchats', 'https://www.snapchat.com/add/acme.snaps')
    assert value_of(r) == 'https://www.snapchat.com/add/acme.snaps'
    assert r['key'] == 'acme.snaps'
    assert value_of(canonicalize('snapchats', 'https://www.snapchat.com/@acmesnaps')) \
        == 'https://www.snapchat.com/add/acmesnaps'
    assert canonicalize('snapchats', 'https://www.snapchat.com/discover/Acme/123') is None
    assert canonicalize('snapchats', 'https://www.snapchat.com/spotlight/abc') is None
    assert canonicalize('snapchats', 'https://www.snapchat.com/unlock/?type=SNAPCODE&uuid=1') is None


def test_canonicalize_threads():
    r = canonicalize('threads', 'https://www.threads.net/@acme.co/post/Cxyz123')
    assert value_of(r) == 'https://www.threads.net/@acme.co'  # post strips to profile
    assert r['key'] == 'acme.co'
    assert value_of(canonicalize('threads', 'https://www.threads.com/@acme')) == 'https://www.threads.net/@acme'
    assert canonicalize('threads', 'https://www.threads.net/search?q=acme') is None
    assert canonicalize('threads', 'https://www.threads.net/login') is None


def test_canonicalize_telegram():
    r = canonicalize('telegrams', 'https://t.me/acme_news/1234')
    assert value_of(r) == 'https://t.me/acme_news'  # trailing message id strips
    assert r['key'] == 'acme_news'
    assert value_of(canonicalize('telegrams', 'https://t.me/s/acme_news')) == 'https://t.me/acme_news'
    assert value_of(canonicalize('telegrams', 'telegram.me/acme_news')) == 'https://t.me/acme_news'
    r = canonicalize('telegrams', 'https://t.me/joinchat/AAAAAEkk2WdoDrB4-Q8-gg')
    assert value_of(r) == 'https://t.me/joinchat/AAAAAEkk2WdoDrB4-Q8-gg'
    r = canonicalize('telegrams', 'https://t.me/+AbCdEfGhIjKlMnOp')
    assert value_of(r) == 'https://t.me/+AbCdEfGhIjKlMnOp'
    assert r['handle'] == 'AbCdEfGhIjKlMnOp'
    assert canonicalize('telegrams', 'https://t.me/share/url?url=x&text=y') is None
    assert canonicalize('telegrams', 'https://t.me/proxy?server=1.2.3.4&port=443') is None
    assert canonicalize('telegrams', 'https://t.me/addstickers/AcmePack') is None
    assert canonicalize('telegrams', 'https://t.me/setlanguage/en') is None
    assert canonicalize('telegrams', 'https://t.me/iv?url=x') is None
    assert canonicalize('telegrams', 'https://t.me/bg/abc') is None


def test_canonicalize_reddit():
    r = canonicalize('reddits', 'https://www.reddit.com/u/acme_dev')
    assert value_of(r) == 'https://www.reddit.com/user/acme_dev'
    assert r['key'] == 'user/acme_dev'
    assert value_of(canonicalize('reddits', 'https://www.reddit.com/user/acme_dev/')) \
        == 'https://www.reddit.com/user/acme_dev'
    r = canonicalize('reddits', 'https://old.reddit.com/r/acme')
    assert value_of(r) == 'https://www.reddit.com/r/acme'
    assert r['key'] == 'r/acme'
    assert canonicalize('reddits', 'https://www.reddit.com/message/compose') is None
    assert canonicalize('reddits', 'https://www.reddit.com/submit?url=x') is None
    assert canonicalize('reddits', 'https://www.reddit.com/search/?q=acme') is None
    assert canonicalize('reddits', 'https://www.reddit.com/wiki/index') is None


def test_canonicalize_whatsapp():
    r = canonicalize('whatsapps', 'https://wa.me/447911123456')
    assert value_of(r) == 'https://wa.me/447911123456'
    assert r['handle'] == '447911123456'
    assert value_of(canonicalize('whatsapps', 'https://api.whatsapp.com/send?phone=%2B420777123456&text=Hi')) \
        == 'https://wa.me/420777123456'
    assert value_of(canonicalize('whatsapps', 'https://web.whatsapp.com/send/?phone=14155552671')) \
        == 'https://wa.me/14155552671'
    assert value_of(canonicalize('whatsapps', 'https://chat.whatsapp.com/AbCdEfGhIjKlMnOpQrSt')) \
        == 'https://chat.whatsapp.com/AbCdEfGhIjKlMnOpQrSt'
    assert canonicalize('whatsapps', 'https://wa.me/message/ABCDEF123XYZ') is None
    assert canonicalize('whatsapps', 'https://api.whatsapp.com/send?text=hello') is None


EXPECTED_MIXED = {
    'linkedins': {'https://www.linkedin.com/company/acme'},
    'twitters': {'https://x.com/acme'},
    'instagrams': {'https://www.instagram.com/acmeoffice',
                   'https://www.instagram.com/acme_insider'},
    'facebooks': {'https://www.facebook.com/acmeoffice'},
    'youtubes': {'https://www.youtube.com/@acme'},
    'tiktoks': {'https://www.tiktok.com/@acmeoffice',
                'https://www.tiktok.com/@acmetech'},
    'pinterests': {'https://www.pinterest.com/acmeoffice'},
    'discords': {'https://discord.gg/acmecommunity'},
    'snapchats': {'https://www.snapchat.com/add/acmesnaps'},
    'threads': {'https://www.threads.net/@acmeoffice'},
    'telegrams': {'https://t.me/acme_official'},
    'reddits': {'https://www.reddit.com/r/acme'},
    'whatsapps': {'https://wa.me/14155552671'},
}

FOOTER_VALUES = {
    'https://www.linkedin.com/company/acme',
    'https://x.com/acme',
    'https://www.facebook.com/acmeoffice',
    'https://www.instagram.com/acmeoffice',
    'https://www.youtube.com/@acme',
    'https://www.tiktok.com/@acmeoffice',
    'https://t.me/acme_official',
    'https://wa.me/14155552671',
}

BODY_VALUES = {
    'https://www.tiktok.com/@acmetech',
    'https://discord.gg/acmecommunity',
    'https://www.reddit.com/r/acme',
    'https://www.pinterest.com/acmeoffice',
    'https://www.snapchat.com/add/acmesnaps',
    'https://www.threads.net/@acmeoffice',
}


def test_mixed_page():
    page = load_page('socials_mixed.html')
    hits, wa_candidates = extract_socials(page)

    grouped = by_platform(hits)
    assert set(grouped) == set(EXPECTED_MIXED), (set(grouped), set(EXPECTED_MIXED))
    for platform, expected_values in EXPECTED_MIXED.items():
        got = {h['value'] for h in grouped[platform]}
        assert got == expected_values, (platform, got, expected_values)
    assert len(hits) == 15  # 13 platforms + extra tiktok + extra instagram, nothing else

    # both tiktok accounts survive as separate keys
    tiktok_keys = {h['key'] for h in grouped['tiktoks']}
    assert tiktok_keys == {'acmeoffice', 'acmetech'}

    # tracking params were stripped from the linkedin footer link
    linkedin = grouped['linkedins'][0]
    assert 'utm' not in linkedin['value']
    assert linkedin['value'] == 'https://www.linkedin.com/company/acme'

    # footer anchors: flags OR-merged across raw-HTML and anchor passes
    for value in FOOTER_VALUES:
        hit = hit_by_value(hits, value)
        assert hit['in_footer'] is True, value
        assert hit['from_href'] is True, value

    # body anchors: linked but not in footer
    for value in BODY_VALUES:
        hit = hit_by_value(hits, value)
        assert hit['in_footer'] is False, value
        assert hit['from_href'] is True, value

    # JSON-LD sameAs instagram: raw-HTML scan only, no anchor
    jsonld = hit_by_value(hits, 'https://www.instagram.com/acme_insider')
    assert jsonld['from_href'] is False
    assert jsonld['in_footer'] is False

    assert wa_candidates == ['+14155552671']


def test_share_links_page():
    page = load_page('socials_share_links.html', url='https://blog.example.com/ten-desks')
    hits, wa_candidates = extract_socials(page)

    # every pure share/intent/content URL yields nothing; the only survivor is
    # the tiktok video link canonicalized to its author profile
    assert len(hits) == 1, [h['value'] for h in hits]
    hit = hits[0]
    assert hit['platform'] == 'tiktoks'
    assert hit['value'] == 'https://www.tiktok.com/@someuser'
    assert hit['key'] == 'someuser'
    assert hit['from_href'] is True
    assert hit['in_footer'] is False
    assert wa_candidates == []


def test_canonicalize_new_platforms():
    # github: profiles, orgs, repo->owner collapse; reserved dropped
    assert canonicalize('githubs', 'https://github.com/omkarcloud')['value'] == 'https://github.com/omkarcloud'
    assert canonicalize('githubs', 'https://github.com/orgs/omkarcloud')['key'] == 'omkarcloud'
    assert canonicalize('githubs', 'https://github.com/omkarcloud/botasaurus')['value'] == 'https://github.com/omkarcloud'
    assert canonicalize('githubs', 'https://github.com/features/actions') is None
    assert canonicalize('githubs', 'https://github.com/pricing') is None

    # bluesky
    assert canonicalize('blueskys', 'https://bsky.app/profile/acme.bsky.social')['value'] == 'https://bsky.app/profile/acme.bsky.social'
    assert canonicalize('blueskys', 'https://bsky.app/settings') is None

    # medium: @user and subdomain forms
    assert canonicalize('mediums', 'https://medium.com/@acme')['value'] == 'https://medium.com/@acme'
    assert canonicalize('mediums', 'https://acme.medium.com/some-post-123')['value'] == 'https://acme.medium.com'
    assert canonicalize('mediums', 'https://medium.com/some-publication') is None

    # calendly: profile, event collapse, d/ links, reserved dropped
    assert canonicalize('calendlys', 'https://calendly.com/acme-sales/30min')['value'] == 'https://calendly.com/acme-sales'
    assert canonicalize('calendlys', 'https://calendly.com/d/abc-def-ghi')['key'] == 'd/abc-def-ghi'
    assert canonicalize('calendlys', 'https://calendly.com/pricing') is None


def test_new_platforms_detection():
    html = '''<html><body><footer>
      <a href="https://github.com/acmecorp/widget-lib">GitHub</a>
      <a href="https://bsky.app/profile/acme.bsky.social">Bluesky</a>
      <a href="https://medium.com/@acme">Medium</a>
      <a href="https://calendly.com/acme-sales/intro">Book a call</a>
    </footer></body></html>'''
    hits, _ = extract_socials(build_page('https://acme.com/', html))
    by_platform = {h['platform']: h for h in hits}
    assert by_platform['githubs']['value'] == 'https://github.com/acmecorp'
    assert by_platform['blueskys']['value'] == 'https://bsky.app/profile/acme.bsky.social'
    assert by_platform['mediums']['value'] == 'https://medium.com/@acme'
    assert by_platform['calendlys']['value'] == 'https://calendly.com/acme-sales'
    assert all(h['in_footer'] and h['from_href'] for h in by_platform.values())


def test_round1_junk_filters():
    # github library credits in bundled CSS must not become hits...
    css_credit = ('<html><head><style>/*! normalize.css v8.0.1 | MIT License |'
                  ' github.com/necolas/normalize.css */</style></head>'
                  '<body><a href="https://github.com/acmecorp">Our GitHub</a></body></html>')
    hits, _ = extract_socials(build_page('https://acme.com/', css_credit))
    githubs = [h['value'] for h in hits if h['platform'] == 'githubs']
    assert githubs == ['https://github.com/acmecorp'], githubs


    # ...and twitter language/settings paths are not handles
    assert canonicalize('twitters', 'https://x.com/en') is None
    assert canonicalize('twitters', 'https://twitter.com/personalization') is None

    # facebook bare /share/... links are shares, not profiles
    assert canonicalize('facebooks', 'https://www.facebook.com/share/p/abc123') is None

    # "Built with Wix" vendor credits are dropped unless the site IS the vendor
    vendor = '<footer><a href="https://x.com/wix">Wix</a><a href="https://x.com/acmecorp">Us</a></footer>'
    hits2, _ = extract_socials(build_page('https://acmecorp.com/', vendor))
    assert [h['value'] for h in hits2] == ['https://x.com/acmecorp'], hits2
    hits3, _ = extract_socials(build_page('https://wix.com/', vendor))
    assert 'https://x.com/wix' in [h['value'] for h in hits3]


def test_ascii_regex_parity():
    # JS \w is ASCII-only: URLs glued to CJK/Cyrillic text must still match
    # (Python Unicode \w in the (?<!\w) lookbehind used to block them).
    hits, _ = extract_socials(build_page(
        'https://a.com/', '<p>关注我们twitter.com/acme 领英linkedin.com/company/acme</p>'))
    values = {h['value'] for h in hits}
    assert 'https://x.com/acme' in values, values
    assert 'https://www.linkedin.com/company/acme' in values, values
    # ...and Unicode case folding must not swallow the Kelvin sign into handles
    hits2, _ = extract_socials(build_page(
        'https://a.com/', '<p>twitter.com/acmeK</p>'))
    assert {h['value'] for h in hits2} == {'https://x.com/acme'}, hits2


def test_telegram_preview_links():
    from .social_regexes import PLATFORM_REGEXES_GLOBAL, find_full_matches
    matches = find_full_matches(PLATFORM_REGEXES_GLOBAL['telegrams'],
                                'see https://t.me/s/durov now')
    assert matches, 'preview form must be detectable'
    assert canonicalize('telegrams', matches[0])['value'] == 'https://t.me/durov'


def test_escaped_json_ld():
    # Next.js / schema.org JSON-LD escapes slashes; detection must still work.
    html = ('<html><body><script type="application/ld+json">'
            '{"sameAs":["https:\\/\\/www.instagram.com\\/acmecorp",'
            '"https:\\/\\/x.com\\/acmecorp"]}</script></body></html>')
    hits, _ = extract_socials(build_page('https://acme.com/', html))
    values = {h['value'] for h in hits}
    assert 'https://www.instagram.com/acmecorp' in values, values
    assert 'https://x.com/acmecorp' in values, values


def main():
    test_canonicalize_linkedin()
    test_canonicalize_twitter()
    test_canonicalize_instagram()
    test_canonicalize_facebook()
    test_canonicalize_youtube()
    test_canonicalize_tiktok()
    test_canonicalize_pinterest()
    test_canonicalize_discord()
    test_canonicalize_snapchat()
    test_canonicalize_threads()
    test_canonicalize_telegram()
    test_canonicalize_reddit()
    test_canonicalize_whatsapp()
    test_mixed_page()
    test_share_links_page()
    test_canonicalize_new_platforms()
    test_new_platforms_detection()
    test_round1_junk_filters()
    test_ascii_regex_parity()
    test_telegram_preview_links()
    test_escaped_json_ld()


if __name__ == '__main__':
    main()
    print('contact_scraper.test_socials tests OK')
