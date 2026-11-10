#!/usr/bin/env python3
"""Risk Manager for scalp-risk: checks a scalp against your limits BEFORE you
place it, sizes it, and keeps the day's record. Standard library only.
It never places an order.

Scalping take on crypto-risk (skill-cryptos-jeto1337), built on trader-risk from
Jakeschincariol/day-trader-skill (MIT, see LICENSE-day-trader-skill). Tighter
limits: small risk per trade, more trades, the day ends after 3 losses, and a
signal older than 3 minutes is stale.

    python3 risk.py check --capital 3000                # trader/plan.json against trader/config.json
    python3 risk.py check --capital 3000 --lev 10 --risk 0.5
    python3 risk.py log --symbol ETH --result -5.2      # record a closed trade in USD
    python3 risk.py today                               # the day so far
    python3 risk.py config                              # the limits in force

The limits (trader/config.json, key "risk"; defaults in brackets):
  max_risk_pct          [0.5]   % of capital lost if the stop fills
  max_leverage          [10]    above it: blocked (isolated margin)
  min_net_r             [1.2]   reward over risk AFTER Binance fees
  max_trades_per_day    [20]
  max_losses_per_day    [3]     the third loss ends the day
  max_daily_loss_pct    [2.0]   % of capital lost today, closed trades
  max_open              [1]     one scalp at a time (from the journal)
  liq_buffer            [2.0]   the liquidation must be at least this many
                                times the stop's distance away from the entry
  min_notional          [20]    USDT: Binance's usual minimum order value
  max_signal_age_min    [3]     minutes after the entry candle's close: later, the
                                signal is stale and the price has moved on

A check prints PASS or BLOCK with every reason, and the ticket to type into
Binance by hand on a PASS. Exit codes: check 0 = PASS, 1 = BLOCK or an error.
"""

import argparse
import datetime
import json
import os
import sys

MAKER, TAKER = 0.0002, 0.0005
DEFAULTS = {
    "max_risk_pct": 0.5, "max_leverage": 10, "min_net_r": 1.2, "max_trades_per_day": 20,
    "max_losses_per_day": 3, "max_daily_loss_pct": 2.0, "max_open": 1, "liq_buffer": 2.0,
    "min_notional": 20.0, "max_signal_age_min": 3,
}


class RiskError(Exception):
    pass


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None, microsecond=0)


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as e:
        raise RiskError("could not read %s: %s" % (path, e))


def write_json(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
        fh.write("\n")


def limits(path):
    cfg = (read_json(path, {}) or {}).get("risk") or {}
    out = dict(DEFAULTS)
    for k, v in cfg.items():
        if k in out:
            out[k] = type(DEFAULTS[k])(v)
    return out


def journal(path):
    return read_json(path, {"trades": []}) or {"trades": []}


def day_stats(j, day):
    rows = [t for t in j["trades"] if t.get("date") == day]
    closed = [t for t in rows if t.get("result") is not None]
    return {
        "trades": len(rows), "open": [t for t in rows if t.get("result") is None],
        "losses": sum(1 for t in closed if t["result"] < 0),
        "pnl": round(sum(t["result"] for t in closed), 2),
    }


def size(capital, risk_pct, entry, stop, lev):
    """Quantity so that a stop fill loses risk_pct of capital, fees included."""
    risk_usd = capital * risk_pct / 100
    per_coin = abs(entry - stop) + entry * MAKER + stop * TAKER
    qty = risk_usd / per_coin
    notional = qty * entry
    return {"qty": qty, "notional": notional, "margin": notional / lev, "risk_usd": risk_usd}


def liquidation(side, entry, lev):
    move = 1.0 / lev - 0.005
    return entry * (1 - move) if side == "buy" else entry * (1 + move)


def check(plan, capital, lev, risk_pct, lim, stats, now):
    reasons, notes = [], []
    if capital <= 0:
        raise RiskError("--capital must be positive")
    side, entry, stop, target = plan["side"], plan["entry"], plan["stop"], plan["target"]
    if risk_pct > lim["max_risk_pct"]:
        reasons.append("riesgo %.2f %% del capital, el límite es %.2f %%" % (risk_pct, lim["max_risk_pct"]))
    if lev > lim["max_leverage"]:
        reasons.append("apalancamiento %gx, el límite es %gx" % (lev, lim["max_leverage"]))
    net_r = plan.get("net_r")
    if net_r is None:
        risk, reward = abs(entry - stop), abs(target - entry)
        net_r = (reward - entry * MAKER - target * MAKER) / (risk + entry * MAKER + stop * TAKER)
    if net_r < lim["min_net_r"]:
        reasons.append("R neto de comisiones %.2f, el mínimo es %.2f" % (net_r, lim["min_net_r"]))
    liq = liquidation(side, entry, lev)
    stop_dist, liq_dist = abs(entry - stop), abs(entry - liq)
    if liq_dist < lim["liq_buffer"] * stop_dist:
        reasons.append("la liquidación (~%g) está a %.2f %% de la entrada, menos de %g veces la distancia del stop "
                       "(%.2f %%): bajá el apalancamiento" % (round(liq, 6), liq_dist / entry * 100,
                                                              lim["liq_buffer"], stop_dist / entry * 100))
    if stats["trades"] >= lim["max_trades_per_day"]:
        reasons.append("ya hiciste %d operaciones hoy, el límite es %d" % (stats["trades"], lim["max_trades_per_day"]))
    if stats["losses"] >= lim["max_losses_per_day"]:
        reasons.append("ya perdiste %d operaciones hoy: el día terminó" % stats["losses"])
    loss_cap = capital * lim["max_daily_loss_pct"] / 100
    if -stats["pnl"] >= loss_cap:
        reasons.append("hoy vas %+.2f USD, el tope de pérdida diaria es -%.2f" % (stats["pnl"], loss_cap))
    elif -stats["pnl"] + capital * risk_pct / 100 > loss_cap:
        reasons.append("si salta este stop, el día cerraría en %+.2f USD, pasando el tope de -%.2f"
                       % (stats["pnl"] - capital * risk_pct / 100, loss_cap))
    if len(stats["open"]) >= lim["max_open"]:
        reasons.append("ya tenés %d posiciones abiertas, el límite es %d" % (len(stats["open"]), lim["max_open"]))
    if plan.get("entry_at") or plan.get("entry_time"):
        if plan.get("entry_at"):        # the full time: a session can cross UTC midnight
            sig = datetime.datetime.strptime(plan["entry_at"], "%Y-%m-%d %H:%M")
        else:
            h, m = (int(x) for x in plan["entry_time"].split(":"))
            sig = datetime.datetime.combine(datetime.date.fromisoformat(plan["date"]), datetime.time(h, m))
        age = (now - sig).total_seconds() / 60
        if age > lim["max_signal_age_min"]:
            reasons.append("la señal cerró a las %s UTC, hace %d minutos: en scalping, después de %d minutos ya es "
                           "vieja" % (plan["entry_time"], age, lim["max_signal_age_min"]))
    sz = size(capital, risk_pct, entry, stop, lev)
    if sz["notional"] < lim["min_notional"]:
        reasons.append("la orden vale %.2f USDT, Binance suele pedir al menos %g" % (sz["notional"], lim["min_notional"]))
    if sz["margin"] > capital:
        reasons.append("el margen (%.2f) supera el capital (%.2f)" % (sz["margin"], capital))
    same = [t for t in stats["open"] if t.get("symbol") == plan["symbol"]]
    if same:
        notes.append("ya hay una posición abierta en %s: esto la duplica" % plan["symbol"])
    if stats["open"]:
        notes.append("las criptos se mueven juntas: %d posición(es) abierta(s) más esta suman riesgo en la misma "
                     "dirección del mercado" % len(stats["open"]))
    return {"pass": not reasons, "reasons": reasons, "notes": notes, "size": sz, "liq": liq, "net_r": net_r}


def ticket(plan, res, lev):
    long = plan["side"] == "buy"
    sz = res["size"]
    sym = plan["symbol"].split("-")[0] + "USDT"
    return [
        "  ORDEN PARA CARGAR EN BINANCE (Futuros USDⓈ-M, a mano):",
        "    par          %s Perpetuo" % sym,
        "    margen       Aislado, %gx" % lev,
        "    tipo         Límite en %g  (%s)" % (plan["entry"], "Comprar / Largo" if long else "Vender / Corto"),
        "    cantidad     %.6g %s  (valor %.2f USDT, margen %.2f USDT)" % (sz["qty"], sym[:-4], sz["notional"],
                                                                          sz["margin"]),
        "    TP/SL        Take profit %g  |  Stop loss %g" % (plan["target"], plan["stop"]),
        "    si salta el stop: -%.2f USD, comisiones incluidas" % sz["risk_usd"],
        "    salir a las  %s UTC, gane o pierda" % plan.get("flat_by", "?"),
    ]


def cmd_check(a):
    plan = read_json(a.plan)
    if not plan:
        raise RiskError("no plan at %s: run /scalp-exit plan --write first" % a.plan)
    lim = limits(a.config)
    now = utc_now() if not a.now else datetime.datetime.fromisoformat(a.now.replace("Z", ""))
    stats = day_stats(journal(a.journal), now.date().isoformat())
    lev = a.lev or plan.get("leverage") or 10
    res = check(plan, a.capital, lev, a.risk, lim, stats, now)
    print("%s  %s %s  entrada %g  stop %g  objetivo %g  (%gx, riesgo %g %% de %g USD)"
          % ("PASA" if res["pass"] else "BLOQUEADA", "LARGO" if plan["side"] == "buy" else "CORTO", plan["symbol"],
             plan["entry"], plan["stop"], plan["target"], lev, a.risk, a.capital))
    for r in res["reasons"]:
        print("  x " + r)
    for n in res["notes"]:
        print("  ! " + n)
    print("  Hoy: %d operaciones, %d perdidas, %+.2f USD, %d abiertas."
          % (stats["trades"], stats["losses"], stats["pnl"], len(stats["open"])))
    if res["pass"]:
        print("\n".join(ticket(plan, res, lev)))
        if a.record:
            j = journal(a.journal)
            j["trades"].append({"date": now.date().isoformat(), "time": now.strftime("%H:%M"),
                                "symbol": plan["symbol"], "side": plan["side"], "entry": plan["entry"],
                                "stop": plan["stop"], "target": plan["target"], "qty": round(res["size"]["qty"], 8),
                                "leverage": lev, "result": None})
            write_json(a.journal, j)
            print("  Anotada como abierta en %s. Al cerrarla: risk.py log --symbol %s --result USD"
                  % (a.journal, plan["symbol"].split("-")[0]))
    print("  Esto revisa tus límites; no es un consejo de inversión. Vos cargás la orden.")
    return 0 if res["pass"] else 1


def clock(a):
    if not getattr(a, "now", None):
        return utc_now()
    return datetime.datetime.fromisoformat(a.now.replace("Z", ""))


def cmd_log(a):
    j = journal(a.journal)
    now = clock(a)
    sym = a.symbol.upper()
    sym = sym if "-" in sym else sym + "-USD"
    for t in reversed(j["trades"]):
        if t.get("symbol") == sym and t.get("result") is None:
            t["result"] = a.result
            t["closed"] = now.strftime("%H:%M")
            break
    else:
        j["trades"].append({"date": now.date().isoformat(), "time": now.strftime("%H:%M"), "symbol": sym,
                            "result": a.result})
    write_json(a.journal, j)
    print("Anotado %s %+.2f USD." % (sym, a.result))
    return cmd_today(a)


def cmd_today(a):
    now = clock(a)
    lim = limits(a.config)
    st = day_stats(journal(a.journal), now.date().isoformat())
    print("Hoy (%s UTC): %d de %d operaciones, %d de %d perdidas, %+.2f USD, %d abiertas."
          % (now.date().isoformat(), st["trades"], lim["max_trades_per_day"], st["losses"],
             lim["max_losses_per_day"], st["pnl"], len(st["open"])))
    if st["losses"] >= lim["max_losses_per_day"]:
        print("  Llegaste al límite de pérdidas: el día terminó.")
    return 0


def cmd_config(a):
    lim = limits(a.config)
    print("Límites en uso (%s, clave \"risk\"; sin archivo, los de por defecto):" % a.config)
    for k, v in lim.items():
        print("  %-20s %s" % (k, v))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Risk Manager for crypto scalping (scalp-risk).")
    ap.add_argument("--config", default="trader/config.json")
    ap.add_argument("--journal", default="trader/journal.json")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("check", help="a plan against the limits, and its size")
    p.add_argument("--plan", default="trader/plan.json")
    p.add_argument("--capital", type=float, required=True, help="USDT in the futures wallet")
    p.add_argument("--risk", type=float, default=0.5, help="%% of capital to risk (default 0.5)")
    p.add_argument("--lev", type=float, help="leverage (default: the plan's, else 10)")
    p.add_argument("--record", action="store_true", help="on a PASS, note the trade as open in the journal")
    p.add_argument("--now")
    p = sub.add_parser("log", help="record a closed trade's result in USD")
    p.add_argument("--symbol", required=True)
    p.add_argument("--result", type=float, required=True)
    p.add_argument("--now", help="pretend it is this UTC time")
    p = sub.add_parser("today", help="the day so far")
    p.add_argument("--now", help="pretend it is this UTC time")
    sub.add_parser("config", help="the limits in force")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"check": cmd_check, "log": cmd_log, "today": cmd_today, "config": cmd_config}[a.cmd](a)
    except RiskError as e:
        print("risk.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
