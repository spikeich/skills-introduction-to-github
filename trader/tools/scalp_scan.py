"""Intraday scalp screen, both sides, on 5-minute bars.

Short: price under VWAP and the last completed bar closed under the low of the bar before it.
Long:  price over VWAP and the last completed bar closed over the high of the bar before it.
Stop past the last three bars' extreme (15 minutes), target 3R, size by risk and a per-trade cap.
Usage: scalp_scan.py RISK_USD CAP_USD SYMBOL...
"""
import importlib.util, sys, time, datetime
REPO = "/home/user/skills-introduction-to-github"
spec = importlib.util.spec_from_file_location("scan", REPO + "/.claude/skills/trader-scanner/scan.py")
scan = importlib.util.module_from_spec(spec); spec.loader.exec_module(scan)
risk_usd, cap_usd = float(sys.argv[1]), float(sys.argv[2])
now = datetime.datetime.now(datetime.timezone.utc).timestamp()
out = []
for s in sys.argv[3:]:
    try:
        d = scan.parse_chart(scan.yahoo_get(scan.chart_path(s, "1d", "5m")), s)
    except Exception:
        continue
    b = [(d["t"][i], d["o"][i], d["h"][i], d["l"][i], d["c"][i], d["v"][i]) for i in range(len(d["t"]))
         if None not in (d["o"][i], d["h"][i], d["l"][i], d["c"][i], d["v"][i]) and d["t"][i] + 300 <= now]
    if len(b) < 6:
        continue
    vwap = sum((h + l + c) / 3 * v for _, _, h, l, c, v in b) / sum(x[5] for x in b)
    last = d["meta"].get("regularMarketPrice") or b[-1][4]
    cur, prv = b[-1], b[-2]
    side = None
    if last < vwap and cur[4] < prv[3]:
        side, stop = "short", round(max(x[2] for x in b[-3:]) + 0.02, 2)
    elif last > vwap and cur[4] > prv[2]:
        side, stop = "long", round(min(x[3] for x in b[-3:]) - 0.02, 2)
    if not side:
        continue
    r = abs(last - stop)
    if r <= 0 or (side == "short" and last >= stop) or (side == "long" and last <= stop):
        continue
    qty = int(min(risk_usd / r, cap_usd / last))
    target = round(last - 3 * r if side == "short" else last + 3 * r, 2)
    out.append(dict(sym=s, side=side, last=last, vwap=vwap, stop=stop, target=target, r=r, pct=r / last, qty=qty,
                    dvol=sum(x[5] for x in b) * vwap, bar=scan.ts_to_eastern(cur[0]).strftime("%H:%M")))
    time.sleep(0.1)
out = [o for o in out if o["dvol"] > 500e6 and 0.002 <= o["pct"] <= 0.012 and o["qty"] > 0]
out.sort(key=lambda o: -o["dvol"])
for o in out:
    print("%-5s %-5s last %8.2f VWAP %8.2f stop %8.2f (%.2f%%) target %8.2f qty %4d cap $%5.0f risk $%5.2f gain $%6.2f  bar %s  $%.0fM" % (
        o["sym"], o["side"], o["last"], o["vwap"], o["stop"], o["pct"] * 100, o["target"], o["qty"], o["qty"] * o["last"],
        o["qty"] * o["r"], 3 * o["qty"] * o["r"], o["bar"], o["dvol"] / 1e6))
