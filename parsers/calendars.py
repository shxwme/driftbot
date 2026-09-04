"""Site-scoped calendar adapters. No round names guessed from neighbouring news."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup

from parsers.generic import extract_date_candidates


def calendar_events(soup: BeautifulSoup, source: dict[str, Any]) -> list[dict[str, Any]]:
    parser = source.get("parser")
    year = source.get("calendar_year")
    if source.get("required_heading"):
        heading = soup.find(
            lambda tag: (
                tag.name in ("h1", "h2", "h3", "h4")
                and tag.get_text(" ", strip=True).casefold() == source["required_heading"].casefold()
            )
        )
        if heading is None:
            raise ValueError(f"Season heading changed: {source['id']}")
    blocks: list[tuple[str, str, str]] = []
    if parser == "drift_masters":
        for card in soup.select(".round-card__details"):
            dates = card.select_one(".round-card__date")
            label = card.select_one(".round-card__round-number")
            venue = card.select_one(".round-card__location")
            if dates and label:
                blocks.append(
                    (
                        dates.get_text(" ", strip=True),
                        label.get_text(strip=True),
                        venue.get_text(" ", strip=True) if venue else "",
                    )
                )
    elif parser == "dmp":
        for span in soup.select(".ht1 span"):
            lines = list(span.stripped_strings)
            if lines and re.match(r"RND\d+", lines[0], re.I) and "//" in lines[0]:
                label, raw = lines[0].split("//", 1)
                blocks.append((raw.strip(), label.strip(), " ".join(lines[1:])))
    elif parser == "formula_drift":
        for node in soup.select("main time[datetime]"):
            # Find nearest card containing a round marker, not the whole schedule.
            for parent in list(node.parents)[:4]:
                marker = parent.find(string=re.compile(r"^RD\s+\d+$", re.I))
                if marker:
                    blocks.append((node.get_text(" ", strip=True), str(marker), ""))
                    break
    elif parser == "tribe":
        for row in soup.select(".tribe-events-calendar-list__event"):
            title = row.select_one(".tribe-events-calendar-list__event-title")
            start = row.select_one(".tribe-event-date-start")
            end = row.select_one(".tribe-event-date-end")
            if title and start:
                time_node = row.select_one("time[datetime]")
                row_year = date.fromisoformat(time_node["datetime"][:10]).year if time_node else year
                dates_a = extract_date_candidates(start.get_text().split("@")[0], default_year=row_year)
                dates_b = (
                    extract_date_candidates(end.get_text().split("@")[0], default_year=row_year) if end else dates_a
                )
                if len(dates_a) == len(dates_b) == 1:
                    a, b = dates_a[0]["start"], dates_b[0]["end"]
                    raw = f"{date.fromisoformat(a):%b %d, %Y} - {date.fromisoformat(b):%b %d, %Y}"
                    blocks.append((raw, title.get_text(" ", strip=True), ""))
    elif parser == "fdj":
        expected = source["schedule_heading"]
        for section in soup.select(".sche-box, .sche-box2, .sche-box3"):
            heading = section.select_one("h3")
            if not heading or heading.get_text(" ", strip=True) != expected:
                continue
            for row in section.select(".sche-txt"):
                lines = list(row.stripped_strings)
                if len(lines) >= 2:
                    label = re.match(r"Rd\.\s*\d+", lines[0], re.I)
                    blocks.append(
                        (
                            " ".join(lines[1:]),
                            label.group() if label else lines[0],
                            lines[0][label.end() :].strip() if label else "",
                        )
                    )
    elif parser == "dmcc":
        for title in soup.select("h3.elementor-heading-title,h4.elementor-heading-title"):
            if not re.match(r"rd\s+\d+\s*•", title.get_text(), re.I):
                continue
            parent = title.find_parent(class_="e-con")
            details = parent.select_one(".elementor-widget-text-editor p") if parent else None
            if details:
                raw, _, venue = details.get_text(" ", strip=True).partition("•")
                blocks.append((raw.strip(), title.get_text(" ", strip=True), venue.strip()))
    elif parser == "fras":
        tables = soup.select(source["event_selector"])
        for table in tables:
            for row in table.select("tbody tr"):
                raw = row.select_one("td.event-time")
                title = row.select_one("td.event-description a")
                if raw and title:
                    blocks.append((raw.get_text(" ", strip=True), title.get_text(" ", strip=True), ""))
    elif parser in ("table", "d1"):
        tables = soup.select(source.get("event_selector", "table"))
        if source.get("table_index") is not None:
            tables = tables[source["table_index"] : source["table_index"] + 1]
        if parser == "d1":
            table = heading.find_next_sibling("figure")
            tables = table.select("table") if table else []
        for table in tables:
            if (
                source.get("table_heading")
                and source["table_heading"].lower() not in table.get_text(" ", strip=True).lower()
            ):
                continue
            for row in table.select("tr"):
                cells = [c.get_text(" ", strip=True) for c in row.select("td")]
                if len(cells) > max(source.get("date_column", 1), source.get("round_column", 0)):
                    raw = cells[source.get("date_column", 1)]
                    label = cells[source.get("round_column", 0)]
                    venue_idx = source.get("venue_column", 2)
                    venue = cells[venue_idx].split("主催：")[0].strip() if venue_idx < len(cells) else ""
                    blocks.append((raw, label, venue))
    elif parser == "scoped":
        for row in soup.select(source["event_selector"]):
            date_node = row.select_one(source["date_selector"])
            title_node = row.select_one(source["title_selector"])
            if date_node and title_node:
                blocks.append((date_node.get_text(" ", strip=True), title_node.get_text(" ", strip=True), ""))
    elif parser == "finland":
        for link in soup.select('a[href*="/osakilpailut/"]'):
            category = link.find("strong")
            if not category or source["division"] not in re.split(r"\s*&\s*", category.get_text(strip=True)):
                continue
            raw, _, venue = link.get_text(" ", strip=True).partition(",")
            blocks.append((raw, venue.strip(), venue.strip()))
    elif parser == "drift_kings":
        # Only explicitly labelled calendar paragraphs; never dates from news prose.
        for heading in soup.select("p,h2,h3,h4"):
            text = heading.get_text(" ", strip=True)
            if text.count("•") >= 3 and re.match(
                r"(?:Round\s+\d|SPECIAL EVENT|Winter Training|The Grand Finale)", text, re.I
            ):
                segment = text.split("•")[-1].strip()
                raw = re.match(r"[A-Za-z]+\s+\d{1,2}(?:\s*[–-]\s*\d{1,2})?", segment)
                if not raw:
                    continue
                blocks.append((raw.group(), text.split("•")[0].strip(), " · ".join(text.split("•")[1:-1]).strip()))
    elif parser is None:
        return []
    else:
        raise ValueError(f"Unknown calendar adapter: {parser}")
    if not blocks:
        raise ValueError(f"Calendar layout not recognized: {source['id']}")
    events: dict[tuple[str, str, str], dict[str, Any]] = {}
    for raw, label, venue in blocks:
        # Japanese table dates and D/M ranges carry their season in the page title.
        normalized = raw
        if year and re.search(r"\d{1,2}月", raw) and not re.search(r"20\d{2}年", raw):
            normalized = f"{year}年{raw}"
        dates = extract_date_candidates(normalized, default_year=year)
        if not dates:
            continue
        if len(dates) != 1:
            # A block with several dates must be refined by its adapter, not guessed.
            continue
        candidate = dates[0]
        label = re.sub(r"^(?:Round|Rd\.?|RND)\s*(\d+)$", r"Runda \1", label.strip(), flags=re.I)
        label = re.sub(r"^RD\.(\d+)&(\d+)$", r"Rundy \1 i \2", label, flags=re.I)
        if label.isdigit():
            label = f"Runda {label}"
        event = {
            **candidate,
            "label": label,
            "venue": venue,
            "verified": True,
            "evidence": raw,
            "source_url": source["url"],
        }
        if source.get("event_scope"):
            event["event_scope"] = source["event_scope"]
        events[(event["start"], event["end"], label)] = event
    if not events:
        raise ValueError(f"No unambiguous event dates in calendar: {source['id']}")
    if len(events) < source.get("minimum_events", 1):
        raise ValueError(f"Incomplete calendar extraction: {source['id']}")
    return sorted(events.values(), key=lambda e: (e["start"], e["label"]))
