"""Verificador público. Comprueba estructura y ejecución, no comprensión escrita."""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

import nbformat
from nbclient import NotebookClient
from jupyter_client import KernelManager
from jupyter_client.kernelspec import KernelSpecManager

ROOT = Path(__file__).resolve().parent


def revisar_estructura(notebook):
    contract = json.loads((ROOT / "contrato.json").read_text(encoding="utf-8"))
    expected = contract["cells"]
    if [c.id for c in notebook.cells] != [c["id"] for c in expected]:
        raise ValueError("No elimines ni reordenes celdas del notebook. Recupera la estructura del starter.")
    pending = []
    for cell, rule in zip(notebook.cells, expected):
        if cell.cell_type != rule["type"]:
            raise ValueError(f"La celda {cell.id} cambió de tipo.")
        if rule["sha256"] is not None:
            actual = hashlib.sha256(cell.source.encode()).hexdigest()
            if actual != rule["sha256"]:
                raise ValueError(f"La celda proporcionada {cell.id} fue modificada. Solo edita respuestas, nombres y las tres funciones.")
        elif "codigo" in rule["tags"]:
            tree = ast.parse(cell.source)
            if any(isinstance(n, ast.Constant) and n.value is Ellipsis for n in ast.walk(tree)):
                pending.append(f"{cell.id}: faltan expresiones en lugar de ...")
        elif "respuesta" in rule["tags"]:
            body = cell.source.split("\n\n", 1)[-1].strip()
            if "ESCRIBE AQUÍ" in cell.source or len(body) < 10:
                pending.append(f"{cell.id}: falta una respuesta escrita")
        elif "identidad" in rule["tags"]:
            if "NOMBRE COMPLETO" in cell.source:
                pending.append("integrantes: completa ambos nombres o indica trabajo individual autorizado")
    for name, digest in contract["protected_files"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"El archivo proporcionado {name} cambió. Usa la copia original del paquete.")
    if pending:
        raise ValueError("ACTIVIDAD INCOMPLETA:\n- " + "\n- ".join(pending))


def ejecutar_limpio(notebook, output_dir, exigir_completo=True):
    """Kernel efímero con el mismo sys.executable que ejecuta este verificador."""
    with tempfile.TemporaryDirectory(prefix="h3-kernel-") as tmp:
        spec_root = Path(tmp)
        spec = spec_root / "h3-local"
        spec.mkdir()
        (spec / "kernel.json").write_text(json.dumps({
            "argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
            "display_name": "Hackathon 3 local", "language": "python",
        }), encoding="utf-8")
        ksm = KernelSpecManager(kernel_dirs=[str(spec_root)])
        km = KernelManager(kernel_name="h3-local", kernel_spec_manager=ksm)
        if exigir_completo:
            notebook.cells.append(nbformat.v4.new_code_cell(
                "assert validacion_tecnica is True, 'La validación final no se completó.'\n"
                "assert validar_final(predecir, actualizar, paso_entrenamiento, historial, parametros_entrenados)\n",
                id="verificador-externo"))
        try:
            client = NotebookClient(notebook, km=km, timeout=120,
                                    resources={"metadata": {"path": str(ROOT)}})
            client.execute(env={**os.environ, "H3_OUTPUT_DIR": str(Path(output_dir).resolve()),
                                "MPLBACKEND": "Agg", "IPYTHONDIR": str(spec_root / "ipython"),
                                "MPLCONFIGDIR": str(spec_root / "matplotlib"),
                                "XDG_CACHE_HOME": str(spec_root / "cache")})
        finally:
            if exigir_completo:
                notebook.cells.pop()
            if km.has_kernel:
                km.shutdown_kernel(now=True)
            if "client" in locals() and client.kc is not None:
                client.kc.stop_channels()
    return notebook


def verificar(path, output_dir):
    source = Path(path).resolve()
    destination = Path(output_dir).resolve()
    notebook = nbformat.read(source, as_version=4)
    nbformat.validate(notebook)
    revisar_estructura(notebook)
    with tempfile.TemporaryDirectory(prefix="h3-run-") as tmp:
        staging = Path(tmp)
        ejecutar_limpio(notebook, staging)
        artifacts = ("traza_entrenamiento.csv", "tabla_and.csv", "entrenamiento_and.png")
        for name in artifacts:
            p = staging / name
            if not p.is_file() or p.stat().st_size == 0:
                raise ValueError(f"La ejecución actual no produjo {name}.")
        destination.mkdir(parents=True, exist_ok=True)
        for name in artifacts:
            shutil.copy2(staging / name, destination / name)
        nbformat.write(notebook, destination / "Hackathon_3_Verificado.ipynb")
        receipt = {"status": "pass_technical_only", "verified_at_utc": datetime.now(timezone.utc).isoformat(),
                   "notebook": source.name, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                   "python": sys.version.split()[0], "python_executable": sys.executable,
                   "human_review": "Las predicciones y reflexiones requieren revisión docente.",
                   "outputs_sha256": {n: hashlib.sha256((destination/n).read_bytes()).hexdigest() for n in artifacts}}
        (destination / "verificacion.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print("VERIFICACIÓN TÉCNICA COMPLETA")
    print(f"Copia ejecutada: {destination / 'Hackathon_3_Verificado.ipynb'}")
    print("La calidad de las respuestas y el orden real de las predicciones requieren revisión docente.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notebook", type=Path, default=ROOT / "Hackathon_3_Starter.ipynb")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output" / "verificacion")
    args = parser.parse_args()
    try:
        verificar(args.notebook, args.output_dir)
    except Exception as exc:
        print(f"VERIFICACIÓN NO COMPLETADA\n{exc}", file=sys.stderr)
        print("El notebook original no se modificó. Las evidencias antiguas no certifican esta ejecución.", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
