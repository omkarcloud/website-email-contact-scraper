# Phone extraction + valid/uncertain classification (plan section 3.3).
#
# Candidates come from tel:-style hrefs, extra href-grade strings (e.g. wa.me
# numbers fed in by the socials extractor) and page text (the wide phone
# regexes unioned with phonenumbers.PhoneNumberMatcher).
#
# Classification note: phonenumbers.is_valid_number alone over-accepts when a
# bare national-format candidate is parsed with the ccTLD fallback region
# (e.g. an 8-digit order number parses as a "valid" DE number). So the
# region-parse fallback promotes a candidate to "phones" only when it is
# href-grade (tel: is explicit intent) or was independently confirmed by
# PhoneNumberMatcher; other region-parsed text matches stay uncertain.

import re
from urllib.parse import unquote

import phonenumbers
import tldextract

from .html_text import scan_safe_text
from .social_regexes import (
    PHONE_MIN_DIGITS,
    PHONE_REGEX,
    PHONE_REGEX_GLOBAL,
    PHONE_URL_PREFIX_REGEX,
    SKIP_PHONE_REGEX,
    find_full_matches,
)

# Empty suffix_list_urls -> bundled public-suffix snapshot, no network.
_tld_extract = tldextract.TLDExtract(suffix_list_urls=())

# Keyed by the LAST label of the tldextract suffix, so 'co.uk' -> 'uk' -> GB
# and 'com.au' -> 'au' -> AU work without listing every second-level form.
# Generic TLDs (com/org/net/io/ai/co/app/dev/...) are simply absent -> None.
CCTLD_REGIONS = {
    'uk': 'GB', 'de': 'DE', 'fr': 'FR', 'au': 'AU', 'in': 'IN', 'ca': 'CA',
    'nl': 'NL', 'es': 'ES', 'it': 'IT', 'at': 'AT', 'ch': 'CH', 'be': 'BE',
    'se': 'SE', 'no': 'NO', 'dk': 'DK', 'fi': 'FI', 'pl': 'PL', 'cz': 'CZ',
    'pt': 'PT', 'ie': 'IE', 'nz': 'NZ', 'br': 'BR', 'mx': 'MX', 'jp': 'JP',
    'kr': 'KR', 'cn': 'CN', 'sg': 'SG', 'hk': 'HK', 'ae': 'AE', 'za': 'ZA',
    'us': 'US',
}

# 2020, 2019-2020, 2019 2020, 2019.2020 - copyright/date-range shapes.
YEAR_RANGE_REGEX = re.compile(r'^(19|20)\d{2}([ .-](19|20)\d{2})?$')

# 52.519060 - decimal numbers (map coordinates, prices, versions) that the
# dotted-phone patterns match; real dotted phones have short fractions.
DECIMAL_NUMBER_REGEX = re.compile(r'^\d{1,3}\.\d{4,}$')

# 49.36.137.230 - IPv4 addresses match the dotted phone patterns.
IP_ADDRESS_REGEX = re.compile(r'^\d{1,3}(\.\d{1,3}){3}$')

# "1200 2015" - product spec + model year (bike/car shops list dozens).
PRODUCT_YEAR_REGEX = re.compile(r'^\d{2,4} (19|20)\d{2}$')

# 336359125457 - bare unformatted 12+ digit runs are listing/tracking ids;
# nobody writes a phone number that way without a + prefix.
BARE_LONG_DIGITS_REGEX = re.compile(r'^\d{12,15}$')

# 31.07.2026 / 12/11/2020 - blanked from the text BEFORE scanning: they both
# pollute phones_uncertain and can even parse into "valid" phones
# (a German "Stand: 31.07.2026" once produced +495082026).
DOTTED_DATE_REGEX = re.compile(r'(?<!\d)\d{1,2}[./]\d{1,2}[./](19|20)\d{2}(?!\d)')

# "CVR no. 40596860", "VAT DE123...", "HRB 12345" - company/tax registration
# numbers directly preceded by their label are not phones. The digit run often
# starts right after a glued uppercase country prefix (DE123456789, ATU1234),
# which the trailing (?-i:[A-Z]{2,3})? absorbs so the label still anchors at $.
REGISTRY_CONTEXT_REGEX = re.compile(
    r'\b(cvr|vat|uid|ust(-idnr)?|gst|hrb|kvk|siret|siren|abn|acn|ein|mwst'
    r'|reg(istration)?|company|tax)'
    r'[.:]?\s*(no|nr|number|id)?[.:]?\s*(?-i:[A-Z]{2,3})?$',
    re.IGNORECASE)


def _registry_context(text, start):
    return bool(REGISTRY_CONTEXT_REGEX.search(text[max(0, start - 28):start]))

# 070000002 / 00001246 - a real trunk prefix is a single zero.
LEADING_ZEROS_REGEX = re.compile(r'^0{3,}')


def region_from_domain(domain):
    if not domain:
        return None
    suffix = _tld_extract(domain).suffix
    if not suffix:
        return None
    return CCTLD_REGIONS.get(suffix.rsplit('.', 1)[-1])


def _digits_only(s):
    return re.sub(r'\D', '', s)


def _candidates(page, region, extra_candidates):
    # Each candidate: value + provenance flags. 'matcher' marks candidates
    # confirmed by PhoneNumberMatcher (trusted for region-fallback parsing).
    out = []
    for anchor in page.anchors:
        if PHONE_URL_PREFIX_REGEX.match(anchor['href']):
            value = unquote(PHONE_URL_PREFIX_REGEX.sub('', anchor['href'])).strip()
            if value:
                out.append({'value': value, 'from_href': True,
                            'in_footer': anchor['in_footer'], 'matcher': False})
    for extra in extra_candidates:
        value = str(extra).strip()
        if value:
            out.append({'value': value, 'from_href': True,
                        'in_footer': False, 'matcher': False})

    text = DOTTED_DATE_REGEX.sub(' ', scan_safe_text(page.text))
    seen_text = {}
    for m in PHONE_REGEX_GLOBAL.finditer(text):
        match = m.group(0)
        if len(_digits_only(match)) < PHONE_MIN_DIGITS:
            continue
        if SKIP_PHONE_REGEX.match(match):
            continue
        if _registry_context(text, m.start()):
            continue
        if match not in seen_text:
            cand = {'value': match, 'from_href': False,
                    'in_footer': False, 'matcher': False}
            seen_text[match] = cand
            out.append(cand)
    # region=None matcher silently yields only +-prefixed numbers; fine.
    for m in phonenumbers.PhoneNumberMatcher(text, region,
                                             leniency=phonenumbers.Leniency.VALID):
        raw = m.raw_string
        if _registry_context(text, m.start):
            continue
        if raw in seen_text:
            seen_text[raw]['matcher'] = True
        else:
            cand = {'value': raw, 'from_href': False,
                    'in_footer': False, 'matcher': True}
            seen_text[raw] = cand
            out.append(cand)
    return out


def extract_phones(page, region=None, extra_candidates=()):
    phones = {}     # key -> hit, insertion-ordered
    uncertain = {}  # key -> hit
    suppress = {}   # digit variants of valid phones -> phones key

    def add(bucket, key, value, cand, region_match):
        hit = bucket.get(key)
        if hit is None:
            bucket[key] = {'value': value, 'key': key,
                           'from_href': cand['from_href'],
                           'in_footer': cand['in_footer'],
                           'region_match': region_match}
        else:
            hit['from_href'] = hit['from_href'] or cand['from_href']
            hit['in_footer'] = hit['in_footer'] or cand['in_footer']
            hit['region_match'] = hit['region_match'] or region_match

    for cand in _candidates(page, region, extra_candidates):
        value = cand['value']
        number = None
        used_region = False
        try:
            number = phonenumbers.parse(value, None)
        except phonenumbers.NumberParseException:
            if region:
                try:
                    number = phonenumbers.parse(value, region)
                    used_region = True
                except phonenumbers.NumberParseException:
                    number = None

        trusted = cand['from_href'] or cand['matcher'] or not used_region
        if number is not None and phonenumbers.is_valid_number(number) and trusted:
            e164 = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
            variants = (_digits_only(e164), str(number.national_number),
                        _digits_only(phonenumbers.format_number(
                            number, phonenumbers.PhoneNumberFormat.NATIONAL)))
            # A national tel: form of this number may already sit in phones
            # under a digits-only key; fold it into the E164 entry.
            for variant in variants:
                stale = phones.pop(variant, None) if variant != e164 else None
                if stale:
                    add(phones, e164, e164, stale, stale['region_match'])
            add(phones, e164, e164, cand,
                phonenumbers.region_code_for_number(number) == region)
            # National-format digit variants let a bare local text form of the
            # same number merge into this entry instead of going uncertain.
            for variant in variants:
                suppress[variant] = e164
            continue

        # tel:-grade OR validated is a union: an href candidate that matches
        # the phone-shape regex stays a phone even if phonenumbers rejects it.
        if cand['from_href'] and PHONE_REGEX.fullmatch(value):
            cleaned = re.sub(r'[^\d+]', '', value)
            key = _digits_only(cleaned)
            mapped = suppress.get(key)
            if mapped is not None and mapped in phones:
                add(phones, mapped, phones[mapped]['value'], cand, False)
            else:
                add(phones, key, cleaned, cand, False)
                # setdefault: must not clobber an E164 entry's variant mapping
                suppress.setdefault(key, key)
            continue

        collapsed = re.sub(r'\s+', ' ', value).strip()
        digits = _digits_only(collapsed)
        if len(digits) < PHONE_MIN_DIGITS or len(digits) > 15:
            continue
        if YEAR_RANGE_REGEX.fullmatch(collapsed):
            continue
        if DECIMAL_NUMBER_REGEX.fullmatch(collapsed):
            continue
        if IP_ADDRESS_REGEX.fullmatch(collapsed):
            continue
        if PRODUCT_YEAR_REGEX.fullmatch(collapsed):
            continue
        if LEADING_ZEROS_REGEX.match(collapsed):
            continue
        if BARE_LONG_DIGITS_REGEX.fullmatch(collapsed):
            continue
        if len(set(digits)) == 1:
            continue
        add(uncertain, digits, collapsed, cand, False)

    # A number valid in phones must not also appear in phones_uncertain:
    # merge (OR flags) any uncertain entry that is a digit-variant of one.
    for key in list(uncertain):
        target = suppress.get(key)
        if target is not None and target in phones:
            hit = uncertain.pop(key)
            phones[target]['from_href'] = phones[target]['from_href'] or hit['from_href']
            phones[target]['in_footer'] = phones[target]['in_footer'] or hit['in_footer']

    return {'phones': list(phones.values()),
            'phones_uncertain': list(uncertain.values())}
