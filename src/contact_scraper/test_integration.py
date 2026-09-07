# Manual live smoke test (network!): runs the full pipeline against a few real
# sites of different shapes and sanity-checks the output contract.
# python3 -m src.contact_scraper.test_integration

import json
import time

from botasaurus import bt

from .api import scrape_contacts

SITES = [
    'vercel.com',       # static/SSG marketing site, socials in the footer
    'sipgate.de',       # German site: impressum priority + DE phone region
    'crawlee.dev',      # docs site with GitHub/Discord links
]

EXPECTED_KEYS = [
    'domain', 'title', 'description',
    'emails', 'phones',
    'linkedins', 'twitters', 'instagrams', 'facebooks', 'youtubes', 'tiktoks',
    'pinterests', 'discords', 'snapchats', 'threads', 'telegrams', 'reddits',
    'whatsapps',
    'githubs', 'blueskys', 'mediums',
    'calendlys',
    'technologies',
    'error',   # always last; None on success, reason string on failure
]

LIST_KEYS = EXPECTED_KEYS[3:-1]   # everything after the scalar identity keys


def check_contract(result):
    assert list(result.keys()) == EXPECTED_KEYS, list(result.keys())
    assert result['error'] is None or isinstance(result['error'], str)
    for key in ('title', 'description'):
        assert result[key] is None or isinstance(result[key], str), (key, result[key])
    for entry in result['technologies']:
        assert isinstance(entry, dict), entry
        assert entry['name'] and isinstance(entry['name'], str), entry
        assert isinstance(entry['versions'], list), entry
        assert isinstance(entry['categories'], list), entry
    for key in LIST_KEYS:
        if key == 'technologies':
            continue
        entries = result[key]
        assert isinstance(entries, list)
        for entry in entries:
            assert entry['value']
            assert entry['sources'], (key, entry)
        flagged = [e for e in entries if e.get('is_likely_official')]
        if entries:
            assert len(flagged) == 1 and entries[0].get('is_likely_official') is True, (key, entries)
    for entry in result['phones']:
        assert entry['value'].startswith('+') or entry['value'].isdigit(), entry


def main():
    results = []

    for site in SITES:
        print(f'--- scraping {site} ---')
        t0 = time.perf_counter()
        result = scrape_contacts(site, cache=False)
        elapsed = time.perf_counter() - t0
        check_contract(result)
        found = {k: len(result[k]) for k in LIST_KEYS if result[k]}
        print(f'{site}: {json.dumps(found)}  ({elapsed:.1f}s)')
        results.append(result)
    bt.write_temp_json(results)


# python -m src.contact_scraper.test_integration
if __name__ == '__main__':
    main()
    print('integration smoke OK')
