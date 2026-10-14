"""
Lab 04 — Exporta de Langfuse los spans de tus corridas a un JSONL que `resumir_trazas.py` lee.

    python exportar_trazas.py --tag taller-04 -o spans.jsonl
    python exportar_trazas.py --sesion grupo-07-base -o spans_base.jsonl
    python exportar_trazas.py --tag taller-04 --desde 2026-10-10T08:00 -o spans.jsonl
    python resumir_trazas.py spans.jsonl --precio propietario_economico

**Por qué existe.** Desde el 2026-10-06 la Parte 1 del Taller 4 se instrumenta con Langfuse,
pero lo que se califica sigue siendo un **archivo**: las cifras del informe tienen que poder
recalcularse sin entrar a la cuenta de nadie. Este script es el puente: pide a Langfuse las
*observations* de tus corridas y escribe una línea por span con la estructura mínima de
`resumir_trazas.py`.

**Cómo traduce.** La observation raíz de cada traza (la de tu `@observe` de `.run()`) es el span
`corrida`; una `generation` es `llm`; una `tool` es `herramienta`; un `guardrail` es
`guardrail`; cualquier otro tipo (span, retriever, agent…) conserva su tipo en minúsculas. La
duración sale de `endTime - startTime` —el campo `latency` llega vacío en los spans de menos de
un milisegundo—. El error es el `statusMessage` de una observation en nivel `ERROR`. Y
`prompt_version` es el que pusiste en `metadata` con `propagate_attributes`, o, si no lo
pusiste, la versión del prompt de Langfuse ligado a la primera generation.

**Los tokens de salida incluyen los de razonamiento.** Langfuse guarda `output` y
`output_reasoning_tokens` por separado; el proveedor cobra los dos como salida. Aquí
`tokens_salida` es la suma, y `tokens_razonamiento` va aparte para que se vea.

**Dos cosas del servidor 4.x que conviene saber** (comprobadas el 2026-10-06 contra Langfuse
4.50.0): la lista de trazas de la API pública responde 404 en el modo *events_only*, así que
se consulta `GET /api/public/v2/observations`, que es lo que hace el SDK con
`api.observations.get_many`; y lo recién enviado tarda unos segundos en ser consultable —corre
este script después de `flush()`, no en la misma línea—.

Necesita `langfuse` (requirements.txt) y `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` y
`LANGFUSE_BASE_URL` en `.env`.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from langfuse import get_client  # noqa: E402

TIPOS = {"GENERATION": "llm", "TOOL": "herramienta", "GUARDRAIL": "guardrail"}
CAMPOS = "core,basic,time,io,metadata,model,usage,prompt"


def _fecha(valor) -> datetime | None:
    """El SDK devuelve datetime; un argumento de la línea de órdenes llega como texto."""
    if valor is None or isinstance(valor, datetime):
        return valor
    return datetime.fromisoformat(str(valor).replace("Z", "+00:00"))


def traer(*, tag: str | None, sesion: str | None, desde: str | None, hasta: str | None) -> list[dict]:
    """Todas las observations que cumplen los filtros, página a página (cursor)."""
    lf = get_client()
    if not lf.auth_check():
        raise SystemExit("Langfuse no responde o las claves no valen: revisa LANGFUSE_* en .env.")
    filtro = ([{"type": "arrayOptions", "column": "tags", "operator": "any of", "value": [tag]}]
              if tag else None)
    obs, cursor = [], None
    while True:
        r = lf.api.observations.get_many(
            fields=CAMPOS, limit=1000, cursor=cursor, session_id=sesion,
            from_start_time=_fecha(desde), to_start_time=_fecha(hasta),
            filter=json.dumps(filtro) if filtro else None)
        obs += [o.dict(by_alias=True) for o in r.data]
        cursor = (r.meta.dict(by_alias=True) if r.meta else {}).get("cursor")
        if not cursor or not r.data:
            return obs


def _ms(o: dict) -> float | None:
    ini, fin = _fecha(o.get("startTime")), _fecha(o.get("endTime"))
    return round((fin - ini).total_seconds() * 1000, 2) if ini and fin else None


def a_spans(obs: list[dict]) -> list[dict]:
    por_traza = defaultdict(list)
    for o in obs:
        por_traza[o["traceId"]].append(o)
    spans = []
    for traza, lista in por_traza.items():
        lista.sort(key=lambda o: _fecha(o.get("startTime")) or datetime.min)
        version = next((str(o["metadata"]["prompt_version"]) for o in lista
                        if isinstance(o.get("metadata"), dict) and o["metadata"].get("prompt_version")),
                       None)
        if version is None:
            v = next((o.get("promptVersion") for o in lista if o.get("promptVersion")), None)
            version = f"v{v}" if v else None
        for o in lista:
            raiz = not o.get("parentObservationId")
            u = o.get("usageDetails") or {}
            razonamiento = u.get("output_reasoning_tokens") or 0
            span = {
                "traza": traza,
                "span": "corrida" if raiz else TIPOS.get(o["type"], o["type"].lower()),
                "nombre": o.get("name"),
                "duracion_ms": _ms(o),
                "error": (o.get("statusMessage") or "error") if o.get("level") == "ERROR" else None,
            }
            if o["type"] == "GENERATION":
                span.update(modelo=o.get("providedModelName") or o.get("model"),
                            tokens_entrada=u.get("input"),
                            tokens_salida=(u.get("output") or 0) + razonamiento,
                            tokens_razonamiento=razonamiento,
                            prompt=o.get("promptName"), prompt_version_ligada=o.get("promptVersion"))
            if raiz:
                span["prompt_version"] = version
            spans.append(span)
    return spans


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", help="la etiqueta que pusiste con propagate_attributes(tags=[...])")
    ap.add_argument("--sesion", help="el session_id de propagate_attributes")
    ap.add_argument("--desde", help="ISO 8601, p. ej. 2026-10-10T08:00:00+00:00")
    ap.add_argument("--hasta")
    ap.add_argument("-o", "--salida", default="spans.jsonl")
    a = ap.parse_args()
    if not (a.tag or a.sesion or a.desde):
        ap.error("filtra por --tag, --sesion o --desde: exportar el proyecto entero mezcla corridas")
    spans = a_spans(traer(tag=a.tag, sesion=a.sesion, desde=a.desde, hasta=a.hasta))
    Path(a.salida).write_text("".join(json.dumps(s, ensure_ascii=False) + "\n" for s in spans),
                              encoding="utf-8")
    trazas = {s["traza"] for s in spans}
    print(f"{len(spans)} spans de {len(trazas)} trazas → {a.salida}")
    if not spans:
        print("⚠ Nada exportado: ¿llamaste a flush()? Lo recién enviado tarda unos segundos.")


if __name__ == "__main__":
    main()
