#!/usr/bin/env python3
"""Chart Scanner for crypto-scanner. Standard library only.

Crypto port of trader-scanner from Jakeschincariol/day-trader-skill (MIT, see
LICENSE-day-trader-skill). Same setups, both directions, on the most traded
coins instead of US stocks, with sessions tied to the Europe and Wall Street
opens.

    python3 scan.py universe                       # top coins by volume -> trader/universe.json
    python3 scan.py daily                          # daily setups, long and short -> trader/watchlist.json
    python3 scan.py orb                            # opening-range breaks of today's Wall Street session
    python3 scan.py orb --session europa           # ... of the London open
    python3 scan.py orb --at 15:30 --or-minutes 30 # cut the clock at 15:30 UTC, 30-minute range

universe  CoinGecko markets by 24h volume (api.coingecko.com). Out: stablecoins,
          wrapped and staked copies, gold tokens, anything under --min-volume
          (100 M USD). Each coin is matched to its Yahoo pair: SYM-USD when
          Yahoo has it, else Yahoo's own search by the coin's name (HYPE is
          HYPE32196-USD there). --limit coins (30), most traded first.

daily     Daily closes, Yahoo spark (3 months of 1-day bars, 20 a request).
          Today's bar is dropped: a crypto daily bar runs 00:00 to 24:00 UTC
          and is not closed yet. Setups:
            breakout_20d / breakdown_20d    last close above / below every close of the 20 before it
            bull_flag / bear_flag           up / down more than 10 % over the 10 days before the
                                            last 5, then the last 5 closes inside a 5 % range
            reclaim_ma20 / lose_ma20        closed under / over the 20-day average, then back over / under
            oversold / overbought           RSI 14 (Wilder) under 30 / over 70
            oversold_bounce                 RSI 14 under 30 yesterday and up today

orb       Opening-range breaks, 5-minute bars (Yahoo v8 chart, one request a coin).
          The range is the first --or-minutes (15) of the session; a break is
          the first completed bar after it to CLOSE above the range high (long)
          or below the range low (short). A coin counts only when every
          5-minute bar from the open to the cutoff is there.

Sessions (each day's own daylight-time offsets, printed in UTC):
  wallstreet         09:30 New York  (14:30 UTC in northern winter, 13:30 in summer)
  europa             08:00 London    (08:00 UTC in winter, 07:00 in summer)

Yahoo's endpoints are free, unofficial and can lag. A scan is a list of charts
that match a rule, not a list of coins to buy or sell.
Exit code 0 when the scan found something, 1 when it did not or could not run.
"""

import argparse
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; crypto-scanner/1.0)"
YAHOO = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")
COINGECKO = ("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd"
             "&order=volume_desc&per_page=100&page=1")
SPARK_MAX = 20
PAUSE = 0.3
CHART_PAUSE = 1.2   # one chart a coin: slower, or Yahoo answers 429
BACKOFF = 10.0
NOTE = "A scan is a list of charts that match a rule, not a list of coins to buy or sell."
SKIP = {
    "usdt", "usdc", "fdusd", "dai", "usde", "tusd", "usdd", "pyusd", "usd1", "usds",
    "busd", "eurc", "rlusd", "susde", "usdtb", "xaut", "paxg", "wbtc", "weth", "steth",
    "wsteth", "cbbtc", "bsc-usd", "usdf", "usdg", "gho", "frax", "lusd", "u", "wbt",
    "weeth", "reth", "jitosol", "msol", "bnsol", "bfusd", "syrupusdc",
}
SESSIONS = {"wallstreet": ("ny", 9 * 60 + 30), "europa": ("london", 8 * 60)}
LABEL = {
    "breakout_20d": ("largo", "cierre por encima de los 20 anteriores"),
    "breakdown_20d": ("corto", "cierre por debajo de los 20 anteriores"),
    "bull_flag": ("largo", "bandera alcista: +10 % y 5 días quieta"),
    "bear_flag": ("corto", "bandera bajista: -10 % y 5 días quieta"),
    "reclaim_ma20": ("largo", "recuperó la media de 20 días"),
    "lose_ma20": ("corto", "perdió la media de 20 días"),
    "oversold": ("largo", "sobreventa, RSI 14 < 30"),
    "overbought": ("corto", "sobrecompra, RSI 14 > 70"),
    "oversold_bounce": ("largo", "rebote desde sobreventa"),
}


class ScanError(Exception):
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
    """New York -4 / -5 (US rule since 2007), London +1 / 0 (EU rule)."""
    if market == "ny":
        return -4 if _nth_sunday(day.year, 3, 2) <= day < _nth_sunday(day.year, 11, 1) else -5
    if market == "london":
        return 1 if _last_sunday(day.year, 3) <= day < _last_sunday(day.year, 10) else 0
    return 0


def open_utc(session, day):
    market, local = SESSIONS[session]
    return local - 60 * utc_offset_hours(market, day)


def hhmm(minutes):
    return "%02d:%02d" % divmod(int(minutes), 60)


def parse_now(text):
    if not text:
        return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None, microsecond=0)
    try:
        dt = datetime.datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        raise ScanError("--now wants a UTC time like \"2026-11-05 15:00\"")
    return dt if dt.tzinfo is None else (dt - dt.utcoffset()).replace(tzinfo=None)


def parse_hhmm(text):
    try:
        h, m = (int(x) for x in text.split(":"))
    except (ValueError, AttributeError):
        raise ScanError("--at wants a UTC time like 15:30, not %r" % text)
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ScanError("--at %r is not a clock time" % text)
    return h * 60 + m


# ---------------------------------------------------------------- network

def http_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def yahoo(path):
    """query2 first, one retry after a 429, then query1 on 429 or 5xx."""
    last = None
    for host in YAHOO:
        for attempt in (0, 1):
            try:
                return http_json(host + path)
            except urllib.error.HTTPError as e:
                last = e.code
                if e.code == 429 and attempt == 0:
                    time.sleep(BACKOFF)
                    continue
                if e.code == 429 or e.code >= 500:
                    break
                if e.code == 404:
                    return None
                raise ScanError("Yahoo answered HTTP %d" % e.code)
            except (urllib.error.URLError, OSError) as e:
                raise ScanError("could not reach Yahoo (is query2.finance.yahoo.com allowed?): %s" % e)
        time.sleep(PAUSE)
    raise ScanError("Yahoo answered HTTP %s on both hosts; try again in a minute" % last)


def spark(symbols, rng, interval):
    """{symbol: (timestamps, closes)} for up to SPARK_MAX symbols a request."""
    out = {}
    for i in range(0, len(symbols), SPARK_MAX):
        chunk = symbols[i:i + SPARK_MAX]
        q = urllib.parse.urlencode({"symbols": ",".join(chunk), "range": rng, "interval": interval})
        doc = yahoo("/v8/finance/spark?" + q) or {}
        for sym, v in doc.items():
            if isinstance(v, dict) and v.get("timestamp") and v.get("close"):
                out[sym] = (v["timestamp"], v["close"])
        time.sleep(PAUSE)
    return out


def chart(sym, rng="2d", interval="5m"):
    q = urllib.parse.urlencode({"range": rng, "interval": interval})
    doc = yahoo("/v8/finance/chart/%s?%s" % (urllib.parse.quote(sym), q)) or {}
    res = ((doc.get("chart") or {}).get("result") or [None])[0]
    if not res:
        return []
    qt = (res.get("indicators") or {}).get("quote", [{}])[0]
    bars = []
    for i, ts in enumerate(res.get("timestamp") or []):
        row = [qt.get(k, [None] * (i + 1))[i] for k in ("open", "high", "low", "close", "volume")]
        if ts is None or None in row[:4] or int(ts) % 300:
            continue
        bars.append({"t": int(ts), "o": row[0], "h": row[1], "l": row[2], "c": row[3], "v": row[4] or 0})
    return bars


# ---------------------------------------------------------------- universe

def build_universe(limit, min_volume):
    coins = None
    for attempt in range(5):
        try:
            coins = http_json(COINGECKO)
            break
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 4:
                raise ScanError("CoinGecko answered HTTP %d%s" % (e.code, ", too many requests: wait a minute"
                                                                  if e.code == 429 else ""))
            time.sleep(20)   # the free tier's rate limit resets within a minute
        except (urllib.error.URLError, OSError) as e:
            raise ScanError("could not reach CoinGecko (is api.coingecko.com allowed?): %s" % e)
    picked = []
    for c in coins:
        s = (c.get("symbol") or "").lower()
        if s in SKIP or "usd" in s or (c.get("total_volume") or 0) < min_volume:
            continue
        picked.append({"sym": s.upper(), "name": c.get("name"), "volume": c.get("total_volume"),
                       "rank": c.get("market_cap_rank"), "yahoo": s.upper() + "-USD"})
        if len(picked) >= limit:
            break
    have = spark([p["yahoo"] for p in picked], "5d", "1d")
    missing = []
    for p in picked:
        if p["yahoo"] in have:
            continue
        found = None
        try:
            q = urllib.parse.urlencode({"q": p["name"], "quotesCount": 6, "newsCount": 0})
            doc = yahoo("/v1/finance/search?" + q) or {}
            for row in doc.get("quotes", []):
                sym = row.get("symbol") or ""
                if row.get("quoteType") == "CRYPTOCURRENCY" and sym.endswith("-USD") \
                        and sym.startswith(p["sym"]):
                    found = sym
                    break
        except ScanError:
            pass
        time.sleep(PAUSE)
        if found:
            p["yahoo"] = found
        else:
            p["yahoo"] = None
            missing.append(p["sym"])
    return [p for p in picked if p["yahoo"]], missing


def load_universe(path, a):
    if a.symbols:
        return [{"sym": s.strip().upper().split("-")[0], "yahoo": s.strip().upper()
                 if "-" in s else s.strip().upper() + "-USD", "volume": 0}
                for s in a.symbols.split(",") if s.strip()]
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))["coins"]
    coins, _ = build_universe(a.limit, a.min_volume)
    return coins


def write_json(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
        fh.write("\n")


# ---------------------------------------------------------------- daily setups

def day_of(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).date()


def rsi(closes, n=14):
    if len(closes) < n + 1:
        return None
    gains = [max(closes[i] - closes[i - 1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0) for i in range(1, len(closes))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    for g, l in zip(gains[n:], losses[n:]):
        ag, al = (ag * (n - 1) + g) / n, (al * (n - 1) + l) / n
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def find_setups(c):
    out = []
    if len(c) < 30:
        return out
    last, prev20 = c[-1], c[-21:-1]
    if last > max(prev20):
        out.append("breakout_20d")
    if last < min(prev20):
        out.append("breakdown_20d")
    run = c[-6] / c[-16] - 1
    box = (max(c[-5:]) - min(c[-5:])) / min(c[-5:])
    if box < 0.05 and run > 0.10:
        out.append("bull_flag")
    if box < 0.05 and run < -0.10:
        out.append("bear_flag")
    ma_now, ma_prev = sum(c[-20:]) / 20, sum(c[-21:-1]) / 20
    if c[-2] < ma_prev and last > ma_now:
        out.append("reclaim_ma20")
    if c[-2] > ma_prev and last < ma_now:
        out.append("lose_ma20")
    r_now, r_prev = rsi(c), rsi(c[:-1])
    if r_now is not None and r_now < 30:
        out.append("oversold")
    if r_now is not None and r_now > 70:
        out.append("overbought")
    if r_prev is not None and r_prev < 30 and last > c[-2]:
        out.append("oversold_bounce")
    return out


def cmd_daily(a):
    now = parse_now(a.now)
    coins = load_universe(a.universe, a)
    data = spark([c["yahoo"] for c in coins], "3mo", "1d")
    rows, stale = [], []
    for c in coins:
        if c["yahoo"] not in data:
            continue
        ts, cl = data[c["yahoo"]]
        pairs = [(t, x) for t, x in zip(ts, cl) if x is not None]
        pairs = [(day_of(t), x) for t, x in pairs if day_of(t) < now.date()]
        if not pairs:
            continue
        closes = [x for _, x in pairs]
        if pairs[-1][0] < now.date() - datetime.timedelta(days=1):
            stale.append(c["sym"])
        setups = find_setups(closes)
        if setups:
            rows.append({"sym": c["sym"], "yahoo": c["yahoo"], "close": closes[-1],
                         "close_date": pairs[-1][0].isoformat(),
                         "rsi14": round(rsi(closes) or 0, 1), "setups": setups,
                         "volume": c.get("volume", 0)})
    rows.sort(key=lambda r: r["volume"] or 0, reverse=True)
    print("SETUPS DIARIOS  (cierres diarios UTC hasta el %s, %d criptos revisadas)" % (
        (now.date() - datetime.timedelta(days=1)).isoformat(), len(coins)))
    if stale:
        print("  OJO: Yahoo no tiene el cierre del %s para %d de %d criptos (%s). Para esas, el último cierre es "
              "anterior y los setups pueden estar viejos." % ((now.date() - datetime.timedelta(days=1)).isoformat(),
                                                               len(stale), len(coins), ", ".join(stale[:8])
                                                               + (" ..." if len(stale) > 8 else "")))
    if not rows:
        print("  Ninguna cumple una regla hoy.")
    for r in rows:
        tags = "; ".join("%s (%s)" % (LABEL[s][1], LABEL[s][0]) for s in r["setups"])
        print("  %-6s %12.6g (%s)  RSI %5.1f  %s" % (r["sym"], r["close"], r["close_date"][5:], r["rsi14"], tags))
    print(NOTE)
    if a.write:
        write_json(a.write, {"created_by": "crypto-scanner daily", "created_at": now.isoformat() + "Z",
                             "rows": rows})
    return 0 if rows else 1


# ---------------------------------------------------------------- opening-range breaks

def orb_scan(bars, day, open_min, cutoff_min, n_range):
    """-> None (unusable), or dict with the range and the first break each way."""
    start = datetime.datetime.combine(day, datetime.time()) + datetime.timedelta(minutes=open_min)
    t0 = int((start - datetime.datetime(1970, 1, 1)).total_seconds())
    t_cut = t0 + (cutoff_min - open_min) * 60
    sess = [b for b in bars if t0 <= b["t"] and b["t"] + 300 <= t_cut]
    want = (cutoff_min - open_min) // 5
    if len(sess) < want or len(sess) <= n_range or any(sess[i]["t"] != t0 + 300 * i for i in range(want)):
        return None
    rng = sess[:n_range]
    hi, lo = max(b["h"] for b in rng), min(b["l"] for b in rng)
    out = {"or_high": hi, "or_low": lo, "last": sess[-1]["c"], "up": None, "down": None}
    for b in sess[n_range:]:
        when = hhmm(((b["t"] - t0) // 60) + open_min + 5)
        if out["up"] is None and b["c"] > hi:
            out["up"] = {"time": when, "close": b["c"], "beyond_pct": (b["c"] / hi - 1) * 100}
        if out["down"] is None and b["c"] < lo:
            out["down"] = {"time": when, "close": b["c"], "beyond_pct": (1 - b["c"] / lo) * 100}
    return out


def cmd_orb(a):
    now = parse_now(a.now)
    day = now.date()
    open_min = open_utc(a.session, day)
    cutoff = parse_hhmm(a.at) if a.at else now.hour * 60 + now.minute
    cutoff -= cutoff % 5
    n = a.or_minutes // 5
    if a.or_minutes % 5 or n < 1:
        raise ScanError("--or-minutes must be a multiple of 5")
    if cutoff < open_min + a.or_minutes + 5:
        raise ScanError("the %s session opens at %s UTC today; the %d-minute range plus one bar ends at %s UTC. "
                        "Run it after that, or pass --at." % (a.session, hhmm(open_min), a.or_minutes,
                                                              hhmm(open_min + a.or_minutes + 5)))
    coins = load_universe(a.universe, a)
    hits, unusable = [], []
    for c in coins:
        try:
            bars = chart(c["yahoo"])
        except ScanError:
            time.sleep(BACKOFF)
            try:
                bars = chart(c["yahoo"])
            except ScanError:
                bars = []
        time.sleep(CHART_PAUSE)
        r = orb_scan(bars, day, open_min, cutoff, n)
        if r is None:
            unusable.append(c["sym"])
            continue
        for side, key in (("LARGO", "up"), ("CORTO", "down")):
            if r[key]:
                hits.append(dict(r[key], sym=c["sym"], yahoo=c["yahoo"], side=side,
                                 or_high=r["or_high"], or_low=r["or_low"], last=r["last"],
                                 volume=c.get("volume", 0)))
    for h in hits:
        h["since_pct"] = (h["last"] / h["close"] - 1) * 100 * (1 if h["side"] == "LARGO" else -1)
        h["weak"] = h["beyond_pct"] < a.min_beyond
    hits.sort(key=lambda h: (h["weak"], h["time"], -(h["volume"] or 0)))
    print("RUPTURAS DEL RANGO DE APERTURA  %s, sesión %s (abre %s UTC), rango %d min, corte %s UTC"
          % (day.isoformat(), a.session, hhmm(open_min), a.or_minutes, hhmm(cutoff)))
    print("  %d criptos revisadas, %d con datos completos." % (len(coins), len(coins) - len(unusable)))
    if not hits:
        print("  Ninguna rompió el rango todavía.")
    print("  %-6s %-5s %-9s %-11s %-11s %-9s %s" % ("cripto", "lado", "ruptura", "cierre", "nivel", "afuera",
                                                    "a las %s UTC" % hhmm(cutoff)))
    weak_shown = False
    for h in hits:
        if h["weak"] and not weak_shown:
            print("  -- rupturas débiles (menos de %.2f %% afuera del rango): suelen ser ruido --" % a.min_beyond)
            weak_shown = True
        lvl = h["or_high"] if h["side"] == "LARGO" else h["or_low"]
        print("  %-6s %-5s %-9s %-11.6g %-11.6g %-9s %.6g (%+.2f %% a favor)"
              % (h["sym"], h["side"], h["time"], h["close"], lvl, "%.2f %%" % h["beyond_pct"], h["last"],
                 h["since_pct"]))
    both = sorted({h["sym"] for h in hits if h["side"] == "LARGO"} & {h["sym"] for h in hits if h["side"] == "CORTO"})
    if both:
        print("  Rompieron para los dos lados (rango sin dirección clara): %s" % ", ".join(both))
    if unusable:
        print("  Sin datos completos (falta alguna vela): %s" % ", ".join(unusable))
    print(NOTE)
    if a.write:
        write_json(a.write, {"created_by": "crypto-scanner orb", "created_at": now.isoformat() + "Z",
                             "session": a.session, "open_utc": hhmm(open_min), "or_minutes": a.or_minutes,
                             "cutoff_utc": hhmm(cutoff), "hits": hits, "unusable": unusable})
    return 0 if hits else 1


def cmd_universe(a):
    coins, missing = build_universe(a.limit, a.min_volume)
    write_json(a.universe, {"created_by": "crypto-scanner universe",
                            "created_at": parse_now(None).isoformat() + "Z", "coins": coins})
    print("Universo: %d criptos con más de %.0f M USD de volumen -> %s" % (len(coins), a.min_volume / 1e6, a.universe))
    print("  " + ", ".join("%s (%s)" % (c["sym"], c["yahoo"]) for c in coins))
    if missing:
        print("  Sin par en Yahoo, quedaron afuera: %s" % ", ".join(missing))
    return 0 if coins else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Chart Scanner for crypto (crypto-scanner).")
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--universe", default="trader/universe.json")
        p.add_argument("--symbols", help="comma list instead of the universe, e.g. BTC,ETH,SOL")
        p.add_argument("--limit", type=int, default=30)
        p.add_argument("--min-volume", type=float, default=100e6)
        p.add_argument("--now", help='pretend it is this UTC time, e.g. "2026-11-05 15:00"')

    p = sub.add_parser("universe", help="top coins by volume, matched to Yahoo")
    common(p)
    p = sub.add_parser("daily", help="daily setups, long and short")
    common(p)
    p.add_argument("--write", nargs="?", const="trader/watchlist.json")
    p = sub.add_parser("orb", help="opening-range breaks of today's session")
    common(p)
    p.add_argument("--session", default="wallstreet", choices=sorted(SESSIONS))
    p.add_argument("--or-minutes", type=int, default=15)
    p.add_argument("--at", help="cut the clock at this UTC time, e.g. 15:30")
    p.add_argument("--min-beyond", type=float, default=0.1, help="%% past the range below which a break is weak")
    p.add_argument("--write", nargs="?", const="trader/orb.json")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"universe": cmd_universe, "daily": cmd_daily, "orb": cmd_orb}[a.cmd](a)
    except ScanError as e:
        print("scan.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
