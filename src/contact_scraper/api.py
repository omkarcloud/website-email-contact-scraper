# Public entrypoint: scrape_contacts(urls) -> one dict per input URL/domain.
# python3 -m contact_scraper.api   runs a manual live self-test.

import re
import time
import traceback

from botasaurus.task import task

from . import chrome_manager, crawler
from .aggregate import build_output, empty_output
from .extract_emails import extract_emails
from .extract_phones import extract_phones, region_from_domain
from .extract_socials import extract_socials
from .fetcher import POOL_KEY, _warm_contact_driver
from .html_text import page_meta, scan_safe_text
from .social_regexes import EMAIL_REGEX_GLOBAL
from .tech_detect import detect_technologies

# Chrome is built LAZILY: the pool spawns a warmer only when a crawl's first
# browser-mode fetch asks for a driver. Registering the warm-up at import time
# guarantees every lazily-built driver is validated end-to-end before it
# enters the ready pool.
chrome_manager.register_warmup(POOL_KEY, _warm_contact_driver)

# Soft cap for the per-page extraction pass; a pathological page must not
# stall the whole crawl (the phone regex alternation can backtrack heavily).
PAGE_EXTRACT_BUDGET_SECONDS = 10

_QUICK_PHONE_RE = re.compile(r'(?:tel|callto):[+0-9(]', re.IGNORECASE)


def _extract_page_record(rec, region):
    page = rec['page']
    started = time.monotonic()
    record = {
        'url': page.url,
        'is_homepage': rec['is_homepage'],
        'weight_class': rec['weight_class'],
        'emails': [],
        'phones': [],
        'phones_uncertain': [],
        'socials': [],
    }
    socials, whatsapp_candidates = extract_socials(page)
    record['socials'] = socials
    if time.monotonic() - started < PAGE_EXTRACT_BUDGET_SECONDS:
        record['emails'] = extract_emails(page)
    if time.monotonic() - started < PAGE_EXTRACT_BUDGET_SECONDS:
        phones = extract_phones(page, region, extra_candidates=whatsapp_candidates)
        record['phones'] = phones['phones']
        record['phones_uncertain'] = phones['phones_uncertain']
    return record


def _scrape_single(query):
    # Cheap saturation signals for the crawler's early exit: full extraction
    # runs after the crawl, so peek at the raw HTML of KEPT pages (discarded
    # off-domain/duplicate fetches must not set the flags).
    state = {'has_email': False, 'has_phone': False}

    def on_page_kept(result):
        html = result.get('html') or ''
        if not html:
            return
        lowered = html[:crawler.MAX_TEXT_SCAN_CHARS].lower()
        if not state['has_email'] and (
                'mailto:' in lowered
                # long-token guard: the email regex backtracks quadratically
                # on minified script/JSON blobs
                or EMAIL_REGEX_GLOBAL.search(scan_safe_text(lowered))):
            state['has_email'] = True
        if not state['has_phone'] and _QUICK_PHONE_RE.search(lowered):
            state['has_phone'] = True

    def early_exit(pages_fetched, best_remaining_score):
        return best_remaining_score < 60 and state['has_email'] and state['has_phone']

    crawl = crawler.crawl_site(query, early_exit_check=early_exit,
                               on_page_kept=on_page_kept)
    domain = crawl['domain'] or crawler.registrable_domain(query)
    if not crawl['pages']:
        return empty_output(domain,
                            error=crawl.get('error') or 'unreachable: no pages fetched')

    region = region_from_domain(domain)
    page_records = [_extract_page_record(rec, region) for rec in crawl['pages']]
    home = crawl['pages'][0]['page']  # crawler always appends the homepage first
    technologies = detect_technologies(home.url, home.html,
                                       crawl.get('homepage_headers'))
    title, description = page_meta(home.soup)
    return build_output(domain, page_records, technologies=technologies,
                        title=title, description=description)


@task(cache=False, parallel=5, close_on_crash=True, create_error_logs=False,
      max_retry=2)
def scrape_contacts(query):
    # botasaurus maps list inputs over this function (parallel=5), so `query`
    # is a single URL/domain here; scrape_contacts(list) returns list of dicts.
    try:
        return _scrape_single(query)
    except Exception as e:
        # Fixed output schema even for unreachable/broken sites. No crawl
        # happened, so the reported domain is the host as the caller gave it.
        traceback.print_exc()
        try:
            domain = crawler._seed_host(query)
        except Exception:
            domain = query
        return empty_output(domain, error=f'{type(e).__name__}: {e}'[:200])


if __name__ == '__main__':
    import json
    result = scrape_contacts('vercel.com')
    print(json.dumps(result, indent=2))
