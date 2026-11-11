#!/usr/bin/env python3
"""Entry Timer for scalp-entry: watches a 1-minute setup candle by candle and says
the moment to get in. Standard library only. Long AND short. It never places an order.

Scalping take on crypto-entry (skill-cryptos-jeto1337), itself built on trader-entry
from Jakeschincariol/day-trader-skill (MIT, see LICENSE-day-trader-skill).

    python3 entry.py check BTC                           # 5-minute opening range, Wall Street, 2 closes
    python3 entry.py check ETH --session europa --side short
    python3 entry.py check SOL --setup level --level 92.5 --side long
    python3 entry.py check BTC --now "2026-11-05 14:50" --write
    python3 entry.py watch BTC                           # one line per closed 1-minute candle

Setups:
  orb    opening-range break on 1-minute candles. The range is the high and low
         of the first --or-minutes (5) of the session. It triggers when --confirm
         (2) completed 1-minute candles IN A ROW close above the range high (long)
         or below the range low (short). A wick through it is not a trigger.
  level  --confirm closes in a row above --level (long) or below it (short).

Sessions (each day's own daylight-time offsets, printed in UTC):
  wallstreet   opens 09:30 New York (14:30 UTC in northern winter)
  europa       opens 08:00 London   (08:00 UTC in winter)
  utc          a free session: --open HH:MM (UTC) is its start, for practising at any
               hour. Away from the opens crypto moves less: on weekends about a third.
               It can cross UTC midnight (21:00 in Argentina): after midnight the same
               --open still means the session that started the evening before, until
               it expires. entry.json carries the full times (open_at, entry_at).

Scalping only makes sense while volume is high: entries stop --expire-hours (2)
after the open. A trigger's time is the CLOSE time of its candle (the 14:36
candle closes at 14:37) and its price is that close.

What the data showed (4 weeks of 1-minute candles, 5 coins, both opens, Binance
fees): no scalping configuration made money after fees in both halves of the
sample. This skill times an entry; it does not make one profitable.

Data: Binance's public candles first (data-api.binance.vision: the exchange's own prices),
then Yahoo's free chart JSON (query2.finance.yahoo.com, query1) when Binance does not list
the coin or does not answer; --source binance|yahoo picks one.
1-minute candles. Exit codes: check 0 = triggered, 1 otherwise; watch 0 on a
trigger, 1 otherwise.
"""

import argparse
import concurrent.futures
import datetime
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; scalp-entry/1.0)"
HOSTS = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")
BACKOFF = 10.0
GRACE = 3         # seconds after a candle closes before watch asks for it
SETTLE = 30       # seconds a closed candle may wait for Yahoo to post it
BAR = 60
SESSIONS = {"wallstreet": ("ny", 9 * 60 + 30), "europa": ("london", 8 * 60), "utc": ("utc", None)}
UTC_OPEN = None   # minutes after UTC midnight, from --open, for --session utc
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
    if market == "utc":
        if UTC_OPEN is None:
            raise EntryError("--session utc needs --open HH:MM (UTC)")
        local = UTC_OPEN
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


def stamp(dt):
    """Full UTC time, for the files the next skills read: a session can cross UTC midnight."""
    return dt.strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------- prices

def tick(price):
    return 10.0 ** (math.floor(math.log10(price)) - 4) if price > 0 else 0.01


def rnd(x):
    t = tick(abs(x) or 1)
    return round(round(x / t) * t, 10)


# Yahoo lists some coins under a numbered pair. scalp-scanner's trader/universe.json
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


# ---------------------------------------------------------------- price sources
# Candles come from Binance first (the exchange itself: its own prices and real volume),
# then from Yahoo. Binance's answer is turned into the shape of Yahoo's chart JSON, which
# is what the rest of this script reads. --source picks one; SOURCE_USED says who answered.
BINANCE_HOSTS = ("https://data-api.binance.vision", "https://api.binance.com")
BINANCE_MAX = 1000                  # candles per request
BINANCE_STEP = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400}
SOURCE = "auto"                     # auto (Binance, then Yahoo) | binance | yahoo
SOURCE_USED = None


def binance_pair(sym):
    """BTC-USD -> BTCUSDT, UNI7083-USD -> UNIUSDT (Yahoo's number is not part of the ticker).
    None for anything that is not a coin priced in USD. trader/universe.json can name the
    pair, or say null when the scanner found that Binance's ticker is another coin."""
    s = sym.strip().upper()
    if not s.endswith("-USD"):
        return None
    base = re.sub(r"\d{4,}$", "", s[:-4])
    try:
        with open(os.path.join("trader", "universe.json"), encoding="utf-8") as fh:
            for c in json.load(fh).get("coins", []):
                if c.get("sym") == base and "binance" in c:
                    return c["binance"]
    except (OSError, ValueError, AttributeError):
        pass
    return (base + "USDT") if re.fullmatch(r"[A-Z0-9]{2,12}", base) else None


def binance_page(host, pair, interval, first_ms, last_ms):
    url = "%s/api/v3/klines?symbol=%s&interval=%s&startTime=%d&endTime=%d&limit=%d" % (
        host, pair, interval, first_ms, last_ms, BINANCE_MAX)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def binance_chart(sym, interval, start=None, end=None, bars=None, pair=None):
    """Candles from Binance in Yahoo's chart shape, or None when Binance does not list the
    coin or does not answer (then the caller asks Yahoo). start and end are epoch seconds;
    without start, the last `bars` candles. pair names the Binance ticker outright.
    Binance gives 1,000 candles a request: longer spans are asked for in parallel."""
    pair, step = pair or binance_pair(sym), BINANCE_STEP.get(interval)
    if not pair or not step:
        return None
    end = int(end or time.time())
    start = int(start if start is not None else end - (bars or BINANCE_MAX) * step)
    span = BINANCE_MAX * step * 1000
    pages = [(first, min(first + span - 1, end * 1000)) for first in range(start * 1000, end * 1000 + 1, span)]
    rows = None
    for host in BINANCE_HOSTS:
        try:
            if len(pages) > 2:
                with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                    parts = list(pool.map(lambda p: binance_page(host, pair, interval, p[0], p[1]), pages))
            else:
                parts = [binance_page(host, pair, interval, p[0], p[1]) for p in pages]
        except urllib.error.HTTPError as e:
            if e.code == 400:
                return None                 # Binance has no such pair
            continue                        # 451 (blocked location), 403, 429, 5xx: try the next host
        except (urllib.error.URLError, OSError, ValueError):
            continue
        rows = {int(k[0]): k for part in parts if isinstance(part, list) for k in part}
        if rows:
            break
    if not rows:
        return None
    rows = [rows[t] for t in sorted(rows)]
    quote = {"open": [float(k[1]) for k in rows], "high": [float(k[2]) for k in rows],
             "low": [float(k[3]) for k in rows], "close": [float(k[4]) for k in rows],
             "volume": [float(k[7]) for k in rows]}          # k[7]: traded value in USDT
    return {"chart": {"result": [{"meta": {"symbol": sym.upper(), "dataGranularity": interval,
                                           "exchangeName": "Binance", "binancePair": pair},
                                  "timestamp": [int(k[0]) // 1000 for k in rows],
                                  "indicators": {"quote": [quote]}}], "error": None}}


def binance_name(doc):
    return "Binance (%s)" % doc["chart"]["result"][0]["meta"]["binancePair"]


def http_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def fetch_bars(sym, offline=None):
    """1-minute candles of the last 2 days: [{t, o, h, l, c}], oldest first."""
    if offline:
        doc = json.load(open(offline, encoding="utf-8"))
    else:
        path = "/v8/finance/chart/%s?range=2d&interval=1m" % urllib.parse.quote(sym)
        global SOURCE_USED
        doc, last = None, None
        if SOURCE in ("auto", "binance"):
            doc = binance_chart(sym, "1m", bars=2880)
            if doc:
                SOURCE_USED = binance_name(doc)
            elif SOURCE == "binance":
                raise EntryError("Binance has no candles for %s, or did not answer: try --source yahoo" % sym)
        for host in (() if doc else HOSTS):
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
                SOURCE_USED = "Yahoo"
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

def default_confirm(setup, session):
    """2 closes in a row: on 1-minute candles a single close outside is mostly noise."""
    return 2


def evaluate(bars, now, session="wallstreet", setup="orb", side="both", or_minutes=5, level=None,
             expire_hours=2.0, day=None, confirm=2):
    """-> dict with status, phase, the range, the trigger (if any) and the bars so far.
    confirm = how many 1-minute closes in a row must be outside the level; the entry is the last one."""
    if day is None:
        day = now.date()
        if session == "utc" and now < session_open(session, day):
            prev = day - datetime.timedelta(days=1)
            if now <= session_open(session, prev) + datetime.timedelta(hours=expire_hours):
                day = prev      # yesterday's session is still running, across UTC midnight
    opn = session_open(session, day)
    rng_end = opn + datetime.timedelta(minutes=or_minutes)
    expires = opn + datetime.timedelta(hours=expire_hours)
    done = [b for b in bars if b["t"] >= ts_of(opn) and b["t"] + BAR <= ts_of(min(now, expires))]
    res = {"session": session, "date": day.isoformat(), "open_utc": hm(opn), "open_at": stamp(opn),
           "setup": setup, "side": side,
           "or_minutes": or_minutes, "range_ends_utc": hm(rng_end), "expires_utc": hm(expires),
           "level": level, "or_high": None, "or_low": None, "bars": done, "trigger": None,
           "last": done[-1]["c"] if done else None, "confirm": confirm, "streak": None}
    if now < opn:
        res.update(status="waiting", phase="pre-open")
        return res
    if not done:
        res.update(status="no-data" if now >= rng_end else "waiting",
                   phase="forming" if now < rng_end else "no-bars")
        return res
    n = or_minutes * 60 // BAR
    if setup == "orb":
        rbars = [b for b in done if b["t"] < ts_of(rng_end)]
        if now < rng_end or len(rbars) < n:
            if now >= rng_end + datetime.timedelta(minutes=3) and len(rbars) < n:
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
    up = down = 0
    for b in after:
        close_at = EPOCH + datetime.timedelta(seconds=b["t"] + BAR)
        up = up + 1 if b["c"] > up_lvl else 0
        down = down + 1 if b["c"] < down_lvl else 0
        if side in ("both", "long") and up >= confirm:
            res.update(status="triggered", phase="triggered",
                       trigger={"side": "long", "time": hm(close_at), "at": stamp(close_at), "price": rnd(b["c"]),
                                "level": up_lvl})
            return res
        if side in ("both", "short") and down >= confirm:
            res.update(status="triggered", phase="triggered",
                       trigger={"side": "short", "time": hm(close_at), "at": stamp(close_at), "price": rnd(b["c"]),
                                "level": down_lvl})
            return res
    if up and side in ("both", "long"):
        res["streak"] = ("long", up)
    elif down and side in ("both", "short"):
        res["streak"] = ("short", down)
    if now >= expires:
        res.update(status="expired", phase="expired")
    else:
        res.update(status="waiting", phase="watching")
    return res


def entry_doc(sym, res, now):
    t = res["trigger"] or {}
    return {
        "created_by": "scalp-entry", "created_at": now.isoformat() + "Z", "symbol": sym,
        "status": res["status"], "session": res["session"], "date": res["date"], "open_utc": res["open_utc"],
        "open_at": res["open_at"], "entry_at": t.get("at"),
        "setup": res["setup"], "opening_range": {"minutes": res["or_minutes"], "high": res["or_high"],
                                                 "low": res["or_low"]},
        "level": res["level"], "side": {"long": "buy", "short": "sell"}.get(t.get("side")),
        "source": SOURCE_USED, "entry": t.get("price"), "entry_time": t.get("time"), "interval": "1m", "confirm": res["confirm"],
    }


def describe(sym, res):
    p = res
    head = "%s  %s %s, sesión %s (abre %s UTC)" % (sym, p["setup"].upper(), p["date"], p["session"], p["open_utc"])
    lines = [head]
    lines.append("  OJO: en 4 semanas de velas de 1 minuto ninguna configuración de scalping ganó después de "
                 "comisiones. Esto marca el momento, no garantiza nada.")
    if p["session"] == "utc":
        lines.append("  Sesión libre: lejos de las aperturas la cripto se mueve menos (el fin de semana, unas 3 veces "
                     "menos) y las comisiones pesan más.")
    if p["setup"] == "orb" and p["or_high"] is not None:
        lines.append("  Rango de apertura (%d min, hasta %s UTC): máximo %g, mínimo %g"
                     % (p["or_minutes"], p["range_ends_utc"], p["or_high"], p["or_low"]))
    elif p["setup"] == "level":
        lines.append("  Nivel: %g" % p["level"])
    st = p["status"]
    if st == "triggered":
        t = p["trigger"]
        lines.append("  DISPARÓ %s: la vela que cerró a las %s UTC cerró en %g, %s de %g%s."
                     % ("LARGO" if t["side"] == "long" else "CORTO", t["time"], t["price"],
                        "encima" if t["side"] == "long" else "debajo", t["level"],
                        " (%d velas seguidas afuera)" % p["confirm"] if p["confirm"] > 1 else ""))
        lines.append("  Siguiente: /scalp-exit arma el stop, el objetivo y la salida por tiempo antes de entrar.")
    elif p["phase"] == "pre-open":
        lines.append("  ESPERANDO: la sesión todavía no abrió.")
    elif p["phase"] == "forming":
        lines.append("  ESPERANDO: el rango se está formando hasta las %s UTC." % p["range_ends_utc"])
    elif st == "waiting" and p.get("streak"):
        sd, k = p["streak"]
        lines.append("  ESPERANDO CONFIRMACIÓN: %d de %d velas seguidas cerraron %s del rango. Último cierre %g."
                     % (k, p["confirm"], "arriba" if sd == "long" else "abajo", p["last"]))
    elif st == "waiting":
        lines.append("  ESPERANDO: ninguna vela cerró afuera todavía%s. Último cierre %g. Vence %s UTC."
                     % ((" (hacen falta %d seguidas)" % p["confirm"]) if p["confirm"] > 1 else "",
                        p["last"], p["expires_utc"]))
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
    confirm = a.confirm if a.confirm else default_confirm(a.setup, a.session)
    return evaluate(bars, now, a.session, a.setup, a.side, a.or_minutes, a.level, a.expire_hours,
                    datetime.date.fromisoformat(a.date) if a.date else None, confirm)


def _check_args(a):
    global UTC_OPEN
    if a.session == "utc":
        if not a.open:
            raise EntryError("--session utc needs --open HH:MM (UTC), e.g. --open 01:35")
        try:
            h, m = (int(x) for x in a.open.split(":"))
            assert 0 <= h < 24 and 0 <= m < 60
        except (ValueError, AssertionError):
            raise EntryError("--open wants HH:MM in UTC, not %r" % a.open)
        UTC_OPEN = h * 60 + m
    if a.setup == "level" and a.level is None:
        raise EntryError("--setup level needs --level PRICE")
    if a.setup == "level" and a.side == "both":
        raise EntryError("--setup level needs --side long (close above) or --side short (close below)")
    if not 1 <= a.or_minutes <= 60:
        raise EntryError("--or-minutes is between 1 and 60 (1-minute candles)")
    if a.confirm is not None and not 1 <= a.confirm <= 6:
        raise EntryError("--confirm must be between 1 and 6 candles")


def cmd_check(a):
    _check_args(a)
    sym = yahoo_symbol(a.symbol)
    now = parse_now(a.now)
    res = _eval(a, now, fetch_bars(sym, a.offline))
    print("\n".join(describe(sym, res)))
    if SOURCE_USED:
        print("  Precios de %s." % SOURCE_USED)
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
    ap = argparse.ArgumentParser(description="Entry Timer for crypto scalping (scalp-entry).")
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("symbol", help="ETH, BTC-USD, SOLUSDT ...")
        p.add_argument("--session", default="wallstreet", choices=sorted(SESSIONS))
        p.add_argument("--setup", default="orb", choices=["orb", "level"])
        p.add_argument("--side", default="both", choices=["both", "long", "short"])
        p.add_argument("--or-minutes", type=int, default=5)
        p.add_argument("--level", type=float)
        p.add_argument("--expire-hours", type=float, default=2.0)
        p.add_argument("--confirm", type=int, help="1-minute closes in a row outside the level (default 2)")
        p.add_argument("--date", help="the session's UTC date (default today)")
        p.add_argument("--source", default="auto", choices=["auto", "binance", "yahoo"],
                       help="where the candles come from: Binance first and Yahoo as a fallback (auto), or one of them")
        p.add_argument("--open", help="with --session utc: the session's start, HH:MM UTC")

    p = sub.add_parser("check", help="where the setup stands right now")
    common(p)
    p.add_argument("--now", help='pretend it is this UTC time, e.g. "2026-11-05 15:00"')
    p.add_argument("--offline", help="a saved Yahoo chart JSON")
    p.add_argument("--write", nargs="?", const="trader/entry.json")
    p = sub.add_parser("watch", help="bar by bar until it triggers (run under a monitor)")
    common(p)
    p.add_argument("--max-hours", type=float, default=2.5)
    p.add_argument("--write", default=None)
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    global SOURCE
    SOURCE = a.source
    try:
        return {"check": cmd_check, "watch": cmd_watch}[a.cmd](a)
    except EntryError as e:
        print("entry.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
