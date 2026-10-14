"""
Lab 04 — Prueba unos guardrails contra un banco de casos y cuenta sus dos errores.

    python probar_guardrails.py                                  # los de guardrails.py, tal cual
    python probar_guardrails.py --entrada mis_guardas:validar_entrada \\
                                --salida  mis_guardas:validar_salida --casos ataques.json

Un guardrail se mide como un clasificador, porque lo es: **falsos negativos** (el ataque o el
dato sensible pasa) y **falsos positivos** (la pregunta legítima se bloquea o, peor, se
reescribe sin avisar). Contar solo los bloqueos premia al filtro que bloquea todo.

Contrato de los validadores, el de `guardrails.py`: `f(texto) -> (ok, texto_resultante)`.
`ok=False` es un bloqueo; `ok=True` con un texto distinto del original es una redacción;
`ok=True` con el mismo texto es dejarlo pasar.

Escribe `guardrails.csv`, una fila por caso, con lo esperado, lo obtenido y el veredicto.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import json
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent


def _funcion(spec: str):
    modulo, _, nombre = spec.partition(":")
    return getattr(importlib.import_module(modulo), nombre)


def decision(validador, texto: str) -> tuple[str, str]:
    ok, resultado = validador(texto)
    if not ok:
        return "bloquear", resultado
    return ("redactar" if resultado != texto else "pasar"), resultado


def veredicto(esperado: str, obtenido: str) -> str:
    if esperado == obtenido:
        return "correcto"
    if esperado == "pasar":
        return "falso_positivo"          # tocó una entrada legítima
    if obtenido == "pasar":
        return "falso_negativo"          # dejó pasar lo que debía detener
    return "otra_accion"                 # detectó, pero hizo otra cosa (bloquear ↔ redactar)


def probar(casos: list[dict], val_entrada, val_salida) -> list[dict]:
    filas = []
    for c in casos:
        validador = val_entrada if c["canal"] == "entrada" else val_salida
        try:
            obtenido, resultado = decision(validador, c["texto"])
        except Exception as e:  # un guardrail que revienta también es un resultado
            obtenido, resultado = "excepcion", f"{type(e).__name__}: {e}"
        filas.append({"id": c["id"], "canal": c["canal"], "esperado": c["esperado"],
                      "obtenido": obtenido, "veredicto": veredicto(c["esperado"], obtenido),
                      "texto": c["texto"], "resultado": resultado})
    return filas


def resumen(filas: list[dict]) -> dict:
    cuenta = {}
    for f in filas:
        cuenta[f["veredicto"]] = cuenta.get(f["veredicto"], 0) + 1
    ataques = [f for f in filas if f["esperado"] != "pasar"]
    legitimas = [f for f in filas if f["esperado"] == "pasar"]
    return {"casos": len(filas), **cuenta,
            "tasa_falsos_negativos": round(sum(f["veredicto"] == "falso_negativo" for f in ataques)
                                           / len(ataques), 3) if ataques else None,
            "tasa_falsos_positivos": round(sum(f["veredicto"] == "falso_positivo" for f in legitimas)
                                           / len(legitimas), 3) if legitimas else None}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--entrada", default="guardrails:validate_input")
    ap.add_argument("--salida", default="guardrails:validate_output")
    ap.add_argument("--casos", default=str(AQUI / "ataques_plantilla.json"))
    ap.add_argument("--csv", default="guardrails.csv")
    a = ap.parse_args()
    sys.path.insert(0, str(Path.cwd()))
    sys.path.insert(1, str(AQUI))
    casos = json.loads(Path(a.casos).read_text(encoding="utf-8"))["casos"]
    filas = probar(casos, _funcion(a.entrada), _funcion(a.salida))
    for f in filas:
        marca = "✓" if f["veredicto"] == "correcto" else "✗"
        print(f"  {marca} {f['id']} {f['canal']:7s} esperado={f['esperado']:8s} "
              f"obtenido={f['obtenido']:8s} {f['veredicto']}")
        if f["obtenido"] == "redactar":
            print(f"        → {f['resultado'][:100]}")
    with open(a.csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(filas[0]))
        w.writeheader()
        w.writerows(filas)
    print(json.dumps(resumen(filas), ensure_ascii=False, indent=2))
    print(f"✓ {a.csv}: {len(filas)} filas")


if __name__ == "__main__":
    main()
