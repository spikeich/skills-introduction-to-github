"""Watch every open simulated position in trader/sim_trades.json each minute.

Exits with one line per event at the first of: a position hits its stop or target (on 1-minute bars
since it opened), the session's open + closed P&L reaches PROFIT_STOP, or FLAT_BY New York.
Usage: portfolio_watch.py SINCE_EPOCH PROFIT_STOP FLAT_BY
  SINCE_EPOCH  positions opened at or after this time count toward the session's P&L
"""
import importlib.util, json, sys, time, datetime
REPO = "/home/user/skills-introduction-to-github"
spec = importlib.util.spec_from_file_location("scan", REPO + "/.claude/skills/trader-scanner/scan.py")
scan = importlib.util.module_from_spec(spec); spec.loader.exec_module(scan)
since, profit_stop, flat_by = float(sys.argv[1]), float(sys.argv[2]), sys.argv[3]


def opened_epoch(x):
    t = datetime.datetime.strptime(x["opened"][:16], "%Y-%m-%d %H:%M")
    return scan.eastern_to_utc(t).replace(tzinfo=datetime.timezone.utc).timestamp()


while True:
    trades = json.load(open(REPO + "/trader/sim_trades.json"))
    session = [x for x in trades if opened_epoch(x) >= since - 60]
    live = [x for x in session if x["status"] == "open"]
    if not live:
        print("No open positions."); sys.exit(0)
    closed_pnl = sum(x.get("pnl_usd", 0) for x in session if x["status"] == "closed")
    events, open_pnl, lines = [], 0.0, []
    for x in live:
        sym, sign = x["symbol"], (1 if x["side"] == "long" else -1)
        try:
            d = scan.parse_chart(scan.yahoo_get(scan.chart_path(sym, "1d", "1m")), sym)
        except Exception:
            continue
        start = opened_epoch(x)
        for i, t in enumerate(d["t"]):
            if t < start or None in (d["h"][i], d["l"][i]):
                continue
            hit_stop = d["l"][i] <= x["stop"] if sign > 0 else d["h"][i] >= x["stop"]
            hit_tgt = d["h"][i] >= x["target"] if sign > 0 else d["l"][i] <= x["target"]
            if hit_stop or hit_tgt:  # the stop is assumed first when one bar touches both
                px = x["stop"] if hit_stop else x["target"]
                events.append("%s %s %s at %.2f: P&L %+.2f" % (scan.ts_to_eastern(t).strftime("%H:%M"), sym,
                              "STOP" if hit_stop else "TARGET", px, sign * (px - x["entry"]) * x["shares"]))
                break
        last = d["meta"].get("regularMarketPrice")
        pnl = sign * (last - x["entry"]) * x["shares"]
        open_pnl += pnl
        lines.append("%s %.2f %+.2f" % (sym, last, pnl))
    now = scan.to_eastern(datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)).strftime("%H:%M")
    if events:
        print("\n".join(events)); print("open now:", "; ".join(lines)); sys.exit(0)
    if closed_pnl + open_pnl >= profit_stop:
        print("%s PROFIT STOP: session P&L %+.2f (closed %+.2f, open %+.2f). %s" % (now, closed_pnl + open_pnl, closed_pnl, open_pnl, "; ".join(lines))); sys.exit(0)
    if now >= flat_by:
        print("%s FLAT-BY: session P&L %+.2f. %s" % (now, closed_pnl + open_pnl, "; ".join(lines))); sys.exit(0)
    time.sleep(60)
