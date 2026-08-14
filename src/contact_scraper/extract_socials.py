# Social profile detection + canonicalization for the 13 platform keys of
# social_regexes.PLATFORM_REGEXES_GLOBAL.
#
# Detection is two-pass: the platform regexes run over raw HTML (which
# catches plain hrefs, JSON-LD sameAs and meta tags), then an anchor pass
# re-tests each resolved href so hits can carry DOM-prominence flags
# (from_href / in_footer). Every raw hit goes through canonicalize();
# None means drop (share/intent/login/content URLs).

import html
import re
from urllib.parse import parse_qsl, urlsplit

import tldextract

from .social_regexes import (
    PLATFORM_REGEXES_GLOBAL,
    TWITTER_RESERVED_PATHS,
    find_full_matches,
)

# Same cap as the text scans: the platform regexes must not crawl multi-MB
# script bundles end to end.
MAX_HTML_SCAN_CHARS = 1_500_000

# Platforms whose URLs routinely appear as library credits in bundled CSS/JS
# (normalize.css -> github.com/necolas, Bootstrap -> github.com/twbs): only
# real anchors count, never the raw-HTML scan.
ANCHOR_ONLY_PLATFORMS = {'githubs'}

# Site-builder vendors whose own social profiles leak in via "Built with X"
# footers; dropped unless the crawled site IS that vendor.
VENDOR_HANDLES = set(
    'wix wixstudio shopify shopifyplus wordpress wordpressdotcom squarespace '
    'godaddy webflow elementor woocommerce weebly jimdo duda strikingly '
    'bigcommerce prestashop'.split())

TRACKING_PARAM_RE = re.compile(
    r'^(utm_.*|fbclid|gclid|msclkid|dclid|yclid|igshid|igsh|si|ref|ref_src'
    r'|ref_url|source|mc_cid|mc_eid|_ga|feature)$',
    re.IGNORECASE | re.ASCII,
)

_SCHEME_RE = re.compile(r'^[a-z][a-z0-9+.\-]*://', re.IGNORECASE | re.ASCII)

_tld_extract = tldextract.TLDExtract(suffix_list_urls=())  # offline snapshot

_TWITTER_RESERVED = set(TWITTER_RESERVED_PATHS.split('|'))

_INSTAGRAM_DROP = {'p', 'reel', 'reels', 'tv', 'explore', 'accounts', 'direct', '_n', '_u'}

_FACEBOOK_DROP = {
    'dialog', 'login', 'plugins', 'groups', 'events', 'watch', 'hashtag',
    'story.php', 'photo.php', 'permalink.php', 'share.php', 'help',
    'settings', 'marketplace', 'gaming', 'business', 'policies',
}

_PINTEREST_DROP = {'pin', 'search', 'ideas', 'today', 'categories', 'discover',
                   'login', 'signup', 'settings', 'source', 'business'}

_DISCORD_DROP = {'channels', 'login', 'register', 'app', 'developers', 'api',
                 'widget', 'download'}

_THREADS_DROP = {'login', 'search', 'explore', 'activity', 'settings', 'about',
                 'privacy', 'terms', 't'}

_TELEGRAM_DROP = {'share', 'proxy', 'socks', 'addstickers', 'addemoji',
                  'setlanguage', 'iv', 'bg', 'login', 'confirmphone'}

_REDDIT_DROP = {'comments', 'submit', 'wiki', 'message', 'search'}

_GITHUB_DROP = set(
    'about features topics collections trending marketplace sponsors settings '
    'notifications explore apps site security contact pricing login join signup '
    'sessions organizations enterprise enterprises team customer-stories readme '
    'resources git-guides events search new codespaces copilot issues pulls '
    'discussions blog solutions premium-support mobile account'.split())

# Non-handle path segments that show up in embed/widget scripts and language
# pickers; kept out of the ported regex (parity) but dropped at canonicalize.
_TWITTER_EXTRA_RESERVED = set(
    'en es de fr it pt ja ko ar ru nl pl tr id sv '
    'personalization download javascripts statuses about jobs'.split())

_CALENDLY_DROP = set(
    'features pricing integrations blog teams help signup login app api '
    'event_types solutions resources customers security newsletter press '
    'careers legal'.split())


def _is_tracking(platform_key, param_name):
    if TRACKING_PARAM_RE.match(param_name):
        return True
    return platform_key == 'twitters' and param_name in ('s', 't')


def _split_url(raw_url):
    # &amp; appears in raw-HTML regex matches (href attributes are entity-escaped)
    url = html.unescape(raw_url.strip())
    if not _SCHEME_RE.match(url):
        url = 'https://' + url
    try:
        parts = urlsplit(url)
        host = (parts.hostname or '').lower()
    except ValueError:
        return None
    changed = True
    while changed:
        changed = False
        for prefix in ('www.', 'm.', 'mobile.'):
            if host.startswith(prefix) and len(host) > len(prefix):
                host = host[len(prefix):]
                changed = True
    segs = [s for s in parts.path.split('/') if s]
    params = parse_qsl(parts.query, keep_blank_values=True)
    return host, segs, params


def _hit(value, key, handle):
    return {'value': value, 'key': key, 'handle': handle}


def _host_is(host, *domains):
    return any(host == d or host.endswith('.' + d) for d in domains)


def _canon_linkedin(host, segs, params):
    if not _host_is(host, 'linkedin.com') or len(segs) < 2:
        return None
    kind = segs[0].lower()
    if kind not in ('in', 'company', 'school'):
        return None
    slug = segs[1]
    return _hit(f'https://www.linkedin.com/{kind}/{slug}', f'{kind}/{slug.lower()}', slug)


def _canon_twitter(host, segs, params):
    if not _host_is(host, 'twitter.com', 'x.com') or not segs:
        return None
    handle = segs[0].lstrip('@')
    if handle.lower() in _TWITTER_RESERVED or handle.lower() in _TWITTER_EXTRA_RESERVED:
        return None
    if not re.fullmatch(r'[a-z0-9_]{1,15}', handle, re.IGNORECASE | re.ASCII):
        return None
    return _hit(f'https://x.com/{handle}', handle.lower(), handle)


def _canon_instagram(host, segs, params):
    if not _host_is(host, 'instagram.com', 'instagr.am') or not segs:
        return None
    first = segs[0].lower()
    if first in _INSTAGRAM_DROP:
        return None
    if first == 'stories':
        if len(segs) < 2:
            return None
        user = segs[1]
    else:
        user = segs[0]
    user = user.rstrip('.')
    if not re.fullmatch(r'[a-z0-9_.]{2,30}', user, re.IGNORECASE | re.ASCII):
        return None
    return _hit(f'https://www.instagram.com/{user}', user.lower(), user)


def _canon_facebook(host, segs, params):
    if not _host_is(host, 'facebook.com', 'fb.com') or not segs:
        return None
    first = segs[0].lower()
    if first.startswith('share') or first in _FACEBOOK_DROP:
        return None  # share, sharer, sharer.php, share.php
    if first.endswith('.php') and first != 'profile.php':
        return None  # login.php, story.php, l.php, ... - endpoints, not usernames
    if first == 'profile.php':
        pid = next((v for k, v in params if k == 'id'), None)
        if not pid or not pid.isdigit():
            return None
        return _hit(f'https://www.facebook.com/profile.php?id={pid}', f'id/{pid}', pid)
    if first in ('people', 'pages'):
        if len(segs) < 3 or not segs[2].isdigit():
            return None
        name, fid = segs[1], segs[2]
        return _hit(f'https://www.facebook.com/{first}/{name}/{fid}', f'{first}/{fid}', name)
    username = segs[0].rstrip('.')
    if not re.fullmatch(r'[a-z0-9.]{5,51}', username, re.IGNORECASE | re.ASCII):
        return None
    return _hit(f'https://www.facebook.com/{username}', username.lower(), username)


def _canon_youtube(host, segs, params):
    # bare youtu.be links are always video ids, never channels
    if _host_is(host, 'youtu.be'):
        return None
    if not _host_is(host, 'youtube.com') or not segs:
        return None
    first = segs[0]
    if first.startswith('@') and len(first) > 1:
        handle = first[1:]
        return _hit(f'https://www.youtube.com/@{handle}', f'@{handle.lower()}', handle)
    kind = first.lower()
    if kind == 'channel' and len(segs) >= 2:
        cid = segs[1]
        # channel ids are case-sensitive: keep case in the dedupe key
        return _hit(f'https://www.youtube.com/channel/{cid}', f'channel/{cid}', cid)
    if kind in ('c', 'user') and len(segs) >= 2:
        name = segs[1]
        return _hit(f'https://www.youtube.com/{kind}/{name}', f'{kind}/{name.lower()}', name)
    return None


def _canon_tiktok(host, segs, params):
    if not _host_is(host, 'tiktok.com') or not segs:
        return None
    first = segs[0]
    if not first.startswith('@') or len(first) < 2:
        return None
    user = first[1:].rstrip('.')
    if not user:
        return None
    return _hit(f'https://www.tiktok.com/@{user}', user.lower(), user)


def _canon_pinterest(host, segs, params):
    # hosts: pinterest.com, pinterest.<cc>(.<cc>), <cc>.pinterest.com
    if 'pinterest' not in host.split('.') or not segs:
        return None
    user = segs[0].rstrip('.')
    if user.lower() in _PINTEREST_DROP:
        return None
    if not re.fullmatch(r'[a-z0-9\-_.]+', user, re.IGNORECASE | re.ASCII):
        return None
    # /<user>/<board> collapses to the profile
    return _hit(f'https://www.pinterest.com/{user}', user.lower(), user)


def _canon_discord(host, segs, params):
    host = host.removeprefix('canary.').removeprefix('ptb.')
    if host == 'discordapp.com':
        host = 'discord.com'
    if not _host_is(host, 'discord.com', 'discord.gg', 'discord.me', 'discord.li', 'discord.io'):
        return None
    if not segs:
        return None
    first = segs[0].lower()
    if first in _DISCORD_DROP:
        return None
    if first == 'users':
        if len(segs) < 2 or not segs[1].isdigit():
            return None
        return _hit(f'https://discord.com/users/{segs[1]}', f'users/{segs[1]}', segs[1])
    if first == 'invite':
        if len(segs) < 2:
            return None
        code = segs[1]
    else:
        code = segs[0]
    if not re.fullmatch(r'[a-z0-9\-_]{2,50}', code, re.IGNORECASE | re.ASCII):
        return None
    # invite codes are case-sensitive: keep case in the dedupe key
    return _hit(f'https://discord.gg/{code}', f'invite/{code}', code)


def _canon_snapchat(host, segs, params):
    if not _host_is(host, 'snapchat.com') or not segs:
        return None
    first = segs[0]
    # everything except add/<user> and @<user> (discover, spotlight, lens,
    # unlock, download, explore, ...) is dropped
    if first.startswith('@') and len(first) > 1:
        user = first[1:]
    elif first.lower() == 'add' and len(segs) >= 2:
        user = segs[1]
    else:
        return None
    user = user.rstrip('.')
    if not re.fullmatch(r'[a-z0-9\-_.]{3,32}', user, re.IGNORECASE | re.ASCII):
        return None
    return _hit(f'https://www.snapchat.com/add/{user}', user.lower(), user)


def _canon_threads(host, segs, params):
    if not _host_is(host, 'threads.net', 'threads.com') or not segs:
        return None
    user = segs[0].lstrip('@')
    if not user or user.lower() in _THREADS_DROP:
        return None
    user = user.rstrip('.')
    if not re.fullmatch(r'[a-z0-9_.]{2,30}', user, re.IGNORECASE | re.ASCII):
        return None
    # /post/<code> after the handle is ignored -> profile
    return _hit(f'https://www.threads.net/@{user}', user.lower(), user)


def _canon_telegram(host, segs, params):
    if not _host_is(host, 't.me', 'telegram.me', 'telegram.dog') or not segs:
        return None
    first = segs[0]
    low = first.lower()
    if low in _TELEGRAM_DROP:
        return None
    if low == 's':  # t.me/s/<channel> web preview
        if len(segs) < 2:
            return None
        first = segs[1]
        low = first.lower()
        if low in _TELEGRAM_DROP:
            return None
    if low == 'joinchat':
        if len(segs) < 2:
            return None
        return _hit(f'https://t.me/joinchat/{segs[1]}', f'joinchat/{segs[1]}', segs[1])
    if first.startswith('+') and len(first) > 1:
        # private invite hash, case-sensitive, kept as-is
        return _hit(f'https://t.me/{first}', first, first[1:])
    if not re.fullmatch(r'[a-z0-9_]{5,32}', first, re.IGNORECASE | re.ASCII):
        return None
    # trailing /<msgid> segments are ignored -> channel/profile
    return _hit(f'https://t.me/{first}', first.lower(), first)


def _canon_reddit(host, segs, params):
    if not _host_is(host, 'reddit.com') or not segs:
        return None
    first = segs[0].lower()
    if first in _REDDIT_DROP:
        return None
    if first in ('u', 'user') and len(segs) >= 2:
        name = segs[1]
        if not re.fullmatch(r'[a-z0-9\-_]{3,20}', name, re.IGNORECASE | re.ASCII):
            return None
        return _hit(f'https://www.reddit.com/user/{name}', f'user/{name.lower()}', name)
    if first == 'r' and len(segs) >= 2:
        name = segs[1]
        if not re.fullmatch(r'[a-z0-9_]{2,21}', name, re.IGNORECASE | re.ASCII):
            return None
        return _hit(f'https://www.reddit.com/r/{name}', f'r/{name.lower()}', name)
    return None


def _canon_whatsapp(host, segs, params):
    if host == 'wa.me':
        if not segs or segs[0].lower() == 'message':
            return None
        digits = segs[0].lstrip('+')
        if not re.fullmatch(r'[0-9]{7,15}', digits):
            return None
        return _hit(f'https://wa.me/{digits}', f'wa.me/{digits}', digits)
    if host == 'chat.whatsapp.com':
        if segs[:1] == ['invite']:
            segs = segs[1:]
        if not segs or not re.fullmatch(r'[a-zA-Z0-9]{16,32}', segs[0]):
            return None
        return _hit(f'https://chat.whatsapp.com/{segs[0]}', f'chat/{segs[0]}', segs[0])
    if _host_is(host, 'whatsapp.com'):
        if [s.lower() for s in segs] != ['send']:
            return None
        phone = next((v for k, v in params if k == 'phone'), None)
        if not phone:
            return None  # text-only send link
        digits = re.sub(r'\D', '', phone)
        if not re.fullmatch(r'[0-9]{7,15}', digits):
            return None
        return _hit(f'https://wa.me/{digits}', f'wa.me/{digits}', digits)
    return None


def _canon_github(host, segs, params):
    if not _host_is(host, 'github.com') or not segs:
        return None
    if segs[0].lower() == 'orgs':
        if len(segs) < 2:
            return None
        login = segs[1]
    else:
        # github.com/<owner>/<repo> collapses to the owner profile
        login = segs[0]
    if login.lower() in _GITHUB_DROP:
        return None
    if not re.fullmatch(r'[a-z0-9][a-z0-9\-]{0,38}', login, re.IGNORECASE | re.ASCII):
        return None
    return _hit(f'https://github.com/{login}', login.lower(), login)


def _canon_bluesky(host, segs, params):
    if not _host_is(host, 'bsky.app'):
        return None
    if len(segs) < 2 or segs[0].lower() != 'profile':
        return None
    handle = segs[1].lower().rstrip('.')
    if not re.fullmatch(r'[a-z0-9][a-z0-9.:\-]{1,255}', handle):
        return None
    return _hit(f'https://bsky.app/profile/{handle}', handle, handle)


def _canon_medium(host, segs, params):
    if host.endswith('.medium.com') and host != 'www.medium.com':
        sub = host[:-len('.medium.com')]
        if not re.fullmatch(r'[a-z0-9\-]{2,50}', sub):
            return None
        return _hit(f'https://{sub}.medium.com', sub, sub)
    if not _host_is(host, 'medium.com') or not segs:
        return None
    first = segs[0]
    if not first.startswith('@') or len(first) < 3:
        return None  # bare publications are too ambiguous with reserved paths
    user = first[1:].rstrip('.')
    if not re.fullmatch(r'[a-z0-9_.\-]{2,50}', user, re.IGNORECASE | re.ASCII):
        return None
    return _hit(f'https://medium.com/@{user}', user.lower(), user)


def _canon_calendly(host, segs, params):
    if not _host_is(host, 'calendly.com') or not segs:
        return None
    first = segs[0]
    if first.lower() in _CALENDLY_DROP:
        return None
    if first.lower() == 'd':
        # one-off shareable scheduling links: calendly.com/d/<code>
        if len(segs) < 2 or not re.fullmatch(r'[a-z0-9\-]{3,30}', segs[1], re.IGNORECASE | re.ASCII):
            return None
        return _hit(f'https://calendly.com/d/{segs[1]}', f'd/{segs[1].lower()}', segs[1])
    if not re.fullmatch(r'[a-z0-9_\-]{2,60}', first, re.IGNORECASE | re.ASCII):
        return None
    # event subpaths (/30min etc.) collapse to the profile
    return _hit(f'https://calendly.com/{first}', first.lower(), first)


_CANONICALIZERS = {
    'linkedins': _canon_linkedin,
    'twitters': _canon_twitter,
    'instagrams': _canon_instagram,
    'facebooks': _canon_facebook,
    'youtubes': _canon_youtube,
    'tiktoks': _canon_tiktok,
    'pinterests': _canon_pinterest,
    'discords': _canon_discord,
    'snapchats': _canon_snapchat,
    'threads': _canon_threads,
    'telegrams': _canon_telegram,
    'reddits': _canon_reddit,
    'whatsapps': _canon_whatsapp,
    'githubs': _canon_github,
    'blueskys': _canon_bluesky,
    'mediums': _canon_medium,
    'calendlys': _canon_calendly,
}


def canonicalize(platform_key, raw_url, _depth=0):
    if _depth > 2 or not raw_url:
        return None
    split = _split_url(raw_url)
    if split is None:
        return None
    host, segs, params = split
    # l.facebook.com/l.php?u=<target> wraps any outbound URL
    if host.endswith('facebook.com') and [s.lower() for s in segs[:1]] == ['l.php']:
        target = next((v for k, v in params if k == 'u'), None)
        if not target:
            return None
        return canonicalize(platform_key, target, _depth + 1)
    params = [(k, v) for k, v in params if not _is_tracking(platform_key, k)]
    fn = _CANONICALIZERS.get(platform_key)
    if fn is None:
        return None
    return fn(host, segs, params)


def _add(hits, order, wa_candidates, platform, raw_url, from_href, in_footer,
         domain_label=''):
    result = canonicalize(platform, raw_url)
    if result is None:
        return
    handle_low = (result['handle'] or '').lower()
    if handle_low in VENDOR_HANDLES and handle_low != domain_label:
        return  # "Built with Wix" footer credit, not this business's profile
    merge_key = (platform, result['key'])
    if merge_key in hits:
        hit = hits[merge_key]
        hit['from_href'] = hit['from_href'] or from_href
        hit['in_footer'] = hit['in_footer'] or in_footer
    else:
        hits[merge_key] = {
            'platform': platform,
            'value': result['value'],
            'key': result['key'],
            'handle': result['handle'],
            'from_href': from_href,
            'in_footer': in_footer,
        }
        order.append(merge_key)
    if platform == 'whatsapps' and result['value'].startswith('https://wa.me/'):
        candidate = '+' + result['handle']
        if candidate not in wa_candidates:
            wa_candidates.append(candidate)


def extract_socials(page):
    """Returns (hits, whatsapp_phone_candidates); hits deduped by
    (platform, key), flags OR-merged, first-seen order."""
    hits = {}
    order = []
    wa_candidates = []
    domain_label = _tld_extract(page.url).domain.lower()
    html_slice = page.html[:MAX_HTML_SCAN_CHARS]
    scan_targets = [html_slice]
    if '\\/' in html_slice:
        # JSON-LD / inline JSON escapes slashes (https:\/\/instagram.com\/x);
        # the platform regexes need the unescaped form to match.
        scan_targets.append(html_slice.replace('\\/', '/'))
    for platform, regex in PLATFORM_REGEXES_GLOBAL.items():
        if platform in ANCHOR_ONLY_PLATFORMS:
            continue
        for target in scan_targets:
            for raw in find_full_matches(regex, target):
                _add(hits, order, wa_candidates, platform, raw, False, False,
                     domain_label)
    for anchor in page.anchors:
        resolved = anchor['resolved']
        if not resolved:
            continue
        for platform, regex in PLATFORM_REGEXES_GLOBAL.items():
            if regex.search(resolved):
                _add(hits, order, wa_candidates, platform, resolved,
                     True, anchor['in_footer'], domain_label)
    return [hits[key] for key in order], wa_candidates
