from botasaurus_server.server import Server
from botasaurus_server.ui import CustomField, ExpandListField, Field, View, filters, sorts

from src.contact_scraper import scrape_contacts

Server.configure(
    title="Website Email & Contact Scraper",
    header_title="Website Email & Contact Scraper",
    description="Extract emails, phone numbers, social media profiles, and the tech stack of any website.",
    right_header={
        "text": "Love It? Star It! ★",
        "link": "https://github.com/omkarcloud/website-email-contact-scraper",
    },
)


def _join_values(key):
    def map_values(record):
        return ", ".join(item["value"] for item in record.get(key) or [])

    return map_values


def _join_names(record):
    return ", ".join(tech["name"] for tech in record.get("technologies") or [])


overview_view = View(
    "Overview",
    [
        Field("domain"),
        Field("title"),
        CustomField("emails", map=_join_values("emails")),
        CustomField("phones", map=_join_values("phones")),
        CustomField("linkedins", map=_join_values("linkedins")),
        CustomField("twitters", map=_join_values("twitters")),
        CustomField("instagrams", map=_join_values("instagrams")),
        CustomField("facebooks", map=_join_values("facebooks")),
        CustomField("youtubes", map=_join_values("youtubes")),
        CustomField("githubs", map=_join_values("githubs")),
        CustomField("technologies", map=_join_names),
        Field("error"),
    ],
)

email_list_view = View(
    "Email List",
    [
        Field("domain"),
        ExpandListField(
            "emails",
            [
                Field("value", output_key="email"),
                Field("is_likely_official"),
                CustomField("sources", map=lambda item, record: ", ".join(item["sources"])),
            ],
        ),
    ],
)

Server.add_scraper(
    scrape_contacts,
    display_name="Website Contact Scraper",
    get_task_name=lambda website: website,
    create_all_task=True,
    split_task=lambda data: [w.strip() for w in data["websites"] if w and w.strip()],
    filters=[
        filters.SearchTextInput("domain"),
        filters.IsTruthyCheckbox("emails", label="Has Emails"),
        filters.IsTruthyCheckbox("phones", label="Has Phones"),
        filters.IsTruthyCheckbox("linkedins", label="Has LinkedIn"),
        filters.IsNotNullCheckbox("error", label="Has Error"),
    ],
    sorts=[
        sorts.AlphabeticAscendingSort("domain"),
    ],
    views=[overview_view, email_list_view],
)
