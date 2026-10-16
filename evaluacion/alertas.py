"""Tres alertas de monitoreo, con el umbral sacado de la medición base y probado en la mejora.

    python -m evaluacion.alertas --base resultados/spans_base.jsonl resultados/resultados_base.csv \\
        --revisar resultados/spans_mejora.jsonl resultados/resultados_mejora.csv -o resultados/alertas.json

Cada alerta se calcula sobre una ventana de VENTANA corridas: el tamaño del golden set, que es lo
que se midió. Con 24 casos un caso vale 4,2 %, así que ningún umbral de tasa puede estar a menos de
un caso de lo medido: saltaría con el primer caso raro.

1. latencia: el p95 de la duración del span `corrida`. Umbral: el p95 de la base redondeado hacia
   arriba a 5 s.
2. tokens: la media de tokens de entrada por corrida que revisó un parche. Umbral: media + 3σ/√n
   de la base; la media de una ventana normal solo lo pasa por azar en ~0,1 % de las ventanas.
3. bloqueos: la tasa de preguntas que el guardrail de entrada bloquea. Umbral: la tasa de la base
   más un caso.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

csv.field_size_limit(sys.maxsize)
VENTANA = 24

QUE_MIRAR = {
    "latencia": "El span corrida de las más lentas y, debajo, qué agente se lleva el tiempo: en la base las dos "
                "más lentas (Q02, X03) eran preguntas que no pedían una revisión y el sistema revisó igual. "
                "Después, la latencia de cada generation: si todas suben a la vez, es el vLLM, no el agente.",
    "tokens": "Los spans llm por agente: el verificador gasta el 29 % de los tokens, una llamada por hallazgo "
              "pendiente; muchos hallazgos o un freno de repetición lo disparan. Después, los retriever "
              "(buscar_reglas): más consultas son más contexto en cada llamada.",
    "bloqueos": "Los spans validar_entrada con decision=bloqueada y su motivo: si una sola intención explica "
                "el aumento sobre preguntas legítimas, es un falso positivo del guardrail («omite las reglas "
                "de estilo», «muéstrame dónde se compara la contraseña» ya bloquean por error fuera del banco, "
                "en tests/test_guardrails.py).",
}


def _percentil(valores: list[float], p: float) -> float:
    xs = sorted(valores)
    k = (len(xs) - 1) * p
    i = int(k)
    return xs[i] + (xs[min(i + 1, len(xs) - 1)] - xs[i]) * (k - i)


def por_corrida(spans: list[dict]) -> list[dict]:
    trazas = defaultdict(list)
    for s in spans:
        trazas[s["traza"]].append(s)
    salida = []
    for lista in trazas.values():
        corrida = next((s for s in lista if s["span"] == "corrida"), None)
        if corrida is None:
            continue
        salida.append({"segundos": (corrida["duracion_ms"] or 0) / 1000,
                       "tokens_entrada": sum(s.get("tokens_entrada") or 0 for s in lista if s["span"] == "llm")})
    return salida


def medir(spans: list[dict], filas: list[dict]) -> dict:
    corridas = por_corrida(spans)
    con_revision = [c["tokens_entrada"] for c in corridas if c["tokens_entrada"] > 0]
    return {
        "corridas": len(corridas),
        "latencia_p95_s": round(_percentil([c["segundos"] for c in corridas], 0.95), 2),
        "tokens_media": round(statistics.mean(con_revision)),
        "tokens_desv": round(statistics.stdev(con_revision)),
        "corridas_con_revision": len(con_revision),
        "bloqueos": sum(f["guardrail_entrada"] == "bloqueada" for f in filas),
        "preguntas": len(filas),
    }


def umbrales(base: dict) -> dict:
    return {
        "latencia": math.ceil(base["latencia_p95_s"] / 5) * 5,
        "tokens": round(base["tokens_media"] + 3 * base["tokens_desv"] / math.sqrt(base["corridas_con_revision"])),
        "bloqueos": round((base["bloqueos"] + 1) / base["preguntas"], 4),
    }


def evaluar(medicion: dict, limites: dict) -> dict:
    valores = {"latencia": medicion["latencia_p95_s"], "tokens": medicion["tokens_media"],
               "bloqueos": round(medicion["bloqueos"] / medicion["preguntas"], 4)}
    return {nombre: {"valor": valores[nombre], "umbral": limites[nombre], "salta": valores[nombre] > limites[nombre]}
            for nombre in limites}


def _leer(spans: Path, resultados: Path) -> tuple[list[dict], list[dict]]:
    with resultados.open(encoding="utf-8", newline="") as f:
        filas = list(csv.DictReader(f))
    return [json.loads(l) for l in spans.read_text(encoding="utf-8").splitlines() if l.strip()], filas


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", nargs=2, type=Path, required=True, metavar=("SPANS", "RESULTADOS"))
    ap.add_argument("--revisar", nargs=2, type=Path, action="append", default=[], metavar=("SPANS", "RESULTADOS"))
    ap.add_argument("-o", "--salida", type=Path)
    a = ap.parse_args()
    base = medir(*_leer(*a.base))
    limites = umbrales(base)
    salida = {
        "ventana_corridas": VENTANA,
        "resolucion_un_caso": round(1 / base["preguntas"], 4),
        "base": base,
        "alertas": {n: {"umbral": limites[n], "que_mirar": QUE_MIRAR[n]} for n in limites},
        "revisiones": {str(spans): evaluar(medir(*_leer(spans, res)), limites) for spans, res in [tuple(a.base), *a.revisar]},
    }
    texto = json.dumps(salida, ensure_ascii=False, indent=2)
    if a.salida:
        a.salida.write_text(texto + "\n", encoding="utf-8")
    print(texto)


if __name__ == "__main__":
    main()
