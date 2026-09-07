# Per-page email extraction: mailto hrefs, Cloudflare-protected addresses,
# plain-text regex matches and a de-obfuscation pass, then false-positive
# filtering.

import html
import re
from urllib.parse import unquote

from .html_text import in_footer, scan_safe_text
from .social_regexes import (
    EMAIL_REGEX,
    EMAIL_REGEX_GLOBAL,
    EMAIL_URL_PREFIX_REGEX,
    find_full_matches,
)

# Asset filenames like logo@2x.png satisfy the email regex (local "logo",
# domain "2x.png"), so they need an explicit drop.
_ASSET_EXT_RE = re.compile(r'\.(png|jpe?g|gif|webp|svg|ico|css|js)$', re.IGNORECASE)

# Build hashes / sentry event ids: 24+ consecutive hex chars in the local part.
_HEX_RUN_RE = re.compile(r'[0-9a-f]{24}', re.IGNORECASE)

_TLD_RE = re.compile(r'[a-z]{2,24}')

# Matched as domain suffixes (exact or ".<blocked>"), which covers the
# registrable-domain intent: foo@mail.example.com drops too. The dummy
# domains mirror js-scraper's isPlaceholderEmail (enrichment/orchestrator.ts)
# so both pipelines drop the same addresses. email.com is a real provider but
# is overwhelmingly used as a placeholder on contact forms.
_BLOCKED_DOMAINS = (
    'example.com', 'example.org', 'example.net',
    'test.com', 'test.org', 'test.net',
    'domain.com', 'email.com', 'yourdomain.com', 'yourcompany.com',
    'mycompany.com', 'mysite.com', 'company.com', 'acme.com', 'localhost',
    'sentry.io', 'sentry-next.wixpress.com',
)

# Placeholder / dummy local parts ("youremail@…", "firstname.lastname@…",
# "test@…", "noreply@…"): template text and form hints that appear in page
# HTML as if they were addresses. Ported from js-scraper's isPlaceholderEmail
# so the native contact scraper drops the same set. Matching is EXACT on the
# local part (plus a few "todo-"-style prefixes) so real addresses that merely
# contain one of these words - firstnamelastname@acme-test.com, marketingplaceholder@acme-test.com
# - survive.
_PLACEHOLDER_LOCALS = frozenset((
    'youremail', 'your.email', 'your_email', 'your-email',
    'yourname', 'your.name', 'your_name', 'your-name',
    'name', 'firstname', 'lastname', 'firstname.lastname', 'first.last',
    'email', 'mail', 'user', 'username', 'user.email',
    'example', 'sample', 'test', 'dummy', 'placeholder', 'foo', 'bar',
    'todo',
    'noreply', 'no-reply', 'no.reply', 'donotreply', 'do-not-reply',
))
_PLACEHOLDER_PREFIXES = ('todo-', 'todo_', 'todo.', 'example-', 'test-', 'sample-')


def is_placeholder_email(value):
    """True when the address is an obvious placeholder/dummy by its local
    part (see _PLACEHOLDER_LOCALS) or its domain (see _BLOCKED_DOMAINS)."""
    local, at, domain = value.lower().strip().rpartition('@')
    if not at or not local:
        return True
    if local in _PLACEHOLDER_LOCALS or local.startswith(_PLACEHOLDER_PREFIXES):
        return True
    return any(domain == blocked or domain.endswith('.' + blocked)
               for blocked in _BLOCKED_DOMAINS)

_LOOKALIKE_TRANSLATION = str.maketrans({
    '＠': '@',  # fullwidth commercial at
    '﹫': '@',  # small commercial at
    '．': '.',  # fullwidth full stop
    '。': '.',  # ideographic full stop
    '․': '.',  # one dot leader
})

_BRACKETED_AT_RE = re.compile(r'\s*[\(\[\{]\s*(?:at|arobase)\s*[\)\]\}]\s*', re.IGNORECASE)
_BRACKETED_DOT_RE = re.compile(r'\s*[\(\[\{]\s*(?:dot|punkt)\s*[\)\]\}]\s*', re.IGNORECASE)

# Spaced words ("name at domain dot com") are high-FP, so a substitution is
# committed only when the whole substituted region fullmatches the email
# shape; otherwise prose like "we met at the office" would be mangled.
# Atoms allow '@' so mixed forms ("john@acme dot com") still resolve.
_SPACED_REGION_RE = re.compile(
    r'[\w@]+(?:[.+-][\w@]+)*(?:\s+(?:at|dot)\s+[\w@]+(?:[.+-][\w@]+)*)+',
    re.IGNORECASE,
)
_SPACED_AT_RE = re.compile(r'(?<=\w)\s+at\s+(?=\w)', re.IGNORECASE)
_SPACED_DOT_RE = re.compile(r'(?<=\w)\s+dot\s+(?=\w)', re.IGNORECASE)


def decode_cfemail(hexstr):
    # Cloudflare email-protection encoding: first hex byte is the XOR key,
    # each following byte is one XOR-ed character of the address.
    key = int(hexstr[:2], 16)
    return ''.join(chr(int(hexstr[i:i + 2], 16) ^ key) for i in range(2, len(hexstr), 2))


def _spaced_region_sub(match):
    token = _SPACED_AT_RE.sub('@', match.group(0))
    token = _SPACED_DOT_RE.sub('.', token)
    if EMAIL_REGEX.fullmatch(token):
        return token
    return match.group(0)


def deobfuscate_text(text):
    text = html.unescape(text)  # defensive: the parser already decodes entities
    text = text.translate(_LOOKALIKE_TRANSLATION)
    text = _BRACKETED_AT_RE.sub('@', text)
    text = _BRACKETED_DOT_RE.sub('.', text)
    text = _SPACED_REGION_RE.sub(_spaced_region_sub, text)
    return text


def _is_false_positive(value):
    if _ASSET_EXT_RE.search(value):
        return True
    local, _, domain = value.rpartition('@')
    if len(local) > 64 or _HEX_RUN_RE.search(local):
        return True
    if is_placeholder_email(value):
        return True
    if not _TLD_RE.fullmatch(domain.rsplit('.', 1)[-1]):
        return True
    return False


def extract_emails(page):
    # -> [{'value', 'from_href', 'in_footer'}], discovery order, deduped by
    # value with flags OR-merged.
    hits = {}

    def add(candidate, from_href, footer):
        if not EMAIL_REGEX.fullmatch(candidate):
            return
        value = candidate.lower()
        if _is_false_positive(value):
            return
        hit = hits.get(value)
        if hit:
            hit['from_href'] = hit['from_href'] or from_href
            hit['in_footer'] = hit['in_footer'] or footer
        else:
            hits[value] = {'value': value, 'from_href': from_href, 'in_footer': footer}

    def add_cfemail(hexstr, from_href, element):
        try:
            decoded = decode_cfemail(hexstr)
        except ValueError:
            return
        add(decoded, from_href, in_footer(element))

    for anchor in page.anchors:
        if not EMAIL_URL_PREFIX_REGEX.match(anchor['href']):
            continue
        addr = EMAIL_URL_PREFIX_REGEX.sub('', anchor['href'])
        addr = unquote(addr).split('?', 1)[0].strip()
        add(addr, True, anchor['in_footer'])

    # Static HTML never runs Cloudflare's email-decode.min.js, so the visible
    # text is the literal "[email protected]" placeholder; decoding the
    # data-cfemail / fragment payload is the only way to get the address.
    for element in page.soup.select('[data-cfemail]'):
        add_cfemail(element.get('data-cfemail', ''), False, element)

    for a_tag in page.soup.find_all('a', href=True):
        if '/cdn-cgi/l/email-protection#' in a_tag['href']:
            add_cfemail(a_tag['href'].split('#', 1)[1], True, a_tag)

    text = scan_safe_text(page.text)
    for match in find_full_matches(EMAIL_REGEX_GLOBAL, text):
        add(match, False, False)

    for match in find_full_matches(EMAIL_REGEX_GLOBAL, deobfuscate_text(text)):
        add(match, False, False)

    return list(hits.values())
