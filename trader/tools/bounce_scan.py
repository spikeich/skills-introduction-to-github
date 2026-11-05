"""Intraday oversold-bounce screen (long side).

A name qualifies when it is liquid, down hard today, oversold on the daily RSI, set its low of the
day at least 30 minutes ago, and is now turning: the last three 5-minute lows are rising and the last
close is above the high of the bar that made the low. Stop just under the day's low, target 3R.
Usage: bounce_scan.py RISK_USD POSITION_CAP_USD SYMBOL...
"""
import importlib.util, sys, time
REPO = "/home/user/skills-introduction-to-github"
spec = importlib.util.spec_from_file_location("scan", REPO + "/.claude/skills/trader-scanner/scan.py")
scan = importlib.util.module_from_spec(spec); spec.loader.exec_module(scan)
risk_usd, cap_usd = float(sys.argv[1]), float(sys.argv[2])
syms = sys.argv[3:]
daily, _ = scan.fetch_spark(syms, "3mo", "1d", 0.2)
rows = []
for s in syms:
    try:
        d = scan.parse_chart(scan.yahoo_get(scan.chart_path(s, "1d", "5m")), s)
    except Exception:
        continue
    b = [(d["t"][i], d["h"][i], d["l"][i], d["c"][i], d["v"][i]) for i in range(len(d["t"]))
         if None not in (d["h"][i], d["l"][i], d["c"][i], d["v"][i])]
    if len(b) < 12:
        continue
    prev = d["meta"].get("chartPreviousClose")
    last = d["meta"].get("regularMarketPrice") or b[-1][3]
    closes = [c for c in (daily.get(s, {}).get("c") or []) if c is not None]
    rsi = scan.rsi(closes[:-1] + [last]) if len(closes) > 15 else None
    k = min(range(len(b)), key=lambda i: b[i][2])
    lo, lo_bar_hi = b[k][2], b[k][1]
    vwap = sum((h + l + c) / 3 * v for _, h, l, c, v in b) / sum(x[4] for x in b)
    bars_since_low = len(b) - 1 - k
    rising = b[-1][2] > b[-2][2] > b[-3][2] if len(b) >= 3 else False
    turning = bars_since_low >= 6 and last > lo_bar_hi and rising
    stop = round(lo - 0.02, 2)
    r = last - stop
    qty = int(min(risk_usd / r, cap_usd / last)) if r > 0 else 0
    rows.append(dict(sym=s, last=last, chg=last / prev - 1 if prev else 0, rsi=rsi, lo=lo,
                     lo_time=scan.ts_to_eastern(b[k][0]).strftime("%H:%M"), vwap=vwap, turning=turning,
                     stop=stop, risk=r, target=round(last + 3 * r, 2), qty=qty, dvol=sum(x[4] for x in b) * vwap,
                     bounce=last / lo - 1))
    time.sleep(0.1)
ok = [r for r in rows if r["chg"] <= -0.05 and r["rsi"] is not None and r["rsi"] < 35 and r["dvol"] > 300e6]
ok.sort(key=lambda r: (not r["turning"], r["rsi"]))
for r in ok:
    print("%-5s %s last %8.2f chg %+5.1f%% RSI %4.1f lo %8.2f @%s bounce %+4.1f%% VWAP %8.2f | stop %8.2f target %8.2f risk/sh %5.2f qty %3d (risk $%.0f, gain $%.0f, $%.0f)" % (
        r["sym"], "TURN" if r["turning"] else "    ", r["last"], r["chg"] * 100, r["rsi"], r["lo"], r["lo_time"], r["bounce"] * 100,
        r["vwap"], r["stop"], r["target"], r["risk"], r["qty"], r["qty"] * r["risk"], r["qty"] * r["risk"] * 3, r["qty"] * r["last"]))
