"""Shared helpers: HTTP session, text normalisation and field extraction from Czech text."""
from __future__ import annotations

import hashlib
import io
import logging
import re
import time
import unicodedata
from datetime import date, datetime
from typing import Optional
from urllib.parse import urljoin

import requests

log = logging.getLogger("scraper")

USER_AGENT = (
    "Mozilla/5.0 (compatible; obecni-byty-watch/1.0; "
    "+https://github.com/ hlidani nabidek obecnich bytu pro osobni potrebu)"
)
REQUEST_DELAY_S = 1.0
TIMEOUT_S = 30
MAX_PDF_BYTES = 15 * 1024 * 1024

_session: Optional[requests.Session] = None
_last_request = 0.0


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "cs,en;q=0.5"})
        _session = s
    return _session


def fetch(url: str, *, binary: bool = False, method: str = "GET", data=None):
    """Polite fetch with a delay between requests. Returns text (or bytes) and final URL."""
    global _last_request
    wait = REQUEST_DELAY_S - (time.time() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.time()
    resp = session().request(method, url, data=data, timeout=TIMEOUT_S, stream=binary)
    resp.raise_for_status()
    if binary:
        chunks, size = [], 0
        for chunk in resp.iter_content(64 * 1024):
            size += len(chunk)
            if size > MAX_PDF_BYTES:
                raise ValueError(f"file too large: {url}")
            chunks.append(chunk)
        return b"".join(chunks), resp.url, resp.headers.get("Content-Type", "")
    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding
    return resp.text, resp.url


def absolute(base: str, href: str) -> str:
    return urljoin(base, href.strip())


def stable_id(*parts: str) -> str:
    return hashlib.sha1("|".join(p or "" for p in parts).encode()).hexdigest()[:12]


def clean(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def fold(text: str) -> str:
    """Lowercase + strip diacritics for keyword matching."""
    nfkd = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


# ---------------------------------------------------------------- relevance

_FLAT = re.compile(r"\bbyt\w*", re.I)  # \b excludes "nebytový"
_OFFER = re.compile(r"pronaj|najem|nabid|vyberov|zamer|obalkov|aukc", re.I)
_NEGATIVE = re.compile(
    r"garaz|pozemk|parkovac|prodej|vymen\w* byt|vypoved|"
    r"exekuc|drazb|nalezen|stavebni povoleni|uzemni",
    re.I,
)


def looks_like_flat_offer(*texts: str) -> bool:
    t = fold(" ".join(texts))
    return bool(_FLAT.search(t) and _OFFER.search(t) and not _NEGATIVE.search(t))


# ---------------------------------------------------------------- field extraction

_DATE = r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})"
_TIME = r"(\d{1,2})[:.](\d{2})"


def parse_date(s: str) -> Optional[str]:
    m = re.search(_DATE, s or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None


def _num(s: str) -> Optional[float]:
    s = s.replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def extract_fields(text: str) -> dict:
    """Best-effort extraction of apartment parameters from free Czech text."""
    t = clean(text)
    f = fold(t)
    out: dict = {}

    disp = re.findall(r"\b([1-6])\s*\+\s*(kk|1|2)\b", f)
    if disp:
        uniq = sorted({f"{a}+{b}" for a, b in disp})
        out["dispozice"] = uniq[0] if len(uniq) == 1 else ", ".join(uniq)

    m = re.search(
        r"(?:vymer\w*|plocha|plose|podlahov\w*)[^0-9]{0,40}?(\d{1,3}(?:[.,]\d{1,2})?)\s*m\s*(?:2|²)", f
    ) or re.search(r"(\d{1,3}(?:[.,]\d{1,2})?)\s*m\s*(?:2|²)(?!\s*/)", f)
    if m:
        v = _num(m.group(1))
        if v and 10 <= v <= 250:
            out["plocha_m2"] = v

    m = re.search(r"(\d{1,2})\s*\.\s*(?:np|nadzemni|podlazi|patr)", f)
    if m:
        out["podlazi"] = f"{m.group(1)}. NP"
    elif re.search(r"\b(prizemi|1\.?\s*pp|suteren)\b", f):
        out["podlazi"] = "přízemí/suterén"

    m = re.search(r"vytah\s*[:\-]?\s*(ano|ne)\b", f)
    if m:
        out["vytah"] = m.group(1) == "ano"
    elif "bez vytahu" in f:
        out["vytah"] = False
    elif re.search(r"(s|je)\s+vytah|vytah\s+je", f):
        out["vytah"] = True

    m = re.search(r"(\d{2,4}(?:[.,]\d{1,2})?)\s*kc\s*/\s*m\s*(?:2|²)", f)
    if m:
        out["najem_m2"] = _num(m.group(1))
    m = re.search(r"(?:mesicni\s+)?najemn\w*[^0-9]{0,40}?(\d{1,3}(?:[ .]\d{3})+|\d{4,6})\s*,?-?\s*kc(?!\s*/\s*m)", f)
    if m:
        out["najem_celkem"] = _num(m.group(1).replace(".", ""))
    m = re.search(r"(?:minimaln\w*|nejnizsi)\s+(?:vyse\s+)?(?:nabid\w*|najemn\w*)[^0-9]{0,40}?(\d{2,4}(?:[.,]\d{1,2})?)\s*kc\s*/\s*m", f)
    if m:
        out["min_nabidka_m2"] = _num(m.group(1))
    m = re.search(r"kategori\w*\s*[:\-]?\s*\b(i{1,3}|iv|v)\b", f)
    if m:
        out["kategorie"] = m.group(1).upper()

    m = re.search(
        r"(?:termin\w*\s+(?:pro\s+)?(?:podani\s+)?zadost\w*\s+do|uzaverk\w*|lhut\w*\s+(?:pro|k)\s+podani\w*"
        r"|nabidk\w*\s+(?:lze\s+)?(?:podat|podavat|dorucit)\w*[^.]{0,40}?do|zadost\w*\s+(?:lze\s+)?(?:podat|podavat)\w*[^.]{0,40}?do"
        r"|(?:podani|doruceni)\s+(?:nabid|zadost)\w*\s+(?:je\s+)?do)[^0-9]{0,40}?" + _DATE,
        f,
    )
    if m:
        d = _date_from_groups(m.groups()[-3:])
        if d:
            out["uzaverka"] = d

    m = re.search(r"prohlid\w*[^0-9]{0,60}?" + _DATE + r"(?:[^0-9]{0,25}?" + _TIME + r")?", f)
    if m:
        g = m.groups()
        d = _date_from_groups(g[0:3])
        if d:
            out["prohlidka"] = d + (f"T{int(g[3]):02d}:{g[4]}" if g[3] else "")

    typ = []
    if re.search(r"obalkov|nejvyss\w* nabid|nabidnut\w* vys\w* najem|nabidkov\w* najem", f):
        typ.append("výběrové řízení – nabídka nájemného")
    if re.search(r"aukc", f):
        typ.append("e-aukce")
    if re.search(r"vlastnim naklad|k oprave|ovn\b", f):
        typ.append("oprava na vlastní náklady")
    if re.search(r"zvlastniho urceni|bezbarier|dps\b|pecovatel", f):
        typ.append("byt zvláštního určení")
    if re.search(r"startovac", f):
        typ.append("startovací byt")
    if typ:
        out["typ"] = typ
    return out


def _date_from_groups(g) -> Optional[str]:
    try:
        return date(int(g[2]), int(g[1]), int(g[0])).isoformat()
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------- PDF

def pdf_text(data: bytes, max_pages: int = 15) -> str:
    try:
        from pdfminer.high_level import extract_text

        return extract_text(io.BytesIO(data), maxpages=max_pages) or ""
    except Exception as e:  # noqa: BLE001 - malformed PDFs are common
        log.warning("PDF text extraction failed: %s", e)
        return ""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------- address

_STREET = r"[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][a-záčďéěíňóřšťúůýž]+\.?"
_ADDR_RE = re.compile(
    rf"((?:{_STREET}|nám\.|náměstí|tř\.|třída|ul\.)(?:\s+(?:{_STREET}|[a-záčďéěíňóřšťúůýž]+\.?)){{0,3}})"
    r"\s+(\d{1,4}[a-zA-Z]?(?:/\d{1,4}[a-zA-Z]?)?)\b"
)
_NOT_STREET = {"byt", "bytu", "byty", "č", "číslo", "nabídka", "pronájem", "výběrové", "záměr", "brno", "mč",
               "městská", "část", "bytový", "bytového", "dům", "domě", "domu", "kategorie", "dne", "do", "od", "ve", "na", "v", "o"}


def extract_address(text: str) -> Optional[str]:
    """Find a 'Street 12' / 'Street 12/34' pattern in Czech text (titles of board documents)."""
    for m in _ADDR_RE.finditer(clean(text)):
        words = m.group(1).split()
        keep_lower = {"nám.", "náměstí", "tř.", "třída"}
        while words and (words[0].lower().rstrip(".") in _NOT_STREET or words[0] == "ul."
                         or (words[0][0].islower() and words[0] not in keep_lower)):
            words.pop(0)
        if not words or words[-1].lower().rstrip(".") in _NOT_STREET:
            continue
        number = m.group(2)
        # skip things like "Brno 616 00" (postal codes) and years
        if re.fullmatch(r"\d{3,4}", number) and int(number) > 400:
            continue
        return f"{' '.join(words)} {number}"
    return None
