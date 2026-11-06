#!/usr/bin/env python3
"""Social and political information for crypto (crypto-social-info). Standard library only.

    python3 social.py study                          # every verified event: before, day 0, 7d, 30d, vs a normal week
    python3 social.py study --scope social           # only social events (or --scope politico)
    python3 social.py study --type prohibicion
    python3 social.py patterns                       # the summaries only: by type, by expectation, repeat test
    python3 social.py calendar                       # upcoming events and how much they moved crypto before
    python3 social.py verify --claim "..." --first-seen "2026-11-04 03:00" \\
        --source "CNBC|https://...|confirma" --source "FXStreet|https://...|confirma" ...
    python3 social.py verify --claim "..." --source "CNBC|https://...|confirma|2026-10-30 09:00" ...
    python3 social.py verify --list
    python3 social.py add-event --date 2026-11-04 --country EE.UU. --scope politico --type elecciones \\
        --dir - --title "..." --src "CNBC, Yahoo Finance" --verification 3
    python3 social.py news                           # crypto and political headlines: Guardian, NYT, BBC (RSS)
    python3 social.py news --query "tariff,china" --days 2
    python3 social.py news --query "stablecoin" --for-verify   # ready-made --source lines for verify

News: the public RSS feeds of The Guardian (www.theguardian.com), The New York
Times (rss.nytimes.com) and the BBC (feeds.bbci.co.uk), the format they publish
for programs to read. No key needed. They only carry the last few days.

Data: the events (events.json) and the calendar (calendar.json) live next to this
script; --events / --calendar point elsewhere. The verification log goes to
trader/verificaciones.json in the project. Prices: Yahoo daily closes
(query2.finance.yahoo.com) for the coin, BTC and the Nasdaq (^IXIC).

The verification rule (see SKILL.md for how to search):
  VERIFICADA  an official document confirms it (a government, regulator or central bank
              page, not a social post), or at least 4 RELIABLE sources confirm the same
              facts (who, what, when, how much) AND they are 80 % or more of the reliable
              sources that speak about it, at least 2 of them independent newspapers,
              with no credible denial
              --high-impact (news that can move the market a lot): at least 6 confirm,
              85 % or more, from 2 regions or more, with an international agency
              (Reuters, AP, AFP, Bloomberg...) or an official document among them
  DUDOSA      close but short of that, facts that do not match, a denial from a
              reliable source, or less than an hour since the news first appeared
  FALSA       an official denial, or 2 confirmations or fewer
The date (add it to each source: "Outlet|url|confirma|2026-10-29 14:00", UTC):
  the age of the news is counted from its EARLIEST reliable report, not from when
  we saw it. NUEVA under 24 h (it can move the price today), RECIENTE 24-72 h
  (mostly priced in), VIEJA over 72 h (context only, never a reason to trade today).
  A confirmation dated more than 7 days before the others is about another event
  and does not count. If the news showed up again (--first-seen) more than 24 h
  after the first report, it is old news going round again: RECICLADA.
Reliable (fuentes.json, by country): a known newspaper, agency or financial outlet, an official
spokesperson (--vocero "Name, role|url|stance") or a recognised economist
(--economist "Name, institution|url|stance"). Crypto outlets, blogs and copies do not
count. State-controlled media (TASS, Xinhua, Antara...) count as that government's
official voice, like a spokesperson. X posts (--social "Account|url|stance|tilde") are only the origin of a rumour:
a blue or no checkmark is discarded, a grey or gold one is noted but never confirms.

This is a study of what happened, not a prediction. A few dozen events chosen by
people are a small, biased sample: the patterns are hints, not rules.
"""

import argparse
import datetime as dt
import email.utils
import json
import os
import statistics as st
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
UA = "Mozilla/5.0 (compatible; crypto-social-info/1.0)"
START = dt.datetime(2017, 1, 1, tzinfo=dt.timezone.utc)
YAHOO_PAIRS = {"HYPE": "HYPE32196-USD", "UNI": "UNI7083-USD", "SUI": "SUI20947-USD",
               "PEPE": "PEPE24478-USD", "TRUMP": "TRUMP35336-USD"}
STANCES = ("confirma", "parcial", "desmiente", "no_dice")
KINDS = ("medio", "oficial", "vocero", "economista", "redes")
TILDES = ("gris", "dorado", "azul", "ninguno")
FRESH_H, RECENT_H = 24, 72        # hours: NUEVA under 24, RECIENTE under 72, then VIEJA
OTHER_EVENT_DAYS = 7              # a confirmation this much older than the others is another event
RECYCLED_H = 24                   # seen again this long after the first report: RECICLADA
FEEDS = {
    "The Guardian": ["https://www.theguardian.com/technology/cryptocurrencies/rss",
                     "https://www.theguardian.com/business/rss",
                     "https://www.theguardian.com/us-news/us-politics/rss"],
    "The New York Times": ["https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
                           "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
                           "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml"],
    "BBC": ["https://feeds.bbci.co.uk/news/business/rss.xml",
            "https://feeds.bbci.co.uk/news/technology/rss.xml",
            "https://feeds.bbci.co.uk/news/world/rss.xml"],
}
CRYPTO_WORDS = ("bitcoin", "crypto", "cryptocurrenc", "stablecoin", "blockchain", "ethereum", "ether ",
                "binance", "coinbase", "digital asset", "digital currenc", "cbdc", "memecoin", "token")
MACRO_WORDS = ("tariff", "federal reserve", "interest rate", "inflation", "sanction", "treasury",
               "central bank", "sec ", "securities and exchange", "election", "congress", "recession")


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


# ---------------------------------------------------------------- news (RSS)

def parse_feed(text, outlet):
    """RSS 2.0 text -> [{outlet, title, url, when (naive UTC), summary}]."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise SocialError("%s sent something that is not RSS: %s" % (outlet, e))
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        when = None
        raw = it.findtext("pubDate")
        if raw:
            try:
                d = email.utils.parsedate_to_datetime(raw)
                when = (d.astimezone(dt.timezone.utc) if d.tzinfo else d).replace(tzinfo=None)
            except (TypeError, ValueError):
                when = None
        summary = " ".join((it.findtext("description") or "").split())
        if title and link:
            out.append({"outlet": outlet, "title": title, "url": link, "when": when, "summary": summary})
    return out


def fetch_feed(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def matches(item, words):
    text = " %s %s " % (item["title"].lower(), item["summary"].lower())
    return [w.strip() for w in words if w in text]


def cmd_news(a):
    items, errors = [], []
    if a.offline:
        for path in a.offline:
            outlet = os.path.basename(path).split(".")[0].replace("_", " ")
            items += parse_feed(open(path, encoding="utf-8").read(), outlet)
    else:
        for outlet, urls in FEEDS.items():
            for url in urls:
                try:
                    items += parse_feed(fetch_feed(url), outlet)
                except SocialError as e:
                    errors.append(str(e))
                except Exception as e:
                    errors.append("%s (%s): %s" % (outlet, urllib.parse.urlparse(url).netloc, e))
                time.sleep(0.3)
    words = [w.strip().lower() for w in a.query.split(",")] if a.query else list(CRYPTO_WORDS) + list(MACRO_WORDS)
    now = parse_now(a.now)
    seen, hits = set(), []
    for it in items:
        if it["url"] in seen:
            continue
        if it["when"] and it["when"] < now - dt.timedelta(days=a.days):
            continue
        m = matches(it, words)
        if m:
            seen.add(it["url"])
            it["tags"] = m
            it["kind"] = "cripto" if any(w in CRYPTO_WORDS for w in m) else "macro/política"
            hits.append(it)
    hits.sort(key=lambda x: x["when"] or dt.datetime.min, reverse=True)
    print("NOTICIAS de los últimos %d días (The Guardian, The New York Times, BBC), hora Argentina" % a.days)
    if errors:
        for e in dict.fromkeys(errors):
            print("  ! no se pudo leer: %s" % e)
        if len(errors) == sum(len(u) for u in FEEDS.values()) and not a.offline:
            print("  ! Ningún feed respondió: ¿están www.theguardian.com, rss.nytimes.com y feeds.bbci.co.uk "
                  "habilitados en la red del entorno?")
    if not hits:
        print("  Nada que coincida con %s." % ", ".join(words[:8]))
    for h in hits[:a.limit]:
        when = (h["when"] - dt.timedelta(hours=3)).strftime("%d/%m %H:%M") if h["when"] else "  ?  "
        if a.for_verify:
            stamp = ("|" + h["when"].strftime("%Y-%m-%d %H:%M")) if h["when"] else ""
            print('  --source "%s|%s|confirma%s"    # %s: %s' % (h["outlet"], h["url"], stamp, when, h["title"][:70]))
        else:
            print("  %s  %-18s [%s] %s\n      %s" % (when, h["outlet"], h["kind"], h["title"], h["url"]))
    if a.for_verify and hits:
        print("  (leé cada nota y cambiá confirma por parcial, desmiente o no_dice según lo que dice)")
    if a.json:
        write_json(a.json, [dict(h, when=h["when"].isoformat() if h["when"] else None) for h in hits])
    return 0 if hits else 1


def parse_now(text):
    if not text:
        return utc_now()
    d = dt.datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    return d if d.tzinfo is None else (d - d.utcoffset()).replace(tzinfo=None)


# ---------------------------------------------------------------- verification

def load_reliable(path):
    """name (lower) -> {country, region, state, agency}, from fuentes.json."""
    doc = read_json(path, {"por_pais": {}})
    region_of = {c: r for r, cs in doc.get("regiones", {}).items() for c in cs}
    agencies = {a.lower() for a in doc.get("agencias", [])}
    out = {}
    for country, groups in doc.get("por_pais", {}).items():
        for kind in ("independientes", "estatales"):
            for name in groups.get(kind, []):
                out[name.lower()] = {"country": country, "region": region_of.get(country, "?"),
                                     "state": kind == "estatales", "agency": name.lower() in agencies}
    for group in doc.get("medios", {}).values():          # older flat format
        for name in group:
            out.setdefault(name.lower(), {"country": "?", "region": "?", "state": False,
                                          "agency": name.lower() in agencies})
    return out


def lookup(name, ok):
    """The catalogue entry for an outlet name, matching 'Reuters' or 'Reuters (via Yahoo)'."""
    n = name.lower().strip()
    best = None
    for m, info in ok.items():
        if n == m or n.startswith(m + " ") or n.startswith(m + ",") or n.startswith(m + " ("):
            if best is None or len(m) > len(best[0]):
                best = (m, info)
    return best[1] if best else None


def parse_when(text, whole=""):
    """'2026-10-29' or '2026-10-29 14:00' (UTC) -> naive UTC datetime."""
    try:
        return dt.datetime.fromisoformat(text.strip().replace("Z", "").replace("T", " "))
    except ValueError:
        raise SocialError("the date of a source is YYYY-MM-DD or \"YYYY-MM-DD HH:MM\" (UTC), not %r in %r"
                          % (text, whole))


def ago(hours):
    if hours < 1:
        return "%d minutos" % max(0, int(hours * 60))
    if hours < 48:
        return "%d horas" % int(hours)
    return "%d días" % int(hours // 24)


def freshness(sources, now, first_seen=None):
    """How old the news is, from the earliest dated reliable report.

    -> (label, info, reasons). Confirmations dated more than OTHER_EVENT_DAYS before
    the median confirmation are about another event: they are marked s["other_event"]
    and the verdict leaves them out."""
    reasons = []
    dated = [s for s in sources if s["when"] and s["reliable"] and not s["copy_of"]
             and s["stance"] in ("confirma", "parcial")]
    for s in sources:
        if s["when"] and s["when"] > now + dt.timedelta(minutes=10):
            raise SocialError("%s is dated %s, in the future (dates are UTC)" % (s["outlet"], s["when"]))
    conf = sorted(s["when"] for s in dated if s["stance"] == "confirma")
    if conf:
        mid = conf[len(conf) // 2] if len(conf) % 2 else conf[len(conf) // 2 - 1]
        other = [s for s in dated if s["when"] < mid - dt.timedelta(days=OTHER_EVENT_DAYS)]
        for s in other:
            s["other_event"] = True
        if other:
            reasons.append("%d fuente(s) con fecha de más de %d días antes que las demás (%s): hablan de otro "
                           "hecho y no cuentan" % (len(other), OTHER_EVENT_DAYS, ", ".join(
                               "%s %s" % (s["outlet"], s["when"].strftime("%d/%m/%Y")) for s in other[:3])))
        dated = [s for s in dated if not s.get("other_event")]
    if not dated:
        undated = [s for s in sources if s["reliable"] and s["stance"] == "confirma" and not s["when"]]
        if undated:
            reasons.append("ninguna fuente tiene fecha: no se sabe si es de hoy (agregá la fecha de cada nota: "
                           "\"Medio|url|confirma|2026-11-06 14:00\")")
        return "SIN FECHA", {}, reasons
    first = min(s["when"] for s in dated)
    hours = (now - first).total_seconds() / 3600
    label = "NUEVA" if hours < FRESH_H else "RECIENTE" if hours < RECENT_H else "VIEJA"
    info = {"primera_nota": first.strftime("%Y-%m-%d %H:%M"), "horas": round(hours, 1), "frescura": label}
    reasons.append("la primera nota es del %s UTC (hace %s): %s" % (first.strftime("%d/%m/%Y %H:%M"), ago(hours), {
        "NUEVA": "es de hoy, puede mover el precio",
        "RECIENTE": "ya tiene %d a %d horas, buena parte ya está en el precio" % (FRESH_H, RECENT_H),
        "VIEJA": "es vieja, ya está en el precio"}[label]))
    if first_seen and (first_seen - first).total_seconds() / 3600 > RECYCLED_H:
        info["reciclada"] = True
        reasons.append("la viste el %s pero los diarios la publicaron el %s: es una noticia vieja que volvió a "
                       "circular (RECICLADA)" % (first_seen.strftime("%d/%m %H:%M"), first.strftime("%d/%m %H:%M")))
    return label, info, reasons


def parse_source(text, kind, ok=None):
    ok = ok or {}
    parts = [p.strip() for p in text.split("|")]
    if len(parts) < 3:
        raise SocialError("--source wants \"Medio|url|confirma\" (or parcial, desmiente, no_dice), "
                          "optionally \"|copia de OTRO\": %r" % text)
    stance = parts[2].lower()
    if stance not in STANCES:
        raise SocialError("the stance must be one of %s, not %r" % (", ".join(STANCES), parts[2]))
    copy_of, tilde, when = None, "", None
    for extra in parts[3:]:
        low = extra.lower()
        if low.startswith("copia de "):
            copy_of = extra[9:].strip()
        elif low in TILDES:
            tilde = low
        elif extra:
            when = parse_when(extra, text)
    if kind == "redes" and tilde not in TILDES:
        raise SocialError("an X post needs its checkmark: \"Cuenta|url|confirma|gris\" (gris, dorado, azul "
                          "or ninguno), not %r" % text)
    tilde = tilde or None
    if kind in ("vocero", "economista") and "," not in parts[0]:
        raise SocialError("a %s needs name and %s: \"Nombre, %s|url|confirma\"" % (
            kind, "role" if kind == "vocero" else "institution", "cargo" if kind == "vocero" else "institución"))
    info = lookup(parts[0], ok) if kind == "medio" else None
    if kind == "medio" and info and info["state"]:
        kind = "estatal"                      # a state outlet speaks for its government
    reliable = kind in ("oficial", "vocero", "economista", "estatal") or (kind == "medio" and info is not None)
    country = (info or {}).get("country") or "?"
    return {"outlet": parts[0], "url": parts[1], "stance": stance, "kind": kind, "copy_of": copy_of,
            "tilde": tilde, "when": when, "reliable": reliable, "country": country, "region": (info or {}).get("region", "?"),
            "agency": bool(info and info["agency"])}


def verdict(sources, age_min, high_impact=False):
    """-> (status, reasons, stats). See the module docstring."""
    reasons = []
    official = [s for s in sources if s["kind"] == "oficial"]
    if any(s["stance"] == "desmiente" for s in official):
        return "FALSA", ["una fuente oficial la desmiente"], {}
    counted, seen, repeated = [], set(), 0
    for s in sources:
        if s["reliable"] and not s["copy_of"] and not s.get("other_event") \
                and s["kind"] in ("medio", "estatal", "vocero", "economista"):
            key = s["outlet"].lower().strip()
            if key in seen:
                repeated += 1            # two notes from one outlet are one source
                continue
            seen.add(key)
            counted.append(s)
    talking = [s for s in counted if s["stance"] in ("confirma", "parcial", "desmiente")]
    confirms = [s for s in counted if s["stance"] == "confirma"]
    indep_conf = [s for s in confirms if s["kind"] == "medio"]
    denies = [s for s in counted if s["stance"] == "desmiente" and s["kind"] == "medio"]
    ratio = len(confirms) / len(talking) if talking else 0.0
    countries = sorted({s["country"] for s in confirms if s["country"] != "?"})
    regions = sorted({s["region"] for s in confirms if s["region"] != "?"})
    agency = any(s["agency"] for s in confirms) or any(s["stance"] == "confirma" for s in official)
    need, need_ratio = (6, 0.85) if high_impact else (4, 0.80)
    stats = {"confirman": len(confirms), "hablan": len(talking), "proporcion": round(ratio, 2),
             "paises": countries, "regiones": regions, "agencia": agency, "alto_impacto": high_impact}

    copies = [s for s in sources if s["copy_of"]]
    posts = [s for s in sources if s["kind"] == "redes"]
    weak = [s for s in sources if s["kind"] == "medio" and not s["reliable"] and not s["copy_of"]]
    dropped = [s for s in posts if s["tilde"] in ("azul", "ninguno")]
    partial = [s for s in counted if s["stance"] == "parcial"]
    if copies:
        reasons.append("%d fuente(s) solo copian a otra y no cuentan" % len(copies))
    if repeated:
        reasons.append("%d nota(s) repetidas de un mismo medio: cada medio cuenta una sola vez" % repeated)
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
        reasons.append("%d fuente(s) dan datos distintos (quién, qué, cuándo o cuánto)" % len(partial))

    short = []
    if len(confirms) < need:
        short.append("confirman %d y hacen falta %d" % (len(confirms), need))
    if talking and ratio < need_ratio:
        short.append("confirman el %.0f %% de las que hablan del tema y hace falta el %.0f %%"
                     % (100 * ratio, 100 * need_ratio))
    if len(indep_conf) < 2:
        short.append("hacen falta al menos 2 diarios independientes (las voces oficiales no alcanzan solas)")
    if high_impact and len(regions) < 2:
        short.append("alto impacto: hace falta confirmación de 2 regiones o más (hay %d)" % len(regions))
    if high_impact and not agency:
        short.append("alto impacto: hace falta una agencia internacional o un documento oficial")

    if official and any(s["stance"] == "confirma" for s in official) and not denies:
        status = "VERIFICADA"
        reasons.insert(0, "lo confirma un documento oficial")
    elif denies:
        status = "DUDOSA"
        reasons.insert(0, "%s la desmiente" % denies[0]["outlet"])
    elif not short:
        status = "VERIFICADA"
        reasons.insert(0, "%d de %d fuentes confiables confirman los mismos datos (%.0f %%), desde %d país(es) y "
                       "%d región(es)" % (len(confirms), len(talking), 100 * ratio, len(countries), len(regions)))
    elif len(confirms) <= 2:
        status = "FALSA"
        reasons.insert(0, "solo %d fuente(s) confiable(s) confirman" % len(confirms))
    else:
        status = "DUDOSA"
        reasons[0:0] = short
    if age_min is not None and age_min < 60 and status == "VERIFICADA":
        status = "DUDOSA"
        reasons.insert(0, "salió hace %d minutos: volver a revisar en una hora (y buscar desmentidos)" % age_min)
    return status, reasons, stats


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
    now = parse_now(a.now)
    first = parse_when(a.first_seen, "--first-seen") if a.first_seen else None
    fresh, finfo, freasons = freshness(sources, now, first)
    starts = [t for t in [first, finfo.get("primera_nota") and parse_when(finfo["primera_nota"])] if t]
    age = int((now - min(starts)).total_seconds() // 60) if starts else None
    status, reasons, stats = verdict(sources, age, a.high_impact)
    stats.update(finfo)
    stats["frescura"] = fresh
    cid = (max(c["id"] for c in log["checks"]) + 1) if log["checks"] else 1
    log["checks"].append({"id": cid, "claim": a.claim, "checked_at": now.strftime("%Y-%m-%d %H:%M"),
                          "first_seen": a.first_seen, "status": status, "freshness": fresh,
                          "reasons": reasons + freasons, "stats": stats, "high_impact": a.high_impact,
                          "sources": [dict(s, when=s["when"].strftime("%Y-%m-%d %H:%M") if s["when"] else None)
                                      for s in sources]})
    write_json(a.log, log)
    mark = {"VERIFICADA": "OK", "DUDOSA": "??", "FALSA": "XX"}[status]
    label = fresh + (" (RECICLADA)" if finfo.get("reciclada") else "")
    print("[%s] %s  (#%d)  fecha: %s\n  %s" % (mark, status, cid, label, a.claim))
    for r in reasons + freasons:
        print("  - " + r)
    if a.high_impact:
        print("  (noticia de alto impacto: 6 confirmaciones, 85 %, 2 regiones y una agencia o documento oficial)")
    groups = {}
    for s in sources:
        key = s["country"] if s["kind"] in ("medio", "estatal") else \
            {"oficial": "documento oficial", "vocero": "voceros", "economista": "economistas",
             "redes": "X"}.get(s["kind"], "?")
        groups.setdefault(key, []).append(s)
    print("  Por país:")
    for key in sorted(groups, key=lambda c: (c in ("?", "X"), c)):
        print("    %s" % ("fuera de la lista" if key == "?" else key))
        for s in groups[key]:
            tag = ("  (otro hecho: fecha distinta)") if s.get("other_event") else \
                  ("  (copia de %s)" % s["copy_of"]) if s["copy_of"] else \
                  ("  (tilde %s)" % s["tilde"]) if s["kind"] == "redes" else \
                  "  (medio estatal: voz del gobierno)" if s["kind"] == "estatal" else \
                  "" if s["reliable"] else "  (no cuenta)"
            when = s["when"].strftime("%d/%m/%Y") if s["when"] else "sin fecha "
            print("      %-9s %-26s %s  %s%s" % (s["stance"], s["outlet"][:26], when, s["url"][:50], tag))
    if status == "VERIFICADA":
        print({"NUEVA": "  Es verdad y es de hoy: se puede usar para operar y para el historial "
                        "(add-event --verification %d)." % cid,
               "RECIENTE": "  Es verdad, pero tiene más de %d horas: buena parte ya está en el precio. Usala con "
                           "cuidado y no persigas el movimiento (add-event --verification %d)." % (FRESH_H, cid),
               "VIEJA": "  Es verdad, pero es vieja: sirve de contexto, no para operar hoy "
                        "(add-event --verification %d para el historial)." % cid,
               "SIN FECHA": "  Es verdad, pero falta la fecha: antes de operar, fijate cuándo pasó "
                            "(add-event --verification %d)." % cid}[fresh])
    else:
        print({"DUDOSA": "  No operar por esta noticia; si hay posiciones abiertas, achicar y volver a revisar en "
                         "1 hora.", "FALSA": "  Descartada."}[status])
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
    p.add_argument("--source", action="append",
                   help='"Outlet|url|confirma|2026-11-06 14:00" (parcial, desmiente, no_dice; date in UTC)')
    p.add_argument("--official", action="append", help="an official document: same format")
    p.add_argument("--vocero", action="append", help='an official spokesperson: "Name, role|url|confirma"')
    p.add_argument("--economist", action="append", help='a recognised economist: "Name, institution|url|confirma"')
    p.add_argument("--social", action="append", help='an X post: "Account|url|confirma|gris" (gris/dorado/azul/ninguno)')
    p.add_argument("--list", action="store_true")
    p.add_argument("--now", help="pretend it is this UTC time")
    p.add_argument("--high-impact", action="store_true",
                   help="news that can move the market a lot: 6 confirmations, 85 %%, 2 regions, an agency")
    p = sub.add_parser("news")
    p.add_argument("--query", help="comma list of words (default: crypto and macro/political words)")
    p.add_argument("--days", type=int, default=3)
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--for-verify", action="store_true", help="print each hit as a --source line for verify")
    p.add_argument("--offline", action="append", help="a saved RSS file instead of the network (Outlet_Name.xml)")
    p.add_argument("--now", help="pretend it is this UTC time")
    p.add_argument("--json")
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
                "add-event": cmd_add_event, "news": cmd_news}[a.cmd](a)
    except SocialError as e:
        print("social.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
