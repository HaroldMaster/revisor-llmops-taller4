"""Registra en Langfuse los prompts de los agentes con la versión de revisor/agentes/prompts.py.

    python -m evaluacion.registrar_prompts

Un prompt de Langfuse por agente (revisor-reviewer_bugs, …, revisor-verificador), con la etiqueta
VERSION, la etiqueta production y CHANGELOG[VERSION] como commit_message. Si la versión ya está
registrada con el mismo texto no hace nada; si está con otro texto, falla: una etiqueta de versión
no puede apuntar a dos prompts distintos. Con --reemplazar crea una versión nueva y le mueve la
etiqueta: solo para corregir una versión que todavía no usó ninguna corrida.
"""

from __future__ import annotations

import argparse

from dotenv import load_dotenv

from revisor.config import RAIZ

load_dotenv(RAIZ / ".env")

from revisor.agentes.prompts import CHANGELOG, REVIEWERS, VERIFICADOR, VERSION  # noqa: E402
from revisor.observabilidad import configurar, nombre_de_prompt  # noqa: E402


def textos() -> dict[str, str]:
    return {**{nombre: d["sistema"] for nombre, d in REVIEWERS.items()}, "verificador": VERIFICADOR}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reemplazar", action="store_true")
    a = ap.parse_args()
    lf = configurar()
    for agente, texto in textos().items():
        nombre = nombre_de_prompt(agente)
        try:
            actual = lf.get_prompt(nombre, label=VERSION, cache_ttl_seconds=0)
        except Exception:
            actual = None
        if actual is not None and actual.prompt == texto:
            print(f"  {nombre}: {VERSION} ya registrada (versión {actual.version} de Langfuse)")
            continue
        if actual is not None and not a.reemplazar:
            raise SystemExit(f"{nombre}: la etiqueta {VERSION} ya apunta a otro texto (¿--reemplazar?)")
        nuevo = lf.create_prompt(name=nombre, type="text", prompt=texto, labels=[VERSION, "production"],
                                 commit_message=CHANGELOG[VERSION])
        print(f"  {nombre}: {VERSION} registrada como versión {nuevo.version} de Langfuse")
    lf.flush()


if __name__ == "__main__":
    main()
