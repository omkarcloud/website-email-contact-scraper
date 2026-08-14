# Cross-page merge, ranking and output assembly (plan section 5).
#
# Entries are deduped across pages by canonical key, scored by page prominence
# plus similarity to the site domain, sorted score-desc (tie-break: first-seen
# crawl order), and the top entry of each non-empty list gets
# is_likely_official=True.

import difflib
import re

import phonenumbers
import tldextract

from .social_regexes import PLATFORM_REGEX_STRINGS

PAGE_WEIGHTS = {'homepage': 5, 'contact': 4, 'about': 3, 'other': 1}
HOMEPAGE_BONUS = 3
FOOTER_BONUS = 2
HREF_BONUS = 2
REGION_BONUS = 2
MAX_SOURCES = 10

GENERIC_LOCAL_PARTS = {'info', 'contact', 'hello', 'support', 'sales',
                       'office', 'mail', 'hi', 'team', 'admin'}
FREE_MAIL_LABELS = {'gmail', 'yahoo', 'hotmail', 'outlook', 'aol', 'proton',
                    'protonmail', 'gmx', 'icloud', 'live', 'msn'}
FREE_MAIL_DOMAINS = {'web.de'}

# dict order of PLATFORM_REGEX_STRINGS is the required output-key order
PLATFORM_KEYS = list(PLATFORM_REGEX_STRINGS)
OUTPUT_KEYS = (['domain', 'title', 'description',
                'emails', 'phones', 'phones_uncertain']
               + PLATFORM_KEYS + ['technologies'])
# First list-valued key in OUTPUT_KEYS; everything before it is scalar.
_FIRST_LIST_KEY = 3

_NON_ALNUM_RE = re.compile(r'[^a-z0-9]')

# Bundled-snapshot extractor: never fetches the live public suffix list, so
# aggregation (and its unit tests) stay fully offline.
_tld_extract = tldextract.TLDExtract(suffix_list_urls=())


def _merge(hit_stream, key_field):
    # hit_stream yields (page_record, hit) pairs in crawl order. Returns
    # entries in first-seen order keeping the first-seen value; each page
    # contributes its weight once per entry; flags OR-merge across every
    # occurrence so bonuses can check "any occurrence".
    entries = {}
    ordered = []
    for page, hit in hit_stream:
        entry = entries.get(hit[key_field])
        if entry is None:
            entry = {
                'value': hit['value'],
                'handle': hit.get('handle'),
                'pages': [],        # first-seen order, unique by url
                'page_urls': set(),
                'in_footer': False,
                'from_href': False,
                'region_match': False,
            }
            entries[hit[key_field]] = entry
            ordered.append(entry)
        if page['url'] not in entry['page_urls']:
            entry['page_urls'].add(page['url'])
            entry['pages'].append({
                'url': page['url'],
                'weight': PAGE_WEIGHTS.get(page.get('weight_class'), PAGE_WEIGHTS['other']),
                'is_homepage': bool(page.get('is_homepage')),
            })
        entry['in_footer'] = entry['in_footer'] or bool(hit.get('in_footer'))
        entry['from_href'] = entry['from_href'] or bool(hit.get('from_href'))
        entry['region_match'] = entry['region_match'] or bool(hit.get('region_match'))
    return ordered


def _prominence_score(entry):
    score = sum(p['weight'] for p in entry['pages'])
    if any(p['is_homepage'] for p in entry['pages']):
        score += HOMEPAGE_BONUS
    if entry['in_footer']:
        score += FOOTER_BONUS
    if entry['from_href']:
        score += HREF_BONUS
    return score


def _email_bonus(value, site_domain):
    local, _, mail_host = value.lower().rpartition('@')
    ext = _tld_extract(mail_host)
    registrable = ext.registered_domain.lower() if ext.registered_domain else mail_host
    bonus = 0
    if registrable and registrable == site_domain:
        bonus += 4
    if local in GENERIC_LOCAL_PARTS:
        bonus += 1
    if ext.domain.lower() in FREE_MAIL_LABELS or registrable in FREE_MAIL_DOMAINS:
        bonus -= 2
    return bonus


def _phone_bonus(entry):
    bonus = 0
    if entry['region_match']:
        bonus += REGION_BONUS
    # deliberate double-count with the prominence href bonus (plan section 5):
    # tel:/wa.me-derived numbers are the strongest phone signal
    if entry['from_href']:
        bonus += HREF_BONUS
    return bonus


def _social_bonus(handle, domain_label):
    handle_norm = _NON_ALNUM_RE.sub('', (handle or '').lower())
    if not handle_norm or not domain_label:
        return 0
    if handle_norm == domain_label:
        return 4
    if handle_norm in domain_label or domain_label in handle_norm:
        return 2
    if difflib.SequenceMatcher(None, handle_norm, domain_label).ratio() >= 0.75:
        return 2
    return 0


def _finalize(entries, bonus_fn, flagged=True):
    # score BEFORE capping sources, so heavily-repeated entries keep their
    # full weight even though only 10 source URLs are emitted
    scored = sorted(
        ((_prominence_score(e) + bonus_fn(e), i, e) for i, e in enumerate(entries)),
        key=lambda t: (-t[0], t[1]))
    out = []
    for rank, (_score, _first_seen, entry) in enumerate(scored):
        # stable sort: equal weights keep first-seen order
        pages = sorted(entry['pages'], key=lambda p: -p['weight'])
        item = {
            'value': entry['value'],
            'sources': [p['url'] for p in pages[:MAX_SOURCES]],
        }
        if flagged:
            item['is_likely_official'] = rank == 0
        out.append(item)
    return out


def _merge_entry_into(match, entry):
    for page in entry['pages']:
        if page['url'] not in match['page_urls']:
            match['page_urls'].add(page['url'])
            match['pages'].append(page)
    match['in_footer'] = match['in_footer'] or entry['in_footer']
    match['from_href'] = match['from_href'] or entry['from_href']
    match['region_match'] = match['region_match'] or entry['region_match']


def _same_number_textual(vdigits, digits):
    # Bounded textual compare for entries phonenumbers can't parse: a bare
    # suffix coincidence (Danish '52331234' vs +14152331234) must NOT merge.
    if not digits or not vdigits:
        return False
    if digits == vdigits:
        return True
    if len(digits) < 7 or len(vdigits) < 7:
        return False
    if abs(len(digits) - len(vdigits)) > 3:  # plausible country-code delta
        return False
    return vdigits.endswith(digits) or digits.endswith(vdigits)


def _parse_e164(value, region=None):
    try:
        n = phonenumbers.parse(value, region)
        return phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        return None


def _same_number(valid, entry):
    # Semantic-first: when the valid side is E.164, the uncertain/national side
    # must parse (in the valid number's region) to the SAME E.164.
    vdigits = re.sub(r'\D', '', valid['value'])
    raw_digits = re.sub(r'\D', '', entry['value'])
    digits = raw_digits.lstrip('0')
    if valid['value'].startswith('+'):
        try:
            vregion = phonenumbers.region_code_for_number(
                phonenumbers.parse(valid['value'], None))
        except phonenumbers.NumberParseException:
            return _same_number_textual(vdigits, digits)
        parsed = _parse_e164(entry['value'], vregion)
        if parsed is not None and parsed == valid['value']:
            return True
        # Truncation artifacts of THIS number (the space-separated patterns often
        # match only a prefix of long formatted numbers):
        # a) fragment carries its own +CC and digit-prefix-matches the number
        if (entry['value'].lstrip().startswith('+') and len(raw_digits) >= 6
                and vdigits.startswith(raw_digits) and vdigits != raw_digits):
            return True
        # b) bare fragment embedded in the number, seen ONLY on pages where the
        # full number was also found (an unrelated same-suffix number from a
        # different page must never merge - the reviewer's Danish/US case)
        if (len(raw_digits) >= 7 and raw_digits in vdigits
                and vdigits != raw_digits
                and entry['page_urls'] <= valid['page_urls']):
            return True
        return False
    return _same_number_textual(vdigits, digits)


def _suppress_validated(valid_entries, uncertain_entries):
    # Cross-page dedupe: a number already validated anywhere on the site must
    # not resurface as uncertain from another page's prose.
    kept = []
    for entry in uncertain_entries:
        match = next((v for v in valid_entries if _same_number(v, entry)), None)
        if match is None:
            kept.append(entry)
        else:
            _merge_entry_into(match, entry)
    return kept


def _fold_valid_variants(valid_entries):
    # A national tel:-form (digits key) and the E.164 form of the SAME number
    # can arrive from different pages; keep the E.164 entry as the survivor.
    e164_entries = [e for e in valid_entries if e['value'].startswith('+')]
    kept = []
    for entry in valid_entries:
        if entry['value'].startswith('+'):
            kept.append(entry)
            continue
        match = next((v for v in e164_entries if _same_number(v, entry)), None)
        if match is None:
            kept.append(entry)
        else:
            _merge_entry_into(match, entry)
    return kept


def _hits(page_records, field):
    for page in page_records:
        for hit in page.get(field, []):
            yield page, hit


def empty_output(domain, error=None):
    out = {'domain': domain, 'title': None, 'description': None}
    for key in OUTPUT_KEYS[_FIRST_LIST_KEY:]:
        out[key] = []
    # Always present, always the LAST key: None on success, reason string
    # when the site could not be scraped (dns/connection/block/crash).
    out['error'] = error
    return out


def build_output(domain, page_records, technologies=None,
                 title=None, description=None):
    site_ext = _tld_extract(domain or '')
    site_domain = (site_ext.registered_domain or domain or '').lower()
    domain_label = site_ext.domain.lower()

    out = empty_output(domain)
    out['title'] = title
    out['description'] = description
    out['emails'] = _finalize(
        _merge(_hits(page_records, 'emails'), 'value'),
        lambda e: _email_bonus(e['value'], site_domain))
    valid_phones = _fold_valid_variants(_merge(_hits(page_records, 'phones'), 'key'))
    uncertain_phones = _suppress_validated(
        valid_phones, _merge(_hits(page_records, 'phones_uncertain'), 'key'))
    out['phones'] = _finalize(valid_phones, _phone_bonus)
    out['phones_uncertain'] = _finalize(uncertain_phones, _phone_bonus, flagged=False)

    per_platform = {key: [] for key in PLATFORM_KEYS}
    for page in page_records:
        for hit in page.get('socials', []):
            if hit.get('platform') in per_platform:
                per_platform[hit['platform']].append((page, hit))
    for key, stream in per_platform.items():
        out[key] = _finalize(
            _merge(stream, 'key'),
            lambda e: _social_bonus(e['handle'], domain_label))
    out['technologies'] = technologies or []
    return out
