# testy.nodio.cz

Studijní testy pro Medu. Web je statický, obsah je ve složce `public/`.

- `public/index.html` – seznam testů
- `public/<nazev-testu>/index.html` – jeden test (samostatný HTML soubor)
- `deploy/` – nastavení VPS (Caddy nebo nginx, jednorázový skript)

Nový test: přidej složku do `public/` a odkaz do `public/index.html`. Po pushi se změna do minuty objeví na webu.
Přístup chrání webserver (Basic Auth), stránky mají `noindex`.

## Vysvědčení (ukládání výsledků)

Test při startu, každé odpovědi a dokončení pošle malý požadavek na `/ping.gif`. Webserver ho zapíše do logu (Caddy, JSON).
Skript `tools/make-stats.py` (cron každou minutu na VPS) z logu skládá `public/vysvedceni/data.json` (bez IP adres), který čte stránka `public/vysvedceni/`.
Pro přehled s IP adresami a prohlížečem (jen pro správce): `python3 tools/make-stats.py --admin`.

Poznámky: data jdou z prohlížeče, takže jdou teoreticky podvrhnout (pro studijní účely stačí). `data.json` je v `.gitignore`.
Nastavení VPS: viz `deploy/Caddyfile.snippet` (log, hlavičky) a cron v README výše.

### Body a odměna

Body 0–100 se počítají z logu: každá otázka se počítá nejlepším dosaženým výsledkem od posledního resetu, váhou je počet dílčích odpovědí. 100 bodů = všechny otázky správně. Zobrazují se v testu (úvodní obrazovka) a ve Vysvědčení.
Reset (po vyzvednutí odměny): `python3 tools/make-stats.py --reset` (zapíše se do `tools/resets.txt`, historie pokusů zůstane).
