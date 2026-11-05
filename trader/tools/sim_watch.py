"""Watch one simulated position each minute; exit with the result when the stop, the target or the
flat-by time is hit. Usage: sim_watch.py SYMBOL short|long ENTRY STOP TARGET NOTIONAL FLAT_BY [OPENED_EPOCH]"""
import importlib.util, sys, time, datetime
REPO = "/home/user/skills-introduction-to-github"
spec = importlib.util.spec_from_file_location("scan", REPO + "/.claude/skills/trader-scanner/scan.py")
scan = importlib.util.module_from_spec(spec); spec.loader.exec_module(scan)
sym, side = sys.argv[1], sys.argv[2]
entry, stop, target, notional = map(float, sys.argv[3:7])
flat_by = sys.argv[7]
# Optional 8th argument: the epoch second the position opened, so bars since then count.
opened = float(sys.argv[8]) if len(sys.argv) > 8 else None
shares = notional / entry
sign = -1 if side == "short" else 1


def pnl(px):
    return sign * (px - entry) * shares


start = opened or datetime.datetime.now(datetime.timezone.utc).timestamp()
while True:
    now = scan.to_eastern(datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None))
    try:
        d = scan.parse_chart(scan.yahoo_get(scan.chart_path(sym, "1d", "1m")), sym)
    except Exception:
        time.sleep(60); continue
    # 1-minute bars since the position opened, so a wick through a level counts.
    for i, t in enumerate(d["t"]):
        if t < start - 60 or None in (d["h"][i], d["l"][i]):
            continue
        hi, lo = d["h"][i], d["l"][i]
        hit_stop = hi >= stop if side == "short" else lo <= stop
        hit_tgt = lo <= target if side == "short" else hi >= target
        when = scan.ts_to_eastern(t).strftime("%H:%M")
        if hit_stop:  # the stop is assumed first when one bar touches both
            print("%s %s STOP at %.2f: P&L %+.2f USD on %.0f USD (%+.2f%%)" % (when, sym, stop, pnl(stop), notional, pnl(stop) / notional * 100)); sys.exit(0)
        if hit_tgt:
            print("%s %s TARGET at %.2f: P&L %+.2f USD on %.0f USD (%+.2f%%)" % (when, sym, target, pnl(target), notional, pnl(target) / notional * 100)); sys.exit(0)
    last = d["meta"].get("regularMarketPrice")
    if now.strftime("%H:%M") >= flat_by and last:
        print("%s %s FLAT-BY exit at %.2f: P&L %+.2f USD on %.0f USD (%+.2f%%)" % (now.strftime("%H:%M"), sym, last, pnl(last), notional, pnl(last) / notional * 100)); sys.exit(0)
    time.sleep(60)
