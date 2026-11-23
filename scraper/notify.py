"""E-mail notifications over SMTP. Configured only via environment variables (GitHub secrets):

SMTP_HOST, SMTP_PORT (465 = SSL, otherwise STARTTLS), SMTP_USER, SMTP_PASSWORD,
MAIL_FROM (defaults to SMTP_USER), MAIL_TO (comma-separated), APP_URL (link to the web app).
"""
from __future__ import annotations

import html
import os
import smtplib
import ssl
from datetime import date
from email.message import EmailMessage

from . import util

REMIND_DAYS = 3


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "–"
    d = date.fromisoformat(iso[:10])
    s = f"{d.day}. {d.month}. {d.year}"
    return s + (f" {iso[11:16]}" if len(iso) > 10 else "")


def _offer_html(o: dict) -> str:
    e = html.escape
    params = [p for p in [
        o.get("dispozice"),
        f"{o['plocha_m2']:g} m²" if o.get("plocha_m2") else None,
        o.get("podlazi"),
        ("výtah" if o.get("vytah") else "bez výtahu") if o.get("vytah") is not None else None,
        f"{o['najem_m2']:g} Kč/m²" if o.get("najem_m2") else None,
        f"min. nabídka {o['min_nabidka_m2']:g} Kč/m²" if o.get("min_nabidka_m2") else None,
    ] if p]
    rows = [f"<b>{e(o['district'])}</b> · {e(' · '.join(params) or 'parametry v příloze')}"]
    if o.get("typ"):
        rows.append(e(", ".join(o["typ"])))
    if o.get("uzaverka"):
        rows.append(f"Uzávěrka: <b>{_fmt_date(o['uzaverka'])}</b>")
    if o.get("prohlidka"):
        rows.append(f"Prohlídka: {_fmt_date(o['prohlidka'])}")
    img = ""
    if o.get("photos"):
        img = f'<img src="{e(o["photos"][0]["thumb"])}" width="160" style="float:right;margin-left:12px;border-radius:6px">'
    return (f'<div style="border:1px solid #ddd;border-radius:8px;padding:12px;margin:10px 0;overflow:hidden">{img}'
            f'<a href="{e(o["url"])}" style="font-size:16px;font-weight:600">{e(o["title"])}</a><br>'
            + "<br>".join(rows) + "</div>")


def build(offers, sources, new_ids, broken) -> tuple[str, str] | None:
    by_id = {o["id"]: o for o in offers}
    new = [by_id[i] for i in new_ids if i in by_id]
    today = date.today()
    soon = [o for o in offers if o.get("active") and o.get("uzaverka") and not o.get("reminded")
            and 0 <= (date.fromisoformat(o["uzaverka"]) - today).days <= REMIND_DAYS and o["id"] not in new_ids]
    if not (new or soon or broken):
        return None
    for o in soon:
        o["reminded"] = True
    parts, subj = [], []
    if new:
        subj.append(f"{len(new)} nová nabídka" if len(new) == 1 else f"{len(new)} nové nabídky")
        parts.append("<h2>Nové nabídky</h2>" + "".join(_offer_html(o) for o in new))
    if soon:
        subj.append(f"uzávěrka do {REMIND_DAYS} dnů: {len(soon)}")
        parts.append(f"<h2>Blíží se uzávěrka (do {REMIND_DAYS} dnů)</h2>" + "".join(_offer_html(o) for o in soon))
    if broken:
        subj.append("nefunkční zdroj")
        items = "".join(f"<li><a href='{html.escape(sources[k]['board'])}'>{html.escape(sources[k]['name'])}</a>: "
                        f"{html.escape(sources[k].get('message', ''))}</li>" for k in broken)
        parts.append("<h2>⚠️ Zdroj se nepodařilo načíst</h2><p>Zkontrolujte desku ručně, než se to opraví:</p>"
                     f"<ul>{items}</ul>")
    app = os.getenv("APP_URL")
    footer = f'<p><a href="{html.escape(app)}">Otevřít přehled</a></p>' if app else ""
    body = ('<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:640px">'
            + "".join(parts) + footer
            + '<p style="color:#888;font-size:12px">Rozhodující je vždy originál na úřední desce.</p></div>')
    return "Obecní byty: " + ", ".join(subj), body


def maybe_send(offers, sources, new_ids, broken) -> None:
    built = build(offers, sources, new_ids, broken)
    if not built:
        util.log.info("nothing to notify")
        return
    host, to = os.getenv("SMTP_HOST"), os.getenv("MAIL_TO")
    if not host or not to:
        util.log.info("SMTP not configured – skipping e-mail (%s)", built[0])
        return
    subject, body = built
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.getenv("MAIL_FROM") or os.getenv("SMTP_USER")
    msg["To"] = to
    msg.set_content("Tento e-mail vyžaduje HTML zobrazení.")
    msg.add_alternative(body, subtype="html")
    port = int(os.getenv("SMTP_PORT", "465"))
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            s.send_message(msg)
    util.log.info("e-mail sent: %s", subject)
