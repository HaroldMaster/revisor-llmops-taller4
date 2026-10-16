"""RAGAS sobre resultados.csv caso por caso, con el script del laboratorio sin tocar.

    python -m evaluacion.ragas_por_caso resultados/resultados_base.csv -o resultados/ragas_base.csv

`evaluar_ragas.py csv` recorre las filas en serie y escribe su CSV solo al final: con gemma3:27b
fueron ~19 minutos por caso, así que un corte a las cuatro horas pierde todo. Aquí cada caso corre
en su propio proceso, uno tras otro, y su resultado queda en `<salida>.casos/<id>.csv` apenas
termina; al volver a correr se saltan los casos ya hechos. Al final se juntan en `<salida>`.

En serie a propósito: con seis procesos a la vez, gemma3 dejó de responder en el Ollama compartido
de la H200 (2026-10-15, 18:49) y volvió apenas se detuvieron. Y con un tope por caso: el cliente
de RAGAS no tiene timeout, y cuando la VPN se cayó (2026-10-15, ~20:33) un caso quedó esperando
toda la noche. Un caso que pasa de MAX_MINUTOS se corta y se reintenta una vez.
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SCRIPT = RAIZ / "lab/ragas-langfuse/evaluar_ragas.py"
PYTHON = RAIZ / ".venv-ragas/bin/python"
MAX_MINUTOS = 40      # el caso más lento de la base tardó 18
csv.field_size_limit(sys.maxsize)


def correr_caso(argumentos: list[str], entorno: dict) -> subprocess.CompletedProcess | None:
    """El caso en su proceso, con tope de tiempo; None si se pasó del tope."""
    try:
        return subprocess.run(argumentos, env=entorno, capture_output=True, text=True, timeout=MAX_MINUTOS * 60)
    except subprocess.TimeoutExpired:
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("resultados", type=Path)
    ap.add_argument("-o", "--salida", type=Path, required=True)
    ap.add_argument("--golden", type=Path, default=RAIZ / "golden_set.json")
    ap.add_argument("--juez", default="gemma3:27b")
    a = ap.parse_args()

    with a.resultados.open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        columnas = lector.fieldnames
        # El mismo filtro de evaluar_ragas.py: las filas que no lo cumplen no tienen RAGAS.
        filas = [r for r in lector if r.get("contextos") and r["tipo"] in {"simple", "multi"} and r.get("respuesta")]
    carpeta = a.salida.with_name(a.salida.name + ".casos")
    carpeta.mkdir(parents=True, exist_ok=True)
    entorno = {**os.environ, "JUEZ_BASE_URL": os.getenv("JUEZ_BASE_URL", "http://172.28.230.10:11434/v1"),
               "EMBEDDING_MODEL": os.getenv("EMBEDDING_MODEL", "bge-m3")}
    for n, fila in enumerate(filas, 1):
        salida = carpeta / f"{fila['id']}.csv"
        if salida.exists():
            print(f"[{n}/{len(filas)}] {fila['id']} ya estaba", flush=True)
            continue
        entrada = carpeta / f".{fila['id']}.entrada.csv"
        with entrada.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=columnas)
            w.writeheader()
            w.writerow(fila)
        inicio = time.time()
        argumentos = [str(PYTHON), "-u", str(SCRIPT), "csv", str(entrada), "--golden", str(a.golden),
                      "--salida", str(salida), "--juez", a.juez]
        proceso = correr_caso(argumentos, entorno)
        if proceso is None or proceso.returncode != 0:
            print(f"[{n}/{len(filas)}] {fila['id']}: {'se pasó de ' + str(MAX_MINUTOS) + ' min' if proceso is None else 'falló'}; "
                  "reintento", flush=True)
            salida.unlink(missing_ok=True)
            proceso = correr_caso(argumentos, entorno)
        entrada.unlink()
        if proceso is None:
            sys.exit(f"{fila['id']} se pasó de {MAX_MINUTOS} min dos veces: ¿VPN, Ollama? Vuelve a correr para seguir.")
        if proceso.returncode != 0:
            salida.unlink(missing_ok=True)
            sys.exit(f"{fila['id']} falló:\n{proceso.stdout[-1500:]}{proceso.stderr[-1500:]}")
        linea = next((l for l in proceso.stdout.splitlines() if l.startswith(f"  {fila['id']}")), "").strip()
        print(f"[{n}/{len(filas)}] {linea}  ({(time.time() - inicio) / 60:.1f} min)", flush=True)

    orden = [r["id"] for r in filas]
    filas_ragas = []
    for id_caso in orden:
        with (carpeta / f"{id_caso}.csv").open(encoding="utf-8", newline="") as f:
            filas_ragas += list(csv.DictReader(f))
    with a.salida.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(filas_ragas[0]))
        w.writeheader()
        w.writerows(filas_ragas)
    medias: dict[str, list[float]] = {}
    for r in filas_ragas:
        if r["valor"] != "":
            medias.setdefault(r["metrica"], []).append(float(r["valor"]))
    print({m: round(sum(v) / len(v), 3) for m, v in medias.items()} | {"casos": len(orden)})
    print(f"→ {a.salida}")


if __name__ == "__main__":
    main()
