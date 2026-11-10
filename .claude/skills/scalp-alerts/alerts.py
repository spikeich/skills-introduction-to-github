#!/usr/bin/env python3
"""Price Alerts for scalp-alerts: rings when a price, your entry, your stop,
your target or your time stop hits. Standard library only. It never
places or changes an order.

Scalping take on crypto-alerts (skill-cryptos-jeto1337), built on trader-alerts from
Jakeschincariol/day-trader-skill (MIT, see LICENSE-day-trader-skill).

    python3 alerts.py watch                            # the plan in trader/plan.json
    python3 alerts.py watch --symbol BTC --above 78000 --below 74000
    python3 alerts.py watch --symbol ETH --above 2400 --plan none
    python3 alerts.py now --symbol ETH,BTC,SOL         # one look at the prices

watch prints one line when it starts, one line per alert as it fires, a
heartbeat every --heartbeat minutes (5) so silence never looks like a
crash, and stops when the trade is over (stop or target touched, or the
time stop), when every price alert has fired, or after --max-hours (1).
Run it under a monitor: each line is a notification.

From a plan (scalp-exit's trader/plan.json):
  entry    the price reaches the entry (a limit order there would fill)
  stop     touched in the entry's minute or later: the trade is out at a loss
           (the price passes the entry before it can reach the stop)
  target   touched in a LATER minute than the entry: out at the target (in the
           entry's own minute it may have been there before the fill)
  flat_by  the plan's time stop (entry + 20 minutes by default), win or lose
  A price that runs to the stop or the target before it ever reached the
  entry fires "missed": the limit order never filled, cancel it.

Prices: Binance's 1-minute candles first (data-api.binance.vision), then Yahoo's
1-minute chart (query2.finance.yahoo.com); --source picks one. Every completed
minute's high, low and close, each judged once and in order, so a wick between
two looks still counts and a look that fails is caught up by the next one. Free and unofficial: it can lag a minute or two behind the exchange.
Exit codes: 0 when the watch ended on an alert, 1 otherwise.
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

UA = "Mozilla/5.0 (compatible; scalp-alerts/1.0)"
HOSTS = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")


class AlertError(Exception):
    pass


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None, microsecond=0)


def say(msg):
    print("%s UTC  %s" % (utc_now().strftime("%H:%M"), msg), flush=True)


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


# CoinGecko's ids for the coins traded most (trader/universe.json adds the rest): a third
# source for the price right now. It has no 1- or 5-minute candles, so it cannot time a trade.
GECKO_IDS = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "XRP": "ripple", "BNB": "binancecoin",
             "DOGE": "dogecoin", "ADA": "cardano", "LINK": "chainlink", "LTC": "litecoin", "BCH": "bitcoin-cash",
             "AVAX": "avalanche-2", "TRX": "tron", "ZEC": "zcash", "SUI": "sui", "HYPE": "hyperliquid",
             "UNI": "uniswap", "NEAR": "near", "PEPE": "pepe", "WLD": "worldcoin-wld", "XLM": "stellar",
             "XMR": "monero", "AAVE": "aave", "ARB": "arbitrum", "ENA": "ethena", "ONDO": "ondo-finance",
             "INJ": "injective-protocol", "TRUMP": "official-trump"}


def gecko_prices(syms):
    """{symbol: the price CoinGecko shows now} for Yahoo-style symbols, in one request."""
    ids = {}
    known = {}
    try:
        with open(os.path.join("trader", "universe.json"), encoding="utf-8") as fh:
            known = {c.get("sym"): c.get("id") for c in json.load(fh).get("coins", []) if c.get("id")}
    except (OSError, ValueError, AttributeError):
        pass
    for sym in syms:
        base = re.sub(r"\d{4,}$", "", sym.upper().replace("-USD", ""))
        cid = known.get(base) or GECKO_IDS.get(base)
        if cid:
            ids[sym] = cid
    if not ids:
        return {}
    url = "https://api.coingecko.com/api/v3/simple/price?ids=%s&vs_currencies=usd" % ",".join(
        urllib.parse.quote(i) for i in sorted(set(ids.values())))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            doc = json.loads(r.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError):
        return {}
    return {sym: (doc.get(cid) or {}).get("usd") for sym, cid in ids.items()}


def minute_bars(sym, since_ts):
    """[(t, high, low, close)] of completed 1-minute bars since since_ts."""
    global SOURCE_USED
    path = "/v8/finance/chart/%s?range=1d&interval=1m" % urllib.parse.quote(sym)
    doc = None
    if SOURCE in ("auto", "binance"):
        doc = binance_chart(sym, "1m", start=since_ts - 60)
        if doc:
            SOURCE_USED = binance_name(doc)
        elif SOURCE == "binance":
            raise AlertError("Binance has no candles for %s, or did not answer" % sym)
    for host in (() if doc else HOSTS):
        try:
            req = urllib.request.Request(host + path, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                doc = json.loads(r.read().decode("utf-8", "replace"))
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise AlertError("Yahoo has no chart for %s" % sym)
            if e.code == 429:
                time.sleep(10)
        except (urllib.error.URLError, OSError) as e:
            raise AlertError("could not reach Yahoo: %s" % e)
    if not doc:
        raise AlertError("Yahoo did not answer")
    if "binancePair" not in ((doc.get("chart") or {}).get("result") or [{}])[0].get("meta", {}):
        SOURCE_USED = "Yahoo"
    res = ((doc.get("chart") or {}).get("result") or [None])[0] or {}
    q = (res.get("indicators") or {}).get("quote", [{}])[0]
    now_ts = int(time.time())
    out = []
    for i, ts in enumerate(res.get("timestamp") or []):
        h, l, c = [(q.get(k) or [None] * (i + 1))[i] if i < len(q.get(k) or []) else None
                   for k in ("high", "low", "close")]
        if ts is None or None in (h, l, c) or ts % 60 or ts + 60 > now_ts or ts < since_ts:
            continue
        out.append((int(ts), h, l, c))
    return out


def flat_at_of(plan):
    """When the plan says to be out, as a naive UTC datetime (None when it does not say).
    Uses the plan's full time (flat_at) when it has one; else its date and HH:MM, on the
    next day when that is not after the entry time (a trade that crosses UTC midnight)."""
    try:
        if plan.get("flat_at"):
            return datetime.datetime.strptime(plan["flat_at"], "%Y-%m-%d %H:%M")
        if not plan.get("flat_by") or not plan.get("date"):
            return None
        h, mi = (int(x) for x in plan["flat_by"].split(":"))
        t = datetime.datetime.combine(datetime.date.fromisoformat(plan["date"]), datetime.time(h, mi))
        if plan.get("entry_time"):
            eh, em = (int(x) for x in plan["entry_time"].split(":"))
            if (h, mi) <= (eh, em):
                t += datetime.timedelta(days=1)
        return t
    except (TypeError, ValueError):
        raise AlertError("the plan's flat_by / flat_at is not a time: %r / %r" % (plan.get("flat_by"), plan.get("flat_at")))


def plan_alerts(plan):
    return {"symbol": plan["symbol"], "side": plan["side"], "entry": plan["entry"], "stop": plan["stop"],
            "target": plan["target"], "date": plan.get("date"), "flat_by": plan.get("flat_by"),
            "flat_at": flat_at_of(plan), "filled": False, "done": False}


def step(state, bars):
    """Advance one symbol's alerts over new bars. -> list of messages."""
    msgs = []
    for t, h, l, c in bars:
        stamp = datetime.datetime.fromtimestamp(t + 60, datetime.timezone.utc).strftime("%H:%M")
        for pa in state["price"]:
            if pa["fired"]:
                continue
            if (pa["dir"] == "above" and h >= pa["level"]) or (pa["dir"] == "below" and l <= pa["level"]):
                pa["fired"] = True
                msgs.append("ALERTA %s %s %g (vela de las %s, cierre %g)"
                            % (state["symbol"], "superó" if pa["dir"] == "above" else "perforó", pa["level"],
                               stamp, c))
        p = state.get("plan")
        if not p or p["done"]:
            continue
        long = p["side"] == "buy"
        hit_stop = (l <= p["stop"]) if long else (h >= p["stop"])
        hit_tp = (h >= p["target"]) if long else (l <= p["target"])
        if not p["filled"]:
            touched = (l <= p["entry"]) if long else (h >= p["entry"])
            if touched:
                p["filled"] = True
                msgs.append("ENTRADA %s: el precio llegó a %g (%s). Si tenías la orden límite, se llenó."
                            % (state["symbol"], p["entry"], stamp))
                # The same minute: the price passes the entry before it can reach the stop, so a
                # stop touched here came after the fill and counts. The target may have come first.
                hit_tp = False
            elif hit_stop or hit_tp:
                p["done"] = True
                msgs.append("PERDIDA %s: tocó %s (%g) sin pasar por la entrada %g. La orden no se llenó: "
                            "cancelala." % (state["symbol"], "el objetivo" if hit_tp else "el stop",
                                            p["target"] if hit_tp else p["stop"], p["entry"]))
                continue
        if p["filled"] and (hit_stop or hit_tp):
            p["done"] = True
            if hit_stop:
                msgs.append("STOP %s tocado en %g (%s): la operación salió con pérdida." % (state["symbol"], p["stop"], stamp))
            else:
                msgs.append("OBJETIVO %s tocado en %g (%s): la operación salió en el take profit."
                            % (state["symbol"], p["target"], stamp))
    return msgs


def cmd_watch(a):
    states = {}
    if a.plan != "none" and os.path.exists(a.plan):
        with open(a.plan, encoding="utf-8") as fh:
            plan = json.load(fh)
        st = states.setdefault(plan["symbol"], {"symbol": plan["symbol"], "price": [], "plan": None})
        st["plan"] = plan_alerts(plan)
    if a.symbol:
        sym = yahoo_symbol(a.symbol)
        st = states.setdefault(sym, {"symbol": sym, "price": [], "plan": None})
        for lvl in a.above or []:
            st["price"].append({"dir": "above", "level": lvl, "fired": False})
        for lvl in a.below or []:
            st["price"].append({"dir": "below", "level": lvl, "fired": False})
    if not states:
        raise AlertError("nothing to watch: no %s and no --symbol with --above/--below" % a.plan)
    start = utc_now()
    for s in states.values():
        s["since"] = int(time.time()) - 120      # each closed minute is judged once, in order
    desc = []
    for s in states.values():
        if s["plan"]:
            p = s["plan"]
            desc.append("%s plan %s: entrada %g, stop %g, objetivo %g, salir %s UTC"
                        % (s["symbol"], "largo" if p["side"] == "buy" else "corto", p["entry"], p["stop"],
                           p["target"], p["flat_by"] or "-"))
        for pa in s["price"]:
            desc.append("%s %s %g" % (s["symbol"], "arriba de" if pa["dir"] == "above" else "abajo de", pa["level"]))
    say("Vigilando: " + " | ".join(desc))
    for s in states.values():
        p = s["plan"]
        if p and p["flat_at"] and start >= p["flat_at"]:
            p["done"] = True
            say("El plan de %s ya venció: había que estar afuera a las %s UTC del %s. Armá un plan nuevo."
                % (s["symbol"], p["flat_by"] or p["flat_at"].strftime("%H:%M"), p["flat_at"].strftime("%d/%m")))
    if not any((s["plan"] and not s["plan"]["done"]) or s["price"] for s in states.values()):
        return 1
    last_beat, errors, fired_any = start, 0, False
    while utc_now() < start + datetime.timedelta(hours=a.max_hours):
        for s in states.values():
            try:
                bars = minute_bars(s["symbol"], s["since"])
                errors = 0
            except AlertError as e:
                errors += 1
                if errors >= 5:
                    say("Corto: 5 errores seguidos (%s)." % e)
                    return 1
                continue
            for m in step(s, bars):
                say(m)
                fired_any = True
            if bars:
                s["last"] = bars[-1][3]
                s["since"] = bars[-1][0] + 60     # a failed look loses nothing: the next one catches up
            time.sleep(1)
        now = utc_now()
        for s in states.values():
            p = s["plan"]
            if p and not p["done"] and p["flat_at"] and now >= p["flat_at"]:
                p["done"] = True
                say("HORA DE SALIR %s: son las %s UTC. %s" % (
                    s["symbol"], now.strftime("%H:%M"), "Cerrá la posición, gane o pierda." if p["filled"]
                    else "La entrada nunca se llenó: cancelá la orden."))
                fired_any = True
        active = [s for s in states.values() if (s["plan"] and not s["plan"]["done"])
                  or any(not pa["fired"] for pa in s["price"])]
        if not active:
            say("Listo: todas las alertas se cumplieron.")
            return 0
        if now - last_beat >= datetime.timedelta(minutes=a.heartbeat):
            last_beat = now
            say("Sigue vigilando: " + ", ".join("%s %g" % (s["symbol"], s.get("last") or 0) for s in active)
                + (" (precios de %s)" % SOURCE_USED if SOURCE_USED else ""))
        time.sleep(max(15, a.every))
    say("Corto: pasaron %g horas." % a.max_hours)
    return 0 if fired_any else 1


def cmd_now(a):
    global SOURCE
    gecko = gecko_prices([yahoo_symbol(x) for x in a.symbol.split(",")]) if a.compare else {}
    for sym in a.symbol.split(","):
        y = yahoo_symbol(sym)
        if a.compare:           # the same coin on the three sources, side by side
            row, keep = [], SOURCE
            for name in ("binance", "yahoo"):
                SOURCE = name
                try:
                    bars = minute_bars(y, int(time.time()) - 600)
                    row.append((name.capitalize(), bars[-1][3] if bars else None))
                except AlertError:
                    row.append((name.capitalize(), None))
            SOURCE = keep
            row.append(("CoinGecko", gecko.get(y)))
            have = [p for _, p in row if p]
            gap = (max(have) / min(have) - 1) * 100 if len(have) > 1 else 0.0
            print("%-12s %s  (diferencia máxima %.2f %%)" % (
                y, " | ".join("%s %s" % (n, ("%g" % p) if p else "sin dato") for n, p in row), gap))
            time.sleep(0.5)
            continue
        bars = minute_bars(y, int(time.time()) - 600)
        if bars:
            t, h, l, c = bars[-1]
            print("%-12s %g  (minuto de las %s UTC, %s)" % (y, c, datetime.datetime.fromtimestamp(
                t, datetime.timezone.utc).strftime("%H:%M"), SOURCE_USED))
        else:
            print("%-12s sin datos recientes" % y)
        time.sleep(0.5)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Price Alerts for crypto scalping (scalp-alerts).")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("watch", help="ring on price levels and on the plan's entry, stop, target and flat-by")
    p.add_argument("--plan", default="trader/plan.json", help='the plan to follow, or "none"')
    p.add_argument("--symbol")
    p.add_argument("--above", type=float, action="append")
    p.add_argument("--below", type=float, action="append")
    p.add_argument("--every", type=float, default=20, help="seconds between looks (min 15)")
    p.add_argument("--heartbeat", type=float, default=5, help="minutes between 'still watching' lines")
    p.add_argument("--max-hours", type=float, default=1)
    p = sub.add_parser("now", help="one look at the prices")
    p.add_argument("--symbol", required=True, help="comma list: ETH,BTC,SOL")
    p.add_argument("--compare", action="store_true",
                   help="show the price on Binance, Yahoo and CoinGecko side by side")
    for p in sub.choices.values():
        p.add_argument("--source", default="auto", choices=["auto", "binance", "yahoo"],
                       help="where the prices come from: Binance first and Yahoo as a fallback (auto), or one")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    global SOURCE
    SOURCE = a.source
    try:
        return {"watch": cmd_watch, "now": cmd_now}[a.cmd](a)
    except AlertError as e:
        print("alerts.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
