"""HTML helpers shared by source parsers."""
from __future__ import annotations

import re
from typing import Iterable, Optional

from bs4 import BeautifulSoup, Tag

from .util import absolute, clean, fold

NEXT_TEXTS = {"dalsi", "dalsi strana", "nasledujici", "dalsi »", ">", "»", "›", ">>"}
_JS_URL = re.compile(r"""['"]([^'"\s]+\.(?:jsp|pdf|php|aspx?)(?:\?[^'"\s]*)?)['"]""", re.I)


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def main_content(s: BeautifulSoup) -> Tag:
    """Strip navigation/header/footer to reduce noise; return the most likely content node."""
    for sel in ("script", "style", "noscript", "nav", "header", "footer", "form[role=search]"):
        for t in s.select(sel):
            t.decompose()
    for sel in ("main", "article", "#content", ".content", "#obsah", ".obsah", "[role=main]"):
        node = s.select_one(sel)
        if node and len(node.get_text(strip=True)) > 50:
            return node
    return s.body or s


def link_url(a: Tag, base: str) -> Optional[str]:
    href = (a.get("href") or "").strip()
    if href and not href.lower().startswith(("javascript:", "#", "mailto:", "tel:")):
        return absolute(base, href)
    js = " ".join(filter(None, [a.get("onclick"), href]))
    m = _JS_URL.search(js)
    return absolute(base, m.group(1)) if m else None


def links(node: Tag, base: str) -> list[tuple[str, str]]:
    out, seen = [], set()
    for a in node.find_all("a"):
        url = link_url(a, base)
        if url and url not in seen:
            seen.add(url)
            out.append((url, clean(a.get_text(" "))))
    return out


def next_page(s: BeautifulSoup, base: str, visited: set[str]) -> Optional[str]:
    for a in s.find_all("a"):
        label = fold(clean(a.get_text(" ")) or a.get("title", "") or a.get("aria-label", ""))
        if label in NEXT_TEXTS or label.startswith("dalsi"):
            url = link_url(a, base)
            if url and url not in visited:
                return url
    return None


def is_pdf(url: str, label: str = "") -> bool:
    u, lab = url.lower(), fold(label)
    return (u.endswith(".pdf") or ".pdf?" in u or "/download/" in u or "download.jsp" in u
            or lab.endswith(".pdf") or ".pdf " in lab or "pdf" in lab.split())


def container_text(a: Tag, max_len: int = 600) -> str:
    """Text of the closest list-item-like ancestor of a link (for dates/metadata)."""
    node: Optional[Tag] = a
    for _ in range(6):
        node = node.parent if node else None
        if node is None:
            break
        if node.name in ("tr", "li", "article") or "item" in " ".join(node.get("class", [])):
            return clean(node.get_text(" "))[:max_len]
    return clean(a.get_text(" "))


def key_values(node: Tag) -> dict[str, str]:
    """Collect key/value pairs from 2-column tables and definition lists."""
    kv: dict[str, str] = {}
    for tr in node.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if len(cells) == 2:
            k, v = clean(cells[0].get_text(" ")), clean(cells[1].get_text(" "))
            if k and v and len(k) < 60:
                kv[fold(k).rstrip(":")] = v
    for dl in node.find_all("dl"):
        for dt in dl.find_all("dt"):
            dd = dt.find_next_sibling("dd")
            if dd:
                kv[fold(clean(dt.get_text(" "))).rstrip(":")] = clean(dd.get_text(" "))
    return kv


def first_match(kv: dict[str, str], keys: Iterable[str]) -> Optional[str]:
    for k, v in kv.items():
        if any(key in k for key in keys):
            return v
    return None
