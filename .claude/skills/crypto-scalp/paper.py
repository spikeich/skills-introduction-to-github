#!/usr/bin/env python3
"""Paper-trade one or more positions against live CoinGecko prices.

Nothing is sent to any exchange. Each stdout line is an event, so this is
meant to run under a monitor: one line per fill, per close, and a summary
every --report-min minutes. State is saved after every poll, so re-running
with the same --state resumes where it stopped.

  --trade ID:SIDE:MARGIN:LEV:SL%:TP%[:LIMIT[:CANCEL]]

    ID      CoinGecko id (ethereum, solana, ripple, bitcoin, zcash ...)
    SIDE    short | long
    MARGIN  USD of margin
    LEV     leverage
    SL%/TP% stop and target as % from the entry price
    LIMIT   optional limit price; without it the entry is at market now
    CANCEL  optional: cancel the unfilled limit if price passes this level

  python3 paper.py --state s.json --trade ethereum:short:1000:10:1.5:2.5
  python3 paper.py --state s.json --trade ethereum:short:500:3:2.8:2.2:2280:2220
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.request

MAKER, TAKER = 0.0002, 0.0005


def now():
    return dt.datetime.now(dt.UTC).strftime("%H:%M UTC")


def say(msg):
    print(now(), msg, flush=True)


def prices(ids):
    url = ("https://api.coingecko.com/api/v3/simple/price?ids="
           + ",".join(ids) + "&vs_currencies=usd")
    for attempt in range(6):
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                return {k: v["usd"] for k, v in json.load(r).items()}
        except Exception:
            if attempt == 5:
                return None
            time.sleep(30)


def parse(spec):
    f = spec.split(":")
    if len(f) < 6:
        sys.exit(f"--trade mal formado: {spec}")
    t = dict(id=f[0], side=f[1], margin=float(f[2]), lev=float(f[3]),
             slp=float(f[4]) / 100, tpp=float(f[5]) / 100,
             limit=float(f[6]) if len(f) > 6 and f[6] else None,
             cancel=float(f[7]) if len(f) > 7 and f[7] else None,
             state="WAIT", res=None)
    if t["side"] not in ("short", "long"):
        sys.exit(f"SIDE tiene que ser short o long: {spec}")
    return t


def fill(t, price, how):
    e = t["limit"] if how == "limit" else price
    s = 1 if t["side"] == "short" else -1
    t.update(state="OPEN", entry=e, qty=t["margin"] * t["lev"] / e,
             sl=e * (1 + s * t["slp"]), tp=e * (1 - s * t["tpp"]),
             fee_in=MAKER if how == "limit" else TAKER)
    say(f"ABRE {t['id']} {'CORTO' if s > 0 else 'LARGO'} {t['lev']:g}x en {e:.5g}"
        f" | TP {t['tp']:.5g} | SL {t['sl']:.5g}")


def upnl(t, p):
    d = (t["entry"] - p) if t["side"] == "short" else (p - t["entry"])
    return d * t["qty"] - t["entry"] * t["qty"] * t["fee_in"] - p * t["qty"] * TAKER


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state", required=True)
    ap.add_argument("--trade", action="append", default=[])
    ap.add_argument("--report-min", type=float, default=20)
    ap.add_argument("--poll", type=float, default=90, help="seconds; keep >= 60")
    a = ap.parse_args()

    if os.path.exists(a.state):
        st = json.load(open(a.state))
    else:
        if not a.trade:
            sys.exit("Sin --trade y sin estado guardado: nada que simular.")
        st = {"trades": [parse(s) for s in a.trade], "last": time.time()}
        p = prices([t["id"] for t in st["trades"]])
        if p is None:
            sys.exit("CoinGecko no respondió; probá de nuevo en un minuto.")
        for t in st["trades"]:
            if t["limit"] is None:
                fill(t, p[t["id"]], "market")
            else:
                say(f"ORDEN LÍMITE {t['id']} {t['side']} en {t['limit']:g}, esperando")
        json.dump(st, open(a.state, "w"))

    ids = [t["id"] for t in st["trades"]]
    capital = sum(t["margin"] for t in st["trades"])
    while any(t["state"] in ("WAIT", "OPEN") for t in st["trades"]):
        time.sleep(a.poll)
        p = prices(ids)
        if p is None:
            continue
        for t in st["trades"]:
            c = p.get(t["id"])
            if c is None:
                continue
            short = t["side"] == "short"
            if t["state"] == "WAIT":
                if (short and c >= t["limit"]) or (not short and c <= t["limit"]):
                    fill(t, c, "limit")
                elif t["cancel"] and ((short and c < t["cancel"]) or
                                      (not short and c > t["cancel"])):
                    t.update(state="CANCEL", res=0.0)
                    say(f"CANCELA {t['id']}: pasó {t['cancel']:g} sin llenar. 0 USD")
            elif t["state"] == "OPEN":
                tp = c <= t["tp"] if short else c >= t["tp"]
                sl = c >= t["sl"] if short else c <= t["sl"]
                if tp or sl:
                    ex = t["tp"] if tp else t["sl"]
                    d = (t["entry"] - ex) if short else (ex - t["entry"])
                    fee = (t["entry"] * t["fee_in"] + ex * (MAKER if tp else TAKER)) * t["qty"]
                    t.update(state="CLOSED", res=round(d * t["qty"] - fee, 2), exit=ex)
                    say(f"CIERRA {t['id']} por {'TAKE PROFIT' if tp else 'STOP LOSS'}"
                        f" en {ex:.5g}: {t['res']:+.2f} USD"
                        f" ({t['res'] / t['margin'] * 100:+.1f}% del margen)")
        if time.time() - st["last"] >= a.report_min * 60:
            st["last"] = time.time()
            parts, tot = [], 0.0
            for t in st["trades"]:
                if t["state"] == "OPEN" and t["id"] in p:
                    v = upnl(t, p[t["id"]])
                    parts.append(f"{t['id']} {v:+.0f}")
                elif t["state"] == "WAIT":
                    v = 0.0
                    parts.append(f"{t['id']} esperando ({p.get(t['id'], 0):.5g})")
                else:
                    v = t["res"] or 0.0
                    parts.append(f"{t['id']} {v:+.0f} (cerrada)")
                tot += v
            say("Resumen: " + " | ".join(parts) + f" | TOTAL {tot:+.0f} USD de {capital:g}")
        json.dump(st, open(a.state, "w"))

    tot = sum(t["res"] or 0 for t in st["trades"])
    say(f"FIN: todas cerradas. Resultado {tot:+.2f} USD sobre {capital:g}"
        f" ({tot / capital * 100:+.2f}%)")


if __name__ == "__main__":
    main()
