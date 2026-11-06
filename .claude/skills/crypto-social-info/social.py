#!/usr/bin/env python3
"""Social and political information for crypto (crypto-social-info). Standard library only.

    python3 social.py study                          # every verified event: before, day 0, 7d, 30d, vs a normal week
    python3 social.py study --scope social           # only social events (or --scope politico)
    python3 social.py study --type prohibicion
    python3 social.py patterns                       # the summaries only: by type, by expectation, repeat test
    python3 social.py calendar                       # upcoming events and how much they moved crypto before
    python3 social.py verify --claim "..." --first-seen "2026-11-04 03:00" \\
        --source "CNBC|https://...|confirma" --source "FXStreet|https://...|confirma" ...
    python3 social.py verify --list
    python3 social.py add-event --date 2026-11-04 --country EE.UU. --scope politico --type elecciones \\
        --dir - --title "..." --src "CNBC, Yahoo Finance" --verification 3

Data: the events (events.json) and the calendar (calendar.json) live next to this
script; --events / --calendar point elsewhere. The verification log goes to
trader/verificaciones.json in the project. Prices: Yahoo daily closes
(query2.finance.yahoo.com) for the coin, BTC and the Nasdaq (^IXIC).

The verification rule (see SKILL.md for how to search):
  VERIFICADA  an official document confirms it (a government, regulator or central bank
              page, not a social post), or 4 of 5 RELIABLE sources confirm the same facts
              (who, what, when, how much), with no credible denial
  DUDOSA      3 of 5, or facts that do not match, a denial from a reliable source,
              or less than an hour since the news first appeared
  FALSA       an official denial, or 2 of 5 or fewer
Reliable (fuentes.json): a known world newspaper, agency or financial outlet, an official
spokesperson (--vocero "Name, role|url|stance") or a recognised economist
(--economist "Name, institution|url|stance"). Crypto outlets, blogs and copies do not
count. X posts (--social "Account|url|stance|tilde") are only the origin of a rumour:
a blue or no checkmark is discarded, a grey or gold one is noted but never confirms.

This is a study of what happened, not a prediction. A few dozen events chosen by
people are a small, biased sample: the patterns are hints, not rules.
"""

import argparse
import datetime as dt
import json
import os
import statistics as st
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
UA = "Mozilla/5.0 (compatible; crypto-social-info/1.0)"
START = dt.datetime(2017, 1, 1, tzinfo=dt.timezone.utc)
YAHOO_PAIRS = {"HYPE": "HYPE32196-USD", "UNI": "UNI7083-USD", "SUI": "SUI20947-USD",
               "PEPE": "PEPE24478-USD", "TRUMP": "TRUMP35336-USD"}
STANCES = ("confirma", "parcial", "desmiente", "no_dice")
KINDS = ("medio", "oficial", "vocero", "economista", "redes")
TILDES = ("gris", "dorado", "azul", "ninguno")


class SocialError(Exception):
    pass


def utc_now():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, microsecond=0)


def read_json(path, default=None):
    if not os.path.exists(path):
        if default is not None:
            return default
        raise SocialError("no %s" % path)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
        fh.write("\n")


# ---------------------------------------------------------------- prices

def yahoo(coin):
    c = coin.upper()
    if c.startswith("^") or c.endswith("-USD"):
        return c
    return YAHOO_PAIRS.get(c, c + "-USD")


_CACHE = {}


def daily(sym):
    """{date: close} from 2017 to today."""
    if sym in _CACHE:
        return _CACHE[sym]
    q = urllib.parse.urlencode({"period1": int(START.timestamp()), "period2": int(time.time()), "interval": "1d"})
    url = "https://query2.finance.yahoo.com/v8/finance/chart/%s?%s" % (urllib.parse.quote(sym), q)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        res = json.load(urllib.request.urlopen(req, timeout=30))["chart"]["result"][0]
    except Exception as e:
        raise SocialError("could not get %s from Yahoo (is query2.finance.yahoo.com allowed?): %s" % (sym, e))
    out = {}
    for t, c in zip(res.get("timestamp") or [], res["indicators"]["quote"][0].get("close") or []):
        if c:
            out[dt.datetime.fromtimestamp(t, dt.timezone.utc).date()] = c
    _CACHE[sym] = out
    time.sleep(0.3)
    return out


def at(series, day, back=True):
    for i in range(6):
        d = day - dt.timedelta(days=i) if back else day + dt.timedelta(days=i)
        if d in series:
            return series[d]
    return None


def windows(s, d0):
    """antes (t-8 -> t-1), dia0 (t-1 -> t0), 7d and 30d (t-1 -> t+k), z = dia0 / normal daily move."""
    g = lambda k: at(s, d0 + dt.timedelta(days=k), back=k <= 0)
    c_m8, c_m1, c0 = g(-8), g(-1), g(0)
    if None in (c_m8, c_m1, c0):
        return None
    c7 = g(7) if d0 + dt.timedelta(days=7) <= dt.date.today() else None
    c30 = g(30) if d0 + dt.timedelta(days=30) <= dt.date.today() else None
    days = sorted(x for x in s if d0 - dt.timedelta(days=91) <= x < d0)
    rets = [s[b] / s[a] - 1 for a, b in zip(days, days[1:])]
    sd = st.pstdev(rets) if len(rets) > 20 else None
    r0 = c0 / c_m1 - 1
    return {"antes": c_m1 / c_m8 - 1, "dia0": r0, "7d": (c7 / c_m1 - 1) if c7 else None,
            "30d": (c30 / c_m1 - 1) if c30 else None, "z": (r0 / sd) if sd else None}


def baseline(btc):
    days = sorted(d for d in btc if d <= dt.date.today() - dt.timedelta(days=8))
    w7 = [at(btc, d + dt.timedelta(days=7)) / btc[d] - 1 for d in days if at(btc, d + dt.timedelta(days=7))]
    return {"sube_7d": sum(1 for x in w7 if x > 0) / len(w7), "mov_7d": st.median(abs(x) for x in w7)}


# ---------------------------------------------------------------- study

def load_events(a):
    ev = read_json(a.events)["events"]
    if a.scope:
        ev = [e for e in ev if e["scope"] == a.scope]
    if a.type:
        ev = [e for e in ev if e["type"] == a.type]
    if not ev:
        raise SocialError("no events match")
    return ev


def run_study(ev):
    btc, nas = daily("BTC-USD"), daily("^IXIC")
    rows = []
    for e in ev:
        d0 = dt.date.fromisoformat(e["date"])
        coin = (e.get("coin") or "BTC").upper()
        cw = None
        if coin != "BTC":
            try:
                cw = windows(daily(yahoo(coin)), d0)
            except SocialError:
                cw = None
        n = windows(nas, d0)
        rows.append(dict(e, btc=windows(btc, d0), coin_w=cw, nas7=(n or {}).get("7d")))
    return rows, baseline(btc)


def pc(x):
    return "   -   " if x is None else "%+6.1f%%" % (100 * x)


def mean(xs):
    xs = [x for x in xs if x is not None]
    return st.mean(xs) if xs else None


def summary_line(label, sel):
    sel = [r for r in sel if r["btc"]]
    if not sel:
        return None
    graded = [r for r in sel if r["dir"] in ("+", "-") and r["btc"]["7d"] is not None]
    ok = sum(1 for r in graded if (r["btc"]["7d"] > 0) == (r["dir"] == "+"))
    z = mean(abs(r["btc"]["z"]) for r in sel if r["btc"]["z"] is not None)
    return "%-24s n=%-2d antes %s día0 %s 7d %s 30d %s  mov. %.1fx normal  acierta en 7d: %s" % (
        label, len(sel), pc(mean(r["btc"]["antes"] for r in sel)), pc(mean(r["btc"]["dia0"] for r in sel)),
        pc(mean(r["btc"]["7d"] for r in sel)), pc(mean(r["btc"]["30d"] for r in sel)), z or 0,
        ("%d de %d" % (ok, len(graded))) if graded else "-")


def print_summaries(rows):
    out = []
    out.append("POR TIPO (bitcoin)")
    for t in sorted({r["type"] for r in rows}):
        line = summary_line(t, [r for r in rows if r["type"] == t])
        if line:
            out.append("  " + line)
    out.append("\nPOR LO QUE SE ESPERABA")
    for lbl, d in (("buenas noticias (+)", "+"), ("malas noticias (-)", "-")):
        line = summary_line(lbl, [r for r in rows if r["dir"] == d])
        if line:
            out.append("  " + line)
    out.append("\nSOCIAL vs POLÍTICO")
    for sc in ("politico", "social"):
        line = summary_line(sc, [r for r in rows if r["scope"] == sc])
        if line:
            out.append("  " + line)
    out.append("\n¿SE REPITE? (antes de 2023 contra 2023 en adelante)")
    for lbl, d, early in (("buenas, hasta 2022", "+", True), ("buenas, 2023+", "+", False),
                          ("malas, hasta 2022", "-", True), ("malas, 2023+", "-", False)):
        line = summary_line(lbl, [r for r in rows if r["dir"] == d and (r["date"] < "2023") == early])
        if line:
            out.append("  " + line)
    return out


def cmd_study(a):
    rows, base = run_study(load_events(a))
    print("Una semana cualquiera (2017 a hoy): bitcoin sube en el %.0f %% de las semanas y se mueve %.1f %% "
          "(mediana)." % (100 * base["sube_7d"], 100 * base["mov_7d"]))
    print("antes = la semana previa; día0 = el día del anuncio; 7d y 30d desde el día previo; z = el día 0 en "
          "veces un día normal.\n")
    print("%-10s %-11s %-20s %-3s %8s %8s %8s %8s %6s %8s  %s" % ("fecha", "país", "tipo", "esp", "antes", "día 0",
                                                              "7d", "30d", "z", "nasdaq7d", "evento"))
    for r in sorted(rows, key=lambda r: r["date"]):
        b = r["btc"] or {}
        extra = ""
        if r["coin_w"]:
            extra = "  [%s: día0 %s, 7d %s]" % (r["coin"], pc(r["coin_w"]["dia0"]).strip(), pc(r["coin_w"]["7d"]).strip())
        print("%-10s %-11s %-20s %-3s %8s %8s %8s %8s %6s %8s  %s%s" % (
            r["date"], r["country"][:11], r["type"][:20], r["dir"], pc(b.get("antes")), pc(b.get("dia0")),
            pc(b.get("7d")), pc(b.get("30d")), ("%+.1f" % b["z"]) if b.get("z") is not None else "-",
            pc(r["nas7"]), r["title"][:60], extra))
    print()
    print("\n".join(print_summaries(rows)))
    if a.json:
        write_json(a.json, {"base": base, "rows": rows})
    print("\nUn estudio de lo que pasó, no una predicción: pocos eventos, elegidos por personas.")
    return 0


def cmd_patterns(a):
    rows, base = run_study(load_events(a))
    print("Base: bitcoin sube en el %.0f %% de las semanas, movimiento típico %.1f %%.\n"
          % (100 * base["sube_7d"], 100 * base["mov_7d"]))
    print("\n".join(print_summaries(rows)))
    return 0


# ---------------------------------------------------------------- calendar

def cmd_calendar(a):
    cal = read_json(a.calendar)["events"]
    today = utc_now().date()
    upcoming = [c for c in cal if today <= dt.date.fromisoformat(c["date"]) <= today + dt.timedelta(days=a.days)]
    if not upcoming:
        print("No hay eventos cargados en los próximos %d días. Buscalos y agregalos a %s." % (a.days, a.calendar))
        return 1
    ev = read_json(a.events)["events"]
    types = {c.get("history_type") for c in upcoming if c.get("history_type")}
    hist = {}
    if types:
        rows, _ = run_study([e for e in ev if e["type"] in types])
        for t in types:
            sel = [r for r in rows if r["type"] == t and r["btc"]]
            if sel:
                hist[t] = (len(sel), mean(abs(r["btc"]["z"]) for r in sel if r["btc"]["z"] is not None),
                           mean(abs(r["btc"]["7d"]) for r in sel if r["btc"]["7d"] is not None))
    print("PRÓXIMOS %d DÍAS (hora UTC; Argentina = UTC-3)" % a.days)
    for c in sorted(upcoming, key=lambda c: (c["date"], c.get("time_utc", ""))):
        h = hist.get(c.get("history_type"))
        if h:
            note = "historial: %d casos, el día se movió %.1f veces lo normal, %.1f %% en la semana" % (
                h[0], h[1] or 0, 100 * (h[2] or 0))
        else:
            note = "sin casos en el historial: tratarlo como día de más volatilidad"
        print("  %s %-5s %-11s %s\n      %s | fuente: %s" % (c["date"], c.get("time_utc", ""), c["country"][:11],
                                                         c["title"], note, c.get("src", "-")))
    print("\nAntes de un evento grande: achicá el tamaño o ensanchá el stop (/crypto-risk).")
    return 0


# ---------------------------------------------------------------- verification

def load_reliable(path):
    doc = read_json(path, {"medios": {}, "no_cuentan": []})
    ok = {m.lower() for group in doc.get("medios", {}).values() for m in group}
    return ok


def is_reliable(name, ok):
    n = name.lower().strip()
    return any(n == m or n.startswith(m + " ") or n.startswith(m + ",") for m in ok)


def parse_source(text, kind, ok=frozenset()):
    parts = [p.strip() for p in text.split("|")]
    if len(parts) < 3:
        raise SocialError("--source wants \"Medio|url|confirma\" (or parcial, desmiente, no_dice), "
                          "optionally \"|copia de OTRO\": %r" % text)
    stance = parts[2].lower()
    if stance not in STANCES:
        raise SocialError("the stance must be one of %s, not %r" % (", ".join(STANCES), parts[2]))
    copy_of, tilde = None, None
    if len(parts) > 3 and parts[3].lower().startswith("copia de "):
        copy_of = parts[3][9:].strip()
    if kind == "redes":
        tilde = parts[3].lower() if len(parts) > 3 else ""
        if tilde not in TILDES:
            raise SocialError("an X post needs its checkmark: \"Cuenta|url|confirma|gris\" (gris, dorado, azul "
                              "or ninguno), not %r" % text)
    if kind in ("vocero", "economista") and "," not in parts[0]:
        raise SocialError("a %s needs name and %s: \"Nombre, %s|url|confirma\"" % (
            kind, "role" if kind == "vocero" else "institution", "cargo" if kind == "vocero" else "institución"))
    reliable = kind in ("oficial", "vocero", "economista") or (kind == "medio" and is_reliable(parts[0], ok))
    return {"outlet": parts[0], "url": parts[1], "stance": stance, "kind": kind, "copy_of": copy_of,
            "tilde": tilde, "reliable": reliable}


def verdict(sources, age_min):
    """-> (status, reasons). See the module docstring."""
    reasons = []
    official = [s for s in sources if s["kind"] == "oficial"]
    if any(s["stance"] == "desmiente" for s in official):
        return "FALSA", ["una fuente oficial la desmiente"]
    indep = [s for s in sources if s["kind"] in ("medio", "vocero", "economista") and s["reliable"]
             and not s["copy_of"]]
    copies = [s for s in sources if s["copy_of"]]
    posts = [s for s in sources if s["kind"] == "redes"]
    weak = [s for s in sources if s["kind"] == "medio" and not s["reliable"] and not s["copy_of"]]
    dropped = [s for s in posts if s["tilde"] in ("azul", "ninguno")]
    confirms = sum(1 for s in indep if s["stance"] == "confirma")
    partial = sum(1 for s in indep if s["stance"] == "parcial")
    denies = [s for s in indep if s["stance"] == "desmiente"]
    of = min(len(indep), 5) if indep else 0
    if copies:
        reasons.append("%d fuente(s) solo copian a otra y no cuentan" % len(copies))
    if weak:
        reasons.append("%d medio(s) fuera de la lista de confiables (%s): se citan pero no cuentan"
                       % (len(weak), ", ".join(s["outlet"] for s in weak[:4])))
    if dropped:
        reasons.append("%d posteo(s) de X sin tilde o con tilde azul (se compra): descartados" % len(dropped))
    if len(posts) > len(dropped):
        reasons.append("%d posteo(s) de X con tilde gris o dorado: es el origen de la noticia, no una "
                       "confirmación (en 2024 hackearon la cuenta de la SEC, que tenía tilde gris)"
                       % (len(posts) - len(dropped)))
    if partial:
        reasons.append("%d fuente(s) dan datos distintos (quién, qué, cuándo o cuánto)" % partial)
    if official and any(s["stance"] == "confirma" for s in official) and not denies:
        status = "VERIFICADA"
        reasons.insert(0, "lo confirma un documento oficial")
    elif denies:
        status = "DUDOSA"
        reasons.insert(0, "%s la desmiente" % denies[0]["outlet"])
    elif confirms >= 4:
        status = "VERIFICADA"
        reasons.insert(0, "%d fuentes confiables confirman los mismos datos" % confirms)
    elif confirms == 3:
        status = "DUDOSA"
        reasons.insert(0, "solo 3 fuentes confiables confirman")
    else:
        status = "FALSA"
        reasons.insert(0, "solo %d fuente(s) confiable(s) confirman" % confirms)
    if age_min is not None and age_min < 60 and status == "VERIFICADA":
        status = "DUDOSA"
        reasons.insert(0, "salió hace %d minutos: volver a revisar en una hora (y buscar desmentidos)" % age_min)
    if of and status != "FALSA":
        reasons.append("revisadas %d fuentes confiables" % len(indep))
    return status, reasons


def cmd_verify(a):
    log = read_json(a.log, {"checks": []})
    if a.list:
        if not log["checks"]:
            print("Todavía no hay verificaciones en %s." % a.log)
        for c in log["checks"]:
            print("#%d %s  %-10s %s" % (c["id"], c["checked_at"], c["status"], c["claim"][:90]))
        return 0
    if not a.claim:
        raise SocialError("verify needs --claim, or --list")
    ok = load_reliable(a.reliable)
    sources = [parse_source(s, "medio", ok) for s in a.source or []] + \
              [parse_source(s, "oficial", ok) for s in a.official or []] + \
              [parse_source(s, "vocero", ok) for s in a.vocero or []] + \
              [parse_source(s, "economista", ok) for s in a.economist or []] + \
              [parse_source(s, "redes", ok) for s in a.social or []]
    if not sources:
        raise SocialError("give the sources you found: --source, --official, --vocero, --economist or --social")
    now = utc_now()
    age = None
    if a.first_seen:
        first = dt.datetime.fromisoformat(a.first_seen.replace("Z", ""))
        age = int((now - first).total_seconds() // 60)
    status, reasons = verdict(sources, age)
    cid = (max(c["id"] for c in log["checks"]) + 1) if log["checks"] else 1
    log["checks"].append({"id": cid, "claim": a.claim, "checked_at": now.strftime("%Y-%m-%d %H:%M"),
                          "first_seen": a.first_seen, "status": status, "reasons": reasons, "sources": sources})
    write_json(a.log, log)
    mark = {"VERIFICADA": "OK", "DUDOSA": "??", "FALSA": "XX"}[status]
    print("[%s] %s  (#%d)\n  %s" % (mark, status, cid, a.claim))
    for r in reasons:
        print("  - " + r)
    for s in sources:
        tag = ("  (copia de %s)" % s["copy_of"]) if s["copy_of"] else \
              ("  (X, tilde %s)" % s["tilde"]) if s["kind"] == "redes" else \
              "" if s["reliable"] else "  (no cuenta)"
        print("    %-9s %-10s %-26s %s%s" % (s["stance"], s["kind"], s["outlet"][:26], s["url"][:64], tag))
    print({"VERIFICADA": "  Se puede usar para operar y para el historial (add-event --verification %d)." % cid,
           "DUDOSA": "  No operar por esta noticia; si hay posiciones abiertas, achicar y volver a revisar en 1 hora.",
           "FALSA": "  Descartada."}[status])
    return 0 if status == "VERIFICADA" else 1


def cmd_add_event(a):
    db = read_json(a.events)
    src = a.src
    if a.verification:
        log = read_json(a.log, {"checks": []})
        chk = next((c for c in log["checks"] if c["id"] == a.verification), None)
        if not chk:
            raise SocialError("no verification #%d in %s" % (a.verification, a.log))
        if chk["status"] != "VERIFICADA":
            raise SocialError("verification #%d is %s, not VERIFICADA: it does not go into the history"
                              % (a.verification, chk["status"]))
        src = src or ", ".join(s["outlet"] for s in chk["sources"] if s["stance"] == "confirma")
    if not src:
        raise SocialError("an event needs its sources: --src or --verification ID")
    dt.date.fromisoformat(a.date)
    if a.scope not in ("politico", "social"):
        raise SocialError("--scope is politico or social")
    if a.dir not in ("+", "-", "?"):
        raise SocialError("--dir is +, - or ?")
    if any(e["date"] == a.date and e["title"] == a.title for e in db["events"]):
        raise SocialError("that event is already there")
    db["events"].append({"date": a.date, "country": a.country, "scope": a.scope, "type": a.type, "dir": a.dir,
                         "conf": "alta", "coin": (a.coin or "BTC").upper(), "title": a.title, "src": src})
    db["events"].sort(key=lambda e: e["date"])
    write_json(a.events, db)
    print("Agregado: %s %s (%s, %s). Ahora hay %d eventos." % (a.date, a.title, a.scope, a.type, len(db["events"])))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Social and political information for crypto (crypto-social-info).")
    ap.add_argument("--events", default=os.path.join(HERE, "events.json"))
    ap.add_argument("--calendar", default=os.path.join(HERE, "calendar.json"))
    ap.add_argument("--log", default="trader/verificaciones.json")
    ap.add_argument("--reliable", default=os.path.join(HERE, "fuentes.json"), help="the list of reliable outlets")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("study", "patterns"):
        p = sub.add_parser(name)
        p.add_argument("--scope", choices=["politico", "social"])
        p.add_argument("--type")
        if name == "study":
            p.add_argument("--json", help="also save the rows")
    p = sub.add_parser("calendar")
    p.add_argument("--days", type=int, default=45)
    p.add_argument("--scope")
    p.add_argument("--type")
    p = sub.add_parser("verify")
    p.add_argument("--claim")
    p.add_argument("--first-seen", help='when the news first appeared, UTC, e.g. "2026-11-04 03:00"')
    p.add_argument("--source", action="append", help='"Outlet|url|confirma" (parcial, desmiente, no_dice)')
    p.add_argument("--official", action="append", help="an official document: same format")
    p.add_argument("--vocero", action="append", help='an official spokesperson: "Name, role|url|confirma"')
    p.add_argument("--economist", action="append", help='a recognised economist: "Name, institution|url|confirma"')
    p.add_argument("--social", action="append", help='an X post: "Account|url|confirma|gris" (gris/dorado/azul/ninguno)')
    p.add_argument("--list", action="store_true")
    p = sub.add_parser("add-event")
    for f in ("date", "country", "scope", "type", "dir", "title"):
        p.add_argument("--" + f, required=True)
    p.add_argument("--coin")
    p.add_argument("--src")
    p.add_argument("--verification", type=int)
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"study": cmd_study, "patterns": cmd_patterns, "calendar": cmd_calendar, "verify": cmd_verify,
                "add-event": cmd_add_event}[a.cmd](a)
    except SocialError as e:
        print("social.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
