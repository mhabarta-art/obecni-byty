"""Brno-Žabovřesky – official RSS feed (https://www.zabovresky.cz/rss/).

The website blocks non-Czech servers and shows an anti-bot page on the board, so we do NOT
scrape it. Instead, a small job on the user's Mac (see mac/) downloads the public RSS feed
and commits it as data/zabovresky_rss.xml. Here we only parse that file.

The feed mixes news and board documents and only keeps ~50 latest items, so offers stay
active for STICKY_DAYS (or until their deadline) instead of disappearing with the feed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import defusedxml.ElementTree as ET

from .. import util
from .common import Context, merge_fields, new_offer

RSS_FILE = Path(__file__).resolve().parents[2] / "data" / "zabovresky_rss.xml"
STALE_DAYS = 3
STICKY_DAYS = 30


def parse_rss(xml: str) -> tuple[list[dict], datetime | None]:
    root = ET.fromstring(xml)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("RSS bez <channel>")
    built = channel.findtext("lastBuildDate")
    built_dt = parsedate_to_datetime(built) if built else None
    items = []
    for it in channel.findall("item"):
        pub = it.findtext("pubDate")
        items.append({
            "title": util.clean(it.findtext("title") or ""),
            "link": util.clean(it.findtext("link") or ""),
            "description": util.clean(it.findtext("description") or ""),
            "published": parsedate_to_datetime(pub).date().isoformat() if pub else None,
        })
    return items, built_dt


def scrape(source: str, cfg: dict, ctx: Context) -> list[dict]:
    path = Path(cfg.get("rss_file", RSS_FILE))
    if not path.exists():
        raise RuntimeError("RSS Žabovřesk zatím nebylo staženo – běží stahování na Macu?")
    items, built = parse_rss(path.read_text("utf-8"))
    ctx.diagnostics["rss_items"] = len(items)
    ctx.diagnostics["rows_seen"] = len(items)
    if built:
        age = (datetime.now(timezone.utc) - built).days
        ctx.diagnostics["rss_age_days"] = age
        if age > STALE_DAYS:
            raise RuntimeError(f"RSS je {age} dní staré – stahování na Macu pravděpodobně neběží.")

    offers = []
    for it in items:
        if not it["link"].startswith("https://") or not util.looks_like_flat_offer(it["title"], it["description"][:300]):
            continue
        o = new_offer(source, cfg["name"], it["link"], it["title"])
        o["published_from"] = it["published"]
        o["sticky_days"] = STICKY_DAYS
        merge_fields(o, util.extract_fields(it["title"] + " " + it["description"]))
        if it["description"]:
            o["snippet"] = it["description"][:600]
        offers.append(o)
    return offers
