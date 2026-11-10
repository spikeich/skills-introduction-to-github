#!/usr/bin/env python3
"""Position size from capital, risk and the stop - the number that matters.

    python3 size.py --capital 500 --entry 2280 --stop 2345 --target 2230
    python3 size.py --capital 500 --risk 2 --entry 2280 --stop 2345 --lev 5

Side is inferred: stop above entry is a short, below is a long.
"""
import argparse

TAKER = 0.0005   # Binance USDT-M futures, regular tier
MAKER = 0.0002


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--capital", type=float, required=True)
    ap.add_argument("--risk", type=float, default=0.5, help="%% of capital (default 0.5)")
    ap.add_argument("--entry", type=float, required=True)
    ap.add_argument("--stop", type=float, required=True)
    ap.add_argument("--target", type=float)
    ap.add_argument("--lev", type=float, default=10.0)
    a = ap.parse_args()

    short = a.stop > a.entry
    dist = abs(a.stop - a.entry)
    risk_usd = a.capital * a.risk / 100
    # The stop is a market order: entry fee (maker, limit) + exit fee (taker).
    per_unit = dist + a.entry * MAKER + a.stop * TAKER
    qty = risk_usd / per_unit
    notional = qty * a.entry
    margin = notional / a.lev
    liq = a.entry * (1 + 1 / a.lev) if short else a.entry * (1 - 1 / a.lev)

    print(f"{'CORTO' if short else 'LARGO'}  entrada {a.entry:g}  stop {a.stop:g}"
          f"  ({dist / a.entry * 100:.2f}% de distancia)")
    print(f"  cantidad      {qty:.4f}")
    print(f"  valor         {notional:,.2f} USDT")
    print(f"  margen {a.lev:g}x    {margin:,.2f} USDT"
          f"  ({margin / a.capital * 100:.0f}% del capital)")
    print(f"  si salta stop -{risk_usd:,.2f} USDT ({a.risk:g}% del capital, "
          f"comisiones incluidas)")
    if a.target:
        gain = abs(a.entry - a.target) * qty - (a.entry * MAKER + a.target * MAKER) * qty
        print(f"  si toca TP    +{gain:,.2f} USDT  (relación {gain / risk_usd:.2f} : 1)")
    print(f"  liquidación   ~{liq:g} (aprox., margen aislado)")
    if (short and liq <= a.stop) or (not short and liq >= a.stop):
        print("  !! La liquidación llega antes que el stop. Bajá el apalancamiento.")
    if margin > a.capital:
        print("  !! El margen supera el capital. Subí el apalancamiento o achicá el riesgo.")
    if notional < 20:
        print("  !! Menos de 20 USDT de valor: Binance suele rechazar la orden.")


if __name__ == "__main__":
    main()
