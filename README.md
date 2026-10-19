# 📧 Website Email & Contact Scraper

Website Email & Contact Scraper is a **free and open-source** scraper that gets you **unlimited** emails, phone numbers, social profiles and the tech stack of any website for free.

## ✨ What Can I Get?

- 📧 **Every email on the site** — including Cloudflare-protected and `name [at] company [dot] com` obfuscated ones that regex scrapers miss
- 📞 **Phone numbers you can dial** — validated with Google's libphonenumber and returned in E.164 format, so your CRM stays clean
- 🔗 **Profiles on 17 social platforms** — LinkedIn, X, Instagram, Facebook, YouTube, TikTok, GitHub, Bluesky, Telegram, WhatsApp, Calendly & more
- 🛠️ **1,300+ technologies detected** — know who runs Shopify, WordPress, React or HubSpot, and segment your leads by stack

Every contact carries the pages it was found on, and the company's real one is flagged `is_likely_official: true`.

## 🎥 Example: A Full Website Contact Record

```json
{
  "domain": "stripe.com",
  "title": "Stripe | Financial Infrastructure to Grow Your Revenue",
  "description": "Stripe is a financial services platform that helps all types of businesses accept payments, build flexible billing models and manage money movement.",
  "emails": [
    { "value": "sales@stripe.com", "sources": ["https://stripe.com/blog"], "is_likely_official": true }
  ],
  "phones": [
    { "value": "+18889262289", "sources": ["https://stripe.com/blog"], "is_likely_official": true }
  ],
  "linkedins": [
    { "value": "https://www.linkedin.com/company/stripe", "sources": ["https://stripe.com/in"], "is_likely_official": true },
    { "value": "https://www.linkedin.com/in/neetika-bansal", "sources": ["https://stripe.com/blog"], "is_likely_official": false }
  ],
  "twitters": [
    { "value": "https://x.com/stripe", "sources": ["https://stripe.com/in", "https://stripe.com/blog"], "is_likely_official": true }
  ],
  "instagrams": [
    { "value": "https://www.instagram.com/stripehq", "sources": ["https://stripe.com/in"], "is_likely_official": true }
  ],
  "facebooks": [
    { "value": "https://www.facebook.com/StripeHQ", "sources": ["https://stripe.com/in"], "is_likely_official": true }
  ],
  "youtubes": [
    { "value": "https://www.youtube.com/@stripe", "sources": ["https://stripe.com/in"], "is_likely_official": true },
    { "value": "https://www.youtube.com/@StripeDev", "sources": ["https://stripe.com/in"], "is_likely_official": false }
  ],
  "githubs": [
    { "value": "https://github.com/stripe", "sources": ["https://stripe.com/in"], "is_likely_official": true }
  ],
  "technologies": [
    { "name": "Bootstrap", "versions": ["55"], "categories": ["UI frameworks"] },
    { "name": "Nginx", "versions": [], "categories": ["Web servers", "Reverse proxies"] },
    { "name": "jQuery", "versions": [], "categories": ["JavaScript libraries"] }
  ],
  "error": null
}
```

*Trimmed for readability — the full record has one list per platform, 17 in all.*

## 🚀 Unlimited Free Contact Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/website-email-contact-scraper
cd website-email-contact-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the scraper:
```bash
python run.py
```

Your browser opens the dashboard at `http://localhost:3000`. Paste your websites, pick a crawl mode, hit **Run**, then filter ("Has Emails", "Has LinkedIn") and export CSV, JSON or Excel — no code needed.

3️⃣ Or get your first data from Python:
```python
from src.contact_scraper import scrape_contacts

scrape_contacts(["stripe.com"])
```

```json
{
  "domain": "stripe.com",
  "title": "Stripe | Financial Infrastructure to Grow Your Revenue",
  "emails": [
    { "value": "sales@stripe.com", "sources": ["https://stripe.com/blog"], "is_likely_official": true }
  ],
  "phones": [
    { "value": "+18889262289", "sources": ["https://stripe.com/blog"], "is_likely_official": true }
  ],
  "linkedins": [
    { "value": "https://www.linkedin.com/company/stripe", "sources": ["https://stripe.com/in"], "is_likely_official": true }
  ],
  "twitters": [
    { "value": "https://x.com/stripe", "sources": ["https://stripe.com/in", "https://stripe.com/blog"], "is_likely_official": true }
  ],
  "githubs": [
    { "value": "https://github.com/stripe", "sources": ["https://stripe.com/in"], "is_likely_official": true }
  ],
  "technologies": [
    { "name": "Nginx", "versions": [], "categories": ["Web servers", "Reverse proxies"] },
    { "name": "jQuery", "versions": [], "categories": ["JavaScript libraries"] }
  ],
  "error": null
}
```

Results are saved to `output/scrape_contacts.json`. Pass a list of websites to scrape them all in one go, or edit `main.py` and run `python main.py`.

## 📚 Options

| Option | How | What it does |
|---|---|---|
| Website | `"stripe.com"` or `"https://stripe.com/"` | A bare domain or a full URL. The crawl stays on that domain, subdomains included |
| Crawl mode | `{"query": "stripe.com", "mode": "deep"}` | `homepage` scans just the homepage · `key_pages` (default) adds the site's top contact-like pages, up to 7 · `deep` crawls up to 20 pages, 2 levels deep |
| Many websites | `scrape_contacts(["stripe.com", "shopify.com"])` | Each site's pages are fetched concurrently. A dead site returns the same schema with an `error` string, so a batch never dies halfway |
| Proxy | `CONTACT_SCRAPER_PROXY=http://user:pass@host:port` | Optional. Only for sites that refuse your IP outright; everything else works direct |
| Docker | `docker-compose build && docker-compose up` | Same dashboard on `http://localhost:3000` |

Pages are fetched with fast HTTP first. When a site renders with JavaScript or sits behind a bot wall (Cloudflare "Just a moment...", PerimeterX, Incapsula), the scraper switches to a real Chrome for that site and clicks through the Cloudflare Turnstile checkbox when one is shown. A site that still refuses comes back with `error: "blocked: ..."` instead of an empty record scraped from the interstitial.

## 🔍 Exploring the Data Without Installing

The same scraper is published on RapidAPI, and its playground is the easiest place to see a full response before you set anything up. Once the data looks right, run it locally for **unlimited free** contacts.

1. [Subscribe to the free plan](https://rapidapi.com/pradeepbardiya13/api/website-social-scraper-api/pricing) — 200 requests/month, no credit card.
2. [Open the playground](https://rapidapi.com/pradeepbardiya13/api/website-social-scraper-api/playground/apiendpoint_7d6be0cc-b57d-47dd-87c4-86cf437b1adb) — Website Contacts is pre-filled with `vercel.com`. Click **Test Endpoint** to see the full response.
3. Happy with it? Clone the repo above and scrape as many websites as you like, for free.

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Website Email & Contact Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20Website%20Email%20%26%20Contact%20Scraper.)

[![Ask Us by Email about Website Email & Contact Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Website%20Email%20Contact%20Scraper&body=I%20need%20help%20using%20the%20Website%20Email%20%26%20Contact%20Scraper.)

Found a website where it misses a contact? [Open an issue](https://github.com/omkarcloud/website-email-contact-scraper/issues) with the URL — real-world edge cases are how the extraction rules got this good.

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — the perfect first step: type "dentists in New York", get every business with its website, then feed those websites into this scraper for a complete lead list. Up to 100K free leads/month.
- [**G2 Scraper**](https://github.com/omkarcloud/g2-scraper) — G2 product details, ratings & pricing as clean JSON
- [**Trustpilot Scraper**](https://github.com/omkarcloud/trustpilot-scraper) — company profiles, rating distributions & every review for any domain
- [**Seek Scraper**](https://github.com/omkarcloud/seek-scraper) — Seek Australia & New Zealand jobs, salaries, companies & reviews
- [**Jobstreet Scraper**](https://github.com/omkarcloud/jobstreet-scraper) — JobStreet & JobsDB jobs across 6 Asian markets, with company reviews & salaries
- [**IMDb Scraper**](https://github.com/omkarcloud/imdb-scraper) — titles, cast, ratings, box office & charts

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/website-email-contact-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/website-email-contact-scraper)
