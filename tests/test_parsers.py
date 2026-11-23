"""Offline tests with synthetic fixtures (structure based on the live sites as of 11/2026)."""
from pathlib import Path

from scraper import util
from scraper.sources import brnostred, edeska, zabovresky
from scraper.sources.common import Context

FX = Path(__file__).parent / "fixtures"


def fake_fetch(routes: dict):
    calls = []

    def fetch(url, binary=False, method="GET", data=None):
        calls.append(url)
        for frag, name in routes.items():
            if frag in url:
                if binary:
                    return b"not a pdf", url, "text/plain"
                return (FX / name).read_text("utf-8"), url
        raise RuntimeError(f"404 {url}")

    fetch.calls = calls
    return fetch


def ctx(routes, known=None):
    return Context(known=known or {}, snapshot=lambda n, h: None, fetch=fake_fetch(routes))


def test_extract_fields_free_text():
    t = ("Byt 2+kk o výměře 48,5 m2 ve 3. NP, dům s výtahem. Minimální výše nabídky nájemného 180 Kč/m2. "
         "Prohlídka bytu dne 25. 11. 2026 v 15:30 hod. Nabídky lze podávat do 2. 12. 2026 obálkovou metodou.")
    f = util.extract_fields(t)
    assert f["dispozice"] == "2+kk"
    assert f["plocha_m2"] == 48.5
    assert f["podlazi"] == "3. NP"
    assert f["vytah"] is True
    assert f["min_nabidka_m2"] == 180
    assert f["prohlidka"] == "2026-11-25T15:30"
    assert f["uzaverka"] == "2026-12-02"
    assert "výběrové řízení – nabídka nájemného" in f["typ"]


def test_relevance():
    assert util.looks_like_flat_offer("Nabídka pronájmu bytu Lesnická 12")
    assert util.looks_like_flat_offer("Nabídky bytů k pronájmu")
    assert not util.looks_like_flat_offer("Záměr pronájmu nebytových prostor")
    assert not util.looks_like_flat_offer("Prodej bytu Sportovní 3")
    assert not util.looks_like_flat_offer("Veřejná vyhláška – stavební povolení")


def test_brnostred():
    c = ctx({"~f32143": "stred_detail.html", "~f32140": "stred_detail.html",
             "/byty/nabidka-bytu": "stred_list.html", "/byty": "stred_list.html"})
    offers = brnostred.scrape("stred", {"name": "Brno-střed", "url": "https://www.brno-stred.cz/potrebuji-si-vyridit/byty"}, c)
    d8 = next(o for o in offers if "dvorakova" in o["url"])
    assert d8["address"] == "Dvořákova 8" and d8["unit"] == "2"
    assert d8["dispozice"] == "3+1" and d8["plocha_m2"] == 107
    assert d8["podlazi"] == "2. nadzemní" and d8["vytah"] is False
    assert d8["najem_m2"] == 240 and d8["kategorie"] == "III"
    assert d8["uzaverka"] == "2026-11-30"
    assert len(d8["photos"]) == 2 and "width1920" in d8["photos"][0]["full"]
    assert d8["virtual_tour"].startswith("https://kuula.co")
    assert d8["attachments"][0]["url"].endswith("/download/32133")
    # OVN listing reuses same fixture -> same ids, flagged as own-cost repair
    assert len(offers) == 2


def test_edeska():
    c = ctx({"page=2": "edeska.html", "eDeskaAktualni": "edeska.html"})
    offers = edeska.scrape("sever", {"name": "Brno-sever", "url": "https://edeska.brno.cz/eDeska04/eDeskaAktualni.jsp"}, c)
    assert len(offers) == 1
    o = offers[0]
    assert o["cj"] == "MCBSev/1/26" and o["dispozice"] == "2+1" and o["plocha_m2"] == 54
    assert o["published_from"] == "2026-11-20" and o["published_to"] == "2026-12-05"
    assert "eDeskaDownload.jsp?id=77" in o["attachments"][0]["url"]
    assert c.diagnostics["pages"] == 2


def test_zabovresky():
    c = ctx({"/detail/555": "zabovresky_detail.html", "/uredni-deska/1": "zabovresky.html",
             "/uredni-deska/2": "zabovresky.html"})
    offers = zabovresky.scrape("zabovresky", {"name": "Brno-Žabovřesky", "url": "https://www.zabovresky.cz/uredni-deska/1"}, c)
    assert len(offers) == 1
    o = offers[0]
    assert o["dispozice"] == "2+kk" and o["uzaverka"] == "2026-12-02" and o["prohlidka"] == "2026-11-25T15:30"
    assert o["published_from"] == "2026-11-18" and o["published_to"] == "2026-12-03"
    assert o["attachments"][0]["url"].endswith("minska20.pdf")


def test_notify_build():
    from datetime import date, timedelta
    from scraper import notify
    soon = (date.today() + timedelta(days=2)).isoformat()
    offers = [
        {"id": "a", "district": "Brno-střed", "title": "Dvořákova 8", "url": "https://x", "dispozice": "3+1",
         "plocha_m2": 107, "active": True, "photos": []},
        {"id": "b", "district": "Brno-sever", "title": "Lesnická <12>", "url": "https://y", "active": True,
         "uzaverka": soon, "photos": []},
    ]
    sources = {"zabovresky": {"name": "Brno-Žabovřesky", "board": "https://z", "message": "boom"}}
    subject, body = notify.build(offers, sources, ["a"], ["zabovresky"])
    assert "1 nová nabídka" in subject and "uzávěrka" in subject and "nefunkční" in subject
    assert "Lesnická &lt;12&gt;" in body and offers[1]["reminded"] is True
    assert notify.build(offers, {}, [], []) is None  # already reminded, nothing new


def test_extract_address():
    e = util.extract_address
    assert e("Nabídka pronájmu bytu Lesnická 12, byt č. 5, 2+1") == "Lesnická 12"
    assert e("Kapucínské náměstí 10, byt č. 12") == "Kapucínské náměstí 10"
    assert e("Byt na ul. Kounicova 39") == "Kounicova 39"
    assert e("Pronájem bytu č. 3 v domě Štefánikova 25a") == "Štefánikova 25a"
    assert e("Nabídka bytů k pronájmu – listopad 2026") is None
