# Shared HTML parsing layer: one parse per page, reused by every extractor.
#
# soup_to_text flattens HTML so that inline elements join without separators
# (so "<b>john</b>@x.com" stays "john@x.com") while block elements break
# lines - bs4's get_text can't do both, hence the manual walk.

import re
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from bs4.element import Comment, NavigableString, Tag

SKIP_TAGS = {'script', 'style', 'noscript', 'template', 'svg', 'canvas', 'iframe'}

BLOCK_TAGS = {
    'address', 'article', 'aside', 'blockquote', 'dd', 'details', 'dialog',
    'div', 'dl', 'dt', 'fieldset', 'figcaption', 'figure', 'footer', 'form',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'header', 'hr', 'li', 'main', 'menu',
    'nav', 'ol', 'p', 'pre', 'section', 'table', 'td', 'th', 'tr', 'ul',
}

NON_PAGE_SCHEMES = ('mailto:', 'tel:', 'phone:', 'telephone:', 'callto:',
                    'javascript:', 'data:', '#')


@dataclass
class Page:
    url: str        # final URL after redirects
    html: str
    soup: BeautifulSoup
    text: str       # flattened plain text (soup_to_text)
    anchors: list   # [{'href', 'resolved', 'text', 'in_footer', 'in_nav'}]


# lxml parses large pages ~5-10x faster than the pure-Python html.parser;
# fall back gracefully so environments without it keep working.
try:
    import lxml  # noqa: F401
    _SOUP_PARSER = 'lxml'
except ImportError:
    _SOUP_PARSER = 'html.parser'


def html_to_soup(html):
    return BeautifulSoup(html, _SOUP_PARSER)


# Tokens longer than this cannot be contact data (emails max out at 254
# chars); dropping them keeps the quadratic-prone phone/email regexes off multi-KB
# digit/word runs, where a single scan can take tens of seconds.
_LONG_TOKEN_RE = re.compile(r'\S{321,}')


def scan_safe_text(text):
    return _LONG_TOKEN_RE.sub(' ', text)


def soup_to_text(soup):
    # Iterative walk: malformed pages nest thousands of tags deep, which
    # a recursive version turns into a RecursionError.
    parts = []
    stack = [soup]
    while stack:
        node = stack.pop()
        if isinstance(node, Comment):
            continue
        if isinstance(node, NavigableString):
            parts.append(str(node))
        elif isinstance(node, Tag):
            if node.name in SKIP_TAGS:
                continue
            if node.name == 'br':
                parts.append('\n')
                continue
            items = list(node.children)
            if node.name in BLOCK_TAGS:
                items = ['\n'] + items + ['\n']
            stack.extend(reversed(items))
        elif isinstance(node, str):  # block-boundary sentinel
            parts.append(node)
    text = ''.join(parts)
    text = re.sub(r'[ \t\xa0]+', ' ', text)
    text = re.sub(r' ?\n ?', '\n', text)
    text = re.sub(r'\n{2,}', '\n', text)
    return text.strip()


def _ancestor_matches(tag, names, marker_re):
    for parent in tag.parents:
        if not isinstance(parent, Tag):
            continue
        if parent.name in names:
            return True
        markers = ' '.join(parent.get('class', [])) + ' ' + (parent.get('id') or '')
        if marker_re.search(markers):
            return True
    return False


_FOOTER_MARKER_RE = re.compile(r'footer', re.IGNORECASE)
_NAV_MARKER_RE = re.compile(r'\b(nav|menu|header)', re.IGNORECASE)


def in_footer(tag):
    return _ancestor_matches(tag, {'footer'}, _FOOTER_MARKER_RE)


def in_nav(tag):
    return _ancestor_matches(tag, {'nav', 'header'}, _NAV_MARKER_RE)


def anchors_with_context(soup, base_url):
    out = []
    for a in soup.find_all('a', href=True):
        href = a['href'].strip()
        if not href:
            continue
        resolved = None
        if not href.lower().startswith(NON_PAGE_SCHEMES):
            try:
                resolved = urljoin(base_url, href)
            except ValueError:
                resolved = None
        out.append({
            'href': href,
            'resolved': resolved,
            'text': a.get_text(' ', strip=True)[:200],
            'in_footer': in_footer(a),
            'in_nav': in_nav(a),
        })
    return out


_META_DESCRIPTION_NAME_RE = re.compile(r'^description$', re.IGNORECASE)


def _meta_content(soup, **attrs):
    tag = soup.find('meta', attrs=attrs)
    content = tag.get('content') if tag else None
    return content or None


def _clean_meta_text(value, limit):
    if not value:
        return None
    return ' '.join(value.split())[:limit] or None


def page_meta(soup):
    # (title, description) of a page, each None when absent. og: variants are
    # the fallback - SPA shells often carry only OpenGraph tags.
    title = soup.title.get_text() if soup.title else None
    if not title or not title.strip():
        title = _meta_content(soup, property='og:title')
    description = _meta_content(soup, name=_META_DESCRIPTION_NAME_RE) \
        or _meta_content(soup, property='og:description')
    return _clean_meta_text(title, 1000), _clean_meta_text(description, 1000)


def build_page(url, html):
    soup = html_to_soup(html)
    return Page(
        url=url,
        html=html,
        soup=soup,
        text=soup_to_text(soup),
        anchors=anchors_with_context(soup, url),
    )
