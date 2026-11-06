#!/usr/bin/env python3
"""Entry Timer for crypto-entry: watches a setup bar by bar and says the
moment to get in. Standard library only. Long AND short. It never places an order.

Crypto take on trader-entry from Jakeschincariol/day-trader-skill (MIT, see
LICENSE-day-trader-skill): same rules, both directions, sessions tied to the
London and Wall Street opens, 24/7.

    python3 entry.py check ETH                           # orb on today's Wall Street open, either side
    python3 entry.py check ETH --session europa --side short
    python3 entry.py check SOL --setup level --level 92.5 --side long
    python3 entry.py check ETH --now "2026-11-05 15:00" --write
    python3 entry.py watch ETH --side short              # one line per closed bar, stops on a trigger

Setups:
  orb    opening-range break. The range is the high and low of the first
         --or-minutes (15) of the session. It triggers on the first COMPLETED
         5-minute bar after the range that CLOSES above the range high (long)
         or below the range low (short). A wick through it is not a trigger.
  level  the first completed bar of the session that closes above --level
         (long) or below it (short).

Sessions (each day's own daylight-time offsets, printed in UTC):
  wallstreet   opens 09:30 New York (14:30 UTC in northern winter)
  europa       opens 08:00 London   (08:00 UTC in winter)

A trigger's time is the trigger bar's CLOSE time (the 14:50 bar closes at
14:55) and its price is that close. A bar counts only once it has closed.
Entries stop --expire-hours (6) after the open: later than that, an
opening-range break is old news.

Statuses: triggered, waiting (not open yet, range still forming, or no close
through the level yet), expired, no-data.

Data: Yahoo's free chart JSON (query2.finance.yahoo.com, query1 as fallback),
5-minute bars. Exit codes: check 0 = triggered, 1 otherwise; watch 0 on a
trigger, 1 otherwise.
"""

import argparse
import datetime
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; crypto-entry/1.0)"
HOSTS = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")
BACKOFF = 10.0
GRACE = 5         # seconds after a bar closes before watch asks for it
SETTLE = 90       # seconds a closed bar may wait for Yahoo to post it
BAR = 300
SESSIONS = {"wallstreet": ("ny", 9 * 60 + 30), "europa": ("london", 8 * 60)}
EPOCH = datetime.datetime(1970, 1, 1)


class EntryError(Exception):
    pass


# ---------------------------------------------------------------- time

def _nth_sunday(year, month, n):
    d = datetime.date(year, month, 1)
    d += datetime.timedelta(days=(6 - d.weekday()) % 7)
    return d + datetime.timedelta(weeks=n - 1)


def _last_sunday(year, month):
    d = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
    return d - datetime.timedelta(days=(d.weekday() + 1) % 7)


def utc_offset_hours(market, day):
    if market == "ny":
        return -4 if _nth_sunday(day.year, 3, 2) <= day < _nth_sunday(day.year, 11, 1) else -5
    if market == "london":
        return 1 if _last_sunday(day.year, 3) <= day < _last_sunday(day.year, 10) else 0
    return 0


def session_open(session, day):
    """The session's open on that UTC day, as a naive UTC datetime."""
    market, local = SESSIONS[session]
    mins = local - 60 * utc_offset_hours(market, day)
    return datetime.datetime.combine(day, datetime.time()) + datetime.timedelta(minutes=mins)


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None, microsecond=0)


def parse_now(text):
    if not text:
        return utc_now()
    try:
        dt = datetime.datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        raise EntryError('--now wants a UTC time like "2026-11-05 15:00"')
    return dt if dt.tzinfo is None else (dt - dt.utcoffset()).replace(tzinfo=None)


def ts_of(dt):
    return int((dt - EPOCH).total_seconds())


def hm(dt):
    return dt.strftime("%H:%M")


# ---------------------------------------------------------------- prices

def tick(price):
    return 10.0 ** (math.floor(math.log10(price)) - 4) if price > 0 else 0.01


def rnd(x):
    t = tick(abs(x) or 1)
    return round(round(x / t) * t, 10)


# Yahoo lists some coins under a numbered pair. crypto-scanner's trader/universe.json
# has the full map; these are the ones it found among the most traded.
YAHOO_PAIRS = {"HYPE": "HYPE32196-USD", "UNI": "UNI7083-USD", "SUI": "SUI20947-USD",
               "PEPE": "PEPE24478-USD", "TRUMP": "TRUMP35336-USD"}


def yahoo_symbol(sym):
    """BTC -> BTC-USD; BTCUSDT -> BTC-USD; UNI -> UNI7083-USD; ETH-USD stays."""
    s = sym.strip().upper().replace("/", "-")
    if s.endswith("USDT") and "-" not in s:
        s = s[:-4]
    if s.endswith("-USD"):
        base = s[:-4]
    elif "-" in s:
        return s
    else:
        base = s
    try:
        with open(os.path.join("trader", "universe.json"), encoding="utf-8") as fh:
            for c in json.load(fh).get("coins", []):
                if c.get("sym") == base and c.get("yahoo"):
                    return c["yahoo"]
    except (OSError, ValueError, AttributeError):
        pass
    return YAHOO_PAIRS.get(base, base + "-USD")


def http_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def fetch_bars(sym, offline=None):
    """5-minute bars of the last 2 days: [{t, o, h, l, c}], oldest first."""
    if offline:
        doc = json.load(open(offline, encoding="utf-8"))
    else:
        path = "/v8/finance/chart/%s?range=2d&interval=5m" % urllib.parse.quote(sym)
        doc, last = None, None
        for host in HOSTS:
            for attempt in (0, 1):
                try:
                    doc = http_json(host + path)
                    break
                except urllib.error.HTTPError as e:
                    last = e.code
                    if e.code == 429 and attempt == 0:
                        time.sleep(BACKOFF)
                        continue
                    if e.code == 404:
                        raise EntryError("Yahoo has no chart for %s: check the symbol" % sym)
                    break
                except (urllib.error.URLError, OSError) as e:
                    raise EntryError("could not reach Yahoo (is query2.finance.yahoo.com allowed?): %s" % e)
            if doc:
                break
        if not doc:
            raise EntryError("Yahoo answered HTTP %s on both hosts; try again in a minute" % last)
    res = ((doc.get("chart") or {}).get("result") or [None])[0]
    if not res:
        raise EntryError("Yahoo has no data for %s" % sym)
    q = (res.get("indicators") or {}).get("quote", [{}])[0]
    bars = []
    for i, ts in enumerate(res.get("timestamp") or []):
        row = [(q.get(k) or [None] * (i + 1))[i] if i < len(q.get(k) or []) else None
               for k in ("open", "high", "low", "close")]
        if ts is None or None in row or int(ts) % BAR:
            continue
        bars.append({"t": int(ts), "o": row[0], "h": row[1], "l": row[2], "c": row[3]})
    return bars


# ---------------------------------------------------------------- the rule

def evaluate(bars, now, session="wallstreet", setup="orb", side="both", or_minutes=15, level=None,
             expire_hours=6.0, day=None):
    """-> dict with status, phase, the range, the trigger (if any) and the bars so far."""
    day = day or now.date()
    opn = session_open(session, day)
    rng_end = opn + datetime.timedelta(minutes=or_minutes)
    expires = opn + datetime.timedelta(hours=expire_hours)
    done = [b for b in bars if b["t"] >= ts_of(opn) and b["t"] + BAR <= ts_of(min(now, expires))]
    res = {"session": session, "date": day.isoformat(), "open_utc": hm(opn), "setup": setup, "side": side,
           "or_minutes": or_minutes, "range_ends_utc": hm(rng_end), "expires_utc": hm(expires),
           "level": level, "or_high": None, "or_low": None, "bars": done, "trigger": None,
           "last": done[-1]["c"] if done else None}
    if now < opn:
        res.update(status="waiting", phase="pre-open")
        return res
    if not done:
        res.update(status="no-data" if now >= rng_end else "waiting",
                   phase="forming" if now < rng_end else "no-bars")
        return res
    n = or_minutes // 5
    if setup == "orb":
        rbars = [b for b in done if b["t"] < ts_of(rng_end)]
        if now < rng_end or len(rbars) < n:
            if now >= rng_end + datetime.timedelta(minutes=10) and len(rbars) < n:
                res.update(status="no-data", phase="gap")
                return res
            res.update(status="waiting", phase="forming")
            return res
        res["or_high"], res["or_low"] = max(b["h"] for b in rbars), min(b["l"] for b in rbars)
        up_lvl, down_lvl = res["or_high"], res["or_low"]
        after = [b for b in done if b["t"] >= ts_of(rng_end)]
    else:
        up_lvl = down_lvl = level
        after = done
    for b in after:
        close_at = EPOCH + datetime.timedelta(seconds=b["t"] + BAR)
        if side in ("both", "long") and b["c"] > up_lvl:
            res.update(status="triggered", phase="triggered",
                       trigger={"side": "long", "time": hm(close_at), "price": rnd(b["c"]), "level": up_lvl})
            return res
        if side in ("both", "short") and b["c"] < down_lvl:
            res.update(status="triggered", phase="triggered",
                       trigger={"side": "short", "time": hm(close_at), "price": rnd(b["c"]), "level": down_lvl})
            return res
    if now >= expires:
        res.update(status="expired", phase="expired")
    else:
        res.update(status="waiting", phase="watching")
    return res


def entry_doc(sym, res, now):
    t = res["trigger"] or {}
    return {
        "created_by": "crypto-entry", "created_at": now.isoformat() + "Z", "symbol": sym,
        "status": res["status"], "session": res["session"], "date": res["date"], "open_utc": res["open_utc"],
        "setup": res["setup"], "opening_range": {"minutes": res["or_minutes"], "high": res["or_high"],
                                                 "low": res["or_low"]},
        "level": res["level"], "side": {"long": "buy", "short": "sell"}.get(t.get("side")),
        "entry": t.get("price"), "entry_time": t.get("time"), "interval": "5m",
    }


def describe(sym, res):
    p = res
    head = "%s  %s %s, sesión %s (abre %s UTC)" % (sym, p["setup"].upper(), p["date"], p["session"], p["open_utc"])
    lines = [head]
    if p["setup"] == "orb" and p["or_high"] is not None:
        lines.append("  Rango de apertura (%d min, hasta %s UTC): máximo %g, mínimo %g"
                     % (p["or_minutes"], p["range_ends_utc"], p["or_high"], p["or_low"]))
    elif p["setup"] == "level":
        lines.append("  Nivel: %g" % p["level"])
    st = p["status"]
    if st == "triggered":
        t = p["trigger"]
        lines.append("  DISPARÓ %s: la vela que cerró a las %s UTC cerró en %g, %s de %g."
                     % ("LARGO" if t["side"] == "long" else "CORTO", t["time"], t["price"],
                        "encima" if t["side"] == "long" else "debajo", t["level"]))
        lines.append("  Siguiente: /crypto-exit arma el stop y el objetivo antes de entrar.")
    elif p["phase"] == "pre-open":
        lines.append("  ESPERANDO: la sesión todavía no abrió.")
    elif p["phase"] == "forming":
        lines.append("  ESPERANDO: el rango se está formando hasta las %s UTC." % p["range_ends_utc"])
    elif st == "waiting":
        lines.append("  ESPERANDO: ninguna vela cerró afuera todavía. Último cierre %g. Vence %s UTC."
                     % (p["last"], p["expires_utc"]))
    elif st == "expired":
        lines.append("  VENCIDO: no disparó antes de las %s UTC. No hay entrada hoy para esta regla." % p["expires_utc"])
    else:
        lines.append("  SIN DATOS: Yahoo no tiene las velas de la sesión (o falta alguna del rango).")
    return lines


# ---------------------------------------------------------------- commands

def write_json(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
        fh.write("\n")


def _eval(a, now, bars):
    return evaluate(bars, now, a.session, a.setup, a.side, a.or_minutes, a.level, a.expire_hours,
                    datetime.date.fromisoformat(a.date) if a.date else None)


def _check_args(a):
    if a.setup == "level" and a.level is None:
        raise EntryError("--setup level needs --level PRICE")
    if a.setup == "level" and a.side == "both":
        raise EntryError("--setup level needs --side long (close above) or --side short (close below)")
    if a.or_minutes % 5 or a.or_minutes < 5:
        raise EntryError("--or-minutes must be a multiple of 5")


def cmd_check(a):
    _check_args(a)
    sym = yahoo_symbol(a.symbol)
    now = parse_now(a.now)
    res = _eval(a, now, fetch_bars(sym, a.offline))
    print("\n".join(describe(sym, res)))
    if a.write:
        write_json(a.write, entry_doc(sym, res, now))
        print("  Escribí %s." % a.write)
    return 0 if res["status"] == "triggered" else 1


def cmd_watch(a):
    """One line per closed bar until a trigger, expiry or --max-hours."""
    _check_args(a)
    sym = yahoo_symbol(a.symbol)
    stop_at = utc_now() + datetime.timedelta(hours=a.max_hours)
    seen, errors = None, 0
    print("Vigilando %s (%s, %s, lado %s). Una línea por vela cerrada." % (sym, a.setup, a.session, a.side),
          flush=True)
    while utc_now() < stop_at:
        now = utc_now()
        try:
            res = _eval(a, now, fetch_bars(sym))
            errors = 0
        except EntryError as e:
            errors += 1
            if errors >= 5:
                print("Corto: 5 errores seguidos (%s)." % e, flush=True)
                return 1
            time.sleep(60)
            continue
        last_t = res["bars"][-1]["t"] if res["bars"] else None
        if last_t != seen and res["bars"]:
            seen = last_t
            b = res["bars"][-1]
            close_at = EPOCH + datetime.timedelta(seconds=b["t"] + BAR)
            extra = ""
            if res["or_high"] is not None:
                extra = "  rango %g-%g" % (res["or_low"], res["or_high"])
            print("%s UTC  cierre %g%s  -> %s" % (hm(close_at), b["c"], extra, res["status"]), flush=True)
        if res["status"] in ("triggered", "expired"):
            print("\n".join(describe(sym, res)), flush=True)
            if res["status"] == "triggered":
                write_json(a.write or "trader/entry.json", entry_doc(sym, res, now))
                return 0
            return 1
        # sleep to just after the next bar closes
        nxt = (ts_of(now) // BAR + 1) * BAR + GRACE
        time.sleep(max(5, min(SETTLE, nxt - ts_of(now))))
    print("Corto: pasaron %g horas sin disparo." % a.max_hours, flush=True)
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Entry Timer for crypto (crypto-entry).")
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("symbol", help="ETH, BTC-USD, SOLUSDT ...")
        p.add_argument("--session", default="wallstreet", choices=sorted(SESSIONS))
        p.add_argument("--setup", default="orb", choices=["orb", "level"])
        p.add_argument("--side", default="both", choices=["both", "long", "short"])
        p.add_argument("--or-minutes", type=int, default=15)
        p.add_argument("--level", type=float)
        p.add_argument("--expire-hours", type=float, default=6.0)
        p.add_argument("--date", help="the session's UTC date (default today)")

    p = sub.add_parser("check", help="where the setup stands right now")
    common(p)
    p.add_argument("--now", help='pretend it is this UTC time, e.g. "2026-11-05 15:00"')
    p.add_argument("--offline", help="a saved Yahoo chart JSON")
    p.add_argument("--write", nargs="?", const="trader/entry.json")
    p = sub.add_parser("watch", help="bar by bar until it triggers (run under a monitor)")
    common(p)
    p.add_argument("--max-hours", type=float, default=7.0)
    p.add_argument("--write", default=None)
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"check": cmd_check, "watch": cmd_watch}[a.cmd](a)
    except EntryError as e:
        print("entry.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
