from __future__ import annotations

import re
import hashlib
from io import BytesIO
from datetime import date
from typing import Any
from urllib.parse import urljoin

import feedparser
from PIL import Image
import pytesseract
import requests
from bs4 import BeautifulSoup

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7,
    "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
MONTHS.update({
    "stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4, "maja": 5, "czerwca": 6,
    "lipca": 7, "sierpnia": 8, "września": 9, "października": 10, "listopada": 11, "grudnia": 12,
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9, "octobre": 10,
    "novembre": 11, "décembre": 12, "decembre": 12,
})


def extract_date_candidates(text: str) -> list[dict[str, str]]:
    """Extract conservative, validated date candidates from rendered calendar text."""
    found: dict[tuple[str, str], dict[str, str]] = {}

    def add(raw: str, start: date, end: date) -> None:
        key = (start.isoformat(), end.isoformat())
        found.setdefault(key, {"raw": raw, "start": key[0], "end": key[1]})

    for match in re.finditer(r"\b(\d{1,2})\s*[–-]\s*(\d{1,2})[./](\d{1,2})[./](20\d{2})\b", text):
        day_a, day_b, month, year = map(int, match.groups())
        try:
            add(match.group(0), date(year, month, day_a), date(year, month, day_b))
        except ValueError:
            continue

    for match in re.finditer(r"\b(\d{1,2})[./](\d{1,2})[./](20\d{2})\b", text):
        day, month, year = map(int, match.groups())
        try:
            value = date(year, month, day)
            add(match.group(0), value, value)
        except ValueError:
            continue

    for match in re.finditer(
        r"\b([A-Za-z]{3,9})\s+(\d{1,2})(?:\s*-\s*([A-Za-z]{3,9})?\s*(\d{1,2}))?[, ]+\s*(20\d{2})\b",
        text,
    ):
        month_a, day_a, month_b, day_b, year = match.groups()
        month_a_num = MONTHS.get(month_a.lower())
        month_b_num = MONTHS.get((month_b or month_a).lower())
        if not month_a_num or not month_b_num:
            continue
        try:
            start = date(int(year), month_a_num, int(day_a))
            end = date(int(year), month_b_num, int(day_b or day_a))
            if end >= start:
                add(match.group(0), start, end)
        except ValueError:
            continue

    inferred_years = [int(value) for value in re.findall(r"\b(20\d{2})\b", text)]
    inferred_year = inferred_years[0] if inferred_years else None
    if inferred_year:
        for match in re.finditer(r"\b([A-Za-zÀ-ÿ]{3,12})\s+(\d{1,2})\s*[–-]\s*(\d{1,2})\b", text, re.I):
            month_name, day_a, day_b = match.groups()
            month_num = MONTHS.get(month_name.lower())
            if not month_num:
                continue
            try:
                add(match.group(0), date(inferred_year, month_num, int(day_a)), date(inferred_year, month_num, int(day_b)))
            except ValueError:
                continue

        for match in re.finditer(
            r"\b([A-Za-z]{3,9})\s+(\d{1,2})\s*-\s*([A-Za-z]{3,9})?\s*(\d{1,2})\b",
            text,
        ):
            month_a, day_a, month_b, day_b = match.groups()
            month_a_num = MONTHS.get(month_a.lower())
            month_b_num = MONTHS.get((month_b or month_a).lower())
            if not month_a_num or not month_b_num:
                continue
            try:
                start = date(inferred_year, month_a_num, int(day_a))
                end = date(inferred_year, month_b_num, int(day_b))
                if end >= start:
                    add(match.group(0), start, end)
            except ValueError:
                continue

        for match in re.finditer(r"\bdu\s+(\d{1,2})\s+au\s+(\d{1,2})\s+([A-Za-zÀ-ÿ]+)\s+(20\d{2})\b", text, re.I):
            day_a, day_b, month_name, year = match.groups()
            month_num = MONTHS.get(month_name.lower())
            if not month_num:
                continue
            try:
                add(match.group(0), date(int(year), month_num, int(day_a)), date(int(year), month_num, int(day_b)))
            except ValueError:
                continue

        for match in re.finditer(r"\b(20\d{2})年(\d{1,2})月(\d{1,2})日(?:[^\d]{0,8}(\d{1,2})月(\d{1,2})日)?", text):
            year, month_a, day_a, month_b, day_b = match.groups()
            try:
                start = date(int(year), int(month_a), int(day_a))
                end = date(int(year), int(month_b or month_a), int(day_b or day_a))
                add(match.group(0), start, end)
            except ValueError:
                continue
    return sorted(found.values(), key=lambda item: (item["start"], item["end"], item["raw"]))


def fetch_rss(source: dict[str, Any]) -> list[dict[str, str]]:
    feed = feedparser.parse(source["url"])
    if getattr(feed, "bozo", False) and not feed.entries:
        raise RuntimeError(f"RSS parse failed for {source['url']}")
    return [
        {
            "id": str(entry.get("id") or entry.get("link") or entry.get("title")),
            "title": str(entry.get("title", "")),
            "url": str(entry.get("link", "")),
            "published": str(entry.get("published", "")),
        }
        for entry in feed.entries[: source.get("max_items", 20)]
    ]


def fetch_html(source: dict[str, Any]) -> dict[str, Any]:
    response = None
    for page_url in [source["url"], *source.get("fallback_urls", [])]:
        candidate = requests.get(
            page_url,
            headers={"User-Agent": "DriftRadar/1.0 (+personal monitor)"},
            timeout=30,
        )
        if candidate.ok:
            response = candidate
            break
    if response is None:
        raise RuntimeError(f"calendar page unavailable: {source['url']}")
    soup = BeautifulSoup(response.text, "html.parser")
    selector = source.get("selector", "body")
    nodes = soup.select(selector)
    if not nodes and selector != "body":
        nodes = soup.select("body")
    if not nodes:
        raise RuntimeError(f"CSS selector {selector!r} matched nothing")
    text = "\n".join(" ".join(node.get_text(" ", strip=True).split()) for node in nodes)
    result: dict[str, Any] = {
        "date_candidates": extract_date_candidates(text),
        "items": [" ".join(node.get_text(" ", strip=True).split()) for node in nodes],
    }
    if source.get("include_images"):
        images = []
        image_refs = [(urljoin(response.url, url), "") for url in source.get("image_urls", [])]
        if not image_refs:
            for image in soup.select("img"):
                raw_url = next(
                    (value for value in (image.get("src"), image.get("data-src"), image.get("data-lazy-src"))
                     if value and value.startswith(("http://", "https://", "/"))),
                    None,
                )
                if raw_url:
                    image_url = urljoin(source["url"], raw_url)
                    image_refs.append((image_url, image.get("alt", "")))
        calendar_refs = [
            (url, alt) for url, alt in image_refs
            if re.search(r"calendar|calendrier|kalendar", f"{url} {alt}", re.I)
        ]
        for image_url, alt in (calendar_refs or image_refs[:10]):
                try:
                    candidates = [image_url, *source.get("fallback_image_urls", [])]
                    image_response = None
                    for candidate_url in candidates:
                        response = requests.get(
                            candidate_url,
                            headers={"User-Agent": "DriftRadar/1.0", "Referer": source["url"]},
                            timeout=30,
                        )
                        if response.ok:
                            image_response = response
                            image_url = candidate_url
                            break
                    if image_response is None:
                        raise RuntimeError("calendar image unavailable")
                    if len(image_response.content) > 12 * 1024 * 1024:
                        raise RuntimeError("calendar image is too large")
                    image_bytes = image_response.content
                    ocr_text = pytesseract.image_to_string(Image.open(BytesIO(image_bytes)), timeout=45)
                    images.append({
                        "url": image_url,
                        "alt": alt,
                        "sha256": hashlib.sha256(image_bytes).hexdigest(),
                        "ocr_text": " ".join(ocr_text.split()),
                        "date_candidates": extract_date_candidates(ocr_text),
                    })
                except pytesseract.TesseractNotFoundError:
                    result.setdefault("image_errors", []).append({"url": image_url, "error": "tesseract_missing"})
                except (requests.RequestException, RuntimeError, OSError) as exc:
                    result.setdefault("image_errors", []).append({"url": image_url, "error": str(exc)})
                except Exception as exc:
                    result.setdefault("image_errors", []).append({"url": image_url, "error": f"{type(exc).__name__}: {exc}"})
        result["image_calendar"] = True
        result["image_urls"] = images
        ocr_dates = [candidate for image in images for candidate in image["date_candidates"]]
        result["ocr_date_candidates"] = sorted(
            {f"{item['start']}|{item['end']}": item for item in ocr_dates}.values(),
            key=lambda item: (item["start"], item["end"]),
        )
    return result
