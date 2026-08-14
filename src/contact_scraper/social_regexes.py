# Email, phone and social-profile regexes. The core patterns are Python ports
# of long-lived JS regexes, kept semantically identical.
#
# Porting rules:
# - JS string escapes collapsed into Python raw strings (\\. -> \., \\\\ -> \\).
# - JS /i flag -> re.IGNORECASE | re.ASCII: JS \w and [a-z]/i are ASCII-only
#   (Python defaults to Unicode \w and Unicode case folding, which both
#   breaks (?<!\w) on CJK/Cyrillic pages and swallows Kelvin-sign/dotless-i
#   lookalikes into handles). JS text.match(/.../ig) returns FULL matches,
#   so use find_full_matches() (finditer + group(0)) - never re.findall, which
#   would return capture group 1 instead of the whole match.
# - JS /^...$/i exact regexes -> compiled_pattern.fullmatch().
# - Historical quirks (unescaped dots in "www." / "twitter.com", "(-|.)" in phone
#   patterns, duplicate phone pattern #2/#3) are kept verbatim for parity.
#
# Documented deviations from the original JS patterns (deliberate, nothing else changed):
# - TWITTER: added x.com host + reserved paths explore|notifications|messages|compose.
# - YOUTUBE: added "@" to the handle char class for youtube.com/@handle channels.
# - Net-new platforms (same style, no JS predecessor): SNAPCHAT, THREADS, TELEGRAM,
#   REDDIT, WHATSAPP.

import re

EMAIL_REGEX_STRING = r'''(?:[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*|"(?:[\x01-\x08\x0b\x0c\x0e-\x1f\x21\x23-\x5b\x5d-\x7f]|\\[\x01-\x09\x0b\x0c\x0e-\x7f])*")@(?:(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?|\[(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[a-z0-9-]*[a-z0-9]:(?:[\x01-\x08\x0b\x0c\x0e-\x1f\x21-\x5a\x53-\x7f]|\\[\x01-\x09\x0b\x0c\x0e-\x7f])+)\])'''

EMAIL_REGEX = re.compile(EMAIL_REGEX_STRING, re.IGNORECASE | re.ASCII)          # use .fullmatch
EMAIL_REGEX_GLOBAL = re.compile(EMAIL_REGEX_STRING, re.IGNORECASE | re.ASCII)   # use .finditer

EMAIL_URL_PREFIX_REGEX = re.compile(r'^mailto:', re.IGNORECASE | re.ASCII)

# Supports URLs starting with tel://, tel:/ and tel:, and similarly phone,
# telephone and callto.
PHONE_URL_PREFIX_REGEX = re.compile(r'^(tel|phone|telephone|callto):(/)?(/)?', re.IGNORECASE | re.ASCII)

# Original order preserved, longer patterns first (incl. the duplicate #2/#3).
PHONE_REGEX_STRINGS = [
    # 775123456
    r'[0-9]{6,15}',
    # 1(413)555-2378 or 1(413)555.2378 or 1 (413) 555-2378 or (303) 494-2320
    r'([0-9]{1,4}( )?)?\([0-9]{2,4}\)( )?[0-9]{2,4}(( )?(-|.))?( )?[0-9]{2,6}',
    # 1(262) 955-95-79 or 1(262)955.95.79
    r'([0-9]{1,4}( )?)?\([0-9]{2,4}\)( )?[0-9]{2,4}(( )?(-|.))?( )?[0-9]{2,6}',
    # (51) 5667-9987 or (19)94138-9398
    r'\([0-9]{2}\)( )?[0-9]{4,5}-[0-9]{4}',
    # 413-577-1234-564
    r'[0-9]{2,4}-[0-9]{2,4}-[0-9]{2,4}-[0-9]{2,6}',
    # 413-577-1234
    r'[0-9]{2,4}-[0-9]{2,4}-[0-9]{2,6}',
    # 413-577
    r'[0-9]{2,4}-[0-9]{2,6}',
    # 413.577.1234.564
    r'[0-9]{2,4}\.[0-9]{2,4}\.[0-9]{2,4}\.[0-9]{2,6}',
    # 413.577.1234
    r'[0-9]{2,4}\.[0-9]{2,4}\.[0-9]{2,6}',
    # 413.577
    r'[0-9]{2,4}\.[0-9]{2,6}',
    # 413 577 1234 564
    r'[0-9]{2,4} [0-9]{2,4} [0-9]{2,4} [0-9]{2,6}',
    # 413 577 1234
    r'[0-9]{2,4} [0-9]{2,4} [0-9]{2,6}',
    # 123 4567
    r'[0-9]{2,4} [0-9]{3,8}',
]

# All phones might be prefixed with '+' or '00'.
PHONE_REGEX_STRINGS = [r'(00|\+)?' + p for p in PHONE_REGEX_STRINGS]

# The phone patterns above are wide and report a lot of false positives; matches
# with fewer digits than this are dropped.
PHONE_MIN_DIGITS = 7

SKIP_PHONE_REGEX = re.compile(r'^([0-9]{4}-[0-9]{2}-[0-9]{2})$', re.IGNORECASE | re.ASCII)  # 2018-11-10

PHONE_REGEX_GLOBAL = re.compile('(' + '|'.join(PHONE_REGEX_STRINGS) + ')', re.IGNORECASE | re.ASCII)
PHONE_REGEX = re.compile('(' + '|'.join(PHONE_REGEX_STRINGS) + ')', re.IGNORECASE | re.ASCII)  # use .fullmatch

LINKEDIN_REGEX_STRING = r'(?<!\w)(?:(?:http(?:s)?:\/\/)?(?:(?:(?:[a-z]+\.)?linkedin\.com\/(?:in|company)\/)([a-z0-9\-_%=]{2,60})(?![a-z0-9\-_%=])))(?:\/)?'

INSTAGRAM_REGEX_STRING = r'(?<!\w)(?:http(?:s)?:\/\/)?(?:(?:www\.)?(?:instagram\.com|instagr\.am)\/)(?!explore|_n|_u)([a-z0-9_.]{2,30})(?![a-z0-9_.])(?:/)?'

TWITTER_RESERVED_PATHS = 'oauth|account|tos|privacy|signup|home|hashtag|search|login|widgets|i|settings|start|share|intent|oct|explore|notifications|messages|compose'
TWITTER_REGEX_STRING = r'''(?<!\w)(?:http(?:s)?:\/\/)?(?:www.)?(?:twitter.com|x.com)\/(?!(?:''' + TWITTER_RESERVED_PATHS + r''')(?:[\'"\?\.\/]|$))([a-z0-9_]{1,15})(?![a-z0-9_])(?:/)?'''

FACEBOOK_RESERVED_PATHS = r'rsrc\.php|apps|groups|events|l\.php|friends|images|photo.php|chat|ajax|dyi|common|policies|login|recover|reg|help|security|messages|marketplace|pages|live|bookmarks|games|fundraisers|saved|gaming|salesgroups|jobs|people|ads|ad_campaign|weather|offers|recommendations|crisisresponse|onthisday|developers|settings|connect|business|plugins|intern|sharer'
FACEBOOK_REGEX_STRING = r'''(?<!\w)(?:http(?:s)?:\/\/)?(?:www.)?(?:facebook.com|fb.com)\/(?!(?:''' + FACEBOOK_RESERVED_PATHS + r''')(?:[\'"\?\.\/]|$))(profile\.php\?id\=[0-9]{3,20}|(?!profile\.php)[a-z0-9\.]{5,51})(?![a-z0-9\.])(?:\/)?'''

YOUTUBE_REGEX_STRING = r'(?<!\w)(?:https?:\/\/)?(?:youtu\.be\/|(?:www\.|m\.)?youtube\.com(?:\/(?:watch|v|embed|user|c(?:hannel)?)(?:\.php)?)?(?:\?[^ ]*v=|\/))([a-zA-Z0-9\-_@]{2,100})'

TIKTOK_REGEX_STRING = r'(?<!\w)(?:http(?:s)?:\/\/)?(?:(?:www|m)\.)?(?:tiktok\.com)\/(((?:(?:v|embed|trending)(?:\?shareId=|\/))[0-9]{2,50}(?![0-9]))|(?:@)[a-z0-9\-_\.]+((?:\/video\/)[0-9]{2,50}(?![0-9]))?)(?:\/)?'

PINTEREST_REGEX_STRING = r'(?<!\w)(?:http(?:s)?:\/\/)?(?:(?:(?:(?:www\.)?pinterest(?:\.com|(?:\.[a-z]{2}){1,2}))|(?:[a-z]{2})\.pinterest\.com)(?:\/))((pin\/[0-9]{2,50})|((?!pin)[a-z0-9\-_\.]+(\/[a-z0-9\-_\.]+)?))(?:\/)?'

DISCORD_REGEX_STRING = r'(?<!\w)(?:https?:\/\/)?(?:www\.)?((?:(?:(?:canary|ptb).)?(?:discord|discordapp)\.com\/channels(?:\/)[0-9]{2,50}(\/[0-9]{2,50})*)|(?:(?:(?:canary|ptb).)?(?:discord\.(?:com|me|li|gg|io)|discordapp\.com)(?:\/invite)?)\/(?!channels)[a-z0-9\-_]{2,50})(?:\/)?'

# --- Net-new platforms (no JS predecessor) ---

SNAPCHAT_REGEX_STRING = r'(?<!\w)(?:http(?:s)?:\/\/)?(?:www\.)?snapchat\.com\/(?:add\/|@)([a-z0-9\-_.]{3,32})(?![a-z0-9\-_.])(?:\/)?'

THREADS_REGEX_STRING = r'''(?<!\w)(?:http(?:s)?:\/\/)?(?:www\.)?threads\.(?:net|com)\/(?!(?:login|search|explore|activity|settings|about|privacy|terms|t)(?:[\'"\?\.\/]|$))@?([a-z0-9_.]{2,30})(?![a-z0-9_.])(?:\/)?'''

TELEGRAM_REGEX_STRING = r'''(?<!\w)(?:http(?:s)?:\/\/)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)\/(?:s\/)?(?!(?:share|addstickers|addemoji|proxy|socks|setlanguage|iv|bg|login|confirmphone|s)(?:[\'"\?\.\/]|$))(joinchat\/[a-zA-Z0-9_-]{10,64}|\+[a-zA-Z0-9_-]{10,64}|[a-z0-9_]{5,32})(?![a-zA-Z0-9_-])(?:\/)?'''

REDDIT_REGEX_STRING = r'(?<!\w)(?:http(?:s)?:\/\/)?(?:(?:www|old|np|m)\.)?reddit\.com\/(?:u(?:ser)?\/([a-z0-9\-_]{3,20})|r\/([a-z0-9_]{2,21}))(?![a-z0-9\-_])(?:\/)?'

WHATSAPP_REGEX_STRING = r'''(?<!\w)(?:http(?:s)?:\/\/)?(?:wa\.me\/([0-9]{7,15})|(?:api|web)\.whatsapp\.com\/send\/?\?[^ \'"<>]*phone=\+?([0-9]{7,15})|chat\.whatsapp\.com\/(?:invite\/)?([a-zA-Z0-9]{16,32}))(?![a-zA-Z0-9])'''

GITHUB_RESERVED_PATHS = 'about|features|topics|collections|trending|marketplace|sponsors|settings|notifications|explore|apps|site|security|contact|pricing|login|join|signup|sessions|organizations|enterprise|enterprises|team|customer-stories|readme|resources|git-guides|events|search|new|codespaces|copilot|issues|pulls|discussions|blog|solutions|premium-support|mobile|account'
GITHUB_REGEX_STRING = r'''(?<!\w)(?:http(?:s)?:\/\/)?(?:www\.)?github\.com\/(?!(?:''' + GITHUB_RESERVED_PATHS + r''')(?:[\'"\?\.\/]|$))(?:orgs\/)?([a-z0-9](?:[a-z0-9\-]{0,38}))(?![a-z0-9\-])(?:\/)?'''

BLUESKY_REGEX_STRING = r'(?<!\w)(?:http(?:s)?:\/\/)?(?:www\.)?bsky\.app\/profile\/([a-z0-9](?:[a-z0-9.:\-]{1,255}))(?![a-z0-9.:\-])(?:\/)?'

MEDIUM_REGEX_STRING = r'(?<!\w)(?:http(?:s)?:\/\/)?(?:(?:www\.)?medium\.com\/(@[a-z0-9_.\-]{2,50})|(?!www\.)([a-z0-9\-]{2,50})\.medium\.com)(?![a-z0-9_.\-])(?:\/)?'

CALENDLY_RESERVED_PATHS = 'features|pricing|integrations|blog|teams|help|signup|login|app|api|event_types|solutions|resources|customers|security|newsletter|press|careers|legal'
CALENDLY_REGEX_STRING = r'''(?<!\w)(?:http(?:s)?:\/\/)?(?:www\.)?calendly\.com\/(?!(?:''' + CALENDLY_RESERVED_PATHS + r''')(?:[\'"\?\.\/]|$))([a-z0-9_\-]{2,60})(?![a-z0-9_\-])(?:\/)?'''

# Keys are the exact output-dict keys of the scraper.
PLATFORM_REGEX_STRINGS = {
    'linkedins': LINKEDIN_REGEX_STRING,
    'twitters': TWITTER_REGEX_STRING,
    'instagrams': INSTAGRAM_REGEX_STRING,
    'facebooks': FACEBOOK_REGEX_STRING,
    'youtubes': YOUTUBE_REGEX_STRING,
    'tiktoks': TIKTOK_REGEX_STRING,
    'pinterests': PINTEREST_REGEX_STRING,
    'discords': DISCORD_REGEX_STRING,
    'snapchats': SNAPCHAT_REGEX_STRING,
    'threads': THREADS_REGEX_STRING,
    'telegrams': TELEGRAM_REGEX_STRING,
    'reddits': REDDIT_REGEX_STRING,
    'whatsapps': WHATSAPP_REGEX_STRING,
    'githubs': GITHUB_REGEX_STRING,
    'blueskys': BLUESKY_REGEX_STRING,
    'mediums': MEDIUM_REGEX_STRING,
    'calendlys': CALENDLY_REGEX_STRING,
}

PLATFORM_REGEXES_GLOBAL = {
    key: re.compile(pattern, re.IGNORECASE | re.ASCII)
    for key, pattern in PLATFORM_REGEX_STRINGS.items()
}


def find_full_matches(compiled_regex, text):
    # JS String.match(/.../g) semantics: the full match, not capture group 1.
    return [m.group(0) for m in compiled_regex.finditer(text)]
