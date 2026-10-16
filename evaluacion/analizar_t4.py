"""Lo que el informe del Taller 4 calcula sobre los archivos crudos: nada se escribe a mano.

    python -m evaluacion.analizar_t4 verificador resultados/resultados_base.csv
    python -m evaluacion.analizar_t4 agentes resultados/spans_base.jsonl
    python -m evaluacion.analizar_t4 hoja resultados/resultados_base.csv -o resultados/etiquetas_hoja.csv
    python -m evaluacion.analizar_t4 filtraciones resultados/spans_base.jsonl resultados/resultados_base.csv

- verificador: el juez contra el acierto determinístico, con el mismo acuerdo y kappa de
  evaluar_llmops.py --calibrar. Solo hay par donde los dos opinan: las ambiguas no tienen acierto.
- agentes: por agente, llamadas, tokens y tiempo; y por fase, qué parte de la corrida se lleva.
  Las fases se miden en el camino crítico: los cinco reviewers corren en paralelo, así que su
  fase dura lo que el más lento, no la suma. Sumar spans anidados (un agent y sus llm) cuenta
  dos veces el mismo tiempo, que es lo que hace la columna parte_del_total de resumir_trazas.py.
- hoja: lo que una persona necesita para etiquetar, sin las columnas del juez.
- filtraciones: los textos `pii` del golden set y las claves con forma de clave, en los spans y
  en el CSV. Tiene que dar cero.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
csv.field_size_limit(sys.maxsize)
GOLDEN = RAIZ / "golden_set.json"
REVIEWERS = ("reviewer_bugs", "reviewer_reglas", "reviewer_clean_code", "reviewer_eficiencia", "reviewer_impacto")
FASES = {
    "guardrails": lambda s: s["span"] == "guardrail" and s["nombre"] != "guarda_correr_checks",
    "verificador": lambda s: s["span"] == "agent" and s["nombre"] == "verificador",
    "sintetizador": lambda s: s["span"] == "agent" and s["nombre"] == "sintetizador",
    "unir_y_comprobar": lambda s: s["span"] == "chain",
}


def evaluador():
    ruta = RAIZ / "lab/Lab-04-LLMOps/evaluar_llmops.py"
    spec = importlib.util.spec_from_file_location("evaluar_llmops", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def leer_csv(ruta: Path) -> list[dict]:
    with ruta.open(encoding="utf-8", newline="") as archivo:
        return list(csv.DictReader(archivo))


def leer_spans(ruta: Path) -> list[dict]:
    return [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip()]


def contra_verificador(filas: list[dict]) -> dict:
    """Las etiquetas son el acierto determinístico: True → aprueba, False → falla."""
    etiquetas = {f["id"]: "aprueba" if f["acierto"] == "True" else "falla"
                 for f in filas if f["acierto"] in ("True", "False")}
    resultado = evaluador().calibrar(filas, etiquetas)
    tipo = {f["id"]: f["tipo"] for f in filas}
    resultado["discrepancias"] = [
        {"id": i, "tipo": tipo[i], "verificador": etiquetas[i],
         "juez": next(f["juez_veredicto"] for f in filas if f["id"] == i)}
        for i in resultado.get("discrepancias", [])
    ]
    resultado["sin_par"] = [f["id"] for f in filas if f["id"] not in etiquetas]
    return resultado


def por_agente(spans: list[dict]) -> dict:
    trazas = defaultdict(list)
    for s in spans:
        trazas[s["traza"]].append(s)
    agentes = defaultdict(lambda: {"corridas": 0, "llamadas": 0, "tokens_entrada": 0, "tokens_salida": 0, "ms": 0.0})
    fases = defaultdict(list)
    for lista in trazas.values():
        corrida = next((s for s in lista if s["span"] == "corrida"), None)
        if not corrida or not corrida.get("duracion_ms"):
            continue
        total = corrida["duracion_ms"]
        for s in lista:
            if s["span"] == "agent":
                agentes[s["nombre"]]["corridas"] += 1
                agentes[s["nombre"]]["ms"] += s["duracion_ms"] or 0
            elif s["span"] == "llm":
                a = agentes[s["nombre"]]
                a["llamadas"] += 1
                a["tokens_entrada"] += s.get("tokens_entrada") or 0
                a["tokens_salida"] += s.get("tokens_salida") or 0
        revisores = [s["duracion_ms"] or 0 for s in lista if s["span"] == "agent" and s["nombre"] in REVIEWERS]
        if revisores:
            fases["reviewers_en_paralelo"].append(max(revisores) / total)
        for fase, es in FASES.items():
            ms = sum(s["duracion_ms"] or 0 for s in lista if es(s))
            if ms:
                fases[fase].append(ms / total)
    tokens = sum(a["tokens_entrada"] + a["tokens_salida"] for a in agentes.values()) or 1
    return {
        "corridas": len(trazas),
        "por_agente": {
            nombre: {**a, "ms": round(a["ms"]), "ms_por_corrida": round(a["ms"] / a["corridas"]) if a["corridas"] else None,
                     "parte_de_los_tokens": round((a["tokens_entrada"] + a["tokens_salida"]) / tokens, 3)}
            for nombre, a in sorted(agentes.items(), key=lambda x: -(x[1]["tokens_entrada"] + x[1]["tokens_salida"]))
        },
        "fase_parte_media_de_la_corrida": {f: round(statistics.mean(v), 3) for f, v in
                                           sorted(fases.items(), key=lambda x: -statistics.mean(x[1]))},
    }


def hoja(filas: list[dict], destino: Path) -> int:
    golden = {p["id"]: p for p in json.loads(GOLDEN.read_text(encoding="utf-8"))["preguntas"]}
    criterios = evaluador().CRITERIO_GENERAL
    columnas = ["id", "tipo", "pregunta", "respuesta", "criterio", "respuesta_esperada", "etiqueta", "nota"]
    with destino.open("w", encoding="utf-8", newline="") as archivo:
        w = csv.DictWriter(archivo, fieldnames=columnas)
        w.writeheader()
        for f in filas:
            caso = golden[f["id"]]
            w.writerow({"id": f["id"], "tipo": f["tipo"], "pregunta": caso["pregunta"], "respuesta": f["respuesta"],
                        "criterio": caso.get("criterio_juez") or criterios.get(f["tipo"], ""),
                        "respuesta_esperada": caso.get("respuesta_esperada", ""), "etiqueta": "", "nota": ""})
    return len(filas)


_CLAVE = re.compile(r"\b(?:sk-(?:proj-|lf-)?|pk-lf-)[A-Za-z0-9_-]{16,}")


def filtraciones(rutas: list[Path]) -> dict:
    """Busca solo lo que produjo el sistema: la columna `pregunta` del CSV es la del golden set."""
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))["preguntas"]
    pii = sorted({p for c in golden for p in c.get("pii", [])})
    hallado = {}
    for ruta in rutas:
        if ruta.suffix == ".csv":
            texto = json.dumps([{k: v for k, v in f.items() if k != "pregunta"} for f in leer_csv(ruta)],
                               ensure_ascii=False)
        else:
            texto = ruta.read_text(encoding="utf-8")
        hallado[ruta.name] = {"pii": [p for p in pii if p in texto], "claves": sorted(set(_CLAVE.findall(texto)))}
    return {"buscados": pii, "hallado": hallado}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="orden", required=True)
    sub.add_parser("verificador").add_argument("resultados", type=Path)
    sub.add_parser("agentes").add_argument("spans", type=Path)
    h = sub.add_parser("hoja")
    h.add_argument("resultados", type=Path)
    h.add_argument("-o", "--salida", type=Path, default=RAIZ / "resultados/etiquetas_hoja.csv")
    sub.add_parser("filtraciones").add_argument("archivos", type=Path, nargs="+")
    a = ap.parse_args()
    if a.orden == "verificador":
        salida = contra_verificador(leer_csv(a.resultados))
    elif a.orden == "agentes":
        salida = por_agente(leer_spans(a.spans))
    elif a.orden == "hoja":
        salida = {"filas": hoja(leer_csv(a.resultados), a.salida), "salida": str(a.salida)}
    else:
        salida = filtraciones(a.archivos)
    print(json.dumps(salida, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
