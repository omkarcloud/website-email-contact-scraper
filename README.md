<p align="center">
  <img src="https://www.omkar.cloud/images/tools/website-email-contact-scraper/logo.png" alt="website email contact scraper" />
</p>
<div align="center" style="margin-top: 0;">
  <h1>✨ Website Email & Contact Scraper 🤖</h1>
  <p><strong>Extract emails, phone numbers, social media profiles, and the tech stack of any website — 100% free and open source.</strong></p>
</div>
<em>
  <h5 align="center">(Programming Language - Python 3)</h5>
</em>
<p align="center">
  <a href="#">
    <img alt="website-email-contact-scraper forks" src="https://img.shields.io/github/forks/omkarcloud/website-email-contact-scraper?style=for-the-badge" />
  </a>
  <a href="#">
    <img alt="Repo stars" src="https://img.shields.io/github/stars/omkarcloud/website-email-contact-scraper?style=for-the-badge&color=yellow" />
  </a>
  <a href="#">
    <img alt="website-email-contact-scraper License" src="https://img.shields.io/github/license/omkarcloud/website-email-contact-scraper?color=orange&style=for-the-badge" />
  </a>
  <a href="https://github.com/omkarcloud/website-email-contact-scraper/issues">
    <img alt="issues" src="https://img.shields.io/github/issues/omkarcloud/website-email-contact-scraper?color=purple&style=for-the-badge" />
  </a>
</p>
<p align="center">
  <img src="https://views.whatilearened.today/views/github/omkarcloud/website-email-contact-scraper.svg" width="80px" height="28px" alt="View" />
</p>


Perfect for **lead generation and enrichment**: feed it a list of websites, get back sales-ready contact data as structured JSON.

- **Rated Excellent — 4.6 based on 25 reviews** on [Trustpilot](https://www.trustpilot.com/review/omkar.cloud). Our open source work is sponsored by [1000+ devs on GitHub](https://github.com/sponsors/omkarcloud).

Use it two ways — both documented below:

1. **[Hosted API](#example-website-contacts-in-one-request)** — one GET request, no installs, no browsers, no infrastructure. 100 Requests Free.
2. **[Open source](#-run-it-yourself--free--open-source)** — this repo. Run it on your machine with a UI dashboard, free forever for unlimited websites extraction.

[![Try the Website Email & Contact Scraper API in the live playground — free, no signup](https://img.shields.io/badge/%E2%96%B6%20Playground-Run%20a%20live%20request%2C%20free-brightgreen?style=for-the-badge)](https://www.omkar.cloud/tools/website-email-contact-scraper/playground?utm_source=github&utm_medium=cpc&utm_content=badge)

[![Free Plan: 100 requests per month](https://img.shields.io/badge/Free%20tier-100%20requests%2Fmonth-blue?style=for-the-badge)](#pricing)

The same scraper is also available as an **Apify Actor** and on **RapidAPI**:

[![Run on Apify](https://img.shields.io/badge/Run%20on-Apify-blue?logo=data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjgiIGhlaWdodD0iMjgiIHZpZXdCb3g9IjAgMCAyOCAyOCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cGF0aCBkPSJNMTQgMjhDMjEuNzMyIDI4IDI4IDIxLjczMiAyOCAxNEMyOCA2LjI2OCAyMS43MzIgMCAxNCAwQzYuMjY4IDAgMCA2LjI2OCAwIDE0QzAgMjEuNzMyIDYuMjY4IDI4IDE0IDI4WiIgZmlsbD0iIzk3RDdGRiIvPjwvc3ZnPg==)](https://apify.com/omkar-cloud/website-email-contact-scraper) [![Run on RapidAPI](https://img.shields.io/badge/Also%20on-RapidAPI-blue?logo=rapidapi)](https://rapidapi.com/pradeepbardiya13/api/website-social-scraper-api)

## Example: Website Contacts in One Request

One request to the contact scraper API:

```
GET https://website-email-contact-scraper.omkar.cloud/contacts?website=vercel.com
```

```json
{
  "domain": "vercel.com",
  "title": "Agentic Infrastructure - Vercel",
  "description": "The autonomous stack for every app and agent.",
  "emails": [
    {
      "value": "privacy@vercel.com",
      "sources": [
        "https://vercel.com/legal/privacy-notice",
        "https://vercel.com/legal/cookie-policy"
      ],
      "is_likely_official": true
    },
    {
      "value": "security@vercel.com",
      "sources": ["https://vercel.com/legal/terms"],
      "is_likely_official": false
    }
  ],
  "phones": [],
  "phones_uncertain": [
    { "value": "800.352.5267", "sources": ["https://vercel.com/legal/terms"] }
  ],
  "linkedins": [
    {
      "value": "https://www.linkedin.com/company/vercel",
      "sources": ["https://vercel.com", "https://vercel.com/contact/sales"],
      "is_likely_official": true
    }
  ],
  "twitters": [
    {
      "value": "https://x.com/vercel",
      "sources": ["https://vercel.com", "https://vercel.com/contact/sales"],
      "is_likely_official": true
    }
  ],
  "instagrams": [
    {
      "value": "https://www.instagram.com/vercel",
      "sources": ["https://vercel.com", "https://vercel.com/contact/sales"],
      "is_likely_official": true
    }
  ],
  "youtubes": [
    {
      "value": "https://www.youtube.com/@VercelHQ",
      "sources": ["https://vercel.com", "https://vercel.com/contact/sales"],
      "is_likely_official": true
    }
  ],
  "githubs": [
    {
      "value": "https://github.com/vercel",
      "sources": ["https://vercel.com", "https://vercel.com/contact/sales"],
      "is_likely_official": true
    }
  ],
  "blueskys": [
    {
      "value": "https://bsky.app/profile/vercel.com",
      "sources": ["https://vercel.com/docs/accounts"],
      "is_likely_official": true
    }
  ],
  "technologies": [
    { "name": "Next.js", "versions": [], "categories": ["Web frameworks", "Web servers"] },
    { "name": "Node.js", "versions": [], "categories": ["Programming languages"] },
    { "name": "React", "versions": [], "categories": ["JavaScript frameworks"] },
    { "name": "Vercel", "versions": [], "categories": ["Web servers"] }
  ],
  "error": null
}
```

*Trimmed for readability — the full response covers 17 social platforms. See the [sample response](#website-contacts) in the API reference.*

**[Run this exact request in the Playground — no signup, no key →](https://www.omkar.cloud/tools/website-email-contact-scraper/playground?utm_source=github&utm_medium=cpc&utm_content=example)**

The playground comes prefilled with this request and runs it against the live API in your browser. 

Use the playground to try any website you go through the effort of installing open source version on your machine.

## 🚀 Run It Yourself — Free & Open Source

This repo is the complete scraper — the same crawler and extraction rules that power the API — and it runs on your machine for free, unlimited extractions.

1️⃣ Clone the repository:
```bash
git clone https://github.com/omkarcloud/website-email-contact-scraper
cd website-email-contact-scraper
```

2️⃣ Install dependencies (this takes a few minutes — it also builds the UI dashboard):
```bash
python -m pip install -r requirements.txt
```

3️⃣ Run the scraper via the UI dashboard:
```bash
python run.py
```

Your browser opens `http://localhost:3000`. Enter websites, hit **Run**, filter results ("Has Emails", "Has LinkedIn"), and export CSV/JSON/Excel — without writing a line of code.

Prefer the terminal? Edit the website list in `main.py` and run:
```bash
python main.py
```
Results are saved to `output/scrape_contacts.json`.

### 🐍 Use it from Python

```python
from src.contact_scraper import scrape_contacts

results = scrape_contacts(["vercel.com", "stripe.com", "shopify.com"])
```

Websites are scraped in parallel (5 at a time), and every result has the same fixed schema — unreachable or broken sites return the schema with an `error` string instead of raising, so batch runs never die halfway.

### 🐳 Docker

```bash
docker-compose build && docker-compose up
```

### When to use the API instead

The open source scraper is perfect for lists you run on your laptop. Reach for the [hosted API](#example-website-contacts-in-one-request) when you want contacts inside a product or pipeline — no Chrome to babysit, no servers to maintain, results in one GET request from any language. [Try it free in the Playground →](https://www.omkar.cloud/tools/website-email-contact-scraper/playground?utm_source=github&utm_medium=cpc&utm_content=os-vs-api)

## ⚡ What You Get

- **📧 Emails** — including Cloudflare-protected and JavaScript-obfuscated emails that simple regex scrapers miss.
- **📞 Phone numbers** — validated with Google's libphonenumber, region-aware based on the site's country domain. Uncertain matches are kept separate in `phones_uncertain`, so your CRM stays clean.
- **🔗 17 social platforms** — LinkedIn, Twitter/X, Instagram, Facebook, YouTube, TikTok, Pinterest, Discord, Snapchat, Threads, Telegram, Reddit, WhatsApp, GitHub, Bluesky, Medium, and Calendly.
- **🛠️ Technology detection** — know if a site runs Shopify, WordPress, React, and hundreds of other technologies (great for segmenting leads).
- **🎯 Official-contact ranking** — every email/phone/profile carries its source URLs, and the most prominent one per list is flagged `is_likely_official: true`.
- **🕷️ Smart crawling** — contact and about pages are prioritized, so it usually finds the goods within a handful of pages instead of blindly crawling the whole site.
- **🥷 Handles tough websites** — fast HTTP requests first, with automatic escalation to a real Chrome browser for JavaScript-rendered sites and bot-protected pages.

## API Reference

### Website Contacts

▶ [Try it live in the Playground — no key needed →](https://www.omkar.cloud/tools/website-email-contact-scraper/playground?utm_source=github&utm_medium=cpc&utm_content=endpoint-contacts)

```
GET https://website-email-contact-scraper.omkar.cloud/contacts?website=vercel.com
```

Accepts a bare domain (`vercel.com`) or a full URL (`https://vercel.com/`). The crawl stays on the site's registrable domain, subdomains included, and is capped at 20 pages / 120 seconds — so a response can take up to ~2 minutes for slow or bot-protected sites.

#### Response

Returns the site's title and description, every email, phone number, and social profile found (with source pages and the `is_likely_official` flag), plus the detected technology stack. The shape is identical for unreachable sites: all lists come back empty and `error` holds a short reason string.

<details>
<summary>Sample Response (click to expand)</summary>

```json
{
  "domain": "vercel.com",
  "title": "Agentic Infrastructure - Vercel",
  "description": "The autonomous stack for every app and agent.",
  "emails": [
    {
      "value": "privacy@vercel.com",
      "sources": [
        "https://vercel.com/legal/privacy-notice",
        "https://vercel.com/legal/cookie-policy"
      ],
      "is_likely_official": true
    },
    {
      "value": "security@vercel.com",
      "sources": [
        "https://vercel.com/legal/terms"
      ],
      "is_likely_official": false
    }
  ],
  "phones": [],
  "phones_uncertain": [
    {
      "value": "800.352.5267",
      "sources": [
        "https://vercel.com/legal/terms"
      ]
    }
  ],
  "linkedins": [
    {
      "value": "https://www.linkedin.com/company/vercel",
      "sources": [
        "https://vercel.com",
        "https://vercel.com/contact/sales"
      ],
      "is_likely_official": true
    }
  ],
  "twitters": [
    {
      "value": "https://x.com/vercel",
      "sources": [
        "https://vercel.com",
        "https://vercel.com/contact/sales"
      ],
      "is_likely_official": true
    }
  ],
  "instagrams": [
    {
      "value": "https://www.instagram.com/vercel",
      "sources": [
        "https://vercel.com",
        "https://vercel.com/contact/sales"
      ],
      "is_likely_official": true
    }
  ],
  "facebooks": [],
  "youtubes": [
    {
      "value": "https://www.youtube.com/@VercelHQ",
      "sources": [
        "https://vercel.com",
        "https://vercel.com/contact/sales"
      ],
      "is_likely_official": true
    }
  ],
  "tiktoks": [],
  "pinterests": [],
  "discords": [],
  "snapchats": [],
  "threads": [],
  "telegrams": [],
  "reddits": [],
  "whatsapps": [],
  "githubs": [
    {
      "value": "https://github.com/vercel",
      "sources": [
        "https://vercel.com",
        "https://vercel.com/contact/sales"
      ],
      "is_likely_official": true
    }
  ],
  "blueskys": [
    {
      "value": "https://bsky.app/profile/vercel.com",
      "sources": [
        "https://vercel.com/docs/accounts"
      ],
      "is_likely_official": true
    }
  ],
  "mediums": [],
  "calendlys": [],
  "technologies": [
    {
      "name": "Next.js",
      "versions": [],
      "categories": [
        "Web frameworks",
        "Web servers"
      ]
    },
    {
      "name": "Node.js",
      "versions": [],
      "categories": [
        "Programming languages"
      ]
    },
    {
      "name": "React",
      "versions": [],
      "categories": [
        "JavaScript frameworks"
      ]
    },
    {
      "name": "Vercel",
      "versions": [],
      "categories": [
        "Web servers"
      ]
    },
    {
      "name": "webpack",
      "versions": [],
      "categories": [
        "Miscellaneous"
      ]
    }
  ],
  "error": null
}
```

</details>

## 📄 Output Schema

Every result — from the API and the open source scraper alike — contains these keys, always in this order:

| Key | Description |
| --- | ----------- |
| `domain` | Final resolved host of the website after redirects (e.g. entering `docker.com` gives `www.docker.com`) |
| `title` / `description` | Homepage title and meta description |
| `emails` | `[{value, sources, is_likely_official}]`, best first |
| `phones` | Validated numbers in E.164 (`+14155551234`) format |
| `phones_uncertain` | Number-like strings that could not be fully validated |
| `linkedins`, `twitters`, `instagrams`, `facebooks`, `youtubes`, `tiktoks`, `pinterests`, `discords`, `snapchats`, `threads`, `telegrams`, `reddits`, `whatsapps`, `githubs`, `blueskys`, `mediums`, `calendlys` | Social profile URLs, one list per platform |
| `technologies` | `[{name, versions, categories}]` detected on the homepage |
| `error` | `null` on success, or a short reason (`"dns: no such host: ..."`) |

## Pricing

| Plan | Price | Requests/Month |
|------|-------|----------------|
| Free | $0 | 100 |
| Grow | $48 | 15,000 |
| Scale | $148 | 75,000 |

1 API call = 1 website scraped

Free Plan Available — [create your API key →](https://www.omkar.cloud/auth/sign-up?redirect=/api-key&utm_source=github&utm_medium=cpc&utm_content=pricing-signup). No credit card for the free tier.

Rather not pay at all? Run the [open source scraper](#-run-it-yourself--free--open-source) — it's the same code, free forever.

## 🧠 How It Works

1. **Crawl** — starts at the homepage and follows same-domain links in priority order: `/contact`, `/impressum`, `/about`, `/support` pages first, capped at 20 pages and 2 levels deep. Crawling exits early once emails and phones have been found and no promising pages remain.
2. **Escalate** — pages are fetched with fast HTTP requests. If the site blocks bots or renders content with JavaScript, the crawler automatically switches to a real Chrome browser for the rest of that site (and reuses the earned cookies to keep subsequent pages fast).
3. **Extract** — emails (including `mailto:`, Cloudflare-encoded, and obfuscated forms like `name [at] company [dot] com`), phones via libphonenumber with the site's region, social links via battle-tested per-platform regexes ported from the Apify SDK, plus JSON-LD structured data.
4. **Rank** — findings are deduped across pages and scored by prominence (homepage/footer/contact-page presence) and similarity to the site's domain. The top entry of each list is flagged `is_likely_official`.

## ❓ FAQs

### Can I try the API before signing up?

Yes. The playground runs live requests in your browser — free, no account, no API key. [Try it in the Playground →](https://www.omkar.cloud/tools/website-email-contact-scraper/playground?utm_source=github&utm_medium=cpc&utm_content=faq)

### Should I use the API or the open source scraper?

Both use same source code and return same JSON. Use the **open source scraper** when you're comfortable running Python locally and want unlimited free scraping on your own machine. Use the **API** when you want contacts inside a product, a no-maintenance pipeline, or a language other than Python.

### How is this different from paid tools like Hunter.io or Apify's Contact Info Scraper?

It gives you the same core data — emails, phones, and social profiles crawled from company websites — with extras most paid tools don't include, like technology detection and official-contact ranking. And unlike per-credit tools, you can always fall back to the open source version at zero cost.

### How do I know which email is the company's official one?

Every email, phone, and social profile includes `sources` (the pages it was found on), and the highest-scoring entry per list is flagged `is_likely_official: true`. Prominence on the homepage/footer/contact page and similarity to the site's domain drive the score.

### Can it scrape JavaScript-heavy or bot-protected websites?

Yes. Sites are first fetched with fast HTTP requests; when a site renders client-side (React/Next.js/Angular shells) or sits behind a bot wall (Cloudflare "Just a moment...", PerimeterX, Incapsula), the scraper automatically escalates to a real Chrome browser for that site.

### Will I get blocked or need proxies?

With the open source scraper, the requests-first + real-Chrome escalation handles the vast majority of sites without any proxy setup.

### What if a website is unreachable or has no contacts?

You still get the full schema: all lists empty and `error` holding a short reason string (`"dns: no such host: ..."`). Batch runs never die halfway — a dead site costs you one record, not the run.

### How many websites can I scrape?

With the open source scraper there are no artificial limits — it's your machine, and websites are processed 5 at a time in parallel. With the API, see [Pricing](#pricing).

### I found a website where it misses contacts. What should I do?

Please [open an issue](https://github.com/omkarcloud/website-email-contact-scraper/issues) with the website URL — real-world edge cases are how the extraction rules got this good. 

Also whatsapp us about it [here](https://api.whatsapp.com/send?phone=918178804274&text=I%20have%20a%20question%20about%20the%20Website%20Email%20%26%20Contact%20Scraper.).

## More Lead-Data Tools: Google Maps, G2, Capterra & Trustpilot

- **[Google Maps Scraper (3100+ Github Stars)](https://github.com/omkarcloud/google-maps-scraper)** — the perfect first step before this scraper: search Google Maps for any niche and location ("dentists in New York") and get every business with its name, address, phone, ratings, and website — then feed those websites straight into this contact scraper to build a complete lead list. Super Generous Free Tier: easily get 100K Leads/month free.
- **[G2 Scraper API](https://github.com/omkarcloud/g2-scraper)** — turn any G2 product page into clean JSON: 40+ fields including reviews, pricing, ratings, and company details. Great for enriching the leads you just scraped contacts for. 62+ Github Stars.  
- **[Capterra Scraper API](https://github.com/omkarcloud/capterra-scraper)** — the same clean JSON, pointed at Capterra: 5-dimension rating breakdowns, pricing plans, integrations, pros/cons for 108,726 products.
- **[Trustpilot Scraper API](https://github.com/omkarcloud/trustpilot-scraper)** — real-time Trustpilot data for 1.6M+ companies: search companies by keyword, full profiles with rating distributions, every review for any domain. 200 free requests/month.

## Support

Built by developers, for developers — when you reach out, you talk to the engineers who built the scraper, not a support script. Message us anytime and we'll solve your query within 1 working day.

[![Contact Us on WhatsApp about Website Email & Contact Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20have%20a%20question%20about%20the%20Website%20Email%20%26%20Contact%20Scraper.)

Email: [happy.to.help@omkar.cloud](mailto:happy.to.help@omkar.cloud?subject=Website%20Email%20Contact%20Scraper%20Question)

[![Email Us about Website Email & Contact Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Website%20Email%20Contact%20Scraper%20Question)

## Love It? Star It! ⭐

From one developer to another: if this scraper saved you time, please [star the repo](https://github.com/omkarcloud/website-email-contact-scraper).

Here's why it matters: most developers judge a scraper by its stars before trying it. Your star helps the next developer — someone deciding whether the contact data here is real and reliable — try it with confidence.

It takes only 1 second, and means the world to me.

Made with ❤️ using [Botasaurus](https://github.com/omkarcloud/botasaurus)
