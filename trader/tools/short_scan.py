"""Short-side scalping screen on free Yahoo data (reuses trader-scanner's fetch helpers).

Stage 1: daily closes for the whole universe (spark) -> liquid names, trend, relative strength.
Stage 2: v8 charts for the best candidates -> true ATR, last session's 5-minute bars, VWAP.
"""
import importlib.util, json, math, sys, time

REPO = "/home/user/skills-introduction-to-github"
spec = importlib.util.spec_from_file_location("scan", REPO + "/.claude/skills/trader-scanner/scan.py")
scan = importlib.util.module_from_spec(spec); spec.loader.exec_module(scan)

OUT = sys.argv[1]


def clean(xs):
    return [x for x in xs if x is not None]


def sma(xs, n):
    return sum(xs[-n:]) / n if len(xs) >= n else None


def rsi(c, n=14):
    return scan.rsi(c, n)


def v8(sym, rng, interval):
    return scan.parse_chart(scan.yahoo_get(scan.chart_path(sym, rng, interval)), sym)


# ------------------------------------------------------------ market context
ctx_syms = ["SPY", "QQQ", "IWM", "DIA", "^VIX", "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP",
            "XLU", "XLB", "XLRE", "XLC", "SMH"]
ctx = {}
for s in ctx_syms:
    try:
        d = v8(s, "3mo", "1d")
        c = clean(d["c"])
        ctx[s] = {"last": c[-1], "d1": c[-1] / c[-2] - 1, "d5": c[-1] / c[-6] - 1, "d20": c[-1] / c[-21] - 1,
                  "ma20": sma(c, 20), "ma50": sma(c, 50), "rsi": rsi(c)}
    except Exception as e:
        ctx[s] = {"error": str(e)}
spy20 = ctx["SPY"]["d20"]

# ------------------------------------------------------------ stage 1
syms = [l.split("|")[0] for l in open(REPO + "/trader/universe.txt") if l.strip()]
data, failed = scan.fetch_spark(syms, "3mo", "1d", 0.3)
rows = []
for s, d in data.items():
    c = clean(d["c"])
    meta = d["meta"]
    px, vol = meta.get("regularMarketPrice"), meta.get("regularMarketVolume")
    if not px or not vol or len(c) < 55 or px < 10 or vol < 2_000_000 or px * vol < 100e6:
        continue
    ma20, ma50 = sma(c, 20), sma(c, 50)
    chg = [abs(c[i] / c[i - 1] - 1) for i in range(len(c) - 20, len(c))]
    rows.append({"sym": s, "px": c[-1], "dvol": px * vol, "ma20": ma20, "ma50": ma50, "rsi": rsi(c),
                 "d1": c[-1] / c[-2] - 1, "d5": c[-1] / c[-6] - 1, "d20": c[-1] / c[-21] - 1,
                 "rs20": (c[-1] / c[-21] - 1) - spy20, "avgmove": sum(chg) / len(chg),
                 "ma20_slope": ma20 / sma(c[:-5], 20) - 1})

# Trend short: below both averages, falling 20-day average, weaker than SPY, not yet oversold.
trend = [r for r in rows if r["px"] < r["ma20"] < r["ma50"] and r["ma20_slope"] < 0
         and r["rs20"] < -0.03 and r["rsi"] and 30 <= r["rsi"] <= 50]
trend.sort(key=lambda r: r["rs20"])
# Fade short: stretched far above the 20-day average with RSI over 75.
fade = [r for r in rows if r["rsi"] and r["rsi"] >= 75 and r["px"] / r["ma20"] - 1 > 0.08]
fade.sort(key=lambda r: -r["rsi"])

# ------------------------------------------------------------ stage 2
def intraday(r):
    d = v8(r["sym"], "3mo", "1d")
    h, l, c = d["h"], d["l"], d["c"]
    trs = []
    for i in range(1, len(c)):
        if None in (h[i], l[i], c[i - 1]):
            continue
        trs.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    r["atr_pct"] = (sum(trs[-14:]) / 14) / r["px"]
    m = v8(r["sym"], "1d", "5m")
    bars = [(m["o"][i], m["h"][i], m["l"][i], m["c"][i], m["v"][i]) for i in range(len(m["t"]))
            if None not in (m["o"][i], m["h"][i], m["l"][i], m["c"][i], m["v"][i])]
    if not bars:
        return r
    pv = sum((b[1] + b[2] + b[3]) / 3 * b[4] for b in bars); v = sum(b[4] for b in bars)
    hi, lo, last = max(b[1] for b in bars), min(b[2] for b in bars), bars[-1][3]
    r["vwap"] = pv / v
    r["vs_vwap"] = last / r["vwap"] - 1
    r["day_pos"] = (last - lo) / (hi - lo) if hi > lo else 0.5
    r["day_range"] = (hi - lo) / last
    r["bar5_range"] = sum((b[1] - b[2]) / b[3] for b in bars) / len(bars)
    r["day_hi"], r["day_lo"] = hi, lo
    return r


picked = trend[:40] + fade[:20]
for r in picked:
    try:
        intraday(r)
    except Exception as e:
        r["err"] = str(e)
    time.sleep(0.2)

json.dump({"ctx": ctx, "liquid": len(rows), "fetched": len(data), "universe": len(syms),
           "trend": trend[:40], "fade": fade[:20], "trend_total": len(trend), "fade_total": len(fade)},
          open(OUT, "w"), indent=1, default=str)
print("done", len(data), len(rows), len(trend), len(fade))
