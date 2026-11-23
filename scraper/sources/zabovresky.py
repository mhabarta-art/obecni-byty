"""Brno-Žabovřesky – generic official board (/uredni-deska/<page>), filtered by keywords."""
from __future__ import annotations

import re

from .. import util
from ..html import container_text, is_pdf, link_url, links, main_content, next_page, soup
from .common import Context, enrich_from_pdfs, merge_fields, new_offer

MAX_PAGES = 6
PAGE_RE = re.compile(r"/uredni-deska/(\d+)/?$")


def _page_links(s, base: str, visited: set[str]) -> list[str]:
    out = []
    nxt = next_page(s, base, visited)
    if nxt:
        out.append(nxt)
    for a in s.find_all("a"):
        url = link_url(a, base)
        if url and PAGE_RE.search(url.split("?")[0]) and url not in visited and url not in out:
            out.append(url)
    return out


def _category_link(s, base: str):
    for a in s.find_all("a"):
        t = util.fold(a.get_text(" "))
        if re.search(r"\bbyt", t) and re.search(r"nabid|pronaj|najem", t) and len(t) < 60:
            return link_url(a, base)
    return None


def scrape(source: str, cfg: dict, ctx: Context) -> list[dict]:
    html, final = ctx.fetch(cfg["url"])
    ctx.snapshot(f"{source}-start", html)
    pages = [(final, html)]
    visited = {final, cfg["url"]}

    cat = _category_link(soup(html), final)
    if cat and cat not in visited:
        visited.add(cat)
        h, f = ctx.fetch(cat)
        pages.append((f, h))
        ctx.diagnostics["category_link"] = cat

    queue = _page_links(soup(html), final, visited)
    while queue and len(pages) < MAX_PAGES:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        try:
            h, f = ctx.fetch(url)
        except Exception:  # noqa: BLE001 - past the last page
            break
        pages.append((f, h))
        queue += [u for u in _page_links(soup(h), f, visited) if u not in queue]
    ctx.diagnostics["pages"] = len(pages)

    offers: dict[str, dict] = {}
    items_seen = 0
    for base, h in pages:
        node = main_content(soup(h))
        for a in node.find_all("a"):
            url = link_url(a, base)
            label = util.clean(a.get_text(" "))
            if not url or len(label) < 8:
                continue
            items_seen += 1
            ctx_text = container_text(a)
            if not util.looks_like_flat_offer(label) and not util.looks_like_flat_offer(ctx_text[:200]):
                continue
            o = new_offer(source, cfg["name"], url, label)
            if o["id"] in offers:
                continue
            dates = re.findall(r"\d{1,2}\.\s*\d{1,2}\.\s*\d{4}", ctx_text)
            if dates:
                o["published_from"] = util.parse_date(dates[0])
                if len(dates) > 1:
                    o["published_to"] = util.parse_date(dates[1])
            merge_fields(o, util.extract_fields(label))
            if is_pdf(url, label):
                o["attachments"] = [{"name": label, "url": url}]
            elif o["id"] not in ctx.known:
                try:
                    dh, df = ctx.fetch(url)
                    dnode = main_content(soup(dh))
                    merge_fields(o, util.extract_fields(dnode.get_text(" ")))
                    o["attachments"] = [{"name": lbl or "příloha", "url": u}
                                        for u, lbl in links(dnode, df) if is_pdf(u, lbl)][:5]
                except Exception as e:  # noqa: BLE001
                    util.log.warning("detail %s failed: %s", url, e)
            else:
                o["attachments"] = ctx.known[o["id"]].get("attachments", [])
            offers[o["id"]] = o
    ctx.diagnostics["rows_seen"] = items_seen
    for o in offers.values():
        enrich_from_pdfs(o, ctx)
    return list(offers.values())
