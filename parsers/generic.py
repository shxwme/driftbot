from __future__ import annotations

import hashlib
import os
import re
import shutil
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import feedparser
import pytesseract
import requests
from bs4 import BeautifulSoup
from PIL import Image

_tesseract = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
if not _tesseract and os.name == "nt":
    _candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Tesseract-OCR" / "tesseract.exe"
    if _candidate.is_file():
        _tesseract = str(_candidate)
if _tesseract:
    pytesseract.pytesseract.tesseract_cmd = _tesseract

MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
MONTHS.update(
    {
        "stycznia": 1,
        "lutego": 2,
        "marca": 3,
        "kwietnia": 4,
        "maja": 5,
        "czerwca": 6,
        "lipca": 7,
        "sierpnia": 8,
        "września": 9,
        "października": 10,
        "listopada": 11,
        "grudnia": 12,
        "janvier": 1,
        "février": 2,
        "fevrier": 2,
        "mars": 3,
        "avril": 4,
        "mai": 5,
        "juin": 6,
        "juillet": 7,
        "août": 8,
        "aout": 8,
        "septembre": 9,
        "octobre": 10,
        "novembre": 11,
        "décembre": 12,
        "decembre": 12,
    }
)


def extract_date_candidates(text: str, *, default_year: int | None = None) -> list[dict[str, str]]:
    """Parse date spans once; explicit years win and ambiguous years stay unknown."""
    import unicodedata

    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"(?<=\d)\.\s+", ".", text)
    years = {int(y) for y in re.findall(r"(?<!\d)(20\d{2})(?!\d)", text)}
    fallback = default_year or (next(iter(years)) if len(years) == 1 else None)
    month = "(?:" + "|".join(sorted(MONTHS, key=len, reverse=True)) + ")"
    spans: list[tuple[int, int]] = []
    found: dict[tuple[str, str], dict[str, str]] = {}

    def collect(pattern: str, convert: Any) -> None:
        for match in re.finditer(pattern, text, re.I):
            if any(match.start() < end and match.end() > start for start, end in spans):
                continue
            # A round label immediately followed by a month is not a date.
            if re.search(r"(?:round|runda|rnd|rd)\.?\s*$", text[max(0, match.start() - 20) : match.start()], re.I):
                continue
            try:
                start, end = convert(match)
                if start is None or end is None or end < start or (end - start).days > 31:
                    continue
            except (ValueError, TypeError, KeyError):
                continue
            spans.append(match.span())
            key = (start.isoformat(), end.isoformat())
            found.setdefault(key, {"raw": match.group(), "start": key[0], "end": key[1]})

    def dt(y: Any, m: Any, d: Any) -> date:
        return date(int(y), MONTHS.get(str(m).lower(), 0) or int(m), int(d))

    collect(
        rf"\b({month})\s+(\d{{1,2}}),?\s+(20\d{{2}})\s*[–-]\s*({month})\s+(\d{{1,2}}),?\s+(20\d{{2}})\b",
        lambda m: (dt(m[3], m[1], m[2]), dt(m[6], m[4], m[5])),
    )
    collect(
        r"\b(\d{1,2})[./](\d{1,2})[./](20\d{2})\s*[–-]\s*(\d{1,2})[./](\d{1,2})[./](20\d{2})\b",
        lambda m: (dt(m[3], m[2], m[1]), dt(m[6], m[5], m[4])),
    )
    collect(
        r"\b(\d{1,2})\.(?:(\d{1,2})\.)?\s*[–-]\s*(\d{1,2})\.(\d{1,2})\.(20\d{2})\b",
        lambda m: (dt(m[5], m[2] or m[4], m[1]), dt(m[5], m[4], m[3])),
    )
    collect(
        r"(?<!\d)(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)",
        lambda m: (dt(m[1], m[2], m[3]), dt(m[1], m[2], m[3])),
    )
    collect(
        r"\b(\d{1,2})(?:\s*[–-]\s*(\d{1,2}))?[./](\d{1,2})[./](20\d{2})\b",
        lambda m: (dt(m[4], m[3], m[1]), dt(m[4], m[3], m[2] or m[1])),
    )
    collect(
        r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日(?:\([^)]*\))?"
        r"(?:\s*[～~–-]\s*(?:(\d{1,2})月)?(\d{1,2})日?)?",
        lambda m: (dt(m[1], m[2], m[3]), dt(m[1], m[4] or m[2], m[5] or m[3])),
    )
    collect(
        rf"\b(?:du\s+)?(\d{{1,2}})(?:st|nd|rd|th)?(?:\s*(?:[–-]|au)\s*(\d{{1,2}})(?:st|nd|rd|th)?)?\s+({month})(?:\s+(20\d{{2}}))?\b",
        lambda m: (dt(m[4] or fallback, m[3], m[1]), dt(m[4] or fallback, m[3], m[2] or m[1])),
    )
    collect(
        rf"\b({month})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:\s*[–-]\s*(?:({month})\s+)?(\d{{1,2}}))?(?:,?\s+(20\d{{2}}))?\b",
        lambda m: (dt(m[5] or fallback, m[1], m[2]), dt(m[5] or fallback, m[3] or m[1], m[4] or m[2])),
    )
    return sorted(found.values(), key=lambda item: (item["start"], item["end"]))


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
    from html import escape

    from parsers.calendars import calendar_events

    response = None
    last_error = None
    events = []
    for page_url in [source["url"], *source.get("fallback_urls", [])]:
        try:
            candidate = requests.get(
                page_url,
                headers={"User-Agent": "DriftRadar/1.0 (+personal monitor)"},
                timeout=30,
            )
        except requests.RequestException:
            continue
        if candidate.ok:
            page = candidate.text
            if "text/plain" in candidate.headers.get("Content-Type", ""):
                page = (
                    "<html><body>" + "".join(f"<p>{escape(line)}</p>" for line in page.splitlines()) + "</body></html>"
                )
            candidate_soup = BeautifulSoup(page, "html.parser")
            try:
                events = calendar_events(candidate_soup, source)
            except ValueError as exc:
                last_error = exc
                continue
            response = candidate
            soup = candidate_soup
            break
    if response is None:
        if last_error:
            raise last_error
        if not source.get("image_urls"):
            raise RuntimeError("Calendar page unavailable")
        soup = BeautifulSoup("", "html.parser")
    selector = source.get("selector", "body")
    nodes = soup.select(selector)
    if not nodes and selector != "body" and not source.get("parser"):
        nodes = soup.select("body")
    if not nodes and not source.get("image_urls"):
        raise RuntimeError(f"CSS selector {selector!r} matched nothing")
    text = "\n".join(" ".join(node.get_text(" ", strip=True).split()) for node in nodes)
    result: dict[str, Any] = {
        "date_candidates": extract_date_candidates(text, default_year=source.get("calendar_year")),
        "items": [" ".join(node.get_text(" ", strip=True).split()) for node in nodes],
    }
    result["events"] = events
    result["retrieved_url"] = response.url if response is not None else source["url"]
    result["verification"] = "verified" if result["events"] else "unverified"
    if source.get("include_images"):
        images = []
        image_refs = [
            (urljoin(response.url if response is not None else source["url"], url), "")
            for url in source.get("image_urls", [])
        ]
        if not image_refs:
            for image in soup.select("img"):
                raw_url = next(
                    (
                        value
                        for value in (image.get("src"), image.get("data-src"), image.get("data-lazy-src"))
                        if value and value.startswith(("http://", "https://", "/"))
                    ),
                    None,
                )
                if raw_url:
                    image_url = urljoin(source["url"], raw_url)
                    image_refs.append((image_url, image.get("alt", "")))
        calendar_refs = [
            (url, alt) for url, alt in image_refs if re.search(r"calendar|calendrier|kalendar", f"{url} {alt}", re.I)
        ]
        for image_url, alt in calendar_refs or image_refs[:10]:
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
                image = Image.open(BytesIO(image_bytes))
                ocr_text = pytesseract.image_to_string(image, config="--psm 6", timeout=45)
                second_text = pytesseract.image_to_string(image, config="--psm 11", timeout=45)
                second_dates = {
                    (c["start"], c["end"])
                    for c in extract_date_candidates(second_text, default_year=source.get("calendar_year"))
                }
                first_dates = extract_date_candidates(ocr_text, default_year=source.get("calendar_year"))
                images.append(
                    {
                        "url": image_url,
                        "alt": alt,
                        "sha256": hashlib.sha256(image_bytes).hexdigest(),
                        "ocr_text": " ".join(ocr_text.split()),
                        "date_candidates": first_dates,
                        "agreed_dates": [c for c in first_dates if (c["start"], c["end"]) in second_dates],
                    }
                )
            except pytesseract.TesseractNotFoundError:
                result.setdefault("image_errors", []).append({"url": image_url, "error": "tesseract_missing"})
            except (requests.RequestException, RuntimeError, OSError) as exc:
                result.setdefault("image_errors", []).append({"url": image_url, "error": str(exc)})
            except Exception as exc:
                result.setdefault("image_errors", []).append(
                    {"url": image_url, "error": f"{type(exc).__name__}: {exc}"}
                )
        result["image_calendar"] = True
        result["image_urls"] = images
        ocr_dates = [candidate for image in images for candidate in image["date_candidates"]]
        result["ocr_date_candidates"] = sorted(
            {f"{item['start']}|{item['end']}": item for item in ocr_dates}.values(),
            key=lambda item: (item["start"], item["end"]),
        )
        text_ranges = {(item["start"], item["end"]) for item in result["events"]}
        ocr_ranges = {(item["start"], item["end"]) for item in result["ocr_date_candidates"]}
        matched_ranges = text_ranges & ocr_ranges
        if text_ranges and ocr_ranges:
            verification_status = (
                "verified" if text_ranges == ocr_ranges else "partial_match" if matched_ranges else "mismatch"
            )
        elif ocr_ranges:
            verification_status = "ocr_only"
        else:
            verification_status = "no_ocr_dates"
        result["ocr_verification"] = {
            "status": verification_status,
            "matched_ranges": len(matched_ranges),
            "text_ranges": len(text_ranges),
            "ocr_ranges": len(ocr_ranges),
        }
        if source.get("ocr_required", True) and image_refs and not images:
            details = "; ".join(error["error"] for error in result.get("image_errors", []))
            raise RuntimeError(f"calendar OCR failed: {details or 'no image was processed'}")
        # Image-only sources require two OCR layouts to agree. OCR remains fallible;
        # publish the provenance explicitly and never synthesize a round number.
        if source.get("ocr_publish") and not result["events"]:
            for image in images:
                for candidate in image.get("agreed_dates", []):
                    result["events"].append(
                        {
                            **candidate,
                            "label": source.get("event_label", "Wydarzenie"),
                            "verified": True,
                            "verification": "ocr_agreement",
                            "source_url": image["url"],
                            "evidence": candidate["raw"],
                        }
                    )
            result["verification"] = "ocr_agreement" if result["events"] else "unverified"
    return result
