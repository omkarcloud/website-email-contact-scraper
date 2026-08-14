# Manual live smoke test (network!): runs the full pipeline against a few real
# sites of different shapes and sanity-checks the output contract.
# python3 -m contact_scraper.test_integration

import json

from botasaurus import bt

from .api import scrape_contacts



SITES = [
    #    "fastmath.app",
    # "midwestchiropractic.com",
    # "peakplatforms.uk",
    # "bysiga.com",
    # "minecraftshop.com",
    # "www.woodlandsbandb.co.uk",
    # "brainwashedusa.com",
    # "decalmoto.com",
    # "jbpetsupplies.com",
    # "autodengi.com",
    # "augustint.com",
    # "foxautoparks.com",
    # "zenanutrition.com",
    # "ntrysid.com",
    # "mundofitness.fr",
    # "www.clickpeculi.com",
    # "lkpab.se",
    # "balega.co.uk",
    # "graceandskye.com",
    # "www.hairharvest.co.uk",
    # "pine.al",
    # "www.engine-rebuild.com",
    # "hrmbeauty.com",
    # "ruvoria.com",
    # "pcprime.es",
    # "babybroderi.dk",
    # "openigloo.com",
    # "vera-underwear.com",
    # "thomasleesheets.com",
    # "librecloud.host",
    # "netkin.de",
    # "lyxonn.com",
    # "www.ciatdesign.com",
    # "homeandbath.co.uk",
    # "italy-ka.it",
    # "www.4footballnews.com",
    # "directdawai.com",
    # "www.samiielts.com",
    # "aromatechscent.com",
    # "debanhams.com",
    # "networkcomputerpros.com",
    # "drnatmed.com",
    # "dkv.be",
    # "erv.ch",
    # "bright-culture.com",
    # "goldenluxury.co",
    # "www.vlabs.agency",
    # "www.lifeinsurance-quotes.co.za",
    # "www.tranquilpc-shop.co.uk",
    # "soonfound.co.uk",
    # "hostblast.net",
    # "beautyandthebulk.com",
    # "icynana.com",
    # "www.wovar.it",
    # "www.studentassignmentwriter.com",
    # "keralagifts.in",
    # "www.biolympiads.com",
    # "12thtribe.com",
    # "homecomfortlondon.co.uk",
    # "theelectronicshub.com",
    # "anonyxghost.com",
    # "predecessorboost.com",
    # "qataren.com",
    # "attitudinebio.it",
    # "shahidmalla.com",
    # "shenwademedia.com",
    # "www.smallclaims.uk.com",
    # "snackboxhub.com",
    # "seedsmafia.com",
    # "coppingzone.com",
    # "regionalfinance.com",
    # "luumii.no",
    # "www.hedensted-vvs.dk",
    # "beeonthetop.com",
    # "fairlyodd.co.uk",
    # "fxdyno.com",
    # "bitcraft.ai",
    # "www.herexclusivegym.com",
    # "retrospares.co.uk",
    # "www.haleyauto.com",
    # "www.theniceshirt.com",
    # "onyxweblab.com",
    # "disabilityconnect.org.uk",
    # "gisterpages.com",
    # "crystalclearcd.com",
    # "heidelprint.com",
    # "eastcheapnikeshoes.net.go.spybt.com",
    # "tulsimala.com",
    # "buzzybytes.ro",
    # "blackbooktravels.com",
    # "upstartdigital.com.au",
    # "www.pdfavor.com",
    # "www.puckator.es",
    # "essentracomponents.com",
    # "fatafatsewa.com",
    # "maxim88sg.online",
    # "armed.cz",
    # "stratusbuildingsolutions.com",
    # "www.meyank.com",

    # "maxim88sg.online",
    # "sqai.net",
    # "trustpilot.com",
    # "www.badabusiness.com"
    
    # 'sipgate.de',       # German site: impressum priority + DE phone region
]
SITES = ["peakplatforms.uk", "bysiga.com", "brainwashedusa.com", "jbpetsupplies.com", "ntrysid.com", "clickpeculi.com", "hairharvest.co.uk", "ruvoria.com", "pcprime.es", "ciatdesign.com", "homeandbath.co.uk", "italy-ka.it", "4footballnews.com", "debanhams.com", "bright-culture.com", "vlabs.agency", "tranquilpc-shop.co.uk", "icynana.com", "studentassignmentwriter.com", "biolympiads.com", "anonyxghost.com", "predecessorboost.com", "snackboxhub.com", "fairlyodd.co.uk", "fxdyno.com", "bitcraft.ai", "theniceshirt.com", "heidelprint.com", "spybt.com", "buzzybytes.ro", "upstartdigital.com.au", "pdfavor.com", "puckator.es", "maxim88sg.online", "meyank.com", "amazoncognito.com"]

SITES = [
    "vercel.com",
#     "stripe.com	",
# "vercel.com",
# # "github.com	",
# "cloudflare.com",
# "hubspot.com",
# "elastic.co",
# "openai.com",
# "anthropic.com ",
# "mozilla.org",
# "docker.com",
# "digitalocean.com",
]
# [:]

# SITES = ["apple.com"]

EXPECTED_KEYS = [
    'domain', 'title', 'description',
    'emails', 'phones', 'phones_uncertain',
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
        if key == 'phones_uncertain':
            assert not flagged
        elif entries:
            assert len(flagged) == 1 and entries[0].get('is_likely_official') is True, (key, entries)
    for entry in result['phones']:
        assert entry['value'].startswith('+') or entry['value'].isdigit(), entry


def main():
    results = []
    for site in SITES:
        print(f'--- scraping {site} ---')
        result = scrape_contacts(site, cache=False)
        check_contract(result)
        found = {k: len(result[k]) for k in LIST_KEYS if result[k]}
        print(f'{site}: {json.dumps(found)}')
        results.append(result)
    bt.write_temp_json(results)


# python -m contact_scraper.test_integration
if __name__ == '__main__':
    main()
    print('integration smoke OK')
