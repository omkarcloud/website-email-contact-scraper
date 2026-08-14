# Website contact scraper: crawls a site and extracts emails, phones and
# social profile links with per-item source URLs and is_likely_official ranking.
#
# Lazy re-export so the pure extractor modules stay importable in tests
# without pulling in botasaurus.


def __getattr__(name):
    if name == 'scrape_contacts':
        from .api import scrape_contacts
        return scrape_contacts
    raise AttributeError(name)
