#!/usr/bin/env python3
"""Z logu Caddy (JSON) udělá public/vysvedceni/data.json (Vysvědčení) a public/logy/data.json (Logy).
Nové události z logu se při každém spuštění připíšou do tools/history.jsonl, takže se historie neztratí,
ani když se log smaže nebo otočí.

Použití:
  python3 tools/make-stats.py                     # vygeneruje data.json (bez IP adres)
  python3 tools/make-stats.py --reset TEST|all    # vynuluje body testu po vyzvednutí odměny
  python3 tools/make-stats.py --name A Meda       # pojmenuje zařízení A z Logů
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
HISTORY_FILE = os.path.join(HERE, "history.jsonl")   # trvalá historie událostí z logu (jen na serveru)
LOGY_OUT = os.path.join(HERE, "..", "public", "logy", "data.json")
DEVICES_FILE = os.path.join(HERE, "devices.json")   # {"id zařízení": "jméno"} (volitelné, ručně přes --name)
RESET_FILE = os.path.join(HERE, "resets.txt")   # řádky "epoch body", poslední = poslední reset
GOAL = 100


def open_any(path):
    return gzip.open(path, "rt", encoding="utf-8", errors="replace") if path.endswith(".gz") else open(path, encoding="utf-8", errors="replace")


def page_path(path):
    """Cesty stránek, které se ukazují v Logách (ne data a obrázky)."""
    return path == "/" or (path.endswith("/") and path.count("/") == 2)


def ingest(log):
    """Připíše nové události z logu do trvalé historie a vrátí všechny události seřazené podle času."""
    have, events = set(), []
    try:
        with open(HISTORY_FILE, encoding="utf-8") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                events.append(e)
                have.add((e["ts"], e["ip"], e["u"]))
    except OSError:
        pass
    base = log[:-4] if log.endswith(".log") else log   # Caddy otočené soubory se jmenují název-datum.log
    fresh = []
    for f in sorted(glob.glob(base + "*")):
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
                    ts = round(float(d["ts"]), 3)
                except Exception:
                    continue
                if d.get("status", 200) >= 400 or req.get("method", "GET") != "GET":
                    continue
                if u.path != "/ping.gif" and not page_path(u.path):
                    continue
                ip = req.get("client_ip") or req.get("remote_ip") or ""
                key = (ts, ip, req["uri"])
                if key in have:
                    continue
                have.add(key)
                ua = (req.get("headers", {}).get("User-Agent") or [""])[0]
                e = {"ts": ts, "ip": ip, "ua": ua, "u": req["uri"]}
                fresh.append(e); events.append(e)
    if fresh:
        try:
            with open(HISTORY_FILE, "a", encoding="utf-8") as fh:
                for e in fresh:
                    fh.write(json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError as ex:
            print("Upozornění: historii nelze zapsat:", ex, file=sys.stderr)
    events.sort(key=lambda e: e["ts"])
    return events


def read_events(log):
    seen = set()
    for e in ingest(log):
        u = urlsplit(e["u"])
        if u.path != "/ping.gif":
            continue
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if not q.get("s") or q.get("e") not in ("start", "ans", "end"):
            continue
        key = (q["s"], q["e"], q.get("q", ""), q.get("r", ""))
        if key in seen:
            continue
        seen.add(key)
        yield e["ts"], q, e["ip"], e["ua"]


def page_views(log):
    """Otevření stránek: záznamy z device.js (mají ID zařízení, fungují i ze mezipaměti) a jako záloha
    požadavky na samotnou stránku (zahodí se, pokud k nim existuje záznam z device.js)."""
    events = ingest(log)
    beacons, gets = [], []
    for e in events:
        u = urlsplit(e["u"])
        if u.path == "/ping.gif":
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if q.get("e") == "view" and page_path(q.get("p", "")):
                beacons.append({"ts": e["ts"], "ip": e["ip"], "ua": e["ua"], "path": q["p"], "did": q.get("d", "")})
        elif page_path(u.path):
            gets.append({"ts": e["ts"], "ip": e["ip"], "ua": e["ua"], "path": u.path, "did": ""})
    out = list(beacons)
    for g in gets:
        if not any(b["ip"] == g["ip"] and b["path"] == g["path"] and abs(b["ts"] - g["ts"]) <= 15 for b in beacons):
            out.append(g)
    return out


def device_labels(sessions, views):
    """Štítky zařízení podle pořadí prvního výskytu (A, B, ...), případně jméno z devices.json."""
    first = {}
    for e in views:
        if e["did"]:
            first[e["did"]] = min(first.get(e["did"], e["ts"]), e["ts"])
    for s in sessions:
        if s.get("did"):
            first[s["did"]] = min(first.get(s["did"], s["start"]), s["start"])
    try:
        names = json.load(open(DEVICES_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        names = {}
    labels = {}
    for n, did in enumerate(sorted(first, key=lambda d: first[d])):
        letter = ""
        k = n
        while True:
            letter = chr(65 + k % 26) + letter
            k = k // 26 - 1
            if k < 0:
                break
        labels[did] = (names.get(did) or "Zařízení " + letter, letter)
    return labels


def device(ua):
    """Zařízení a prohlížeč z User-Agent (jen hrubě)."""
    u = ua or ""
    dev = ("iPhone" if "iPhone" in u else "iPad" if "iPad" in u else "Android" if "Android" in u else
           "Mac" if "Macintosh" in u else "Windows" if "Windows" in u else "Linux" if "Linux" in u else "?")
    br = ("Edge" if "Edg/" in u else "Firefox" if "Firefox" in u or "FxiOS" in u else "Chrome" if "Chrome" in u or "CriOS" in u
          else "Safari" if "Safari" in u else "")
    return dev + (" · " + br if br else "")


def mask_ip(ip):
    if ":" in ip:
        return ":".join(ip.split(":")[:3]) + "::"
    parts = ip.split(".")
    return ".".join(parts[:3] + ["•"]) if len(parts) == 4 else ip


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
                                         "ended": False, "p": 0, "x": 0, "answers": [], "ip": ip, "ua": ua, "last": ts, "did": q.get("d", "")})
        s["last"] = ts
        if q.get("d") and not s.get("did"):
            s["did"] = q["d"]
        if q["e"] == "start":
            s["start"] = ts; s["mode"] = q.get("mode", ""); s["n"] = num(q.get("n")); tws[s["test"]] = num(q.get("tw")) or tws.get(s["test"], 0)
        elif q["e"] == "ans":
            s["answers"].append({"ts": ts, "q": q.get("q", ""), "l": q.get("l", ""), "p": num(q.get("p")), "x": max(num(q.get("x")), 1)})
        elif q["e"] == "end":
            s["ended"] = True; s["end_ts"] = ts; s["p"] = num(q.get("p")); s["x"] = num(q.get("x")); s["mode"] = q.get("mode", s["mode"])
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


def logs_data(sessions, views, limit=300):
    """Události pro stránku Logy: otevření stránek, spuštění a dokončení testů (IP s maskovanou poslední částí)."""
    labels = device_labels(sessions, views)
    rows = []
    for e in views:
        rows.append({"ts": e["ts"], "e": "page", "path": e["path"], "dev": device(e["ua"]), "ip": mask_ip(e["ip"]),
                     "who": labels.get(e["did"], ("", ""))[0]})
    for s in sessions:
        base = {"dev": device(s["ua"]), "ip": mask_ip(s["ip"]), "test": s["test"], "mode": s["mode"],
                "who": labels.get(s.get("did", ""), ("", ""))[0]}
        rows.append(dict(base, ts=s["start"], e="start", n=s["n"], answered=len(s["answers"]), done=bool(s["ended"])))
        if s["ended"]:
            rows.append(dict(base, ts=s.get("end_ts", s["last"]), e="end", p=s["p"], x=s["x"]))
    rows.sort(key=lambda r: -r["ts"])
    for r in rows:
        dt = local(r["ts"]); r["date"] = dt.strftime("%Y-%m-%d"); r["time"] = dt.strftime("%H:%M:%S"); del r["ts"]
    return {"updated": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"), "devices": len(labels), "rows": rows[:limit], "total": len(rows)}


def name_device(sessions, views, key, name):
    labels = device_labels(sessions, views)
    match = [d for d, (lab, letter) in labels.items() if key in (d, letter, lab)]
    if len(match) != 1:
        sys.exit("Zařízení '%s' nenalezeno. Dostupná: %s" % (key, ", ".join("%s (%s)" % (l[1], d) for d, l in labels.items()) or "žádná"))
    try:
        names = json.load(open(DEVICES_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        names = {}
    names[match[0]] = name
    json.dump(names, open(DEVICES_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("Zařízení %s se teď jmenuje: %s" % (match[0], name))


def admin(sessions, labels=None):
    labels = labels or {}
    print("%-17s %-16s %-14s %-12s %-9s %s" % ("začátek", "IP", "zařízení", "část", "body", "prohlížeč"))
    for s in sessions:
        pts = "%d/%d" % (s["p"], s["x"]) if s["ended"] else "%d odp." % len(s["answers"])
        print("%-17s %-16s %-14s %-12s %-9s %s" % (local(s["start"]).strftime("%Y-%m-%d %H:%M"), s["ip"], labels.get(s.get("did", ""), ("-", ""))[0][:14], s["mode"], pts, s["ua"][:50]))
    ips = defaultdict(int)
    for s in sessions:
        ips[s["ip"]] += 1
    print("\nPočet pokusů podle IP:", dict(ips))


def main():
    global HISTORY_FILE, LOGY_OUT, RESET_FILE, DEVICES_FILE
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=DEFAULT_LOG)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--admin", action="store_true")
    ap.add_argument("--name", nargs=2, metavar=("ZAŘÍZENÍ", "JMÉNO"), help="pojmenuje zařízení (písmeno z Logů, např. A, nebo jeho ID)")
    ap.add_argument("--devices", default=DEVICES_FILE, help=argparse.SUPPRESS)
    ap.add_argument("--history", default=HISTORY_FILE, help=argparse.SUPPRESS)
    ap.add_argument("--logy-out", default=LOGY_OUT, help=argparse.SUPPRESS)
    ap.add_argument("--resets", default=RESET_FILE, help=argparse.SUPPRESS)
    ap.add_argument("--reset", metavar="TEST", help="vynuluje body jednoho testu (id nebo začátek id) nebo 'all'; historie pokusů zůstane")
    a = ap.parse_args()
    HISTORY_FILE, LOGY_OUT, RESET_FILE, DEVICES_FILE = a.history, a.logy_out, a.resets, a.devices
    sessions, tws = build(a.log)
    if a.name:
        name_device(sessions, page_views(a.log), a.name[0], a.name[1])
    elif a.reset:
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
        admin(sessions, device_labels(sessions, page_views(a.log))); return
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    tmp = a.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(public_data(sessions, tws), f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, a.out)
    os.makedirs(os.path.dirname(os.path.abspath(LOGY_OUT)), exist_ok=True)
    with open(LOGY_OUT + ".tmp", "w", encoding="utf-8") as f:
        json.dump(logs_data(sessions, page_views(a.log)), f, ensure_ascii=False, separators=(",", ":"))
    os.replace(LOGY_OUT + ".tmp", LOGY_OUT)
    print("OK:", len(sessions), "pokusů ->", a.out)


if __name__ == "__main__":
    main()
