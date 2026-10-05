# testy.nodio.cz

Studijní testy pro Medu. Web je statický, obsah je ve složce `public/`.

- `public/index.html` – seznam testů
- `public/<nazev-testu>/index.html` – jeden test (samostatný HTML soubor)
- `deploy/` – nastavení VPS (Caddy nebo nginx, jednorázový skript)

Nový test: přidej složku do `public/` a odkaz do `public/index.html`. Po pushi se změna do minuty objeví na webu.
Přístup chrání webserver (Basic Auth), stránky mají `noindex`.
