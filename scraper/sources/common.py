"""Building blocks shared by all source parsers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .. import util
from ..html import is_pdf

MAX_PDFS_PER_OFFER = 3


@dataclass
class Context:
    """What the main runner gives each parser."""

    known: dict  # id -> previously stored offer
    snapshot: Callable[[str, str], None]  # (name, html) -> None
    fetch: Callable = util.fetch
    diagnostics: dict = field(default_factory=dict)


def new_offer(source: str, district: str, url: str, title: str, key: Optional[str] = None) -> dict:
    return {
        "id": util.stable_id(source, key or url),
        "source": source,
        "district": district,
        "url": url,
        "title": util.clean(title),
        "attachments": [],
        "photos": [],
    }


def merge_fields(offer: dict, fields: dict, overwrite: bool = False) -> None:
    for k, v in fields.items():
        if v in (None, "", []):
            continue
        if k == "typ":
            offer["typ"] = sorted(set(offer.get("typ", [])) | set(v))
        elif overwrite or offer.get(k) in (None, "", []):
            offer[k] = v


def enrich_from_pdfs(offer: dict, ctx: Context) -> None:
    """Download PDF attachments of a *new* offer and extract parameters from their text.

    Known offers reuse previously extracted fields, so PDFs are downloaded only once.
    """
    prev = ctx.known.get(offer["id"])
    if prev and prev.get("pdf_checked"):
        for k in ("dispozice", "plocha_m2", "podlazi", "vytah", "najem_m2", "najem_celkem",
                  "min_nabidka_m2", "kategorie", "uzaverka", "prohlidka", "typ", "pdf_text_missing",
                  "snippet", "pdf_checked"):
            if k in prev and k not in offer:
                offer[k] = prev[k]
        return
    texts = []
    pdf_atts = [a for a in offer["attachments"] if is_pdf(a["url"], a.get("name", ""))][:MAX_PDFS_PER_OFFER]
    for att in pdf_atts:
        try:
            data, _, ctype = ctx.fetch(att["url"], binary=True)
        except Exception as e:  # noqa: BLE001
            util.log.warning("PDF download failed %s: %s", att["url"], e)
            continue
        if data[:4] == b"%PDF" or "pdf" in ctype.lower():
            texts.append(util.pdf_text(data))
    offer["pdf_checked"] = bool(texts) or not pdf_atts  # retry next run if every download failed
    text = "\n".join(t for t in texts if t.strip())
    if texts and not text.strip():
        offer["pdf_text_missing"] = True  # scanned PDF without a text layer
    if text:
        merge_fields(offer, util.extract_fields(text))
        offer["snippet"] = util.clean(text)[:600]
