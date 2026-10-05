#!/usr/bin/env bash
# Sleduje log Caddy a po každém dokončeném testu (událost e=end) hned přepočítá Vysvědčení.
# Běží jako systemd služba (viz deploy/testy-stats.service).
LOG="${LOG:-/var/log/caddy/testy.nodio.cz.log}"
DIR="$(dirname "$(readlink -f "$0")")"
tail -n0 -F "$LOG" 2>/dev/null | grep --line-buffered -F '&e=end&' | while read -r _; do
  sleep 1
  python3 "$DIR/make-stats.py" ${STATS_ARGS:-} >/dev/null 2>&1
done
