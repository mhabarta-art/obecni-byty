"""Brno city eDeska (JSP) – used by Brno-sever (eDeska04) and Brno-Královo Pole (eDeska03).

The board lists documents in a table: Kategorie | Název | Číslo jednací | Zveřejnit od | do | Dokument.
We try, in order: a category link/filter for "Nabídky bytů", then paging through the whole board,
keeping rows whose category or title looks like an apartment offer.
"""
from __future__ import annotations

import re
from typing import Optional

from .. import util
from ..html import is_pdf, link_url, next_page, soup
from .common import Context, enrich_from_pdfs, merge_fields, new_offer

MAX_PAGES = 15
CATEGORY_RE = re.compile(r"(?:nabidk|pronajm)\w*.{0,25}\bbyt", re.I)


def _category_url(s, base: str) -> Optional[str]:
    for a in s.find_all("a"):
        if CATEGORY_RE.search(util.fold(a.get_text(" "))):
            return link_url(a, base)
    return None


def _category_form(s, base: str):
    """If categories are a <select> in a form, return (method, url, data) selecting 'Nabídky bytů'."""
    for form in s.find_all("form"):
        for sel in form.find_all("select"):
            for opt in sel.find_all("option"):
                if CATEGORY_RE.search(util.fold(opt.get_text(" "))):
                    data = {}
                    for inp in form.find_all("input"):
                        if inp.get("name") and inp.get("type", "text").lower() not in ("submit", "button", "image"):
                            data[inp["name"]] = inp.get("value", "")
                    for other in form.find_all("select"):
                        if other.get("name"):
                            chosen = other.find("option", selected=True) or other.find("option")
                            data[other["name"]] = chosen.get("value", "") if chosen else ""
                    data[sel.get("name", "")] = opt.get("value", opt.get_text(strip=True))
                    count = form.find("select", attrs={"name": "count"})  # page size – take the largest
                    if count:
                        sizes = [o.get("value", "") for o in count.find_all("option") if o.get("value", "").isdigit()]
                        if sizes:
                            data["count"] = max(sizes, key=int)
                    method = form.get("method", "get").upper()
                    return method, util.absolute(base, form.get("action") or base), data
    return None


def _header_map(table) -> dict[str, int]:
    for tr in table.find_all("tr"):
        ths = tr.find_all("th")
        if ths:
            m = {}
            for i, th in enumerate(ths):
                t = util.fold(th.get_text(" "))
                for key, needle in (("kategorie", "kategor"), ("nazev", "nazev"), ("cj", "cislo"),
                                    ("od", "od"), ("do", "do data"), ("dokument", "dokument")):
                    if needle in t and key not in m:
                        m[key] = i
            if "nazev" in m:
                return m
    return {}


def parse_rows(html: str, base: str, filtered: bool) -> tuple[list[dict], int]:
    """Return raw row dicts and number of table rows seen (diagnostics)."""
    s = soup(html)
    rows, seen = [], 0
    for table in s.find_all("table"):
        hm = _header_map(table)
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 3:
                continue
            seen += 1
            cells = [util.clean(td.get_text(" ")) for td in tds]

            def cell(key, default_idx):
                i = hm.get(key, default_idx)
                return cells[i] if i is not None and i < len(cells) else ""

            category = cell("kategorie", 0)
            title = cell("nazev", 1)
            cj = cell("cj", 2)
            dates = re.findall(r"\d{1,2}\.\s*\d{1,2}\.\s*\d{4}", " ".join(cells))
            fcat, ftitle = util.fold(category), util.fold(title)
            flat_category = bool(CATEGORY_RE.search(fcat)) or (filtered and re.search(r"\bbyt", fcat))
            # A flat category may also hold non-residential premises ("PSP", "nebytové prostory")
            # or bulk notices, so the title itself must mention a flat ("byt č. 5", "2+1").
            title_is_flat = bool(re.search(r"\bbyt\b|\bbyt(u|y|ech)\b|\b[1-6]\s*\+\s*(kk|1)\b", ftitle)) \
                and not re.search(r"nebyt|\bpsp\b|garaz|pozem|zameru", ftitle)
            if not ((flat_category and title_is_flat) or util.looks_like_flat_offer(category, title)):
                continue
            atts = []
            for a in tr.find_all("a"):
                url = link_url(a, base)
                if url:
                    atts.append({"name": util.clean(a.get_text(" ")) or "dokument", "url": url})
            rows.append({
                "category": category, "title": title, "cj": cj, "attachments": atts,
                "published_from": util.parse_date(dates[0]) if dates else None,
                "published_to": util.parse_date(dates[1]) if len(dates) > 1 else None,
            })
    return rows, seen


def scrape(source: str, cfg: dict, ctx: Context) -> list[dict]:
    start = cfg["url"]
    html, final = ctx.fetch(start)
    ctx.snapshot(f"{source}-start", html)
    s = soup(html)
    # The board root is a wrapper page with <iframe src="eDeskaAktualni.jsp">; follow it.
    if not s.find("table"):
        fr = s.find("iframe", src=True) or s.find("frame", src=True)
        if fr:
            html, final = ctx.fetch(util.absolute(final, fr["src"]))
            s = soup(html)
            ctx.diagnostics["iframe"] = True

    filtered = False
    pages: list[tuple[str, str]] = []
    cat_url = _category_url(s, final)
    form = None if cat_url else _category_form(s, final)
    if cat_url:
        html, final = ctx.fetch(cat_url)
        filtered = True
    elif form:
        method, url, data = form
        if method == "POST":
            html, final = ctx.fetch(url, method="POST", data=data)
        else:
            from urllib.parse import urlencode
            html, final = ctx.fetch(url + ("&" if "?" in url else "?") + urlencode(data))
        filtered = True
    ctx.diagnostics["category_filter"] = "link" if cat_url else ("form" if form else "none")

    visited = {final}
    pages.append((final, html))
    while len(pages) < MAX_PAGES:
        nxt = next_page(soup(pages[-1][1]), pages[-1][0], visited)
        if not nxt:
            break
        visited.add(nxt)
        h, f = ctx.fetch(nxt)
        pages.append((f, h))
    ctx.diagnostics["pages"] = len(pages)
    if len(pages) > 1 or filtered:
        ctx.snapshot(f"{source}-list", pages[0][1])

    offers, rows_seen = {}, 0
    for base, h in pages:
        rows, n = parse_rows(h, base, filtered)
        rows_seen += n
        for r in rows:
            key = r["cj"] or r["title"]
            o = new_offer(source, cfg["name"], (r["attachments"][0]["url"] if r["attachments"] else base),
                          r["title"], key=key + "|" + r["title"])
            o.update(cj=r["cj"], category=r["category"], published_from=r["published_from"],
                     published_to=r["published_to"], attachments=r["attachments"])
            merge_fields(o, util.extract_fields(r["title"]))
            # A non-PDF link is usually a detail page; prefer it as the main URL.
            detail = next((a["url"] for a in r["attachments"] if not is_pdf(a["url"], a["name"])), None)
            if detail:
                o["url"] = detail
            offers[o["id"]] = o
    ctx.diagnostics["rows_seen"] = rows_seen

    for o in offers.values():
        enrich_from_pdfs(o, ctx)
    return list(offers.values())
