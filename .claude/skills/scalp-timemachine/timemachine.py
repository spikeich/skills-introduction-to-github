#!/usr/bin/env python3
"""Time Machine for scalp-timemachine. Standard library only.

Scalping take on crypto-timemachine (skill-cryptos-jeto1337), itself a port of
trader-timemachine from Jakeschincariol/day-trader-skill (MIT, see
LICENSE-day-trader-skill). Same algorithm, on 1-minute candles:

  --session wallstreet   from 09:30 New York (default)
  --session europa       from 08:00 London
  --session utc --open HH:MM   a free session that starts at that UTC time
A session is the 3 hours after its open: 2 hours in which entries count (scalp-entry
expires then) and 1 more to hold the last ones. Each day's open is worked out from
that day's own daylight-time offsets, and a free session may cross UTC midnight.
Symbols are Yahoo crypto pairs: BTC-USD, ETH-USD ... All times UTC, 24-hour clock.

Replays a planned scalp before you risk a dollar: 10,000 simulated runs from the
entry to the plan's time stop (flat_by, 20 minutes by default), plus the same rule
on every past session in the data, each trade held at most the same time.

    python3 timemachine.py run                          # trader/plan.json, 10,000 replays, seed 19
    python3 timemachine.py run --write                  # also save trader/timemachine.json
    python3 timemachine.py run --until 14:55            # end each replay at another time
    python3 timemachine.py run --symbol BTC --date 2026-11-06 --side buy \\
        --entry 75783 --stop 75593 --target 76163 --entry-time 14:42 --hold 20
    python3 timemachine.py run --session utc --open 23:45 --symbol BTC --date 2026-11-05 \\
        --entry 76129 --stop 75938 --target 76511 --entry-time 00:03   # --date is the day it opened
    python3 timemachine.py chart                        # ASCII fan chart of the replays

How the replays work:
  1. Fetch about 28 days of 1-minute candles (Yahoo keeps 30 days of them and gives
     7 per request: 4 requests). Keep the sessions before the plan's date that have
     the whole window; up to 5 missing minutes in a day are filled with a flat
     candle at the last close. Today is left out.
  2. The pool: for every minute of the window, each past session's candle as ratios
     to the previous close: (open, high, low, close) / prev close.
  3. One replay starts at the entry price and walks to --until. For each minute it
     picks a slot within +-window minutes, then one past candle from that slot, and
     scales it to the current price. The stop is checked before the target in every
     candle, so a candle that touches both counts as the stop.
  4. Outcomes: target, stop, or neither (still open at --until: the time stop).
  5. History: the plan's rule (opening range of the same minutes, the same confirm
     closes, the same stop rule and target R, out after --hold minutes) on each past
     session, entries in the first 2 hours.
  6. Fees: every number is also given after Binance futures fees (limit entry and
     target at maker 0.02 %, stop and time exits at taker 0.05 %). At a 0.25 % stop a
     2R win is worth about +1.84R and a loss costs about 1.28R, so the target has to
     come first in 41 % of the decided replays to break even, not 33 %. The verdict
     "after fees" is the one that counts for a scalp.

The verdict compares target / (target + stop) with 1 / (1 + R), as in crypto-timemachine:
  less than 5 points    close to break-even
  5 to 15 points        leans toward the target / the stop
  15 points or more     strongly toward the target / the stop

The run refuses with a plain message when there are fewer than 15 full sessions or
the entry candle is not in the data. A simulation built from four weeks of a coin's
own candles is not a prediction.

Data: https://query2.finance.yahoo.com/v8/finance/chart/<T>?period1=..&period2=..&interval=1m
--offline FILE reads a saved chart JSON (.json or .json.gz), or a folder holding
<SYM>-28d1m.json; --now "2026-11-06 14:50" pins the clock.
"""

import argparse
import concurrent.futures
import datetime
import gzip
import json
import math
import os
import random
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; scalp-timemachine/1.0)"
PAUSE = 0.5          # seconds between requests: be polite to free endpoints
BACKOFF = 5.0        # seconds to wait once after a 429
HOSTS = ("query2", "query1")
INTERVAL = 60        # 1-minute candles, in seconds
BM = 1               # minutes per candle
CHUNK_DAYS = 7       # Yahoo gives 7 days of 1-minute candles per request
CHUNKS = 4           # and keeps about 30 days: 4 requests = 28 days
MAX_GAP = 5          # missing minutes a session may have (filled flat at the last close)
HOLD = 20            # default time stop, minutes
WINDOW = 180         # minutes of a session: ENTRY_MIN of entries plus an hour to hold the last ones
ENTRY_MIN = 120      # entries count in the first 2 hours after the open (scalp-entry expires then)
DAY = 24 * 60
# name: (anchor market, local open in minutes, length in minutes)
SESSIONS = {
    "wallstreet": ("ny", 9 * 60 + 30, WINDOW),   # from the New York open
    "europa": ("london", 8 * 60, WINDOW),        # from the London open
}
SESSION = SESSIONS["wallstreet"]          # set_session() changes it
SESSION_NAME = "wallstreet"
SESSION_BARS = SESSION[2] // BM
OPEN_MIN = 14 * 60 + 30                   # the plan day's open and close in UTC: set_plan_day()
CLOSE_MIN = OPEN_MIN + SESSION[2]
MIN_SESSIONS = 15
MAKER, TAKER = 0.0002, 0.0005   # Binance futures: limit entry and target at maker, stop and time exits at taker
SAMPLE_PATHS = 160
BAND_PATHS = 2000
BAND_Q = (0.05, 0.25, 0.5, 0.75, 0.95)
HIST_BINS = 24
COIN_FLIP = 0.05     # verdict thresholds, see the docstring
STRONG = 0.15
MANY_NEITHER = 0.40
EPOCH = datetime.datetime(1970, 1, 1)
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def set_session(name, open_hhmm=None):
    """Pick the session: a named market open, or 'utc' with its own open time."""
    global SESSION, SESSION_BARS, SESSION_NAME
    if name == "utc":
        if not open_hhmm:
            raise TMError("--session utc needs --open HH:MM (UTC), or a plan from scalp-exit that carries it")
        SESSION = ("utc", parse_clock(open_hhmm, "--open") % DAY, WINDOW)
    elif name in SESSIONS:
        SESSION = SESSIONS[name]
    else:
        raise TMError("--session must be one of %s or utc" % ", ".join(SESSIONS))
    SESSION_NAME = name
    SESSION_BARS = SESSION[2] // BM
    set_plan_day(datetime.datetime.now(datetime.timezone.utc).date())


def _nth_sunday(year, month, n):
    d = datetime.date(year, month, 1)
    d += datetime.timedelta(days=(6 - d.weekday()) % 7)
    return d + datetime.timedelta(weeks=n - 1)


def _last_sunday(year, month):
    d = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
    return d - datetime.timedelta(days=(d.weekday() + 1) % 7)


def utc_offset_hours(market, day):
    """Hours from UTC at the market's open on that day. New York: -4 from the
    second Sunday of March to the first Sunday of November, else -5 (US rule
    since 2007). London: +1 from the last Sunday of March to the last Sunday of
    October, else 0 (EU rule). UTC: 0."""
    if market == "ny":
        return -4 if _nth_sunday(day.year, 3, 2) <= day < _nth_sunday(day.year, 11, 1) else -5
    if market == "london":
        return 1 if _last_sunday(day.year, 3) <= day < _last_sunday(day.year, 10) else 0
    return 0


def open_utc(day):
    """The session's open on that day, in minutes after UTC midnight."""
    if isinstance(day, str):
        day = datetime.date.fromisoformat(day)
    market, local_open, _ = SESSION
    return local_open - 60 * utc_offset_hours(market, day)


def set_plan_day(day):
    global OPEN_MIN, CLOSE_MIN
    OPEN_MIN = open_utc(day)
    CLOSE_MIN = OPEN_MIN + SESSION[2]


def tick(price):
    """Price step for rounding: about 1/10,000 of the price (0.01 at 100, 0.0001 at 1)."""
    if price <= 0:
        return 0.01
    return 10.0 ** (math.floor(math.log10(price)) - 4)


def rnd(x):
    t = tick(abs(x) or 1)
    return round(round(x / t) * t, 10)


class TMError(Exception):
    pass


# ---------------------------------------------------------------- time (UTC everywhere)

def session_day(now):
    """The date of the session that `now` falls in: a free session that opened yesterday
    can still be running after UTC midnight."""
    day = now.date()
    prev = day - datetime.timedelta(days=1)
    mins = now.hour * 60 + now.minute
    if mins < open_utc(day) and mins + DAY - open_utc(prev) < SESSION[2]:
        return prev
    return day


def parse_now(text):
    """ISO time -> naive UTC. A time without an offset is taken as UTC."""
    if not text:
        return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)
    t = text.strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(t)
    except ValueError:
        raise TMError("--now wants a UTC time like \"2026-11-05 14:00\"")
    if dt.tzinfo is None:
        return dt
    return (dt - dt.utcoffset()).replace(tzinfo=None)


def utc_of(ts):
    return EPOCH + datetime.timedelta(seconds=int(ts))


def parse_clock(text, what):
    """'14:00' or '2:00 PM' (UTC) -> minutes after midnight. 24-hour clock, no guessing."""
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*(?:([AaPp])\.?\s*[Mm]\.?)?\s*$", str(text or ""))
    if not m:
        raise TMError("%s wants a UTC time like 14:00, not %r" % (what, text))
    h, mi, ap = int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower()
    if mi > 59 or h > 23 or (ap and not 1 <= h <= 12):
        raise TMError("%s %r is not a clock time" % (what, text))
    if ap == "p" and h != 12:
        h += 12
    elif ap == "a" and h == 12:
        h = 0
    if h == 24 or (h == 0 and mi == 0 and what == "--until"):
        return 24 * 60
    return h * 60 + mi


def clock12(minutes):
    """Kept under the original name: prints a 24-hour UTC clock."""
    return "%02d:%02d UTC" % divmod(minutes % DAY, 60)


def clock24(minutes):
    return "%02d:%02d" % divmod(minutes % DAY, 60)


# ---------------------------------------------------------------- data

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


def chart_url(sym, host="query2", period1=None, period2=None):
    return "https://%s.finance.yahoo.com/v8/finance/chart/%s?period1=%d&period2=%d&interval=1m" % (
        host, urllib.parse.quote(yahoo_symbol(sym)), period1, period2)


def _sleep(seconds):
    time.sleep(seconds)


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


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


def fetch_chart(sym, now_utc=None):
    """About 28 days of 1-minute candles as one chart JSON text: Binance first (in parallel
    requests), then Yahoo in 7-day requests."""
    global SOURCE_USED
    end = int(((now_utc or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)) - EPOCH)
              .total_seconds()) // 60 * 60
    if SOURCE in ("auto", "binance"):
        doc = binance_chart(yahoo_symbol(sym), "1m", start=end - CHUNKS * CHUNK_DAYS * 86400, end=end)
        if doc:
            SOURCE_USED = binance_name(doc)
            return json.dumps(doc)
        if SOURCE == "binance":
            raise TMError("Binance has no candles for %s, or did not answer: try --source yahoo" % sym.upper())
    SOURCE_USED = "Yahoo"
    merged, meta = {}, None
    for n in range(CHUNKS):
        p2 = end - n * CHUNK_DAYS * 86400
        p1 = p2 - CHUNK_DAYS * 86400 + 60
        if n:
            _sleep(PAUSE)
        res = chart_result(fetch_chunk(sym, p1, p2), sym)
        meta = meta or res.get("meta") or {}
        q = ((res.get("indicators") or {}).get("quote") or [{}])[0] or {}
        cols = [q.get(k) or [] for k in ("open", "high", "low", "close", "volume")]
        for i, ts in enumerate(res.get("timestamp") or []):
            if ts is not None:
                merged[int(ts)] = [c[i] if i < len(c) else None for c in cols]
    stamps = sorted(merged)
    quote = {k: [merged[t][j] for t in stamps] for j, k in enumerate(("open", "high", "low", "close", "volume"))}
    return json.dumps({"chart": {"result": [{"meta": meta, "timestamp": stamps,
                                             "indicators": {"quote": [quote]}}], "error": None}})


def fetch_chunk(sym, period1, period2):
    """One request. query2 first, one retry after a 429, then query1 on 429 or 5xx."""
    last = None
    for n, host in enumerate(HOSTS):
        if n:
            _sleep(PAUSE)
        for attempt in (0, 1):
            url = chart_url(sym, host, period1, period2)
            try:
                return _get(url)
            except urllib.error.HTTPError as e:
                last = e.code
                try:
                    e.close()
                except Exception:
                    pass
                if e.code == 429 and attempt == 0:
                    _sleep(BACKOFF)
                    continue
                if e.code == 429 or e.code >= 500:
                    break
                if e.code == 404:
                    raise TMError("Yahoo has no chart for %s (HTTP 404): check the ticker" % sym.upper())
                raise TMError("Yahoo answered HTTP %d for %s" % (e.code, sym.upper()))
            except urllib.error.URLError as e:
                raise TMError("could not reach Yahoo: %s" % e.reason)
            except OSError as e:
                raise TMError("could not reach Yahoo: %s" % e)
    if last == 429:
        raise TMError("Yahoo is rate limiting (HTTP 429). Wait a minute and run it again.")
    raise TMError("Yahoo answered HTTP %s for %s on both hosts. Try again later." % (last, sym.upper()))


def read_offline(path, sym):
    """A saved Yahoo chart file (.json or .json.gz), or a folder holding <SYM>-28d1m.json(.gz)."""
    if os.path.isdir(path):
        for name in ("%s-28d1m.json" % sym.upper(), "%s-28d1m.json.gz" % sym.upper()):
            if os.path.exists(os.path.join(path, name)):
                path = os.path.join(path, name)
                break
        else:
            raise TMError("no %s-28d1m.json(.gz) in %s" % (sym.upper(), path))
    if not os.path.exists(path):
        raise TMError("no offline chart file %s" % path)
    opener = gzip.open if path.endswith(".gz") else open
    try:
        with opener(path, "rt", encoding="utf-8") as fh:
            return fh.read()
    except OSError as e:
        raise TMError("could not read %s: %s" % (path, e))


def chart_result(text, sym):
    try:
        data = json.loads(text)
    except ValueError:
        raise TMError("Yahoo returned something that is not JSON for %s" % sym.upper())
    chart = data.get("chart") if isinstance(data, dict) else None
    if not isinstance(chart, dict):
        raise TMError("Yahoo returned something unexpected for %s" % sym.upper())
    res = chart.get("result")
    if not res:
        err = chart.get("error") or {}
        raise TMError("Yahoo has no data for %s: %s" % (sym.upper(), err.get("description") or "unknown ticker"))
    return res[0]


def parse_bars(result, now_utc):
    """Yahoo chart result -> (meta, bars, dropped). 1-minute candles inside the window,
    oldest first. Dropped: bars with a missing price, bars off the 1-minute grid
    (the live tick, e.g. 10:49:45), bars not complete yet (now < start + 5 min,
    where now is the earlier of --now and the data's own regularMarketTime), and
    bars outside the session window (UTC)."""
    meta = result.get("meta") or {}
    stamps = result.get("timestamp") or []
    q = ((result.get("indicators") or {}).get("quote") or [{}])[0] or {}
    cols = [q.get(k) or [] for k in ("open", "high", "low", "close", "volume")]
    as_of = now_utc
    rmt = meta.get("regularMarketTime")
    if isinstance(rmt, (int, float)) and utc_of(rmt) < as_of:
        as_of = utc_of(rmt)
    dropped = {"no_price": 0, "off_grid": 0, "not_complete": 0, "outside_hours": 0}
    bars = {}
    for i, ts in enumerate(stamps):
        o, h, l, c, v = [col[i] if i < len(col) else None for col in cols]
        if ts is None or None in (o, h, l, c):
            dropped["no_price"] += 1
            continue
        ts = int(ts)
        if ts % INTERVAL:
            dropped["off_grid"] += 1
            continue
        start = utc_of(ts)
        day = start.date()
        mins = start.hour * 60 + start.minute - open_utc(day)
        if mins < 0:        # before today's open: it may be yesterday's session, past UTC midnight
            day -= datetime.timedelta(days=1)
            mins = start.hour * 60 + start.minute + DAY - open_utc(day)
        if mins < 0 or mins >= SESSION_BARS * BM:
            dropped["outside_hours"] += 1
            continue
        if start + datetime.timedelta(seconds=INTERVAL) > as_of:
            dropped["not_complete"] += 1
            continue
        bars[ts] = {"date": day.isoformat(), "slot": mins // BM, "start": start.strftime("%H:%M"),
                    "o": o, "h": h, "l": l, "c": c, "v": v or 0}
    return meta, [bars[t] for t in sorted(bars)], dropped


def split_sessions(bars):
    """{date: {slot: bar}}."""
    days = {}
    for b in bars:
        days.setdefault(b["date"], {})[b["slot"]] = b
    return days


def full_sessions(days, before):
    """Sessions strictly before the plan's date with the whole window, oldest first, and
    the short ones left out. Up to MAX_GAP missing minutes (never the first) are filled
    with a flat candle at the last close: Yahoo skips the odd quiet minute."""
    full, short = [], []
    for d in sorted(days):
        if d >= before:
            continue
        s = days[d]
        if 0 in s and len(s) >= SESSION_BARS - MAX_GAP:
            rows, prev = [], None
            for i in range(SESSION_BARS):
                b = s.get(i)
                if b is None:
                    c = prev["c"]
                    b = dict(prev, slot=i, o=c, h=c, l=c, c=c, v=0, filled=True)
                rows.append(b)
                prev = b
            full.append((d, rows))
        else:
            short.append({"date": d, "bars": len(s)})
    return full, short


# ---------------------------------------------------------------- the simulation (sim.py)

def build_pool(sessions):
    """pool[i] = every past session's bar i as (o, h, l, c) / bar i-1's close, in date order."""
    pool = [[] for _ in range(SESSION_BARS)]
    for _, D in sessions:
        for i in range(1, SESSION_BARS):
            pc = D[i - 1]["c"]
            pool[i].append((D[i]["o"] / pc, D[i]["h"] / pc, D[i]["l"] / pc, D[i]["c"] / pc))
    return pool


def pct(a, q):
    return a[min(len(a) - 1, int(q * len(a)))]


def net_r(entry, exit_price, risk, long, exit_fee):
    """A trade's result after fees, in units of the plan's risk: limit entry at maker, exit at exit_fee."""
    gross = (exit_price - entry) if long else (entry - exit_price)
    return (gross - entry * MAKER - exit_price * exit_fee) / risk


def simulate(pool, entry, stop, target, k, last, replays=10000, seed=19, window=2, side="buy"):
    """Monte Carlo replays of bars k+1..last. Same draws and order as the reel's sim.py."""
    long = side == "buy"
    risk = (entry - stop) if long else (stop - entry)
    r_target = round(((target - entry) if long else (entry - target)) / risk, 4)

    def slot(rng, i):
        return i if window == 0 else min(SESSION_BARS - 1, max(1, i + rng.randint(-window, window)))

    rng = random.Random(seed)
    choice = rng.choice
    outcomes, closes, paths = [], [], []
    for n in range(replays):
        p = entry
        outcome = None
        keep = n < SAMPLE_PATHS
        path = [entry]
        for i in range(k + 1, last + 1):
            o, h, l, c = choice(pool[slot(rng, i)])
            hi, lo, cl = p * h, p * l, p * c
            if outcome is None:
                if long:
                    if lo <= stop:
                        outcome = "stop"        # both inside one bar: count the loss (conservative)
                    elif hi >= target:
                        outcome = "target"
                else:
                    if hi >= stop:
                        outcome = "stop"
                    elif lo <= target:
                        outcome = "target"
            p = cl
            if keep:
                path.append(rnd(p))
        outcomes.append(outcome or "close")
        closes.append(p)
        if keep:
            paths.append(path)
    cnt = {x: outcomes.count(x) for x in ("target", "stop", "close")}
    green = sum(1 for o, p in zip(outcomes, closes)
                if o == "target" or (o == "close" and (p > entry if long else p < entry)))
    Rs = [r_target if o == "target" else -1.0 if o == "stop" else ((p - entry) if long else (entry - p)) / risk
          for o, p in zip(outcomes, closes)]
    # The same replays after Binance fees, in units of the plan's risk: a win is worth less
    # than the target's R and a loss costs more than 1R.
    win = net_r(entry, target, risk, long, MAKER)
    loss = net_r(entry, stop, risk, long, TAKER)
    net = [win if o == "target" else loss if o == "stop" else net_r(entry, p, risk, long, TAKER)
           for o, p in zip(outcomes, closes)]
    srt = sorted(closes)
    # percentile bands per bar for the fan chart: a second run of 2,000 paths, same seed
    rng = random.Random(seed)
    choice = rng.choice
    allp = []
    for n in range(BAND_PATHS):
        p = entry
        path = [entry]
        for i in range(k + 1, last + 1):
            o, h, l, c = choice(pool[slot(rng, i)])
            p = p * c
            path.append(p)
        allp.append(path)
    bands = []
    for j in range(last - k + 1):
        col = sorted(pp[j] for pp in allp)
        bands.append([rnd(pct(col, q)) for q in BAND_Q])
    lo_, hi_ = pct(srt, 0.01), pct(srt, 0.99)
    W = (hi_ - lo_) / HIST_BINS
    bins = [0] * HIST_BINS
    for c in srt:
        b = int((c - lo_) / W) if W > 0 else 0
        if 0 <= b < HIST_BINS:
            bins[b] += 1
    return {
        "replays": replays, "seed": seed, "window": window, "bars_left": last - k,
        "p_target": round(cnt["target"] / replays, 4), "p_stop": round(cnt["stop"] / replays, 4),
        "p_neither": round(cnt["close"] / replays, 4), "p_green": round(green / replays, 4),
        "median_close": rnd(pct(srt, 0.5)), "p5_close": rnd(pct(srt, 0.05)),
        "p95_close": rnd(pct(srt, 0.95)), "avg_R": round(statistics.mean(Rs), 3),
        "r_at_target": r_target, "band_paths": BAND_PATHS, "bands": bands, "sample_paths": paths,
        "net": {"win_R": round(win, 3), "loss_R": round(loss, 3), "avg_R": round(statistics.mean(net), 3),
                "break_even": round(-loss / (win - loss), 4)},
        "hist": {"lo": rnd(lo_), "hi": rnd(hi_), "bins": bins},
    }


# ---------------------------------------------------------------- stop rules and the history replay

def cents_away(x, long):
    """Round a stop to the coin's tick, away from the entry: down for a buy, up for a sell."""
    t = tick(x)
    c = round(x / t, 4)
    return round((math.floor(c) if long else math.ceil(c)) * t, 10)


def opening_range(D, n):
    """(high, low) of the first n bars of a session given as {slot: bar} or a list."""
    rows = [D[i] for i in range(n)]
    return max(b["h"] for b in rows), min(b["l"] for b in rows)


def rule_stop(rule, oh, ol, entry, long):
    r = rule["stop_rule"]
    if r == "or_mid":
        return cents_away((oh + ol) / 2, long)
    if r in ("or_low", "or_high"):
        return cents_away(ol if long else oh, long)
    frac = rule["stop_pct"] / 100.0
    return cents_away(entry * (1 - frac) if long else entry * (1 + frac), long)


def history_replay(sessions, rule, last, side="buy"):
    """The plan's rule on every past full session: entry = the first candle after the
    opening range to close beyond it, `confirm` in a row (anywhere in the window), then
    stop first, then target, candle by candle, else the close after `hold` minutes."""
    long = side == "buy"
    n = rule["or_minutes"] // BM
    hold = rule.get("hold") or HOLD
    trades = []
    for d, D in sessions:
        oh, ol = opening_range(D, n)
        need = rule.get("confirm", 1)
        out = lambda i: D[i]["c"] > oh if long else D[i]["c"] < ol
        kk = next((i for i in range(n + need - 1, min(SESSION_BARS - 1, ENTRY_MIN // BM))
                   if all(out(j) for j in range(i - need + 1, i + 1))), None)
        if kk is None:
            continue
        e = rnd(D[kk]["c"])
        s = rule_stop(rule, oh, ol, e, long)
        risk = (e - s) if long else (s - e)
        if risk <= 0:
            continue
        t = rnd(e + rule["target_r"] * risk) if long else rnd(e - rule["target_r"] * risk)
        oc = None
        end = min(SESSION_BARS - 1, kk + hold)
        for b in D[kk + 1:end + 1]:
            if (b["l"] <= s) if long else (b["h"] >= s):
                oc = "stop"
                break
            if (b["h"] >= t) if long else (b["l"] <= t):
                oc = "target"
                break
        cl = D[end]["c"]
        R = ((t - e) if long else (e - t)) / risk if oc == "target" else -1.0 if oc == "stop" else \
            ((cl - e) if long else (e - cl)) / risk
        Rn = net_r(e, t, risk, long, MAKER) if oc == "target" else net_r(e, s, risk, long, TAKER) if oc == "stop" \
            else net_r(e, cl, risk, long, TAKER)
        trades.append({"date": d, "time": clock12(open_utc(d) + BM * (kk + 1)), "entry": e, "stop": s, "target": t,
                       "outcome": oc or "close", "R": round(R, 2), "R_net": round(Rn, 2)})
    return {
        "sessions": len(sessions), "triggered": len(trades),
        "target": sum(1 for x in trades if x["outcome"] == "target"),
        "stop": sum(1 for x in trades if x["outcome"] == "stop"),
        "close": sum(1 for x in trades if x["outcome"] == "close"),
        "green": sum(1 for x in trades if x["R"] > 0),
        "avg_R": round(statistics.mean(x["R"] for x in trades), 3) if trades else None,
        "avg_R_net": round(statistics.mean(x["R_net"] for x in trades), 3) if trades else None,
        "rule": rule, "trades": trades,
    }


# ---------------------------------------------------------------- the plan

def _num(v, what):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise TMError("the plan needs a number for %s, got %r" % (what, v))
    if not x > 0 or math.isinf(x):
        raise TMError("the plan's %s must be a positive price, got %r" % (what, v))
    return x


def load_plan(a, now_utc):
    """The plan from --plan (trader/plan.json) or from the flags, checked and normalized."""
    if a.symbol:
        missing = [f for f in ("entry", "stop", "target", "entry_time") if getattr(a, f) is None]
        if missing:
            raise TMError("with --symbol also give %s" % ", ".join("--" + m.replace("_", "-") for m in missing))
        raw = {"symbol": a.symbol, "side": a.side, "date": a.date or session_day(now_utc).isoformat(),
               "entry": a.entry, "stop": a.stop, "target": a.target, "entry_time": a.entry_time,
               "setup": a.setup, "opening_range": {"minutes": a.or_minutes}, "stop_rule": a.stop_rule,
               "interval": "1m", "hold_minutes": a.hold, "confirm": a.confirm}
        src = "flags"
    else:
        if not os.path.exists(a.plan):
            raise TMError("no plan at %s: run /scalp-exit first, or pass --symbol --date --entry --stop "
                          "--target --entry-time" % a.plan)
        try:
            with open(a.plan, encoding="utf-8") as fh:
                raw = json.load(fh)
        except ValueError as e:
            raise TMError("%s is not valid JSON: %s" % (a.plan, e))
        if not isinstance(raw, dict):
            raise TMError("%s is not a plan" % a.plan)
        src = a.plan
    return normalize_plan(raw, src)


def normalize_plan(raw, src="flags"):
    """A plan dict (trader/plan.json shape) -> the checked plan the time machine runs."""
    sym = str(raw.get("symbol") or "").strip().upper()
    if not re.match(r"^[A-Z0-9][A-Z0-9.\-/]{0,14}$", sym):
        raise TMError("the plan needs a crypto symbol like ETH or ETH-USD, got %r" % raw.get("symbol"))
    sym = yahoo_symbol(sym)
    side = str(raw.get("side") or "buy").lower()
    if side not in ("buy", "sell"):
        raise TMError("side must be buy or sell, got %r" % raw.get("side"))
    interval = str(raw.get("interval") or "1m")
    if interval != "1m":
        raise TMError("1-minute candles only (the plan says %s): for 5-minute plans use crypto-timemachine "
                      "from skill-cryptos-jeto1337" % interval)
    try:
        date = datetime.date.fromisoformat(str(raw.get("date") or "")).isoformat()
    except ValueError:
        raise TMError("the plan needs a date like 2026-10-19, got %r" % raw.get("date"))
    entry, stop, target = (_num(raw.get(k), k) for k in ("entry", "stop", "target"))
    set_plan_day(datetime.date.fromisoformat(date))
    long = side == "buy"
    if long and not stop < entry < target:
        raise TMError("a buy needs stop < entry < target (got stop %s, entry %s, target %s)" % (stop, entry, target))
    if not long and not target < entry < stop:
        raise TMError("a sell needs target < entry < stop (got target %s, entry %s, stop %s)" % (target, entry, stop))
    k = None
    if raw.get("entry_time"):
        rel = parse_clock(raw["entry_time"], "entry_time") - OPEN_MIN
        if rel <= 0:
            rel += DAY          # after UTC midnight, in a session that opened the day before
        k = rel // BM - 1
    if raw.get("entry_bar") is not None:
        try:
            kb = int(raw["entry_bar"])
        except (TypeError, ValueError):
            raise TMError("entry_bar must be a bar number, got %r" % raw["entry_bar"])
        if k is not None and kb != k:
            raise TMError("the plan disagrees with itself: entry_bar %d but entry_time %s is bar %d"
                          % (kb, raw["entry_time"], k))
        k = kb
    if k is None:
        raise TMError("the plan needs entry_time (the entry bar's close, UTC, e.g. 14:00) or entry_bar")
    if not 0 <= k <= SESSION_BARS - 2:
        raise TMError("the entry must close between %s and %s, inside the session window, to leave bars "
                      "to replay (got %s); pick another --session if needed"
                      % (clock12(OPEN_MIN + BM), clock12(CLOSE_MIN - BM), clock12(OPEN_MIN + BM * (k + 1))))
    orng = raw.get("opening_range") or {}
    or_min = orng.get("minutes", 5) if isinstance(orng, dict) else 5
    try:
        or_min = int(or_min)
    except (TypeError, ValueError):
        raise TMError("opening_range.minutes must be a number")
    if or_min < 1 or or_min >= (CLOSE_MIN - OPEN_MIN):
        raise TMError("opening_range.minutes must be between 1 and the window's length (got %s)" % or_min)
    try:
        hold = int(raw.get("hold_minutes") or HOLD)
    except (TypeError, ValueError):
        raise TMError("hold_minutes must be a number of minutes")
    if not 1 <= hold <= SESSION[2]:
        raise TMError("hold_minutes must be between 1 and %d" % SESSION[2])
    risk = (entry - stop) if long else (stop - entry)
    return {
        "symbol": sym, "side": side, "date": date, "setup": str(raw.get("setup") or "orb"),
        "entry": entry, "entry_time": clock12(OPEN_MIN + BM * (k + 1)), "entry_bar": k, "hold_minutes": hold,
        "stop": stop, "target": target, "risk_per_share": rnd(risk),
        "target_r": round(((target - entry) if long else (entry - target)) / risk, 2),
        "opening_range": dict(orng, minutes=or_min) if isinstance(orng, dict) else {"minutes": or_min},
        "stop_rule": str(raw.get("stop_rule") or "auto"), "interval": "1m",
        "flat_by": raw.get("flat_by"), "from": src, "confirm": int(raw.get("confirm") or 1),
    }


def resolve_rule(plan, entry_day):
    """The rule the history replay uses: orb, the plan's opening range, its stop rule
    (or_mid, or_low / or_high, or 'pct' = the plan's stop distance as a percent of
    the entry), and the plan's target R. 'auto' works the stop rule out from the
    plan day's own opening range. None when the setup is not orb."""
    if plan["setup"].lower() != "orb":
        return None
    long = plan["side"] == "buy"
    n = plan["opening_range"]["minutes"] // BM
    rule = {"setup": "orb", "or_minutes": plan["opening_range"]["minutes"], "stop_rule": plan["stop_rule"],
            "target_r": plan["target_r"], "confirm": plan.get("confirm", 1), "hold": plan["hold_minutes"],
            "stop_pct": round(100.0 * plan["risk_per_share"] / plan["entry"], 4)}
    far = "or_low" if long else "or_high"
    if rule["stop_rule"] == "auto":
        rule["stop_rule"] = "pct"
        if all(i in entry_day for i in range(n)):
            oh, ol = opening_range(entry_day, n)
            if abs(cents_away((oh + ol) / 2, long) - plan["stop"]) < tick(plan["stop"]) / 2:
                rule["stop_rule"] = "or_mid"
            elif abs(cents_away(ol if long else oh, long) - plan["stop"]) < tick(plan["stop"]) / 2:
                rule["stop_rule"] = far
    elif rule["stop_rule"] in ("or_low", "or_high") and rule["stop_rule"] != far:
        rule["stop_rule"] = "pct"
    elif rule["stop_rule"] not in ("or_mid", far):
        rule["stop_rule"] = "pct"
    if rule["stop_rule"] != "pct":
        del rule["stop_pct"]
    return rule


# ---------------------------------------------------------------- the run

def _until12(mc):
    t = mc.get("until") or clock24(CLOSE_MIN)
    return clock12(int(t[:2]) * 60 + int(t[3:]))


def lean(mc):
    """(gap, share, break_even): the target's share of the replays that hit one side,
    minus the share that breaks even at the target's R. None when nothing hit a side."""
    pt, ps = mc["p_target"], mc["p_stop"]
    if pt + ps <= 0:
        return None
    r = mc.get("r_at_target") or 1.0
    share, even = pt / (pt + ps), 1.0 / (1.0 + r)
    return share - even, share, even


def verdict(mc):
    """One line from the numbers, see the docstring for the thresholds."""
    pt, ps = mc["p_target"], mc["p_stop"]
    lv = lean(mc)
    if lv is None:
        return "No replay reached the target or the stop by %s: the price at %s decides every one." % (
            _until12(mc), _until12(mc))
    d, share, even = lv
    r = mc.get("r_at_target") or 1.0
    one_r = abs(r - 1.0) < 0.005
    if abs(d) < COIN_FLIP:
        head = "Close to a coin flip" if one_r else "Close to break-even"
    elif abs(d) < STRONG:
        head = "Leans toward the target" if d > 0 else "Leans toward the stop"
    else:
        head = "Strongly toward the target" if d > 0 else "Strongly toward the stop"
    odds = "target first %.1f %% vs stop first %.1f %%" % (100 * pt, 100 * ps)
    if one_r:
        return "%s: %s." % (head, odds)
    return ("%s: at %gR the target has to come first in %.0f %% of the replays that hit one side; "
            "it did in %.0f %% (%s)." % (head, round(r, 2), 100 * even, 100 * share, odds))


def verdict_net(mc):
    """The same comparison after fees: the lines that count for a scalp."""
    n = mc.get("net")
    if not n:
        return []
    out = ["After Binance fees (entry and target 0.02 %%, stop and time exits 0.05 %%): a win is worth %+.2fR and a "
           "loss costs %.2fR. Average R after fees: %+.3f." % (n["win_R"], -n["loss_R"], n["avg_R"])]
    pt, ps = mc["p_target"], mc["p_stop"]
    if pt + ps > 0:
        share, even = pt / (pt + ps), n["break_even"]
        d = share - even
        if abs(d) < COIN_FLIP:
            head = "close to break-even"
        elif abs(d) < STRONG:
            head = "leans toward the target" if d > 0 else "leans toward the stop"
        else:
            head = "strongly toward the target" if d > 0 else "strongly toward the stop"
        out.append("Verdict after fees: %s. The target has to come first in %.0f %% of the replays that hit one "
                   "side to pay the fees; it did in %.0f %%." % (head, 100 * even, 100 * share))
    return out


def verdict_notes(mc):
    """The lines printed right below the verdict, so nothing reads as one-sided."""
    notes = []
    pn = mc.get("p_neither", 0)
    if pn > MANY_NEITHER and lean(mc) is not None:
        notes.append("%.1f %% of the replays hit neither by %s; the price at %s decides those."
                     % (100 * pn, _until12(mc), _until12(mc)))
    lv = lean(mc)
    avg = mc.get("avg_R")
    if lv and abs(lv[0]) >= COIN_FLIP and avg is not None and avg != 0 and (avg > 0) != (lv[0] > 0):
        notes.append("Average R is %+.3f all the same: the replays that hit neither pull it the other way." % avg)
    return notes


def time_machine(text, plan, now_utc, replays=10000, seed=19, window=2, until=None, source="yahoo"):
    """Chart JSON text + a normalized plan -> the timemachine.json document."""
    if not 1 <= replays <= 1000000:
        raise TMError("--replays must be between 1 and 1,000,000")
    if not 0 <= window <= 10:
        raise TMError("--window must be between 0 and 10 bars")
    sym = plan["symbol"]
    result = chart_result(text, sym)
    meta, bars, dropped = parse_bars(result, now_utc)
    msym = str(meta.get("symbol") or "").upper()
    if msym and msym != sym:
        raise TMError("the data is for %s but the plan is for %s" % (msym, sym))
    gran = meta.get("dataGranularity")
    if gran and gran != "1m":
        raise TMError("the data has %s bars; the scalping time machine needs 1-minute candles" % gran)
    if not bars:
        raise TMError("no complete 1-minute candles for %s in the window" % sym)
    k = plan["entry_bar"]
    end_min = CLOSE_MIN
    if until is None and plan.get("flat_by"):
        until = plan["flat_by"]
    if until is None:
        rel = BM * (k + 1) + plan["hold_minutes"]
    else:
        rel = parse_clock(until, "--until") - OPEN_MIN
        if rel <= 0:
            rel += DAY          # the time stop falls after UTC midnight
    until_min = min(end_min, OPEN_MIN + rel)
    last = (until_min - OPEN_MIN) // BM - 1
    if last <= k:
        raise TMError("--until %s leaves nothing to replay after the %s entry" % (clock12(until_min),
                                                                             plan["entry_time"]))
    days = split_sessions(bars)
    entry_day = days.get(plan["date"], {})
    if k not in entry_day:
        reason = ("no bars for that day" if not entry_day else
                  "the data stops at the %s bar" % entry_day[max(entry_day)]["start"])
        raise TMError("the entry is not in the data: no complete %s bar (closing %s) on %s for %s (%s)"
                      % (clock24(OPEN_MIN + BM * k), plan["entry_time"], plan["date"], sym, reason))
    eb = entry_day[k]
    warn = []
    if not eb["l"] - tick(eb["l"]) <= plan["entry"] <= eb["h"] + tick(eb["h"]):
        warn.append("the plan's entry %g is outside that bar's range %g to %g"
                    % (plan["entry"], eb["l"], eb["h"]))
    sessions, short = full_sessions(days, plan["date"])
    if len(sessions) < MIN_SESSIONS:
        raise TMError("only %d full session(s) of %s before %s in the data; the time machine needs at least %d"
                      % (len(sessions), sym, plan["date"], MIN_SESSIONS))
    pool = build_pool(sessions)
    mc = simulate(pool, plan["entry"], plan["stop"], plan["target"], k, last, replays, seed, window, plan["side"])
    mc = dict(mc, until=clock24(until_min), pool_sessions=len(sessions), pool_from=sessions[0][0],
              pool_to=sessions[-1][0],
              band_times=[clock24(OPEN_MIN + BM * (j + 1)) for j in range(k, last + 1)])
    rule = resolve_rule(plan, entry_day)
    plan_out = {kk: v for kk, v in plan.items() if v is not None}
    if rule:
        plan_out["stop_rule"] = rule["stop_rule"]
        history = history_replay(sessions, rule, last, plan["side"])
    else:
        history = {"sessions": len(sessions), "triggered": 0, "rule": None, "trades": [],
                   "note": "skipped: the history replay knows the opening-range breakout (orb) only, "
                           "this plan's setup is %r" % plan["setup"]}
    last_bar = bars[-1]
    return {
        "created_by": "scalp-timemachine",
        "created_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
        "data": {"symbol": msym or sym, "interval": "1m", "range": "28d",
                 "last_bar": "%s %s UTC" % (last_bar["date"], last_bar["start"]),
                 "session": SESSION_NAME, "window_utc": "%s-%s" % (clock24(OPEN_MIN), clock24(CLOSE_MIN)),
                 "dropped": dropped, "short_sessions_left_out": short},
        "plan": plan_out,
        "mc": mc,
        "history": history,
        "verdict": verdict(mc),
        "verdict_notes": verdict_notes(mc),
        "verdict_net": verdict_net(mc),
        "warnings": warn,
        "note": ("A simulation built from %s's own last %d full sessions (%s, %s-%s UTC on the plan day). "
                 "It is not a prediction: news, liquidations and exchange outages can do things those "
                 "sessions never did. Same seed, same numbers."
                 % (sym, len(sessions), SESSION_NAME, clock24(OPEN_MIN), clock24(CLOSE_MIN))),
    }


# ---------------------------------------------------------------- output

def pc(x):
    return "%.1f %%" % (100.0 * x)


def report(doc):
    p, m, h = doc["plan"], doc["mc"], doc["history"]
    long = p["side"] == "buy"
    until = clock12(int(m["until"][:2]) * 60 + int(m["until"][3:]))
    wd = WEEKDAYS[datetime.date.fromisoformat(p["date"]).weekday()]
    r = p["target_r"]
    lines = [
        "%s %s, %s %s: entry %g at %s (bar %d), stop %g, target %g (%sR, risk %g a coin)."
        % (p["symbol"], p["side"], wd, p["date"], p["entry"], p["entry_time"], p["entry_bar"], p["stop"],
           p["target"], ("%g" % r), p["risk_per_share"]),
        "%s replays from the entry to the time stop, %s to %s (%d one-minute candles), seed %d."
        % ("{:,}".format(m["replays"]), p["entry_time"], until, m["bars_left"], m["seed"]),
        "Each candle is drawn whole from %s's own 1-minute candles at the same UTC time (+-%d minutes) over its last "
        "%d full sessions (%s to %s)." % (p["symbol"], m["window"], m["pool_sessions"], m["pool_from"], m["pool_to"]),
        "",
        "  target first   %s" % pc(m["p_target"]),
        "  stop first     %s" % pc(m["p_stop"]),
        "  neither        %-8s still open at %s" % (pc(m["p_neither"]), until),
        "  green          %-8s target first, or %s the entry at %s" % (pc(m["p_green"]),
                                                                       "above" if long else "below", until),
        "",
        "  Price at %s: median %g, 90 %% of replays between %g and %g."
        % (until, m["median_close"], m["p5_close"], m["p95_close"]),
        "  Average R: %+.3f (R = the %g risk: %sR at the target, -1R at the stop)."
        % (m["avg_R"], p["risk_per_share"], ("+%g" % m["r_at_target"]), ),
        "",
    ]
    if h.get("rule"):
        ru = h["rule"]
        stop_words = {"or_mid": "opening-range midpoint", "or_low": "opening-range low",
                      "or_high": "opening-range high"}.get(ru["stop_rule"],
                                                           "%g %% from the entry" % ru.get("stop_pct", 0))
        if h["triggered"]:
            lines.append("History: the same rule (%d-min opening range%s, stop at the %s, %gR target) on each of "
                         "those %d real sessions fired %d times: %d target, %d stop, %d neither. Average R %+.3f"
                         "%s."
                         % (ru["or_minutes"], (", %d closes in a row outside" % ru["confirm"])
                            if ru.get("confirm", 1) > 1 else "", stop_words, ru["target_r"], h["sessions"],
                            h["triggered"], h["target"], h["stop"], h["close"], h["avg_R"],
                            (", %+.3f after fees" % h["avg_R_net"]) if h.get("avg_R_net") is not None else ""))
        else:
            lines.append("History: the same rule never fired in those %d sessions." % h["sessions"])
    else:
        lines.append("History: " + h.get("note", "skipped."))
    lines += ["", doc["verdict"]] + list(doc.get("verdict_notes") or []) + list(doc.get("verdict_net") or []) + [""]
    for w in doc.get("warnings") or []:
        lines.append("Note: " + w + ".")
    if doc["data"]["short_sessions_left_out"]:
        lines.append("Left out %d short session(s) (data gaps): %s."
                     % (len(doc["data"]["short_sessions_left_out"]),
                        ", ".join(x["date"] for x in doc["data"]["short_sessions_left_out"])))
    lines.append(doc["note"] + " Repeat this run with --seed %d." % m["seed"])
    return lines


def render_chart(doc, height=17):
    """ASCII fan chart of the bands: one column per 1-minute candle."""
    p, m = doc["plan"], doc["mc"]
    bands, times = m["bands"], m["band_times"]
    lo = min([b[0] for b in bands] + [p["stop"], p["target"]])
    hi = max([b[4] for b in bands] + [p["stop"], p["target"]])
    pad = (hi - lo) * 0.04 or 0.01
    lo, hi = lo - pad, hi + pad
    step = (hi - lo) / (height - 1)

    def row(price):
        return max(0, min(height - 1, int(round((hi - price) / step))))
    grid = [[" "] * len(bands) for _ in range(height)]
    for j, b in enumerate(bands):
        r5, r25, r50, r75, r95 = [row(x) for x in b]
        for r in range(r95, r5 + 1):
            grid[r][j] = "."
        for r in range(r75, r25 + 1):
            grid[r][j] = ":"
        grid[r50][j] = "*"
    marks = {row(p["target"]): "target", row(p["stop"]): "stop"}
    if row(p["entry"]) not in marks:
        marks[row(p["entry"])] = "entry"
    for r in (row(p["target"]), row(p["stop"])):
        grid[r] = ["-" if ch == " " else ch for ch in grid[r]]
    out = ["%s %s, %s replay paths from the %s entry (seed %d)" % (
        p["symbol"], p["date"], "{:,}".format(m.get("band_paths", BAND_PATHS)), p["entry_time"], m["seed"])]
    for r in range(height):
        label = marks.get(r)
        price = {"target": p["target"], "stop": p["stop"], "entry": p["entry"]}.get(label, hi - r * step)
        left = ("%9.5g |" % price) if (label or r in (0, height - 1)) else "          |"
        out.append(left + "".join(grid[r]) + ("  " + label if label else ""))
    axis = [" "] * len(bands)
    for j in sorted({0, len(bands) // 2, len(bands) - 1}):
        t = times[j]
        hh, mm = int(t[:2]), t[3:]
        lab = "%02d:%s" % (hh, mm)
        s = max(0, min(j, len(bands) - len(lab)))
        axis[s:s + len(lab)] = list(lab)
    out.append("          +" + "-" * len(bands))
    out.append("           " + "".join(axis))
    out.append("* median   : middle half of the paths   . 90 % of the paths   - stop and target")
    return out


# ---------------------------------------------------------------- commands

def _write(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
        fh.write("\n")


def compute(a):
    now = parse_now(a.now)
    plan = load_plan(a, now)
    if a.offline:
        text, source = read_offline(a.offline, plan["symbol"]), "offline"
    else:
        text = fetch_chart(plan["symbol"], now)
        source = SOURCE_USED.lower()
    return time_machine(text, plan, now, a.replays, a.seed, a.window, a.until, source)


def cmd_run(a):
    doc = compute(a)
    if a.write:
        _write(a.write, doc)
    if a.json:
        slim = dict(doc, mc={k: v for k, v in doc["mc"].items() if k != "sample_paths"})
        print(json.dumps(slim, indent=2))
    else:
        print("\n".join(report(doc)))
        if a.write:
            print("Wrote %s." % a.write)
        if doc.get("source") != "offline":
            print("Prices from %s." % SOURCE_USED)
        print("Next: /scalp-risk sizes it to your capital and checks your limits.")
    return 0


def cmd_chart(a):
    if a.from_file:
        if not os.path.exists(a.from_file):
            raise TMError("no %s: run timemachine.py run --write first" % a.from_file)
        try:
            with open(a.from_file, encoding="utf-8") as fh:
                doc = json.load(fh)
            doc["mc"]["bands"]
        except (ValueError, KeyError, TypeError):
            raise TMError("%s is not a time machine result" % a.from_file)
    else:
        doc = compute(a)
    print("\n".join(render_chart(doc)))
    print("\n".join([doc.get("verdict", "")] + list(doc.get("verdict_notes") or [])
                    + list(doc.get("verdict_net") or [])))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Time Machine: replay a planned crypto scalp (scalp-timemachine).")
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--plan", default="trader/plan.json", help="the plan from scalp-exit")
        p.add_argument("--symbol", help="or give the plan as flags: ETH, BTC-USD, SOLUSDT ...")
        p.add_argument("--session", choices=sorted(SESSIONS) + ["utc"],
                       help="the daily window (default: the plan's, else wallstreet)")
        p.add_argument("--open", help="with --session utc: the session's start, HH:MM UTC")
        p.add_argument("--side", default="buy", choices=["buy", "sell"])
        p.add_argument("--date", help="the day the session opened, YYYY-MM-DD (default: the session now running)")
        p.add_argument("--entry", type=float)
        p.add_argument("--stop", type=float)
        p.add_argument("--target", type=float)
        p.add_argument("--entry-time", help="the entry bar's close, UTC, e.g. 14:00")
        p.add_argument("--setup", default="orb")
        p.add_argument("--or-minutes", type=int, default=5)
        p.add_argument("--hold", type=int, default=HOLD, help="with --symbol: minutes in the trade at most")
        p.add_argument("--confirm", type=int, default=2,
                       help="with --symbol: closes in a row the history's rule waits for (scalp-entry's default, 2)")
        p.add_argument("--stop-rule", default="auto", choices=["auto", "or_mid", "or_low", "or_high", "pct"])
        p.add_argument("--replays", type=int, default=10000)
        p.add_argument("--seed", type=int, default=19)
        p.add_argument("--window", type=int, default=2, help="draw from the same minute +- this many minutes")
        p.add_argument("--until", help="end each replay at this UTC time (default: the plan's flat_by)")
        p.add_argument("--offline", metavar="FILE", help="a saved Yahoo chart JSON (.json or .json.gz), no network")
        p.add_argument("--now", help='pretend it is this UTC time, e.g. "2026-11-05 14:00"')
        p.add_argument("--source", default="auto", choices=["auto", "binance", "yahoo"],
                       help="where the candles come from: Binance first and Yahoo as a fallback (auto), or one")

    p = sub.add_parser("run", help="replay the plan: 10,000 simulated sessions plus the history")
    common(p)
    p.add_argument("--json", action="store_true")
    p.add_argument("--write", nargs="?", const="trader/timemachine.json", metavar="PATH",
                   help="save the result (default trader/timemachine.json)")
    p = sub.add_parser("chart", help="ASCII fan chart of the replays")
    common(p)
    p.add_argument("--from", dest="from_file", nargs="?", const="trader/timemachine.json", metavar="PATH",
                   help="draw a saved result instead of running again")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        session, opn = a.session, a.open
        if not a.symbol and os.path.exists(a.plan):
            try:
                with open(a.plan, encoding="utf-8") as fh:
                    raw = json.load(fh) or {}
                session, opn = session or raw.get("session"), opn or raw.get("open_utc")
            except (OSError, ValueError):
                pass
        global SOURCE
        SOURCE = a.source
        set_session(session if session in SESSIONS or session == "utc" else "wallstreet", opn)
        return {"run": cmd_run, "chart": cmd_chart}[a.cmd](a)
    except TMError as e:
        print("timemachine.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
