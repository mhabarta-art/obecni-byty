# Obecní byty Brno – hlídač nabídek

Třikrát denně projde úřední desky MČ **Brno-střed, Brno-sever, Žabovřesky a Královo Pole**, vytáhne nabídky obecních bytů (dispozice, plocha, podlaží, výtah, nájemné, uzávěrka, prohlídka, fotky, PDF) a:

- zobrazí je v jednoduché webové appce (GitHub Pages): karty s náhledem domu z Mapy.com Panorama, filtr podle MČ, štítek **Nové**, odpočet do uzávěrky, detail s fotkami, PDF a exportem do kalendáře,
- pošle e-mail, když se objeví nová nabídka, když se blíží uzávěrka (≤ 3 dny) nebo když některý zdroj přestane fungovat.

```
GitHub Actions (cron) ──► scraper/ (Python) ──► data/*.json ──► GitHub Pages (web/index.html)
                                   │                                   │
                                   └─► SMTP e-mail                     └─► Mapy.com Panorama (náhled domu, v prohlížeči)
```

## Zprovoznění (cca 15 minut)

1. **Repozitář** – vytvořte na GitHubu nový repozitář (např. `obecni-byty`) a nahrajte do něj tento adresář:
   ```bash
   git init && git add . && git commit -m "init" && git branch -M main
   git remote add origin git@github.com:<uzivatel>/obecni-byty.git && git push -u origin main
   ```
   Pro GitHub Pages zdarma musí být repozitář **veřejný** (data jsou stejně veřejná z úředních desek).
2. **Pages** – *Settings → Pages → Build and deployment → Source: GitHub Actions*.
3. **Oprávnění workflow** – *Settings → Actions → General → Workflow permissions: Read and write*.
4. **E-mail** (volitelné) – *Settings → Secrets and variables → Actions*:
   | Secret | Příklad |
   |---|---|
   | `SMTP_HOST` | `smtp.gmail.com` |
   | `SMTP_PORT` | `465` (SSL) nebo `587` (STARTTLS) |
   | `SMTP_USER` | váš e-mail |
   | `SMTP_PASSWORD` | u Gmailu **heslo aplikace** (vyžaduje 2FA), ne běžné heslo |
   | `MAIL_TO` | `vy@example.cz,partner@example.cz` |
   | `MAIL_FROM` | volitelné |

   A v záložce *Variables* `APP_URL` = adresa appky (`https://<uzivatel>.github.io/obecni-byty/`), aby e-mail obsahoval odkaz.
5. **První běh** – *Actions → Kontrola nabídek bytů → Run workflow*, zaškrtněte **Uložit HTML snapshoty**. Do `data/debug/` se uloží stažené stránky, podle kterých se dají doladit parsery (viz níže).
6. **Náhled domu** (volitelné) – na [developer.mapy.com](https://developer.mapy.com) si založte účet a API klíč (tarif Basic s bezplatnými kredity).
   V nastavení klíče **omezte povolené domény** na `<uzivatel>.github.io` – klíč je v načtené stránce vidět, omezení brání jeho zneužití jinde.
   Klíč vložte do *Settings → Secrets and variables → Actions → Variables* jako `MAPY_API_KEY`. Při nasazení se doplní do stránky.
   Bez klíče karty ukazují fotky od MČ (Brno-střed) nebo neutrální plochu. Obrázky se podle podmínek Mapy.com neukládají, načítají se vždy živě.

## Žabovřesky – stahování z Macu

Web Žabovřesk neodpovídá serverům mimo ČR (GitHub) a úřední deska má ochranu proti robotům, kterou nechceme obcházet. Používáme proto jejich **veřejné RSS** (`https://www.zabovresky.cz/rss/`), které stahuje malá úloha na Macu a nahrává ho do `data/zabovresky_rss.xml`:

```bash
cd ~/Claude/obecni-byty
bash mac/install.sh      # nainstaluje úlohu (5:50, 11:50, 17:50 + po probuzení Macu)
bash mac/uninstall.sh    # odinstaluje
```

Log: `~/Library/Logs/obecni-byty-zabovresky.log`. Úloha pracuje v samostatné kopii repozitáře `~/.obecni-byty-sync`, takže nezasahuje do vašich úprav. Když RSS není aktualizované déle než 3 dny, appka u Žabovřesk ukáže varování.

RSS obsahuje jen titulek a krátký popis, takže u Žabovřesk bývá méně parametrů – detail je v originálu. Nabídka z RSS zůstává aktivní 30 dní nebo do uzávěrky.

## Stav parserů – přečtěte si

Při vývoji nebyly weby MČ z vývojového prostředí dostupné, takže parsery jsou postavené na popisu struktury a otestované na syntetických vzorcích (`tests/fixtures`):

| MČ | Jistota | Poznámka |
|---|---|---|
| Brno-střed | vysoká | struktura detailu bytu ověřená (tabulka „Technický popis“, galerie, PDF, 3D prohlídka) |
| Brno-sever, Královo Pole | střední | eDeska města Brna – najde odkaz/filtr kategorie „Nabídky bytů“, jinak projde celou desku a filtruje |
| Žabovřesky | střední | oficiální RSS stahované z Macu, filtr podle klíčových slov, údaje jen z titulku a popisu |

Pokud zdroj nic nenajde nebo spadne, appka i e-mail to **výslovně ukážou** (oranžová/červená tečka u MČ). Po prvním běhu se snapshoty z `data/debug/` dají použít k přesnému doladění.

Údaje z PDF se vytahují heuristicky; naskenované PDF bez textu se označí „PDF je sken“. **Rozhodující je vždy originál na úřední desce.**

## Lokální vývoj

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest
pytest -q                                          # offline testy
python -m scraper.main --no-email --snapshots      # ostrý běh (potřebuje přístup na weby MČ)
cd web && ln -sf ../data data && python -m http.server 8000   # appka na http://localhost:8000
```

## Struktura

- `scraper/sources/brnostred.py`, `edeska.py`, `zabovresky.py` – parsery zdrojů
- `mac/` – úloha pro Mac, která stahuje RSS Žabovřesk
- `scraper/util.py` – stahování (1 s pauza mezi požadavky), rozpoznání bytové nabídky, extrakce parametrů z textu/PDF
- `scraper/main.py` – sloučení s historií, archiv ukončených nabídek, stav zdrojů
- `scraper/notify.py` – HTML e-mail
- `web/index.html` – celá appka v jednom souboru
