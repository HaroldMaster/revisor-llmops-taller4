"""Lo que el informe del Taller 4 calcula sobre los archivos crudos: nada se escribe a mano.

    python -m evaluacion.analizar_t4 verificador resultados/resultados_base.csv
    python -m evaluacion.analizar_t4 agentes resultados/spans_base.jsonl
    python -m evaluacion.analizar_t4 hoja resultados/resultados_base.csv -o resultados/etiquetas_hoja.csv
    python -m evaluacion.analizar_t4 filtraciones resultados/spans_base.jsonl resultados/resultados_base.csv
    python -m evaluacion.analizar_t4 recalificar resultados/resultados_base.csv -o resultados/resultados_base_v2.csv
    python -m evaluacion.analizar_t4 tres resultados/resultados_base.csv resultados/etiquetas.csv
    python -m evaluacion.analizar_t4 comparar resultados/resultados_base_v3.csv resultados/resultados_mejora.csv

- verificador: el juez contra el acierto determinístico, con el mismo acuerdo y kappa de
  evaluar_llmops.py --calibrar. Solo hay par donde los dos opinan: las ambiguas no tienen acierto.
- agentes: por agente, llamadas, tokens y tiempo; y por fase, qué parte de la corrida se lleva.
  Las fases se miden en el camino crítico: los cinco reviewers corren en paralelo, así que su
  fase dura lo que el más lento, no la suma. Sumar spans anidados (un agent y sus llm) cuenta
  dos veces el mismo tiempo, que es lo que hace la columna parte_del_total de resumir_trazas.py.
- hoja: lo que una persona necesita para etiquetar, sin las columnas del juez.
- recalificar: el acierto de las mismas respuestas con el golden set actual (v2), y acierto_v1 al lado.
- tres: persona, juez y verificador, par a par, y los casos en que no coinciden.
- comparar: antes y después caso por caso, con lo que la mejora buscaba separado del azar.
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


def recalificar(filas: list[dict], golden: dict[str, dict]) -> list[dict]:
    """El acierto de cada respondible con otro golden set, sobre las mismas respuestas: cuando lo
    que cambia es el verificador y no el sistema, no hace falta volver a correr el sistema."""
    e = evaluador()
    salida = []
    for f in filas:
        nueva = {**f, "acierto_v1": f["acierto"]}
        if f["tipo"] in e.RESPONDIBLES and f["estado"] != "excepcion":
            ok = e.acierto_general(golden[f["id"]], f["respuesta"], e.T3.se_abstiene(f["respuesta"]),
                                   f["herramientas_usadas"].split())
            nueva["acierto"] = "" if ok is None else str(ok)
        salida.append(nueva)
    return salida


def _de_verificador(acierto: str) -> str:
    return {"True": "aprueba", "False": "falla"}.get(acierto, "")


def tres_fuentes(filas: list[dict], etiquetas: dict[str, dict]) -> dict:
    """Persona, juez y verificador sobre los mismos casos: acuerdo de cada par y los casos en
    que no coinciden, con el motivo del juez y la nota de la persona."""
    calibrar = evaluador().calibrar

    def par(a: dict[str, str], b: dict[str, str]) -> dict:
        comunes = [i for i in a if i in b and a[i] and b[i]]
        filas_b = [{"id": i, "juez_veredicto": b[i]} for i in comunes]
        r = calibrar(filas_b, {i: a[i] for i in comunes})
        return {k: r[k] for k in ("pares", "acuerdo", "kappa") if k in r}

    humano = {i: e["etiqueta"] for i, e in etiquetas.items() if e["etiqueta"]}
    juez = {f["id"]: f["juez_veredicto"] for f in filas if f["juez_veredicto"] in ("aprueba", "falla")}
    verificador = {f["id"]: _de_verificador(f["acierto"]) for f in filas if _de_verificador(f["acierto"])}
    casos = []
    for f in filas:
        votos = {"humano": humano.get(f["id"], ""), "juez": juez.get(f["id"], ""),
                 "verificador": verificador.get(f["id"], "")}
        if len({v for v in votos.values() if v}) > 1:
            casos.append({"id": f["id"], "tipo": f["tipo"], **votos, "juez_motivo": f["juez_motivo"],
                          "nota_humano": etiquetas.get(f["id"], {}).get("nota", "")})
    return {"juez_vs_humano": par(humano, juez), "verificador_vs_humano": par(humano, verificador),
            "juez_vs_verificador": par(verificador, juez), "desacuerdos": casos}


# Lo que la mejora de la 2.c buscaba, y con qué parte: el resto de los cambios es azar del modelo.
OBJETIVOS = {"S01": "prompt v2: severidad y seguridad", "A01": "prompt v2: test borrado",
             "C01": "prompt v2: test roto", "P01": "prompt v2: test que falta",
             "C09": "adaptador: dos reglas en una línea"}


def comparar(antes: list[dict], despues: list[dict], objetivos: dict[str, str] = OBJETIVOS) -> dict:
    """Caso por caso, el acierto (mismo golden set) y el juez de dos corridas, y si el caso era
    un objetivo de la mejora. Un cambio fuera de los objetivos es azar del modelo hasta que se
    demuestre lo contrario: el modelo muestrea y cada caso se corre una vez."""
    por_id = {f["id"]: f for f in despues}
    filas = []
    for a in antes:
        d = por_id[a["id"]]
        cambio = a["acierto"] != d["acierto"]
        filas.append({"id": a["id"], "tipo": a["tipo"], "objetivo": objetivos.get(a["id"], ""),
                      "acierto_antes": a["acierto"], "acierto_despues": d["acierto"],
                      "juez_antes": a["juez_veredicto"], "juez_despues": d["juez_veredicto"],
                      "tokens_antes": a["tokens_entrada"], "tokens_despues": d["tokens_entrada"],
                      "segundos_antes": a["segundos"], "segundos_despues": d["segundos"],
                      "cambio": ("mejora" if d["acierto"] == "True" else "empeora") if cambio else ""})

    def cuenta(xs, valor):
        return sum(f[valor] == "True" for f in xs)

    resp = [f for f in filas if f["acierto_antes"] in ("True", "False") or f["acierto_despues"] in ("True", "False")]
    buscados = [f for f in filas if f["objetivo"]]
    otros = [f for f in filas if not f["objetivo"]]
    return {
        "aciertos": {"antes": cuenta(resp, "acierto_antes"), "despues": cuenta(resp, "acierto_despues"), "de": len(resp)},
        "juez_aprueba": {"antes": sum(f["juez_antes"] == "aprueba" for f in filas),
                         "despues": sum(f["juez_despues"] == "aprueba" for f in filas), "de": len(filas)},
        "objetivos": {"mejoran": [f["id"] for f in buscados if f["cambio"] == "mejora"],
                      "siguen_fallando": [f["id"] for f in buscados if f["acierto_despues"] == "False"],
                      "empeoran": [f["id"] for f in buscados if f["cambio"] == "empeora"]},
        "fuera_de_objetivo": {"mejoran": [f["id"] for f in otros if f["cambio"] == "mejora"],
                              "empeoran": [f["id"] for f in otros if f["cambio"] == "empeora"]},
        "casos": filas,
    }


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
    r = sub.add_parser("recalificar")
    r.add_argument("resultados", type=Path)
    r.add_argument("-o", "--salida", type=Path, required=True)
    c = sub.add_parser("comparar")
    c.add_argument("antes", type=Path)
    c.add_argument("despues", type=Path)
    t = sub.add_parser("tres")
    t.add_argument("resultados", type=Path)
    t.add_argument("etiquetas", type=Path)
    a = ap.parse_args()
    if a.orden == "verificador":
        salida = contra_verificador(leer_csv(a.resultados))
    elif a.orden == "agentes":
        salida = por_agente(leer_spans(a.spans))
    elif a.orden == "hoja":
        salida = {"filas": hoja(leer_csv(a.resultados), a.salida), "salida": str(a.salida)}
    elif a.orden == "recalificar":
        golden = {p["id"]: p for p in json.loads(GOLDEN.read_text(encoding="utf-8"))["preguntas"]}
        filas = recalificar(leer_csv(a.resultados), golden)
        with a.salida.open("w", encoding="utf-8", newline="") as archivo:
            w = csv.DictWriter(archivo, fieldnames=list(filas[0]))
            w.writeheader()
            w.writerows(filas)
        salida = {"cambian": [{"id": f["id"], "v1": f["acierto_v1"], "v2": f["acierto"]} for f in filas
                              if f["acierto"] != f["acierto_v1"]], "salida": str(a.salida)}
    elif a.orden == "comparar":
        salida = comparar(leer_csv(a.antes), leer_csv(a.despues))
    elif a.orden == "tres":
        etiquetas = {e["id"]: e for e in leer_csv(a.etiquetas)}
        salida = tres_fuentes(leer_csv(a.resultados), etiquetas)
    else:
        salida = filtraciones(a.archivos)
    print(json.dumps(salida, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
