from src.contact_scraper import scrape_contacts

if __name__ == "__main__":
    # Pass one website or a list of websites; results are saved to
    # output/scrape_contacts.json. Each item is a domain/URL string (crawl
    # mode 'key_pages') or {"query": ..., "mode": "homepage" | "key_pages" | "deep"}.
    scrape_contacts(["vercel.com"])
