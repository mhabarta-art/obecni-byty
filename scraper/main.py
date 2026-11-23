"""Run all sources, merge with stored data, write data/*.json and send notifications.

Usage:  python -m scraper.main [--snapshots] [--no-email] [--only stred,sever]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import traceback
from datetime import date, datetime
from pathlib import Path

from . import notify, util
from .sources import brnostred, edeska, zabovresky
from .sources.common import Context

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

SOURCES = {
    "stred": {"name": "Brno-střed", "kind": brnostred,
              "url": "https://www.brno-stred.cz/potrebuji-si-vyridit/byty",
              "board": "https://www.brno-stred.cz/potrebuji-si-vyridit/byty"},
    "sever": {"name": "Brno-sever", "kind": edeska,
              "url": "https://edeska.brno.cz/eDeska04/eDeskaAktualni.jsp",
              "board": "https://edeska.brno.cz/eDeska04/eDeskaAktualni.jsp"},
    "zabovresky": {"name": "Brno-Žabovřesky", "kind": zabovresky,
                   "url": "https://www.zabovresky.cz/uredni-deska/1",
                   "board": "https://www.zabovresky.cz/uredni-deska/1"},
    "kralovopole": {"name": "Brno-Královo Pole", "kind": edeska,
                    "url": "https://edeska.brno.cz/eDeska03/eDeskaAktualni.jsp",
                    "board": "https://edeska.brno.cz/eDeska03/"},
}


def load(name: str, default):
    p = DATA / name
    return json.loads(p.read_text("utf-8")) if p.exists() else default


def save(name: str, obj) -> None:
    DATA.mkdir(exist_ok=True)
    (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n", "utf-8")


def run(only: set[str] | None, snapshots: bool, email: bool) -> int:
    offers_list = load("offers.json", [])
    offers = {o["id"]: o for o in offers_list}
    sources = load("sources.json", {})
    now = util.now_iso()
    snap_dir = DATA / "debug"

    def snapshot(name: str, html: str) -> None:
        if snapshots:
            snap_dir.mkdir(parents=True, exist_ok=True)
            (snap_dir / f"{name}.html").write_text(html, "utf-8")

    new_ids: list[str] = []
    newly_broken: list[str] = []
    for key, cfg in SOURCES.items():
        if only and key not in only:
            continue
        st = sources.get(key, {})
        st.update(name=cfg["name"], board=cfg["board"], last_run=now)
        ctx = Context(known={i: o for i, o in offers.items() if o["source"] == key}, snapshot=snapshot)
        try:
            found = cfg["kind"].scrape(key, cfg, ctx)
        except Exception as e:  # noqa: BLE001 - one broken source must not stop the others
            util.log.error("%s failed: %s\n%s", key, e, traceback.format_exc())
            st["fail_streak"] = st.get("fail_streak", 0) + 1
            st.update(status="error", message=f"{type(e).__name__}: {e}"[:300], diagnostics=ctx.diagnostics)
            if st["fail_streak"] == 2:  # alert on the 2nd consecutive failure, once
                newly_broken.append(key)
            sources[key] = st
            continue

        rows_seen = ctx.diagnostics.get("rows_seen", 0)
        st.update(fail_streak=0, last_ok=now, count=len(found), diagnostics=ctx.diagnostics)
        if rows_seen == 0:
            st.update(status="warning", message="Na stránce nebyla nalezena žádná položka – možná se změnila struktura webu.")
        else:
            st.update(status="ok", message="")
        sources[key] = st

        seen_ids = set()
        for o in found:
            seen_ids.add(o["id"])
            if not o.get("address"):
                addr = util.extract_address(o.get("title", ""))
                if addr:
                    o["address"] = addr
            prev = offers.get(o["id"])
            if prev:
                o["first_seen"] = prev["first_seen"]
                o["reminded"] = prev.get("reminded", False)
            else:
                o["first_seen"] = now
                new_ids.append(o["id"])
            o["last_seen"] = now
            o["active"] = True
            o.pop("gone_since", None)
            offers[o["id"]] = o
        # Offers no longer on the board -> archive (only when the source worked).
        if st["status"] == "ok":
            for o in offers.values():
                if o["source"] == key and o["id"] not in seen_ids and o.get("active"):
                    o["active"] = False
                    o["gone_since"] = now

    today = date.today().isoformat()
    for o in offers.values():
        if o.get("active") and o.get("published_to") and o["published_to"] < today:
            o["active"] = False
            o.setdefault("gone_since", now)

    ordered = sorted(offers.values(), key=lambda o: (not o.get("active"), o.get("first_seen", "")), reverse=False)
    ordered.sort(key=lambda o: o.get("first_seen", ""), reverse=True)
    ordered.sort(key=lambda o: not o.get("active"))
    save("offers.json", ordered)
    save("sources.json", sources)
    save("meta.json", {"updated": now, "new_last_run": new_ids})

    if email:
        notify.maybe_send(ordered, sources, new_ids, newly_broken)
        save("offers.json", ordered)  # 'reminded' flags may have changed
    util.log.info("done: %d offers (%d new)", len(ordered), len(new_ids))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshots", action="store_true", default=os.getenv("SAVE_SNAPSHOTS") == "1")
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    only = set(filter(None, a.only.split(","))) or None
    return run(only, a.snapshots, not a.no_email)


if __name__ == "__main__":
    raise SystemExit(main())
