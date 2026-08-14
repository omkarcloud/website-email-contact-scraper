# Runs every offline unit-test module. No network.
# python3 -m contact_scraper.test_extractors

from . import test_aggregate, test_crawler, test_emails, test_phones, test_socials


def main():
    test_emails.main()
    test_phones.main()
    test_socials.main()
    test_aggregate.main()
    test_crawler.main()


if __name__ == '__main__':
    main()
    print('all contact_scraper unit tests OK')
