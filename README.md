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

Body 0–100 se počítají z logu: každá otázka se počítá nejlepším dosaženým výsledkem z dokončených testů od posledního resetu, váhou je počet dílčích odpovědí. 100 bodů = všechny otázky správně. Zobrazují se v testu (úvodní obrazovka) a ve Vysvědčení.
Odměna a reset jsou po jednotlivých testech. Reset jednoho testu po vyzvednutí odměny: `python3 tools/make-stats.py --reset <id testu nebo jeho začátek>` (všechny: `--reset all`). Zapíše se do `tools/resets.txt`, historie pokusů zůstane.

### Kdy se Vysvědčení přepočítá

- Hned po dokončení testu: systemd služba `deploy/testy-stats.service` (skript `tools/watch-stats.sh`) sleduje log a po události `e=end` spustí `make-stats.py`.
- Záložně cronem každých 10 minut (výpadek služby apod.). Nedokončené pokusy se ve Vysvědčení ukazují, ale body se z nich nepočítají.
- Po `--reset` se `data.json` vygeneruje hned.

Seznam testů pro body: `public/tests.json` (id, název, odkaz). Nový test = nový záznam tam + složka v `public/` + odkaz v `public/index.html`. Test bez pokusu se do souhrnu bodů počítá jako 0.

### Logy a trvalá historie

Stránka `public/logy/` (odkaz v zápatí Vysvědčení) ukazuje otevření stránek a spuštění/dokončení testů s časem, zařízením a IP adresou s maskovanou poslední částí.
Při každém spuštění `tools/make-stats.py` se nové události z logu Caddy připíšou do `tools/history.jsonl` (jen na serveru, v `.gitignore`), takže se historie neztratí, ani když se log smaže nebo otočí.
Neodstraňuj `tools/history.jsonl`. Log už mazat není potřeba.

### Zařízení

`public/device.js` (načítá ho každá stránka) uloží do prohlížeče náhodné ID a při každém otevření stránky ho pošle do logu (i když se stránka vzala z mezipaměti). Pokusy v testu ho posílají také.
V Logách se zařízení jmenují „Zařízení A, B, …“ podle pořadí prvního výskytu. Pojmenování na serveru: `python3 tools/make-stats.py --name A "Meda iPhone"` (uloží se do `tools/devices.json`, není v gitu).
ID je jen náhodný řetězec v daném prohlížeči. Po vymazání dat stránek nebo v anonymním režimu vznikne nové zařízení.
