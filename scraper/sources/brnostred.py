"""Brno-střed – structured monthly offer pages with a detail page per apartment.

Listing: /potrebuji-si-vyridit/byty/nabidka-bytu (and /nabidka-bytu-ovn for flats repaired at own cost)
Detail:  /potrebuji-si-vyridit/byty/nabidka-bytu/<slug>~f<ID>
         "Technický popis" table (výměra, podlaží, výtah, nájemné, termín žádostí), gallery, PDF, virtual tour.
"""
from __future__ import annotations

import re

from .. import util
from ..html import first_match, key_values, links, main_content, soup
from .common import Context, enrich_from_pdfs, merge_fields, new_offer

BYTY = "/potrebuji-si-vyridit/byty/"
DEFAULT_LISTINGS = ["nabidka-bytu", "nabidka-bytu-ovn", "uredni-deska-byty"]
DETAIL_RE = re.compile(r"~f\d+/?$")
IMG_RE = re.compile(r"\.(jpe?g|png|webp)(\?|$)", re.I)


def _listing_urls(html: str, base: str) -> list[str]:
    urls = [util.absolute(base, BYTY + p) for p in DEFAULT_LISTINGS]
    for url, label in links(soup(html), base):
        path = url.split("brno-stred.cz")[-1]
        if path.startswith(BYTY) and "nabidk" in util.fold(label + path) and not DETAIL_RE.search(path):
            if url not in urls and "/download/" not in url:
                urls.append(url)
    return urls


def parse_detail(html: str, url: str) -> dict:
    s = soup(html)
    photos, seen = [], set()
    for a in s.find_all("a"):
        href = a.get("href") or ""
        img = a.find("img")
        if IMG_RE.search(href) and img is not None:
            full = util.absolute(url, href)
            if full not in seen:
                seen.add(full)
                photos.append({"full": full, "thumb": util.absolute(url, img.get("src") or href)})
    if not photos:
        for img in s.find_all("img"):
            src = img.get("src") or ""
            if "image-thumb" in src or "/dokumenty/" in src:
                full = util.absolute(url, src)
                if full not in seen:
                    seen.add(full)
                    photos.append({"full": full, "thumb": full})

    tour = None
    for fr in s.find_all("iframe"):
        src = fr.get("src") or fr.get("data-src") or ""
        if "kuula.co" in src or "matterport" in src:
            tour = util.absolute(url, src)
            break
    node = main_content(s)
    text = node.get_text(" ")
    out = util.extract_fields(text)
    out.pop("typ", None)  # page boilerplate mentions auctions, own-cost repairs etc. on every detail
    kv = key_values(node)
    tech = {
        "plocha_m2": first_match(kv, ("vymer", "plocha")),
        "podlazi": first_match(kv, ("podlazi", "patro")),
        "vytah": first_match(kv, ("vytah",)),
        "najem": first_match(kv, ("najem",)),
        "uzaverka": first_match(kv, ("termin", "uzaverk")),
        "dispozice": first_match(kv, ("dispozic", "velikost")),
        "prohlidka": first_match(kv, ("prohlid",)),
    }
    if tech["plocha_m2"]:
        m = re.search(r"(\d+(?:[.,]\d+)?)", tech["plocha_m2"])
        if m:
            out["plocha_m2"] = float(m.group(1).replace(",", "."))
    if tech["podlazi"]:
        out["podlazi"] = tech["podlazi"]
    if tech["vytah"]:
        out["vytah"] = util.fold(tech["vytah"]).startswith("ano")
    if tech["najem"]:
        merge_fields(out, util.extract_fields("nájemné " + tech["najem"]), overwrite=True)
    if tech["uzaverka"] and util.parse_date(tech["uzaverka"]):
        out["uzaverka"] = util.parse_date(tech["uzaverka"])
    if tech["dispozice"]:
        d = util.extract_fields(tech["dispozice"]).get("dispozice")
        if d:
            out["dispozice"] = d
    if tech["prohlidka"]:
        p = util.extract_fields("prohlídka " + tech["prohlidka"]).get("prohlidka")
        if p:
            out["prohlidka"] = p
        else:
            out["prohlidka_text"] = tech["prohlidka"]

    atts = []
    for link, label in links(s, url):
        if "/download/" in link or link.lower().endswith(".pdf"):
            atts.append({"name": label or "PDF", "url": link})
        elif "kuula.co" in link or "matterport" in link or "virtual" in util.fold(label):
            tour = tour or link
    out["attachments"] = atts
    out["photos"] = photos[:24]
    if tour:
        out["virtual_tour"] = tour
    out["tech"] = kv
    h1 = s.find("h1")
    if h1 and util.clean(h1.get_text(" ")):
        out["h1"] = util.clean(h1.get_text(" "))
    return out


def scrape(source: str, cfg: dict, ctx: Context) -> list[dict]:
    html, final = ctx.fetch(cfg["url"])
    ctx.snapshot(f"{source}-start", html)
    offers: dict[str, dict] = {}
    listings_ok = 0
    for listing in _listing_urls(html, final):
        try:
            lh, lfinal = ctx.fetch(listing)
        except Exception as e:  # noqa: BLE001 - a missing optional listing is fine
            util.log.info("listing %s unavailable: %s", listing, e)
            continue
        listings_ok += 1
        ctx.snapshot(f"{source}-{listing.rstrip('/').rsplit('/', 1)[-1]}", lh)
        is_ovn = "ovn" in listing
        for url, label in links(main_content(soup(lh)), lfinal):
            if not DETAIL_RE.search(url) or BYTY not in url:
                continue
            path = url.split("brno-stred.cz")[-1]
            o = offers.get(util.stable_id(source, path)) or new_offer(source, cfg["name"], url, label, key=path)
            dh, _ = ctx.fetch(url)
            d = parse_detail(dh, url)
            o["attachments"], o["photos"] = d.pop("attachments"), d.pop("photos")
            o["tech"] = d.pop("tech")
            h1 = d.pop("h1", None)
            label_clean = re.sub(r"^\s*\d{1,2}\.\s*\d{1,2}\.\s*\d{4}\s*", "", label)
            o["title"] = h1 or re.split(r"\s+Pronájem\b", label_clean)[0]
            merge_fields(o, util.extract_fields(label))
            merge_fields(o, d, overwrite=True)
            pub = util.parse_date(label)  # listing items start with the publication date
            if pub:
                o["published_from"] = pub
            if is_ovn:
                o["typ"] = sorted(set(o.get("typ", [])) | {"oprava na vlastní náklady"})
            m = re.match(r"(.+?)\s*,?\s*byt\s*(?:č\.?)?\s*(\d+)", o["title"], re.I)
            if m:
                o["address"], o["unit"] = m.group(1).strip(" ,"), m.group(2)
            offers[o["id"]] = o
    ctx.diagnostics["listings"] = listings_ok
    ctx.diagnostics["rows_seen"] = len(offers) if listings_ok else 0
    if not listings_ok:
        raise RuntimeError("žádná stránka s nabídkou bytů nenalezena")
    for o in offers.values():
        if not o.get("plocha_m2") or not o.get("uzaverka"):
            enrich_from_pdfs(o, ctx)
    return list(offers.values())
