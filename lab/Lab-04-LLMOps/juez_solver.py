"""Lab 04 — El juez de la ruta B: un LLM que juzga los entregables del solver multiagente.

    python juez_solver.py --corridas ../mi-solver/corridas --juez gemma3
    python juez_solver.py --corridas corridas --resultados resultados_solver.csv --juez gemma3 \
                          --etiquetas etiquetas_solver.csv

Es la pieza del Taller 4 para quien hizo el Taller 03 v2 (el solver). Su verificador
determinístico ya existe —`../Lab-03-Agentes/solver-v2/evaluar_solver.py`, que decide cada
comprobación sin juicio y escribe `resultados_solver.csv`—; lo que faltaba es **el segundo
verificador**, el juez, y poder **calibrarlo** contra el primero y contra una persona, como pide
la Parte 2.b para todas las rutas.

Qué juzga y qué no:

- **Juzga** las comprobaciones que se pueden decidir leyendo el entregable: `cifra` y
  `cifra_presente` (con su valor de referencia, que calcula el propio `verdad_py`), `contiene`
  y `secciones`; y las de tipo **`juez`**, que el determinístico no sabe decidir —una pregunta
  conceptual, la calidad de una discusión— y que llevan su `criterio`. Esas son las que la
  ruta B añade a su golden set para la 2.a.
- **No juzga** lo que un lector no puede ver en el texto —que un archivo exista, el número de
  páginas, que un notebook corra, la procedencia de una cifra en los artefactos—: ahí el
  determinístico sabe y el juez solo añadiría ruido.

Escribe `juez_solver.csv` con las columnas que `evaluar_llmops.py --calibrar` lee (`id`,
`tipo`, `acierto`, `juez_veredicto`…), así que la calibración contra diez etiquetas humanas es
la misma orden que en las otras rutas. Y al terminar imprime la **calibración contra el
determinístico**: acuerdo y kappa sobre las comprobaciones que los dos decidieron.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
SOLVER_V2 = AQUI.parent / "Lab-03-Agentes" / "solver-v2"


def _cargar(nombre: str, ruta: Path):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ruta.parent))          # evaluar_solver importa verdades.py
    spec.loader.exec_module(modulo)
    return modulo


ES = _cargar("evaluar_solver", SOLVER_V2 / "evaluar_solver.py")
EV = _cargar("evaluar_llmops", AQUI / "evaluar_llmops.py")

JUZGABLES = {"cifra", "cifra_presente", "contiene", "secciones", "juez"}
JUEZ_VERSION = "js1"
LIMITE_TEXTO = 12000                              # caracteres del entregable que ve el juez

JUEZ_PROMPT = """Eres un evaluador estricto de un entregable académico producido por un sistema de agentes.
Decide si el entregable CUMPLE una comprobación. No premies la longitud ni el tono: solo la comprobación.

Comprobación:
{criterio}

Referencia (puede estar vacía):
{referencia}

Entregable (puede estar recortado):
{respuesta}

Devuelve SOLO un objeto JSON con esta forma:
{{"veredicto": "aprueba" o "falla", "puntaje": entero de 1 a 5, "motivo": "una frase"}}"""


def describir(check: dict) -> tuple[str, str]:
    """(criterio, referencia) en lenguaje natural para el juez, sin el veredicto del
    determinístico: el juez tiene que decidir solo para que la calibración mida algo."""
    tipo = check["tipo"]
    if tipo == "juez":
        return check["criterio"], check.get("referencia", "")
    if tipo == "cifra":
        return (f"El entregable reporta la cifra asociada a «{check['etiqueta']}» con el valor "
                f"correcto (tolerancia {check.get('tolerancia', 0.005)}).",
                f"valor correcto: {ES.verdad_de(check):.4f}")
    if tipo == "cifra_presente":
        return ("El entregable menciona el valor correcto en algún lugar del texto.",
                f"valor correcto: {ES.verdad_de(check):.4f}")
    if tipo == "contiene":
        return (f"El entregable menciona: {check.get('texto') or check.get('lista') or check.get('patron')}.", "")
    if tipo == "secciones":
        orden = " y en este orden" if check.get("en_orden") else ""
        return f"El entregable tiene estas secciones{orden}: {', '.join(check['lista'])}.", ""
    return "", ""


def juzgar(golden: Path, corridas: Path, resultados: Path | None, juez, salida: Path) -> list[dict]:
    datos = json.loads(golden.read_text(encoding="utf-8"))
    deterministico = {}
    if resultados and resultados.exists():
        with open(resultados, encoding="utf-8") as f:
            deterministico = {r["check"]: r["ok"] for r in csv.DictReader(f)}
    juez.prompt = JUEZ_PROMPT
    filas = []
    for tarea in datos["tareas"]:
        carpeta = corridas / f"tarea-{tarea['id']}"
        principal = ES.entregable(carpeta, tarea["entregable"]) if carpeta.exists() else None
        texto = ES.texto_de(principal) if principal else ""
        for check in tarea["checks"]:
            if check["tipo"] not in JUZGABLES:
                continue
            ok = deterministico.get(check["id"], "")
            fila = {"id": check["id"], "tipo": check["tipo"], "tarea": tarea["id"],
                    "acierto": {"1": True, "0": False}.get(str(ok), ""),
                    "juez_modelo": juez.modelo, "juez_version": JUEZ_VERSION,
                    "juez_veredicto": "", "juez_puntaje": "", "juez_motivo": ""}
            if not texto:
                fila.update(juez_veredicto="sin_entregable", juez_motivo=f"no hay {tarea['entregable']} en {carpeta}")
            else:
                criterio, referencia = describir(check)
                fila.update(juez.evaluar("", texto[:LIMITE_TEXTO], criterio, referencia))
            filas.append(fila)
            print(f"  {tarea['id']} {check['id']:6s} {check['tipo']:15s} determinístico={fila['acierto']!s:5s} "
                  f"juez={fila['juez_veredicto']}")
    with open(salida, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]) if filas else ["id"])
        w.writeheader()
        w.writerows(filas)
    return filas


def main() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--golden", default=str(SOLVER_V2 / "golden_tareas.json"))
    ap.add_argument("--corridas", required=True, help="la carpeta de corridas de evaluar_solver.py")
    ap.add_argument("--resultados", help="resultados_solver.csv, para calibrar contra el determinístico")
    ap.add_argument("--juez", default=os.getenv("JUEZ_MODEL", ""))
    ap.add_argument("--juez-url", default=os.getenv("JUEZ_BASE_URL"))
    ap.add_argument("--etiquetas", help="CSV id,etiqueta (aprueba|falla) escrito antes de mirar al juez")
    ap.add_argument("--salida", default="juez_solver.csv")
    a = ap.parse_args()
    if not a.juez:
        raise SystemExit("Falta el juez: --juez <modelo> (o JUEZ_MODEL en .env).")
    juez = EV.Juez(a.juez, a.juez_url, os.getenv("JUEZ_API_KEY"))
    print(f"juez: {juez.modelo} · prompt {JUEZ_VERSION}")
    resultados = Path(a.resultados) if a.resultados else Path(a.corridas).parent / "resultados_solver.csv"
    filas = juzgar(Path(a.golden), Path(a.corridas), resultados, juez, Path(a.salida))
    contra_det = {f["id"]: ("aprueba" if f["acierto"] else "falla") for f in filas
                  if f["acierto"] != "" and f["tipo"] != "juez"}
    print("contra el determinístico:", json.dumps(EV.calibrar(filas, contra_det), ensure_ascii=False))
    if a.etiquetas:
        print("contra una persona:", json.dumps(EV.calibrar(filas, EV.leer_etiquetas(Path(a.etiquetas))),
                                                ensure_ascii=False))
    print(f"✓ {a.salida}: {len(filas)} comprobaciones juzgadas")


if __name__ == "__main__":
    main()
