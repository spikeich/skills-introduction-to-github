#!/usr/bin/env python3
"""Exit Planner for scalp-exit: sets the stop, the target and the time stop BEFORE
you enter. Standard library only. Long AND short. It never places an order.

Scalping take on crypto-exit (skill-cryptos-jeto1337), built on trader-exit from
Jakeschincariol/day-trader-skill (MIT, see LICENSE-day-trader-skill).

    python3 exit.py plan                                  # from trader/entry.json: 0.25 % stop, 2R, out in 20 min
    python3 exit.py plan --stop pct:0.35 --target 3R --hold 30 --write
    python3 exit.py plan --stop atr:1.5                   # 1.5 x the 14-candle ATR of the 1-minute candles
    python3 exit.py plan --symbol BTC --side buy --entry 75783 --entry-time 14:42 --date 2026-11-06
    python3 exit.py plan --lev 10                         # also checks the liquidation price
    python3 exit.py show                                  # the current trader/plan.json

Stops (rounded to the coin's tick, AWAY from the entry):
  pct:X      X percent from the entry (default pct:0.25)
  or-mid     the opening-range midpoint
  or-far     the far side of the range: its low for a long, its high for a short
  price:X    your price
  atr:K      K times the 14-candle ATR of the session's 1-minute candles up to the entry

Targets: 2R (default), 1.5R, 3R ... or price:X.

Time stop (--hold, default 20 minutes): out at the entry time + hold, win or lose.
A scalp that has not worked in 20 minutes is not a scalp any more. The plan carries
the full times (entry_at, flat_at), so a trade may cross UTC midnight.

Refused, with the reason: a stop on the wrong side, a target on the wrong side, a
risk under --min-risk-pct (0.15 %), where the round-trip fee already eats about half
of it, and an entry.json that has not triggered (unless you give --entry).

Fees: R gross and R NET of Binance futures fees (limit entry at maker 0.02 %, stop at
taker 0.05 %, target at maker 0.02 %). In scalping the fees are most of the story: at
a 0.25 % stop they cost about 0.3 R a trade. With --lev it prints the isolated-margin
liquidation price and refuses a plan whose liquidation comes before the stop.

A stop is a plan, not a guarantee. Exit codes: plan 0 = a plan, 1 = refused or an error.
"""

import argparse
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

UA = "Mozilla/5.0 (compatible; scalp-exit/1.0)"
HOSTS = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")
MAKER, TAKER = 0.0002, 0.0005
ATR_BARS = 14
BAR = 60
STAMP = "%Y-%m-%d %H:%M"     # full UTC times in the plan: a scalp can cross UTC midnight
EPOCH = datetime.datetime(1970, 1, 1)
NOTE = "Un stop es un plan, no una garantía: un mercado rápido o una cascada de liquidaciones puede ejecutarlo peor."
SESSIONS = {"wallstreet": ("ny", 9 * 60 + 30, 6 * 60 + 30), "europa": ("london", 8 * 60, 8 * 60 + 30),
            "utc": ("utc", None, 120)}   # utc: a free session starting at --open (the entry's open_utc)


class PlanError(Exception):
    pass


# ---------------------------------------------------------------- time and prices

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


def session_times(session, day, open_hhmm=None):
    """(open, close) naive UTC datetimes of the session on that day."""
    market, local, length = SESSIONS[session]
    if market == "utc":
        if not open_hhmm:
            raise PlanError("a utc session needs its start: --open HH:MM, or an entry.json from scalp-entry")
        h, m = (int(x) for x in open_hhmm.split(":"))
        local = h * 60 + m
    opn = datetime.datetime.combine(day, datetime.time()) + datetime.timedelta(
        minutes=local - 60 * utc_offset_hours(market, day))
    return opn, opn + datetime.timedelta(minutes=length)


def tick(price):
    return 10.0 ** (math.floor(math.log10(price)) - 4) if price > 0 else 0.01


def snap(x, mode, ref=None):
    """Round to the tick of ref (default x): 'down', 'up' or 'near'."""
    t = tick(ref or x)
    q = round(x / t, 6)
    n = math.floor(q) if mode == "down" else math.ceil(q) if mode == "up" else math.floor(q + 0.5)
    return round(n * t, 10)


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


# ---------------------------------------------------------------- rules

def parse_stop(text):
    t = (text or "").strip().lower()
    if t in ("or-mid", "or-far"):
        return t, None
    m = re.match(r"^(price|pct|atr):([0-9]*\.?[0-9]+)$", t)
    if not m:
        raise PlanError("--stop wants or-mid, or-far, price:X, pct:X or atr:K, not %r" % text)
    return m.group(1), float(m.group(2))


def parse_target(text):
    t = (text or "").strip().lower()
    m = re.match(r"^([0-9]*\.?[0-9]+)r$", t)
    if m:
        return "r", float(m.group(1))
    m = re.match(r"^price:([0-9]*\.?[0-9]+)$", t)
    if m:
        return "price", float(m.group(1))
    raise PlanError("--target wants 2R, 1.5R ... or price:X, not %r" % text)


def compute(side, entry, stop_rule, stop_p, target_rule, target_p, or_high=None, or_low=None, atr=None,
            min_risk_pct=0.15):
    long = side == "buy"
    away = "down" if long else "up"
    if stop_rule in ("or-mid", "or-far"):
        if or_high is None or or_low is None:
            raise PlanError("%s needs the opening range: a level entry has none, give --stop price:X or pct:X"
                            % stop_rule)
        raw = (or_high + or_low) / 2 if stop_rule == "or-mid" else (or_low if long else or_high)
    elif stop_rule == "price":
        raw = stop_p
    elif stop_rule == "pct":
        raw = entry * (1 - stop_p / 100) if long else entry * (1 + stop_p / 100)
    else:
        if atr is None:
            raise PlanError("atr:K needs the session's bars")
        raw = entry - stop_p * atr if long else entry + stop_p * atr
    stop = snap(raw, away, entry)
    if (long and stop >= entry) or (not long and stop <= entry):
        raise PlanError("the stop %g is on the wrong side of the %s entry %g%s" % (
            stop, "long" if long else "short", entry,
            " (the entry is inside the range: use or-far or a price)" if stop_rule == "or-mid" else ""))
    risk = abs(entry - stop)
    if risk / entry * 100 < min_risk_pct:
        raise PlanError("the risk is %.3f %% of the price, under %.2f %%: Binance's round-trip fee (~0.07 %%) "
                        "would eat half of it. Use a wider stop." % (risk / entry * 100, min_risk_pct))
    if target_rule == "r":
        target = snap(entry + target_p * risk if long else entry - target_p * risk, "near", entry)
    else:
        target = snap(target_p, "near", entry)
    if (long and target <= entry) or (not long and target >= entry):
        raise PlanError("the target %g is on the wrong side of the entry %g" % (target, entry))
    reward = abs(target - entry)
    fee_stop = entry * MAKER + stop * TAKER
    fee_tp = entry * MAKER + target * MAKER
    return {"stop": stop, "target": target, "risk": round(risk, 10), "reward": round(reward, 10),
            "target_r": round(reward / risk, 2),
            "net_r": round((reward - fee_tp) / (risk + fee_stop), 2),
            "risk_pct": round(risk / entry * 100, 3), "reward_pct": round(reward / entry * 100, 3),
            "stop_rule": {"or-mid": "or_mid", "or-far": "or_low" if long else "or_high"}.get(stop_rule, "pct"),
            "stop_label": {"or-mid": "mitad del rango", "or-far": "otro extremo del rango", "price": "precio fijo",
                           "pct": "porcentaje", "atr": "ATR"}[stop_rule]}


def liquidation(side, entry, lev):
    """Isolated margin, rough: the price moves 1/lev against you, minus ~0.5 % maintenance."""
    move = 1.0 / lev - 0.005
    return entry * (1 - move) if side == "buy" else entry * (1 + move)


# ---------------------------------------------------------------- data for atr

def fetch_bars(sym, offline=None):
    if offline:
        doc = json.load(open(offline, encoding="utf-8"))
    else:
        path = "/v8/finance/chart/%s?range=2d&interval=1m" % urllib.parse.quote(sym)
        doc = None
        for host in HOSTS:
            try:
                req = urllib.request.Request(host + path, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=20) as r:
                    doc = json.loads(r.read().decode("utf-8", "replace"))
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    time.sleep(10)
            except (urllib.error.URLError, OSError) as e:
                raise PlanError("could not reach Yahoo for the ATR: %s" % e)
        if not doc:
            raise PlanError("Yahoo did not answer for the ATR; try again or use another stop")
    res = ((doc.get("chart") or {}).get("result") or [None])[0] or {}
    q = (res.get("indicators") or {}).get("quote", [{}])[0]
    out = []
    for i, ts in enumerate(res.get("timestamp") or []):
        row = [(q.get(k) or [])[i] if i < len(q.get(k) or []) else None for k in ("high", "low", "close")]
        if ts is not None and None not in row and int(ts) % BAR == 0:
            out.append({"t": int(ts), "h": row[0], "l": row[1], "c": row[2]})
    return out


def atr_of(bars, n=ATR_BARS):
    trs = []
    for i, b in enumerate(bars):
        pc = bars[i - 1]["c"] if i else None
        trs.append(max(b["h"] - b["l"], abs(b["h"] - pc), abs(b["l"] - pc)) if pc else b["h"] - b["l"])
    use = trs[-n:]
    return sum(use) / len(use), len(use)


# ---------------------------------------------------------------- plan

def read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as e:
        raise PlanError("could not read %s: %s" % (path, e))


def gather(a):
    """Entry facts from flags, or trader/entry.json."""
    if a.symbol:
        if a.entry is None or not a.side:
            raise PlanError("with --symbol also give --side buy|sell and --entry")
        return {"symbol": yahoo_symbol(a.symbol), "side": a.side, "entry": a.entry,
                "entry_time": a.entry_time, "date": a.date or datetime.datetime.now(datetime.timezone.utc).date().isoformat(),
                "session": a.session or "wallstreet", "setup": "orb" if a.or_high is not None else "level",
                "or_high": a.or_high, "or_low": a.or_low, "or_minutes": a.or_minutes, "confirm": 1,
                "open_utc": a.open, "entry_at": None}
    if not os.path.exists(a.from_file):
        raise PlanError("no %s: run /scalp-entry first, or pass --symbol --side --entry" % a.from_file)
    e = read_json(a.from_file)
    if e.get("status") != "triggered" and a.entry is None:
        raise PlanError("%s says %s, not triggered: wait for the trigger, or plan ahead with --entry PRICE "
                        "--side buy|sell" % (a.from_file, e.get("status")))
    orng = e.get("opening_range") or {}
    side = a.side or e.get("side")
    if side not in ("buy", "sell"):
        raise PlanError("no side: the entry has not triggered, give --side buy|sell")
    return {"symbol": e["symbol"], "side": side, "entry": a.entry if a.entry is not None else e["entry"],
            "entry_time": a.entry_time or e.get("entry_time"), "date": e.get("date"),
            "session": a.session or e.get("session") or "wallstreet", "setup": e.get("setup") or "orb",
            "or_high": orng.get("high"), "or_low": orng.get("low"), "or_minutes": orng.get("minutes") or 5,
            "confirm": e.get("confirm") or 1, "open_utc": a.open or e.get("open_utc"),
            "entry_at": None if (a.entry_time or a.entry is not None) else e.get("entry_at")}


def build_plan(a):
    f = gather(a)
    stop_rule, stop_p = parse_stop(a.stop or "pct:0.25")
    target_rule, target_p = parse_target(a.target)
    day = datetime.date.fromisoformat(f["date"])
    opn, _ = session_times(f["session"], day, f.get("open_utc"))
    entry_at = None            # the entry candle's close, as a full UTC time
    if f.get("entry_at"):
        entry_at = datetime.datetime.strptime(f["entry_at"], STAMP)
    elif f["entry_time"]:
        h, m = (int(x) for x in f["entry_time"].split(":"))
        entry_at = datetime.datetime.combine(day, datetime.time(h, m))
        if f["session"] == "utc" and entry_at < opn:
            entry_at += datetime.timedelta(days=1)     # after UTC midnight, in a session opened the day before
    atr, atr_n = None, None
    if stop_rule == "atr":
        bars = fetch_bars(f["symbol"], a.offline)
        cut = entry_at
        sess = [b for b in bars if b["t"] >= int((opn - EPOCH).total_seconds())
                and (cut is None or b["t"] + BAR <= int((cut - EPOCH).total_seconds()))]
        if not sess:
            raise PlanError("no bars of the session up to the entry for the ATR")
        atr, atr_n = atr_of(sess)
    r = compute(f["side"], f["entry"], stop_rule, stop_p, target_rule, target_p, f["or_high"], f["or_low"],
                atr, a.min_risk_pct)
    start = entry_at or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None, second=0, microsecond=0)
    if a.flat_by:
        try:
            h, m = (int(x) for x in a.flat_by.split(":"))
            flat_at = datetime.datetime.combine(start.date(), datetime.time(h, m))
        except ValueError:
            raise PlanError("--flat-by wants a UTC time like 15:05, not %r" % a.flat_by)
        if flat_at <= start:
            flat_at += datetime.timedelta(days=1)      # the next time the clock shows it
    else:
        flat_at = start + datetime.timedelta(minutes=a.hold)
    flat_by = flat_at.strftime("%H:%M")
    plan = {
        "created_by": "scalp-exit", "symbol": f["symbol"], "side": f["side"], "date": f["date"],
        "session": f["session"], "setup": f["setup"], "entry": f["entry"], "entry_time": f["entry_time"],
        "stop": r["stop"], "target": r["target"], "stop_rule": r["stop_rule"], "stop_label": r["stop_label"],
        "target_r": r["target_r"],
        "net_r": r["net_r"], "risk_per_coin": r["risk"], "risk_pct": r["risk_pct"],
        "reward_pct": r["reward_pct"], "opening_range": {"minutes": f["or_minutes"], "high": f["or_high"],
                                                        "low": f["or_low"]},
        "flat_by": flat_by, "hold_minutes": a.hold, "interval": "1m", "confirm": f["confirm"],
        "open_at": opn.strftime(STAMP), "entry_at": entry_at.strftime(STAMP) if entry_at else None,
        "flat_at": flat_at.strftime(STAMP),
    }
    if f["session"] == "utc":
        plan["open_utc"] = opn.strftime("%H:%M")
    if atr is not None:
        plan["atr"] = {"value": round(atr, 10), "bars": atr_n, "k": stop_p}
    if a.lev:
        liq = liquidation(f["side"], f["entry"], a.lev)
        plan["leverage"] = a.lev
        plan["liquidation"] = snap(liq, "near", f["entry"])
        if (f["side"] == "buy" and liq >= r["stop"]) or (f["side"] == "sell" and liq <= r["stop"]):
            raise PlanError("at %gx the liquidation (~%g) comes before the stop %g: lower the leverage"
                            % (a.lev, plan["liquidation"], r["stop"]))
    return plan


def describe(p):
    long = p["side"] == "buy"
    lines = [
        "%s %s  %s, sesión %s" % ("LARGO" if long else "CORTO", p["symbol"], p["date"], p["session"]),
        "  entrada  %g%s" % (p["entry"], "  (vela que cierra %s UTC)" % p["entry_time"] if p["entry_time"] else ""),
        "  stop     %g   (%s, %.2f %% en contra)" % (p["stop"], p.get("stop_label") or p["stop_rule"], p["risk_pct"]),
        "  objetivo %g   (%gR, %.2f %% a favor)" % (p["target"], p["target_r"], p["reward_pct"]),
        "  R neto de comisiones: %gR   (entrada límite maker, stop taker, objetivo maker)" % p["net_r"],
        "  afuera a las %s UTC (%s minutos como máximo), gane o pierda" % (p["flat_by"], p.get("hold_minutes", "?")),
    ]
    if p.get("atr"):
        lines.append("  ATR %g sobre %d velas%s" % (p["atr"]["value"], p["atr"]["bars"],
                                                   "" if p["atr"]["bars"] >= ATR_BARS else
                                                   " (menos de 14: promedio de todas)") + " de 1 minuto")
    if p.get("leverage"):
        lines.append("  %gx aislado: liquidación aprox. %g (el stop salta antes)" % (p["leverage"], p["liquidation"]))
    if p["net_r"] < 1.0:
        lines.append("  OJO: después de comisiones ganás menos de lo que arriesgás (%gR neto)." % p["net_r"])
    lines.append("  " + NOTE)
    lines.append("  Siguiente: /scalp-timemachine prueba este plan; /scalp-risk dice cuánto abrir.")
    return lines


def write_json(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
        fh.write("\n")


def cmd_plan(a):
    p = build_plan(a)
    if a.json:
        print(json.dumps(p, indent=2))
    else:
        print("\n".join(describe(p)))
    if a.write:
        write_json(a.write, p)
        print("  Escribí %s." % a.write)
    return 0


def cmd_show(a):
    if not os.path.exists(a.write_path):
        print("No hay plan en %s." % a.write_path)
        return 1
    print("\n".join(describe(read_json(a.write_path))))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Exit Planner for crypto scalping (scalp-exit).")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("plan", help="stop, target and flat-by time for an entry")
    p.add_argument("--from", dest="from_file", default="trader/entry.json")
    p.add_argument("--symbol")
    p.add_argument("--side", choices=["buy", "sell"])
    p.add_argument("--entry", type=float)
    p.add_argument("--entry-time", help="the entry bar's close, UTC, e.g. 14:55")
    p.add_argument("--date", help="UTC date of the session, YYYY-MM-DD")
    p.add_argument("--session", choices=sorted(SESSIONS))
    p.add_argument("--open", help="with --session utc: the session's start, HH:MM UTC")
    p.add_argument("--or-high", type=float)
    p.add_argument("--or-low", type=float)
    p.add_argument("--or-minutes", type=int, default=5)
    p.add_argument("--stop", help="pct:X (default pct:0.25) | or-mid | or-far | price:X | atr:K")
    p.add_argument("--hold", type=int, default=20, help="minutes to stay in at most (default 20)")
    p.add_argument("--target", default="2R", help="2R, 1.5R ... or price:X")
    p.add_argument("--flat-by", help="UTC time to be out by, e.g. 20:55")
    p.add_argument("--lev", type=float, help="leverage, to check the liquidation price")
    p.add_argument("--min-risk-pct", type=float, default=0.15)
    p.add_argument("--offline", help="a saved Yahoo chart JSON, for atr:K")
    p.add_argument("--json", action="store_true")
    p.add_argument("--write", nargs="?", const="trader/plan.json")
    p = sub.add_parser("show", help="print trader/plan.json")
    p.add_argument("--path", dest="write_path", default="trader/plan.json")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"plan": cmd_plan, "show": cmd_show}[a.cmd](a)
    except PlanError as e:
        print("exit.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
