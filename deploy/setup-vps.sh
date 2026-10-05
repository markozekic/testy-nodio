#!/usr/bin/env bash
# Jednorázové nastavení na VPS. Po něm se každá změna v GitHub repozitáři
# objeví na https://testy.nodio.cz do minuty (VPS si změny stahuje sám).
#
# Použití (na VPS, jako uživatel s sudo):
#   REPO=git@github.com:<UZIVATEL>/testy-nodio.git bash setup-vps.sh
set -euo pipefail
: "${REPO:?Nastav REPO, např. REPO=git@github.com:uzivatel/testy-nodio.git}"
SITE=/var/www/testy.nodio.cz
KEY="$HOME/.ssh/testy-nodio-deploy"

# 1) Deploy klíč jen pro čtení tohoto repozitáře
if [ ! -f "$KEY" ]; then
  ssh-keygen -t ed25519 -N "" -f "$KEY" -C "testy.nodio.cz deploy"
  echo
  echo ">>> Přidej tento veřejný klíč v GitHubu: repozitář > Settings > Deploy keys (bez write přístupu):"
  cat "$KEY.pub"
  echo
  read -r -p "Až klíč přidáš, stiskni Enter... " _
fi
export GIT_SSH_COMMAND="ssh -i $KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

# 2) Klon repozitáře
sudo mkdir -p "$SITE" && sudo chown "$USER" "$SITE"
[ -d "$SITE/.git" ] || git clone "$REPO" "$SITE"

# 3) Stahování změn každou minutu
CRON="* * * * * GIT_SSH_COMMAND='ssh -i $KEY -o IdentitiesOnly=yes' git -C $SITE pull --ff-only -q >/dev/null 2>&1"
( crontab -l 2>/dev/null | grep -v "$SITE" ; echo "$CRON" ) | crontab -

echo "Hotovo. Teď přidej blok z deploy/Caddyfile.snippet (nebo nginx.conf.snippet) a reloadni webserver."
