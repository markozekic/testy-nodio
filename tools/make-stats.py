#!/usr/bin/env python3
"""Z logu Caddy (JSON) udělá public/vysvedceni/data.json pro stránku Vysvědčení.

Použití:
  python3 tools/make-stats.py                     # vygeneruje data.json (bez IP adres)
  python3 tools/make-stats.py --reset TEST|all    # vynuluje body testu po vyzvednutí odměny
  python3 tools/make-stats.py --admin             # vypíše přehled včetně IP a prohlížeče (jen pro Marka)
  python3 tools/make-stats.py --log CESTA --out CESTA
"""
import argparse, glob, gzip, json, math, os, sys, time
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import urlsplit, parse_qs
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Prague")
except Exception:
    TZ = timezone.utc

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOG = "/var/log/caddy/testy.nodio.cz.log"
DEFAULT_OUT = os.path.join(HERE, "..", "public", "vysvedceni", "data.json")
TESTS_FILE = os.path.join(HERE, "..", "public", "tests.json")
RESET_FILE = os.path.join(HERE, "resets.txt")   # řádky "epoch body", poslední = poslední reset
GOAL = 100


def open_any(path):
    return gzip.open(path, "rt", encoding="utf-8", errors="replace") if path.endswith(".gz") else open(path, encoding="utf-8", errors="replace")


def read_events(log):
    base = log[:-4] if log.endswith(".log") else log   # Caddy otočené soubory se jmenují název-datum.log
    files = sorted(glob.glob(base + "*"))
    seen = set()
    for f in files:
        try:
            fh = open_any(f)
        except OSError:
            continue
        with fh:
            for line in fh:
                try:
                    d = json.loads(line)
                    req = d["request"]
                    u = urlsplit(req["uri"])
                except Exception:
                    continue
                if u.path != "/ping.gif" or d.get("status", 200) >= 400:
                    continue
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                if not q.get("s") or q.get("e") not in ("start", "ans", "end"):
                    continue
                key = (q["s"], q["e"], q.get("q", ""), q.get("r", ""))
                if key in seen:
                    continue
                seen.add(key)
                ua = (req.get("headers", {}).get("User-Agent") or [""])[0]
                ip = req.get("client_ip") or req.get("remote_ip") or ""
                yield float(d.get("ts", 0)), q, ip, ua


def num(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def build(log):
    sessions = {}
    tws = {}
    for ts, q, ip, ua in sorted(read_events(log), key=lambda x: x[0]):
        s = sessions.setdefault(q["s"], {"id": q["s"], "test": q.get("t", ""), "start": ts, "mode": "", "n": 0,
                                         "ended": False, "p": 0, "x": 0, "answers": [], "ip": ip, "ua": ua, "last": ts})
        s["last"] = ts
        if q["e"] == "start":
            s["start"] = ts; s["mode"] = q.get("mode", ""); s["n"] = num(q.get("n")); tws[s["test"]] = num(q.get("tw")) or tws.get(s["test"], 0)
        elif q["e"] == "ans":
            s["answers"].append({"ts": ts, "q": q.get("q", ""), "l": q.get("l", ""), "p": num(q.get("p")), "x": max(num(q.get("x")), 1)})
        elif q["e"] == "end":
            s["ended"] = True; s["p"] = num(q.get("p")); s["x"] = num(q.get("x")); s["mode"] = q.get("mode", s["mode"])
    return sorted(sessions.values(), key=lambda s: s["start"]), tws


def resets():
    """Seznam (epoch, test_id nebo None = všechny testy, body)."""
    out = []
    try:
        for line in open(RESET_FILE, encoding="utf-8"):
            parts = line.split()
            if not parts:
                continue
            if len(parts) >= 3:
                out.append((float(parts[0]), parts[1], parts[2]))
            else:
                out.append((float(parts[0]), None, parts[1] if len(parts) > 1 else "?"))
    except OSError:
        pass
    return out


def since_for(rs, test):
    return max([r[0] for r in rs if r[1] in (None, test)] or [0])


def points(sessions, tws, since, test):
    """Body 0..GOAL pro jeden test: každá otázka se počítá nejlepším dosaženým poměrem z dokončených testů od posledního resetu, váhou je počet dílčích bodů."""
    best, weight = {}, {}
    for s in sessions:
        if s["test"] != test or not s["ended"]:   # body jen z dokončených testů
            continue
        for a in s["answers"]:
            if a["ts"] <= since:
                continue
            weight[a["q"]] = a["x"]
            best[a["q"]] = max(best.get(a["q"], 0.0), a["p"] / a["x"])
    total = max(tws.get(test, 0), sum(weight.values()), 1)
    got = sum(best[q] * weight[q] for q in best)
    return min(GOAL, int(math.floor(GOAL * got / total + 1e-9)))


def known_tests():
    try:
        return json.load(open(TESTS_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        return []


def per_test(sessions, tws):
    """Stav každého testu z public/tests.json: body od jeho posledního resetu, počet vyzvednutých odměn."""
    rs = resets()
    out = []
    for t in known_tests():
        since = since_for(rs, t["id"])
        pts = points(sessions, tws, since, t["id"])
        out.append(dict(t, points=pts, unlocked=pts >= GOAL, rewards=sum(1 for r in rs if r[1] in (None, t["id"])),
                        since=local(since).strftime("%Y-%m-%d") if since else None))
    return out


def local(ts):
    return datetime.fromtimestamp(ts, TZ)


def public_data(sessions, tws):
    out_s, days = [], defaultdict(lambda: {"attempts": 0, "answers": 0})
    qs = defaultdict(lambda: {"l": "", "p": 0, "x": 0, "n": 0})
    for s in sessions:
        a_p = sum(a["p"] for a in s["answers"]); a_x = sum(a["x"] for a in s["answers"])
        if s["ended"]:
            p, x = s["p"], s["x"]
        else:
            p, x = a_p, a_x
        dt = local(s["start"])
        out_s.append({"test": s["test"], "date": dt.strftime("%Y-%m-%d"), "time": dt.strftime("%H:%M"), "mode": s["mode"], "n": s["n"],
                      "answered": len(s["answers"]), "done": bool(s["ended"]), "p": p, "x": x,
                      "pct": round(100 * p / x) if x else None})
        d = days[dt.strftime("%Y-%m-%d")]
        d["attempts"] += 1; d["answers"] += len(s["answers"])
        for a in s["answers"]:
            r = qs[a["q"]]; r["l"] = a["l"] or r["l"]; r["p"] += a["p"]; r["x"] += a["x"]; r["n"] += 1
    qlist = [{"q": k, "l": v["l"], "n": v["n"], "pct": round(100 * v["p"] / v["x"])} for k, v in qs.items() if v["x"]]
    qlist.sort(key=lambda r: (r["pct"], -r["n"]))
    return {"updated": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"),
            "goal": GOAL, "tests": per_test(sessions, tws),
            "sessions": out_s[::-1],
            "days": [{"date": k, **v} for k, v in sorted(days.items())],
            "questions": qlist}


def admin(sessions):
    print("%-17s %-16s %-26s %-5s %s" % ("začátek", "IP", "část", "body", "prohlížeč"))
    for s in sessions:
        pts = "%d/%d" % (s["p"], s["x"]) if s["ended"] else "%d odp." % len(s["answers"])
        print("%-17s %-16s %-26s %-9s %s" % (local(s["start"]).strftime("%Y-%m-%d %H:%M"), s["ip"], s["mode"], pts, s["ua"][:70]))
    ips = defaultdict(int)
    for s in sessions:
        ips[s["ip"]] += 1
    print("\nPočet pokusů podle IP:", dict(ips))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=DEFAULT_LOG)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--admin", action="store_true")
    ap.add_argument("--reset", metavar="TEST", help="vynuluje body jednoho testu (id nebo začátek id) nebo 'all'; historie pokusů zůstane")
    a = ap.parse_args()
    sessions, tws = build(a.log)
    if a.reset:
        tests = per_test(sessions, tws)
        ids = [t["id"] for t in tests]
        if a.reset == "all":
            targets = ids
        else:
            targets = [i for i in ids if i == a.reset] or [i for i in ids if i.startswith(a.reset)]
            if len(targets) != 1:
                sys.exit("Zadej přesně jeden test nebo 'all'. Dostupné: " + ", ".join(ids))
        with open(RESET_FILE, "a", encoding="utf-8") as f:
            for t in tests:
                if t["id"] in targets:
                    f.write("%f %s %d\n" % (time.time(), t["id"], t["points"]))
                    print("Reset testu %s (body před resetem: %d)." % (t["id"], t["points"]))
    elif a.admin:
        for t in per_test(sessions, tws):
            print("%s: %d / %d (vyzvednutých odměn: %d)" % (t["id"], t["points"], GOAL, t["rewards"]))
        print()
        admin(sessions); return
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    tmp = a.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(public_data(sessions, tws), f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, a.out)
    print("OK:", len(sessions), "pokusů ->", a.out)


if __name__ == "__main__":
    main()
