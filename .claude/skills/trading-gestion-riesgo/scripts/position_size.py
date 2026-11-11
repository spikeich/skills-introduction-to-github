#!/usr/bin/env python3
"""Calcula el tamaño de posición a partir del riesgo máximo por operación."""

import argparse
import json
import math
import sys


def calcular(capital, riesgo_pct, entrada, stop, objetivo=None,
             multiplicador=1.0, comision=0.0, lote=1.0):
    if capital <= 0:
        raise ValueError("el capital debe ser mayor que cero")
    if not 0 < riesgo_pct <= 100:
        raise ValueError("el riesgo debe estar entre 0 y 100 %")
    if entrada <= 0 or stop <= 0:
        raise ValueError("entrada y stop deben ser mayores que cero")
    if entrada == stop:
        raise ValueError("el stop no puede ser igual a la entrada")
    if multiplicador <= 0 or lote <= 0 or comision < 0:
        raise ValueError("multiplicador y lote deben ser positivos; la comisión, no negativa")

    direccion = "largo" if stop < entrada else "corto"
    distancia = abs(entrada - stop)
    riesgo_dinero = capital * riesgo_pct / 100
    riesgo_unidad = distancia * multiplicador + comision

    # Se redondea hacia abajo para no superar nunca el riesgo máximo.
    # El epsilon evita perder un lote por errores de coma flotante.
    lotes = math.floor(riesgo_dinero / riesgo_unidad / lote + 1e-9)
    tamano = lotes * lote
    riesgo_real = tamano * riesgo_unidad
    exposicion = tamano * entrada * multiplicador

    resultado = {
        "direccion": direccion,
        "tamano": tamano,
        "riesgo_maximo": round(riesgo_dinero, 2),
        "riesgo_real": round(riesgo_real, 2),
        "riesgo_real_pct": round(riesgo_real / capital * 100, 3),
        "exposicion": round(exposicion, 2),
        "apalancamiento": round(exposicion / capital, 2),
    }

    if objetivo is not None:
        a_favor = (objetivo > entrada) if direccion == "largo" else (objetivo < entrada)
        if not a_favor:
            raise ValueError("el objetivo está del mismo lado que el stop")
        rb = abs(objetivo - entrada) / distancia
        beneficio_unidad = abs(objetivo - entrada) * multiplicador - comision
        resultado["riesgo_beneficio"] = round(rb, 2)
        resultado["beneficio_potencial"] = round(tamano * beneficio_unidad, 2)
        resultado["win_rate_equilibrio_pct"] = round(100 / (1 + rb), 1)

    return resultado


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--capital", type=float, required=True)
    p.add_argument("--riesgo-pct", type=float, default=1.0,
                   help="porcentaje del capital a arriesgar (por defecto 1)")
    p.add_argument("--entrada", type=float, required=True)
    p.add_argument("--stop", type=float, required=True)
    p.add_argument("--objetivo", type=float)
    p.add_argument("--multiplicador", type=float, default=1.0,
                   help="valor en dinero de un punto de precio por unidad")
    p.add_argument("--comision", type=float, default=0.0,
                   help="comisión por unidad, ida y vuelta")
    p.add_argument("--lote", type=float, default=1.0,
                   help="tamaño mínimo negociable (por ejemplo 0.001 en cripto)")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    try:
        r = calcular(args.capital, args.riesgo_pct, args.entrada, args.stop,
                     args.objetivo, args.multiplicador, args.comision, args.lote)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0

    print(f"Dirección:        {r['direccion']}")
    print(f"Tamaño:           {r['tamano']:g} unidades")
    print(f"Riesgo real:      {r['riesgo_real']:.2f} ({r['riesgo_real_pct']:g} % del capital, "
          f"máximo {r['riesgo_maximo']:.2f})")
    print(f"Exposición:       {r['exposicion']:.2f} ({r['apalancamiento']:g}x el capital)")
    if "riesgo_beneficio" in r:
        print(f"Riesgo/beneficio: 1:{r['riesgo_beneficio']:g}")
        print(f"Beneficio pot.:   {r['beneficio_potencial']:.2f}")
        print(f"Win rate de equilibrio: {r['win_rate_equilibrio_pct']:g} %")
    if r["tamano"] == 0:
        print("Aviso: el riesgo permitido no alcanza para un lote mínimo.")
    if r["apalancamiento"] > 1:
        print("Aviso: la posición supera el capital; requiere apalancamiento.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
