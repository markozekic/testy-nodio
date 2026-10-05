#!/usr/bin/env python3
"""Z logu Caddy (JSON) udělá public/vysvedceni/data.json pro stránku Vysvědčení.

Použití:
  python3 tools/make-stats.py                     # vygeneruje data.json (bez IP adres)
  python3 tools/make-stats.py --admin             # vypíše přehled včetně IP a prohlížeče (jen pro Marka)
  python3 tools/make-stats.py --log CESTA --out CESTA
"""
import argparse, glob, gzip, json, os, sys
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
    for ts, q, ip, ua in sorted(read_events(log), key=lambda x: x[0]):
        s = sessions.setdefault(q["s"], {"id": q["s"], "test": q.get("t", ""), "start": ts, "mode": "", "n": 0,
                                         "ended": False, "p": 0, "x": 0, "answers": [], "ip": ip, "ua": ua, "last": ts})
        s["last"] = ts
        if q["e"] == "start":
            s["start"] = ts; s["mode"] = q.get("mode", ""); s["n"] = num(q.get("n"))
        elif q["e"] == "ans":
            s["answers"].append({"q": q.get("q", ""), "l": q.get("l", ""), "p": num(q.get("p")), "x": max(num(q.get("x")), 1)})
        elif q["e"] == "end":
            s["ended"] = True; s["p"] = num(q.get("p")); s["x"] = num(q.get("x")); s["mode"] = q.get("mode", s["mode"])
    return sorted(sessions.values(), key=lambda s: s["start"])


def local(ts):
    return datetime.fromtimestamp(ts, TZ)


def public_data(sessions):
    out_s, days = [], defaultdict(lambda: {"attempts": 0, "answers": 0})
    qs = defaultdict(lambda: {"l": "", "p": 0, "x": 0, "n": 0})
    for s in sessions:
        a_p = sum(a["p"] for a in s["answers"]); a_x = sum(a["x"] for a in s["answers"])
        if s["ended"]:
            p, x = s["p"], s["x"]
        else:
            p, x = a_p, a_x
        dt = local(s["start"])
        out_s.append({"date": dt.strftime("%Y-%m-%d"), "time": dt.strftime("%H:%M"), "mode": s["mode"], "n": s["n"],
                      "answered": len(s["answers"]), "done": bool(s["ended"]), "p": p, "x": x,
                      "pct": round(100 * p / x) if x else None})
        d = days[dt.strftime("%Y-%m-%d")]
        d["attempts"] += 1; d["answers"] += len(s["answers"])
        for a in s["answers"]:
            r = qs[a["q"]]; r["l"] = a["l"] or r["l"]; r["p"] += a["p"]; r["x"] += a["x"]; r["n"] += 1
    qlist = [{"q": k, "l": v["l"], "n": v["n"], "pct": round(100 * v["p"] / v["x"])} for k, v in qs.items() if v["x"]]
    qlist.sort(key=lambda r: (r["pct"], -r["n"]))
    return {"updated": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"),
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
    a = ap.parse_args()
    sessions = build(a.log)
    if a.admin:
        admin(sessions); return
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    tmp = a.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(public_data(sessions), f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, a.out)
    print("OK:", len(sessions), "pokusů ->", a.out)


if __name__ == "__main__":
    main()
