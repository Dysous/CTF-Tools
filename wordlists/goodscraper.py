#!/usr/bin/env python3
"""
Scrape a Goodreads "read" shelf page and extract data needed
in order to create read book lists for sample users in another project.

Usage:
    python goodscraper.py 162248230 > books.json
    python goodscraper.py "https://www.goodreads.com/review/list/162248230?shelf=read" > books.json
    python goodscraper.py "Noah-read-shelf.html" > books.json
"""

import argparse
import hashlib
import json
import os
import re
import sys
from urllib.parse import urljoin, urlparse, parse_qsl, urlencode, urlunparse

from bs4 import BeautifulSoup

try:
    import requests
except ImportError:
    requests = None

GOODREADS_BASE = "https://www.goodreads.com"


def resolve_input(arg: str) -> str:
    """
    - If arg is an existing file: treat as local HTML
    - If arg is all digits: treat as Goodreads user id
    - Else if it starts with http(s): treat as URL
    - Else, fallback: and treat as path
    """
    #if local file
    if os.path.exists(arg):
        return arg

    #if just user id like "162248230"
    if arg.isdigit():
        # can tweak params (per_page, sort)
        return f"{GOODREADS_BASE}/review/list/{arg}?shelf=read"

    #full url?
    if arg.startswith("http://") or arg.startswith("https://"):
        return arg

    #otherwise fallback
    return arg


def load_html(path_or_url: str) -> str:
    """
    Load HTML from a local file or via HTTP.

    - If it's a file on disk, just open it.
    - If it's a URL, send a browser-y User-Agent so Goodreads
      is less likely to block us with 403.
    """
    # Local file?
    if os.path.exists(path_or_url):
        with open(path_or_url, "r", encoding="utf-8") as f:
            return f.read()

    # Not a file -> treat as URL
    if not requests:
        raise RuntimeError(
            "requests is not installed; can't fetch URL. "
            "Install with: pip install requests"
        )

    headers = {
        #act as a normal chromium browser on windows
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.goodreads.com/",
    }

    resp = requests.get(path_or_url, headers=headers)
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        # Give a cleaner error message if Goodreads blocks us
        msg = (
            f"HTTP error {resp.status_code} when fetching {path_or_url}.\n"
            "If this is a Goodreads shelf URL and you got 403:\n"
            "  - Goodreads may be blocking automated requests.\n"
            "  - Workaround: open the page in your browser while logged in,\n"
            "    then File -> Save Page As... (HTML only) and run this script\n"
            "    on the saved .html file instead.\n"
        )
        raise SystemExit(msg) from e

    return resp.text


def extract_external_id(book_href: str) -> str | None:
    """
    From a Goodreads book URL like:
        /book/show/364549.A_Letter_Concerning_Toleration
    or   https://www.goodreads.com/book/show/364549.A_Letter...
    pull out the numeric ID: "364549".
    """
    if not book_href:
        return None

    path = urlparse(book_href).path
    m = re.search(r"/book/show/(\d+)", path)
    if m:
        return m.group(1)
    return None


def extract_int_from_text(text: str | None) -> int | None:
    if not text:
        return None
    digits = re.findall(r"\d+", text.replace(",", ""))
    if not digits:
        return None
    try:
        return int(digits[0])
    except ValueError:
        return None


def extract_year_from_date(text: str | None) -> int | None:
    """
    Goodreads 'date pub' cell looks like "Mar 18, 2025".
    I just grab the last 4-digit year if it is present.
    """
    if not text:
        return None
    m = re.search(r"(\d{4})", text)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def compute_key_hash(source: str, external_id: str | None,
                     title: str, authors: str | None) -> str:
    """
    Compute a deterministic key hash "source + externalId + title + authors" 
    """
    parts = [
        source or "",
        external_id or "",
        title or "",
        authors or "",
    ]
    raw = "|".join(p.strip() for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_shelf(html: str, shelf_url: str | None = None) -> list[dict]:
    """
    Parse the Goodreads shelf HTML and return a list of dicts
    that map cleanly onto my curr Book entity.
    """
    soup = BeautifulSoup(html, "html.parser")

    books: list[dict] = []

    #<tr id="review_xxx" class="bookalike review"> ... </tr>
    for row in soup.find_all("tr", class_="bookalike"):
        #title/book/externalid
        title_td = row.find("td", class_="field title")
        if not title_td:
            continue

        title_link = title_td.find("a", href=True)
        if not title_link:
            continue

        title = title_link.get_text(strip=True)
        book_href = title_link["href"]
        if shelf_url and not book_href.startswith("http"):
            book_url = urljoin(GOODREADS_BASE, book_href)
        else:
            book_url = book_href

        external_id = extract_external_id(book_href)

        #author
        author_td = row.find("td", class_="field author")
        authors = None
        if author_td:
            author_links = author_td.find_all("a")
            if author_links:
                authors = ", ".join(a.get_text(strip=True) for a in author_links)
            else:
                authors = author_td.get_text(strip=True) or None

        #cover url (image)
        cover_td = row.find("td", class_="field cover")
        cover_url = None
        if cover_td:
            img = cover_td.find("img")
            if img and img.get("src"):
                cover_url = img["src"]

        #page count
        pages_td = row.find("td", class_="field num_pages")
        page_count = None
        if pages_td:
            text = pages_td.get_text(" ", strip=True)
            page_count = extract_int_from_text(text)

        #year published
        date_pub_td = row.find("td", class_="field date_pub")
        published_year = None
        if date_pub_td:
            text = date_pub_td.get_text(" ", strip=True)
            published_year = extract_year_from_date(text)

        # Map Goodreads to your BookSource enum; probably OTHER in your system
        source = "OTHER"

        key_hash = compute_key_hash(
            source=source,
            external_id=external_id,
            title=title,
            authors=authors,
        )

        book_obj = {
            #"keyHash": key_hash,
            "source": source,              #BookSource.OTHER (our enum doesn't include goodreads)
            #"externalId": external_id,     #goodreads numeric id
            "title": title,
            "authors": authors,
            #"publishedYear": published_year,
            "pageCount": page_count,
            #"publisher": None,             #would need to grab for other page
            #"categories": None,            #would need to grab for other page
            "coverUrl": cover_url,
            #"goodreadsUrl": book_url,
        }

        books.append(book_obj)

    return books


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "shelf",
        help=(
            "Goodreads user id, Goodreads 'read' shelf URL, "
            "or local HTML file path"
        ),
    )
    args = ap.parse_args()
    resolved = resolve_input(args.shelf)

    #just parse once if local html file
    if os.path.exists(resolved):
        html = load_html(resolved)
        books = parse_shelf(html, shelf_url=resolved)

    #paginate goodreads.com shelf url
    elif "goodreads.com/review/list" in resolved:
        all_books: list[dict] = []
        page = 1

        while True:
            #parse and rebuild url with per_page + page
            parsed = urlparse(resolved)
            qs = dict(parse_qsl(parsed.query))

            #max per_page goodreads will give is 200, yet this fails at 200?
            #largest working value I found was 15 might need to tweak
            qs.setdefault("per_page", "10")
            qs["page"] = str(page)

            page_url = urlunparse(parsed._replace(query=urlencode(qs)))

            html = load_html(page_url)
            page_books = parse_shelf(html, shelf_url=page_url)

            if not page_books:
                break

            all_books.extend(page_books)

            #if fewer than per page (per_page), then scraper is at the last page
            try:
                per_page = int(qs["per_page"])
            except ValueError:
                per_page = None

            if per_page is None or len(page_books) < per_page:
                break

            page += 1

        books = all_books
    else:
        html = load_html(resolved)
        books = parse_shelf(html, shelf_url=resolved)

    json.dump(books, fp=sys.stdout, indent=2, ensure_ascii=False)



if __name__ == "__main__":
    main()
