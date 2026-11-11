#!/usr/bin/env python3
"""Scan the most traded coins and rank them for scalping.

Reads live data from CoinGecko (api.coingecko.com, no key needed). No other
network, nothing written except what you pass with --json.

    python3 scan.py                 # table + top 5 picks
    python3 scan.py --top 8         # more picks
    python3 scan.py --json out.json # also save the raw rows
"""
import argparse
import json
import sys
import time
import urllib.request

URL = ("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd"
       "&order=volume_desc&per_page=80&page=1"
       "&price_change_percentage=1h,24h,7d")

# Stablecoins, wrapped and staked copies, gold tokens: nothing to scalp.
SKIP = {
    "usdt", "usdc", "fdusd", "dai", "usde", "tusd", "usdd", "pyusd", "usd1",
    "usds", "busd", "eurc", "rlusd", "susde", "usdtb", "xaut", "paxg", "wbtc",
    "weth", "steth", "wsteth", "cbbtc", "bsc-usd", "usdf", "usdg", "gho",
    "frax", "lusd", "u", "wbt", "weeth", "reth", "jitosol", "msol", "bnsol",
}

MIN_VOLUME = 300e6     # below this, spreads on a normal exchange eat the edge
MIN_RANGE = 5.0        # % high-low in 24h; less than this leaves no room
MAX_RANGE = 14.0       # more than this is usually one news candle, not a range
MAX_TURNOVER = 0.5     # volume / market cap; above it is pure speculation


def fetch():
    for attempt in range(5):
        try:
            with urllib.request.urlopen(URL, timeout=20) as r:
                return json.load(r)
        except Exception as e:  # 429 rate limit is the usual one
            if attempt == 4:
                sys.exit(f"CoinGecko no respondió: {e}")
            time.sleep(20)


def rows(data):
    out = []
    for c in data:
        sym = c["symbol"].lower()
        if sym in SKIP or "usd" in sym:
            continue
        hi, lo, p = c.get("high_24h"), c.get("low_24h"), c.get("current_price")
        if not (hi and lo and p and c.get("market_cap")):
            continue
        rng = (hi - lo) / p * 100
        pos = (p - lo) / (hi - lo) * 100 if hi > lo else 50.0
        out.append({
            "id": c["id"], "sym": sym.upper(), "rank": c["market_cap_rank"],
            "price": p, "volume": c["total_volume"], "range": rng,
            "pos": max(0.0, min(100.0, pos)),
            "turnover": c["total_volume"] / c["market_cap"],
            "ch1h": c.get("price_change_percentage_1h_in_currency") or 0.0,
            "ch24h": c.get("price_change_percentage_24h") or 0.0,
            "ch7d": c.get("price_change_percentage_7d_in_currency") or 0.0,
        })
    return out


def bias(r):
    """Which side a scalp should lean, from where price sits in its day."""
    if r["pos"] <= 35 and r["ch24h"] < 0:
        return "CORTO en rebotes"
    if r["pos"] >= 65 and r["ch24h"] > 0:
        return "LARGO en caídas"
    if r["pos"] >= 30 and r["ch24h"] > -4:
        return "LARGO en caídas (fuerza relativa)"
    return "neutral, esperar"


def why_not(r):
    if r["volume"] < MIN_VOLUME:
        return "poco volumen"
    if r["range"] < MIN_RANGE:
        return f"se mueve poco ({r['range']:.1f}%)"
    if r["range"] > MAX_RANGE:
        return f"rango de noticia ({r['range']:.1f}%)"
    if r["turnover"] > MAX_TURNOVER:
        return "especulación pura (volumen ~ capitalización)"
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--json")
    a = ap.parse_args()

    rs = rows(fetch())
    rs.sort(key=lambda r: r["volume"], reverse=True)

    print(f"{'cripto':7}{'rank':>5}{'vol 24h $M':>11}{'precio':>12}"
          f"{'rango%':>8}{'pos%':>6}{'1h%':>7}{'24h%':>7}{'7d%':>7}  nota")
    picks = []
    for r in rs[:25]:
        no = why_not(r)
        if not no and len(picks) < a.top:
            picks.append(r)
        print(f"{r['sym']:7}{r['rank'] or 0:>5}{r['volume']/1e6:>11.0f}"
              f"{r['price']:>12.5g}{r['range']:>8.1f}{r['pos']:>6.0f}"
              f"{r['ch1h']:>7.1f}{r['ch24h']:>7.1f}{r['ch7d']:>7.1f}  "
              f"{no or ''}")

    at_low = sum(1 for r in rs[:25] if r["pos"] <= 10)
    print(f"\nMercado: {at_low} de 25 en el mínimo del día (pos% <= 10).")
    print(f"\nTOP {len(picks)} PARA SCALPING")
    for i, r in enumerate(picks, 1):
        print(f"  {i}. {r['sym']:6} {r['price']:>11.5g}  rango {r['range']:.1f}%"
              f"  vol ${r['volume']/1e6:,.0f}M  -> {bias(r)}  (id: {r['id']})")

    if a.json:
        json.dump({"rows": rs, "picks": picks}, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
