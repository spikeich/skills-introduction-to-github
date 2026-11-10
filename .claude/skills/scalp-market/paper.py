#!/usr/bin/env python3
"""Paper-trade a scalp: plays the plan from /scalp-exit (trader/plan.json) on real
1-minute candles, with Binance futures fees, and says what it would have made.
Nothing is sent to any exchange. Standard library only.

    python3 paper.py --capital 3000                         # live: waits for each new 1-minute candle
    python3 paper.py --capital 3000 --risk 0.5 --lev 10
    python3 paper.py --capital 3000 --offline BTC-1m.json   # replay on saved candles, instantly

The rules, candle by candle (the candle's high and low, so a wick counts):
  fill     a limit order at the plan's entry, from the candle after the signal: a buy
           fills when the price is AT OR BELOW the entry, a sell when it is at or above
           (a price that is already through the limit fills it at once: a limit order
           does not protect you from a move against you, only from chasing the price).
           Not reached within --fill-minutes (3): cancelled, nothing happens.
  stop     touched from the fill candle on: out at the stop (taker fee). On the fill
           candle the stop counts, because the price passes the entry before it can
           reach the stop.
  target   touched after the fill candle: out at the target (maker fee). On the fill
           candle it does not count: the price may have been there before the fill.
           A candle that touches both counts as the stop.
  time     the plan's flat_by (entry + 20 minutes by default): out at that
           candle's close (taker fee), win or lose.

Size: the quantity that loses --risk % of --capital at the stop, fees included
(the same as /scalp-risk). Fees: entry maker 0.02 %, stop and time exits taker
0.05 %, target maker 0.02 %. Real fills can be worse, above all at the stop.

Prices: Binance's 1-minute candles first (data-api.binance.vision: the exchange's own
prices), then Yahoo's 1-minute chart; --source binance|yahoo picks one. Each line on stdout is
an event, so it can run under a monitor. Exit code 0 when the trade ended (or
was cancelled), 1 on an error.
"""
import argparse
import concurrent.futures
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

MAKER, TAKER = 0.0002, 0.0005
UA = "Mozilla/5.0 (compatible; scalp-market/1.0)"
EPOCH = dt.datetime(1970, 1, 1)


class PaperError(Exception):
    pass


def say(msg):
    print(msg, flush=True)


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


def candles(sym, offline=None, since=None):
    """[(start, open, high, low, close)] of 1-minute candles, oldest first (from `since` on,
    a naive UTC datetime, when the source can start there)."""
    global SOURCE_USED
    doc = None
    if offline:
        doc = json.load(open(offline, encoding="utf-8"))
    elif SOURCE in ("auto", "binance"):
        start = int((since - EPOCH).total_seconds()) - 300 if since else None
        doc = binance_chart(sym, "1m", start=start, bars=360)      # from the signal on, else the last 6 hours
        if doc:
            SOURCE_USED = binance_name(doc)
        elif SOURCE == "binance":
            raise PaperError("Binance has no candles for %s, or did not answer: try --source yahoo" % sym)
    if doc is None:
        SOURCE_USED = "Yahoo"
        url = "https://query2.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=1m" % urllib.parse.quote(sym)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                doc = json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            raise PaperError("could not reach Yahoo (is query2.finance.yahoo.com allowed?): %s" % e)
    res = ((doc.get("chart") or {}).get("result") or [None])[0] or {}
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    out = []
    for i, t in enumerate(res.get("timestamp") or []):
        row = [(q.get(k) or [None] * (i + 1))[i] for k in ("open", "high", "low", "close")]
        if t is None or None in row or int(t) % 60:
            continue
        out.append((EPOCH + dt.timedelta(seconds=int(t)),) + tuple(row))
    return out


def size(capital, risk_pct, entry, stop, lev):
    risk_usd = capital * risk_pct / 100
    qty = risk_usd / (abs(entry - stop) + entry * MAKER + stop * TAKER)
    return {"qty": qty, "notional": qty * entry, "margin": qty * entry / lev, "risk_usd": risk_usd}


def at(plan, hhmm):
    h, m = (int(x) for x in hhmm.split(":"))
    return dt.datetime.combine(dt.date.fromisoformat(plan["date"]), dt.time(h, m))


def plan_time(plan, key_at, key_hm, after=None):
    """The plan's full UTC time (entry_at / flat_at) when it has one; else its date and
    HH:MM, moved to the next day when that falls before `after` (a trade that crosses
    UTC midnight)."""
    if plan.get(key_at):
        return dt.datetime.strptime(plan[key_at], "%Y-%m-%d %H:%M")
    t = at(plan, plan[key_hm])
    if after is not None and t <= after:
        t += dt.timedelta(days=1)
    return t


def close_trade(st, plan, when, px, kind, fee):
    long = plan["side"] == "buy"
    e, q = plan["entry"], st["qty"]
    gross = (px - e) * q if long else (e - px) * q
    fees = e * q * MAKER + px * q * fee
    pnl = gross - fees
    st.update(state="CLOSED", exit_time=when, exit=px, kind=kind, pnl=round(pnl, 2), fees=round(fees, 2))
    return "%s UTC  %s en %g: %+.2f USD (comisiones %.2f, %.2fR)" % (when, kind, px, pnl, fees, pnl / st["risk_usd"])


def step(st, plan, c):
    """Advance the trade by one closed candle. Returns the event lines (none, one or two)."""
    start, o, h, l, cl = c
    long = plan["side"] == "buy"
    e, s, t = plan["entry"], plan["stop"], plan["target"]
    close_at = start + dt.timedelta(minutes=1)
    when = close_at.strftime("%H:%M")
    hit_stop = l <= s if long else h >= s
    hit_target = h >= t if long else l <= t
    if st["state"] == "WAIT":
        if (l <= e) if long else (h >= e):      # at or through the limit: the order fills
            st.update(state="OPEN", filled=when)
            lines = ["%s UTC  ENTRA %s %s en %g (orden límite llenada)" % (when, "LARGO" if long else "CORTO",
                                                                        plan["symbol"], e)]
            # The same candle: the price reaches the entry before it can reach the stop, so a stop
            # touched here came after the fill and counts. The target may have come before: it waits.
            if hit_stop:
                lines.append(close_trade(st, plan, when, s, "STOP", TAKER))
            return lines
        if close_at >= st["fill_deadline"]:
            st.update(state="CANCELLED", exit_time=when, pnl=0.0)
            return ["%s UTC  CANCELADA: el precio no llegó a %g en %d minutos. No pasó nada." % (
                when, e, st["fill_minutes"])]
        return []
    if st["state"] != "OPEN":
        return []
    if hit_stop:
        return [close_trade(st, plan, when, s, "STOP", TAKER)]
    if hit_target:
        return [close_trade(st, plan, when, t, "OBJETIVO", MAKER)]
    if close_at >= st["flat_by"]:
        return [close_trade(st, plan, when, cl, "SALIDA POR TIEMPO", TAKER)]
    return []


def main(argv=None):
    ap = argparse.ArgumentParser(description="Paper-trade a scalp plan on 1-minute candles (scalp-market).")
    ap.add_argument("--plan", default="trader/plan.json")
    ap.add_argument("--capital", type=float, required=True)
    ap.add_argument("--risk", type=float, default=0.5, help="%% of capital lost at the stop (default 0.5)")
    ap.add_argument("--lev", type=float, default=10.0)
    ap.add_argument("--fill-minutes", type=int, default=3)
    ap.add_argument("--state", default="trader/paper.json")
    ap.add_argument("--offline", help="a saved Yahoo 1-minute chart JSON: replay instantly")
    ap.add_argument("--poll", type=float, default=20, help="seconds between looks, live (default 20)")
    ap.add_argument("--source", default="auto", choices=["auto", "binance", "yahoo"],
                    help="where the candles come from: Binance first and Yahoo as a fallback (auto), or one")
    a = ap.parse_args(argv)
    global SOURCE
    SOURCE = a.source
    try:
        if not os.path.exists(a.plan):
            raise PaperError("no plan at %s: run /scalp-exit plan --write first" % a.plan)
        plan = json.load(open(a.plan, encoding="utf-8"))
        for k in ("symbol", "side", "entry", "stop", "target", "entry_time", "date", "flat_by"):
            if plan.get(k) in (None, ""):
                raise PaperError("the plan has no %s" % k)
        sz = size(a.capital, a.risk, plan["entry"], plan["stop"], a.lev)
        signal = plan_time(plan, "entry_at", "entry_time")
        st = {"state": "WAIT", "qty": sz["qty"], "risk_usd": sz["risk_usd"], "fill_minutes": a.fill_minutes,
              "fill_deadline": signal + dt.timedelta(minutes=a.fill_minutes),
              "flat_by": plan_time(plan, "flat_at", "flat_by", after=signal)}
        say("SIMULACIÓN %s %s: entrada %g, stop %g, objetivo %g, afuera a las %s UTC | %.6g unidades, %.2f USDT, "
            "margen %.2f a %gx, riesgo %.2f USD" % ("LARGO" if plan["side"] == "buy" else "CORTO", plan["symbol"],
                                                    plan["entry"], plan["stop"], plan["target"], plan["flat_by"],
                                                    sz["qty"], sz["notional"], sz["margin"], a.lev, sz["risk_usd"]))
        seen, errors = signal, 0
        while st["state"] in ("WAIT", "OPEN"):
            now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
            try:
                rows = candles(plan["symbol"], a.offline, signal)
                errors = 0
                if SOURCE_USED and not st.get("source"):
                    st["source"] = SOURCE_USED
                    say("Precios de %s." % SOURCE_USED)
            except PaperError as e:
                errors += 1
                if a.offline or errors >= 6:
                    raise
                say("(Yahoo no respondió, reintento en %d s: %s)" % (a.poll, e))
                time.sleep(a.poll)
                continue
            for c in rows:
                if c[0] < seen or c[0] + dt.timedelta(minutes=1) > (now if not a.offline else dt.datetime.max):
                    continue
                seen = c[0] + dt.timedelta(minutes=1)
                for line in step(st, plan, c):
                    say(line)
                if st["state"] not in ("WAIT", "OPEN"):
                    break
            if st["state"] in ("WAIT", "OPEN"):
                if a.offline:
                    raise PaperError("the saved candles end before the trade did")
                time.sleep(a.poll)
        doc = dict(st, fill_deadline=st["fill_deadline"].strftime("%H:%M"), flat_by=st["flat_by"].strftime("%H:%M"),
                   plan=plan, capital=a.capital, risk_pct=a.risk, lev=a.lev)
        d = os.path.dirname(a.state)
        if d:
            os.makedirs(d, exist_ok=True)
        json.dump(doc, open(a.state, "w", encoding="utf-8"), indent=1)
        if st["state"] == "CLOSED":
            say("Para anotarlo: python3 risk.py log --symbol %s --result %.2f" % (plan["symbol"].split("-")[0],
                                                                                st["pnl"]))
        return 0
    except PaperError as e:
        print("paper.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
