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


def test_zabovresky_rss():
    c = ctx({})
    offers = zabovresky.scrape("zabovresky", {"name": "Brno-Žabovřesky", "rss_file": FX / "zabovresky_rss.xml"}, c)
    assert len(offers) == 1  # job ad and land lease are filtered out
    o = offers[0]
    assert o["dispozice"] == "2+kk" and o["plocha_m2"] == 48.5 and o["uzaverka"] == "2026-12-09"
    assert o["published_from"] == "2026-11-23" and o["sticky_days"] == 30
    assert c.fetch.calls == []  # never touches the website


def test_zabovresky_stale_rss(tmp_path):
    import pytest
    stale = (FX / "zabovresky_rss.xml").read_text("utf-8")
    import re
    stale = re.sub(r"<lastBuildDate>.*?</lastBuildDate>", "<lastBuildDate>Mon, 02 Nov 2026 10:00:00 GMT</lastBuildDate>", stale)
    f = tmp_path / "rss.xml"
    f.write_text(stale, "utf-8")
    with pytest.raises(RuntimeError, match="dní staré"):
        zabovresky.scrape("zabovresky", {"name": "Brno-Žabovřesky", "rss_file": f}, ctx({}))


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


def test_aia_issuer_url():
    import datetime as dt
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import AuthorityInformationAccessOID, NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "edeska.example")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(now).not_valid_after(now + dt.timedelta(days=1))
            .add_extension(x509.AuthorityInformationAccess([x509.AccessDescription(
                AuthorityInformationAccessOID.CA_ISSUERS, x509.UniformResourceIdentifier("http://ca.example/int.crt"))]),
                critical=False)
            .sign(key, hashes.SHA256()))
    pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    assert util.aia_issuer_url(pem) == "http://ca.example/int.crt"


def test_brnostred_no_boilerplate_typ_and_iframe_tour():
    from scraper.sources.brnostred import parse_detail
    html = (FX / "stred_detail.html").read_text("utf-8").replace(
        "</main>", '<aside><a href="/x">Elektronické aukce</a> <a href="/y">byty k opravě vlastním nákladem</a></aside>'
        '<iframe src="https://kuula.co/share/collection/ABC"></iframe></main>').replace(
        '<a href="https://kuula.co/share/collection/7dP7L">Virtuální prohlídka</a>', "")
    d = parse_detail(html, "https://www.brno-stred.cz/potrebuji-si-vyridit/byty/nabidka-bytu/x~f1")
    assert "typ" not in d
    assert d["virtual_tour"] == "https://kuula.co/share/collection/ABC"


def test_edeska_iframe_wrapper_and_pdf_detection():
    from scraper.html import is_pdf
    assert is_pdf("https://edeska.brno.cz/eDeska04/download.jsp?idPriloha=37900", "Pradlacka_11_byt_10_2_1.pdf")
    assert not is_pdf("https://edeska.brno.cz/eDeska04/eDeskaDetail.jsp?detailId=37899", "Přadlácká 11, byt 10, 2+1")
    (FX / "_wrapper.html").write_text('<html><body><iframe src="eDeskaAktualni.jsp" id="mainFrame"></iframe></body></html>')
    try:
        c = ctx({"eDeska03/eDeskaAktualni": "edeska.html", "page=2": "edeska.html", "eDeska03/": "_wrapper.html"})
        offers = edeska.scrape("kralovopole", {"name": "Brno-Královo Pole", "url": "https://edeska.brno.cz/eDeska03/"}, c)
        assert len(offers) == 1 and c.diagnostics["iframe"]
    finally:
        (FX / "_wrapper.html").unlink()
