#!/usr/bin/env python3
"""Chart Scanner for scalp-scanner. Standard library only.

Scalping take on crypto-scanner (skill-cryptos-jeto1337), built on trader-scanner
from Jakeschincariol/day-trader-skill (MIT, see LICENSE-day-trader-skill). Only
the most liquid coins, 1-minute candles, a 5-minute opening range.

    python3 scan.py universe                       # the most traded coins -> trader/universe.json
    python3 scan.py orb                            # 1-minute breaks of today's Wall Street open
    python3 scan.py orb --session europa           # ... of the London open
    python3 scan.py orb --at 14:50 --or-minutes 5  # cut the clock at 14:50 UTC
    python3 scan.py daily                          # daily context (trend, RSI), not scalping signals

universe  CoinGecko markets by 24h volume (api.coingecko.com). Out: stablecoins,
          wrapped and staked copies, gold tokens, anything under --min-volume
          (1,000 M USD: scalping needs the tightest spreads). Each coin is matched
          to its Yahoo pair. --limit coins (8), most traded first.

daily     Daily closes, Yahoo spark (3 months of 1-day bars, 20 a request).
          Today's bar is dropped: a crypto daily bar runs 00:00 to 24:00 UTC
          and is not closed yet. Setups:
            breakout_20d / breakdown_20d    last close above / below every close of the 20 before it
            bull_flag / bear_flag           up / down more than 10 % over the 10 days before the
                                            last 5, then the last 5 closes inside a 5 % range
            reclaim_ma20 / lose_ma20        closed under / over the 20-day average, then back over / under
            oversold / overbought           RSI 14 (Wilder) under 30 / over 70
            oversold_bounce                 RSI 14 under 30 yesterday and up today

orb       Opening-range breaks on 1-minute candles (Yahoo v8 chart, one request a coin).
          The range is the first --or-minutes (5) of the session; a break is
          --confirm (2) completed candles IN A ROW closing above the range high
          (long) or below the range low (short). A coin counts when the whole
          range and at least 90 % of the minutes since the open are there
          (Yahoo skips the odd quiet minute).

Sessions (each day's own daylight-time offsets, printed in UTC):
  wallstreet         09:30 New York  (14:30 UTC in northern winter, 13:30 in summer)
  europa             08:00 London    (08:00 UTC in winter, 07:00 in summer)

Yahoo's endpoints are free, unofficial and can lag. A scan is a list of charts
that match a rule, not a list of coins to buy or sell.
Exit code 0 when the scan found something, 1 when it did not or could not run.
"""

import argparse
import concurrent.futures
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; scalp-scanner/1.0)"
YAHOO = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")
COINGECKO = ("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd"
             "&order=volume_desc&per_page=100&page=1")
SPARK_MAX = 20
PAUSE = 0.3
CHART_PAUSE = 1.2   # one chart a coin: slower, or Yahoo answers 429
BACKOFF = 10.0
RATE_WAIT = 30.0   # both Yahoo hosts rate-limited: wait this long and try again
NOTE = "A scan is a list of charts that match a rule, not a list of coins to buy or sell."
SKIP = {
    "usdt", "usdc", "fdusd", "dai", "usde", "tusd", "usdd", "pyusd", "usd1", "usds",
    "busd", "eurc", "rlusd", "susde", "usdtb", "xaut", "paxg", "wbtc", "weth", "steth",
    "wsteth", "cbbtc", "bsc-usd", "usdf", "usdg", "gho", "frax", "lusd", "u", "wbt",
    "weeth", "reth", "jitosol", "msol", "bnsol", "bfusd", "syrupusdc",
}
SESSIONS = {"wallstreet": ("ny", 9 * 60 + 30), "europa": ("london", 8 * 60), "utc": ("utc", None)}
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


# Yahoo lists some coins under a numbered pair (the plain ticker is another coin, or nothing).
YAHOO_PAIRS = {"HYPE": "HYPE32196-USD", "UNI": "UNI7083-USD", "SUI": "SUI20947-USD",
               "PEPE": "PEPE24478-USD", "TRUMP": "TRUMP35336-USD"}
# When CoinGecko does not answer and no universe is saved: the largest coins, so a scan still runs.
DEFAULT_COINS = ("BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "LINK", "LTC", "BCH", "AVAX", "TRX")
PRICE_BAND = (0.5, 2.0)     # Yahoo's last close over CoinGecko's price: outside this, it is another coin
STALE_HOURS = 24            # a saved universe older than this gets a warning
OFFLINE = None              # a folder of saved Yahoo charts (<PAIR>.json) instead of the network
SOURCE_COUNT = {}           # how many coins each source answered for, in this run
HERE = os.path.dirname(os.path.abspath(__file__))


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
    return "%02d:%02d" % divmod(int(minutes) % (24 * 60), 60)


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


def yahoo(path, rounds=3):
    """query2 first, one retry after a 429, then query1 on 429 or 5xx. When both hosts
    rate-limit, wait RATE_WAIT seconds and go round again, up to `rounds` times."""
    last = None
    for r in range(rounds):
        try:
            return _yahoo_once(path)
        except RateLimited as e:
            last = e.code
            if r < rounds - 1:
                time.sleep(RATE_WAIT)
    raise ScanError("Yahoo answered HTTP %s on both hosts %d times in a row; try again in a few minutes"
                    % (last, rounds))


class RateLimited(Exception):
    def __init__(self, code):
        self.code = code


def _yahoo_once(path):
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
    raise RateLimited(last)


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


def daily_closes(symbols, days=100):
    """{symbol: (timestamps, closes)} of daily closes: Binance coin by coin, Yahoo for the rest."""
    out, rest = {}, []
    for sym in symbols:
        doc = binance_chart(sym, "1d", bars=days) if SOURCE in ("auto", "binance") else None
        if doc:
            res = doc["chart"]["result"][0]
            out[sym] = (res["timestamp"], res["indicators"]["quote"][0]["close"])
            SOURCE_COUNT["Binance"] = SOURCE_COUNT.get("Binance", 0) + 1
        elif SOURCE != "binance":
            rest.append(sym)
    if rest:
        out.update(spark(rest, "3mo", "1d"))
        SOURCE_COUNT["Yahoo"] = SOURCE_COUNT.get("Yahoo", 0) + len(rest)
    return out


def chart(sym, rng="1d", interval="1m"):
    if OFFLINE:
        path = os.path.join(OFFLINE, sym + ".json")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    else:
        global SOURCE_USED
        doc = binance_chart(sym, interval, bars=1440) if SOURCE in ("auto", "binance") else None
        if doc:
            SOURCE_USED = "Binance"
            SOURCE_COUNT["Binance"] = SOURCE_COUNT.get("Binance", 0) + 1
        elif SOURCE == "binance":
            return []
        else:
            SOURCE_COUNT["Yahoo"] = SOURCE_COUNT.get("Yahoo", 0) + 1
            q = urllib.parse.urlencode({"range": rng, "interval": interval})
            doc = yahoo("/v8/finance/chart/%s?%s" % (urllib.parse.quote(sym), q)) or {}
            SOURCE_USED = "Yahoo"
    res = ((doc.get("chart") or {}).get("result") or [None])[0]
    if not res:
        return []
    qt = (res.get("indicators") or {}).get("quote", [{}])[0]
    bars = []
    for i, ts in enumerate(res.get("timestamp") or []):
        row = [qt.get(k, [None] * (i + 1))[i] for k in ("open", "high", "low", "close", "volume")]
        if ts is None or None in row[:4] or int(ts) % 60:
            continue
        bars.append({"t": int(ts), "o": row[0], "h": row[1], "l": row[2], "c": row[3], "v": row[4] or 0})
    return bars


# ---------------------------------------------------------------- universe

def same_coin(price, closes):
    """Is this Yahoo series the coin CoinGecko means? Tickers repeat, so compare the prices."""
    last = next((x for x in reversed(closes or []) if x), None)
    if not last or not price:
        return False
    return PRICE_BAND[0] <= last / price <= PRICE_BAND[1]


def build_universe(limit, min_volume, max_rank=100):
    """-> (coins, missing, wrong): the most traded coins matched to their Yahoo pair, the ones
    Yahoo does not have, and the ones whose ticker on Yahoo is a different coin."""
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
        rank = c.get("market_cap_rank")
        if s in SKIP or "usd" in s or (c.get("total_volume") or 0) < min_volume:
            continue
        if max_rank and (rank is None or rank > max_rank):
            continue      # traded a lot today, but a small coin: mostly one-day speculation
        picked.append({"sym": s.upper(), "id": c.get("id"), "name": c.get("name"), "volume": c.get("total_volume"),
                       "rank": rank, "price": c.get("current_price"), "yahoo": s.upper() + "-USD"})
        if len(picked) >= limit:
            break
    have = spark([p["yahoo"] for p in picked], "5d", "1d")
    missing, wrong = [], []
    for p in picked:
        if p["yahoo"] in have and same_coin(p["price"], have[p["yahoo"]][1]):
            continue
        clash = p["yahoo"] in have      # Yahoo has that ticker, but its price says it is another coin
        found = None
        try:
            q = urllib.parse.urlencode({"q": p["name"], "quotesCount": 6, "newsCount": 0})
            doc = yahoo("/v1/finance/search?" + q) or {}
            cands = [row.get("symbol") for row in doc.get("quotes", [])
                     if row.get("quoteType") == "CRYPTOCURRENCY" and row.get("symbol") != p["yahoo"]
                     and re.fullmatch(re.escape(p["sym"]) + r"\d*-USD", row.get("symbol") or "")]
            if cands:
                got = spark(cands[:3], "5d", "1d")
                found = next((y for y in cands[:3] if y in got and same_coin(p["price"], got[y][1])), None)
        except ScanError:
            pass
        time.sleep(PAUSE)
        if found:
            p["yahoo"] = found
        else:
            p["yahoo"] = None
            (wrong if clash else missing).append(p["sym"])
    for p in picked:        # the same check on Binance: its ticker has to be this coin
        doc = binance_chart(p["sym"] + "-USD", "1d", bars=2, pair=p["sym"] + "USDT")
        closes = doc["chart"]["result"][0]["indicators"]["quote"][0]["close"] if doc else []
        p["binance"] = (p["sym"] + "USDT") if same_coin(p["price"], closes) else None
        if p["binance"] and not p["yahoo"] and p["sym"] in missing:
            p["yahoo"] = p["sym"] + "-USD"      # Yahoo does not list it, Binance does: keep the coin
            missing.remove(p["sym"])            # (a ticker that is ANOTHER coin on Yahoo stays out)
    return [p for p in picked if p["yahoo"]], missing, wrong


def load_universe(path, a):
    known = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            saved = json.load(fh)
        known = {c["sym"]: c["yahoo"] for c in saved.get("coins", [])}
    if a.symbols:
        out = []
        for s in a.symbols.split(","):
            s = s.strip().upper()
            if s:
                base = s[:-4] if s.endswith("-USD") else s
                pair = s if "-" in s else known.get(base) or YAHOO_PAIRS.get(base, base + "-USD")
                out.append({"sym": base, "yahoo": pair, "volume": 0})
        return out
    if OFFLINE:         # no list given: the coins that have a saved chart
        return [{"sym": f[:-5].split("-")[0], "yahoo": f[:-5], "volume": 0}
                for f in sorted(os.listdir(OFFLINE)) if f.endswith(".json")]
    if known:
        try:
            made = datetime.datetime.fromisoformat(saved["created_at"].replace("Z", ""))
            if parse_now(getattr(a, "now", None)) - made > datetime.timedelta(hours=STALE_HOURS):
                print("  OJO: la lista de criptos de %s es del %s. Actualizala con: scan.py universe"
                      % (path, made.strftime("%d/%m %H:%M UTC")))
        except (KeyError, ValueError, AttributeError):
            pass
        return saved["coins"]
    try:
        coins, _, _ = build_universe(a.limit, a.min_volume, a.max_rank)
    except ScanError as e:
        print("  OJO: no pude armar la lista de criptos (%s). Uso la lista fija de las más grandes." % e)
        return [{"sym": s, "yahoo": YAHOO_PAIRS.get(s, s + "-USD"), "volume": 0} for s in DEFAULT_COINS]
    if coins:           # keep it: the next scan of the day reads the same list
        write_json(path, {"created_by": os.path.basename(HERE) + " universe",
                          "created_at": parse_now(None).isoformat() + "Z", "coins": coins})
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
    data = daily_closes([c["yahoo"] for c in coins])
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
    if not OFFLINE and SOURCE_COUNT:
        print("  Precios: %s." % ", ".join("%s (%d)" % kv for kv in sorted(SOURCE_COUNT.items())))
    print(NOTE)
    if a.write:
        write_json(a.write, {"created_by": "scalp-scanner daily", "created_at": now.isoformat() + "Z",
                             "rows": rows})
    return 0 if rows else 1


# ---------------------------------------------------------------- opening-range breaks

def orb_scan(bars, day, open_min, cutoff_min, n_range, confirm=2):
    """-> None (unusable), or dict with the range and the first confirmed break each way."""
    start = datetime.datetime.combine(day, datetime.time()) + datetime.timedelta(minutes=open_min)
    t0 = int((start - datetime.datetime(1970, 1, 1)).total_seconds())
    t_cut = t0 + (cutoff_min - open_min) * 60
    sess = [b for b in bars if t0 <= b["t"] and b["t"] + 60 <= t_cut]
    want = cutoff_min - open_min
    rng = [b for b in sess if b["t"] < t0 + 60 * n_range]
    if len(rng) < n_range or len(sess) <= n_range or len(sess) < 0.9 * want:
        return None
    hi, lo = max(b["h"] for b in rng), min(b["l"] for b in rng)
    out = {"or_high": hi, "or_low": lo, "last": sess[-1]["c"], "up": None, "down": None}
    up = down = 0
    for b in sess[len(rng):]:
        when = hhmm(((b["t"] - t0) // 60) + open_min + 1)
        up = up + 1 if b["c"] > hi else 0
        down = down + 1 if b["c"] < lo else 0
        if out["up"] is None and up >= confirm:
            out["up"] = {"time": when, "close": b["c"], "beyond_pct": (b["c"] / hi - 1) * 100}
        if out["down"] is None and down >= confirm:
            out["down"] = {"time": when, "close": b["c"], "beyond_pct": (1 - b["c"] / lo) * 100}
    return out


def cmd_orb(a):
    now = parse_now(a.now)
    day = now.date()
    if a.session == "utc":
        if not a.open:
            raise ScanError("--session utc needs --open HH:MM (UTC)")
        open_min = parse_hhmm(a.open)
    else:
        open_min = open_utc(a.session, day)
    cutoff = parse_hhmm(a.at) if a.at else now.hour * 60 + now.minute
    if a.session == "utc" and cutoff < open_min and cutoff + 24 * 60 - open_min <= 180:
        day -= datetime.timedelta(days=1)       # a free session that opened last night, past UTC midnight
        cutoff += 24 * 60
    n = a.or_minutes
    if not 1 <= n <= 60:
        raise ScanError("--or-minutes is between 1 and 60 (1-minute candles)")
    if cutoff < open_min + a.or_minutes + a.confirm:
        raise ScanError("the %s session opens at %s UTC today; the %d-minute range plus %d candle(s) ends at %s UTC. "
                        "Run it after that, or pass --at." % (a.session, hhmm(open_min), a.or_minutes, a.confirm,
                                                              hhmm(open_min + a.or_minutes + a.confirm)))
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
        if not OFFLINE and SOURCE_USED != "Binance":
            time.sleep(CHART_PAUSE)      # Yahoo answers 429 when asked too fast; Binance does not
        r = orb_scan(bars, day, open_min, cutoff, n, a.confirm)
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
    print("RUPTURAS DE 1 MINUTO  %s, sesión %s (abre %s UTC), rango %d min, %d velas seguidas, corte %s UTC"
          % (day.isoformat(), a.session, hhmm(open_min), a.or_minutes, a.confirm, hhmm(cutoff)))
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
    if not OFFLINE and SOURCE_COUNT:
        print("  Precios: %s." % ", ".join("%s (%d)" % kv for kv in sorted(SOURCE_COUNT.items())))
    print(NOTE)
    if a.write:
        write_json(a.write, {"created_by": "scalp-scanner orb", "created_at": now.isoformat() + "Z",
                             "session": a.session, "open_utc": hhmm(open_min), "or_minutes": a.or_minutes,
                             "cutoff_utc": hhmm(cutoff), "hits": hits, "unusable": unusable})
    return 0 if hits else 1


def cmd_universe(a):
    coins, missing, wrong = build_universe(a.limit, a.min_volume, a.max_rank)
    write_json(a.universe, {"created_by": "scalp-scanner universe",
                            "created_at": parse_now(None).isoformat() + "Z", "coins": coins})
    print("Universo: %d criptos con más de %.0f M USD de volumen -> %s" % (len(coins), a.min_volume / 1e6, a.universe))
    print("  " + ", ".join("%s (%s)" % (c["sym"], c.get("binance") or c["yahoo"]) for c in coins))
    print("  En Binance: %d de %d. El resto se lee de Yahoo." % (sum(1 for c in coins if c.get("binance")), len(coins)))
    if missing:
        print("  Sin par en Yahoo, quedaron afuera: %s" % ", ".join(missing))
    if wrong:
        print("  En Yahoo ese símbolo es otra moneda (el precio no coincide), quedaron afuera: %s" % ", ".join(wrong))
    return 0 if coins else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Chart Scanner for crypto scalping (scalp-scanner).")
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--universe", default="trader/universe.json")
        p.add_argument("--symbols", help="comma list instead of the universe, e.g. BTC,ETH,SOL")
        p.add_argument("--limit", type=int, default=8)
        p.add_argument("--min-volume", type=float, default=1e9)
        p.add_argument("--source", default="auto", choices=["auto", "binance", "yahoo"],
                       help="where the candles come from: Binance first and Yahoo as a fallback (auto), or one")
        p.add_argument("--max-rank", type=int, default=100,
                       help="leave out coins below this market-cap rank (default 100; 0 = no limit)")
        p.add_argument("--now", help='pretend it is this UTC time, e.g. "2026-11-05 15:00"')

    p = sub.add_parser("universe", help="top coins by volume, matched to Yahoo")
    common(p)
    p = sub.add_parser("daily", help="daily setups, long and short")
    common(p)
    p.add_argument("--write", nargs="?", const="trader/watchlist.json")
    p = sub.add_parser("orb", help="opening-range breaks of today's session")
    common(p)
    p.add_argument("--session", default="wallstreet", choices=sorted(SESSIONS))
    p.add_argument("--or-minutes", type=int, default=5)
    p.add_argument("--confirm", type=int, default=2, help="1-minute closes in a row outside the range")
    p.add_argument("--open", help="with --session utc: the session's start, HH:MM UTC")
    p.add_argument("--at", help="cut the clock at this UTC time, e.g. 14:50")
    p.add_argument("--min-beyond", type=float, default=0.05, help="%% past the range below which a break is weak")
    p.add_argument("--write", nargs="?", const="trader/orb.json")
    p.add_argument("--offline", help="a folder of saved Yahoo charts (<PAIR>.json) instead of the network")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    global OFFLINE, SOURCE
    SOURCE = a.source
    OFFLINE = getattr(a, "offline", None)
    if OFFLINE and not os.path.isdir(OFFLINE):
        print("scan.py: --offline wants a folder of saved charts, not %r" % OFFLINE, file=sys.stderr)
        return 1
    try:
        return {"universe": cmd_universe, "daily": cmd_daily, "orb": cmd_orb}[a.cmd](a)
    except ScanError as e:
        print("scan.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
