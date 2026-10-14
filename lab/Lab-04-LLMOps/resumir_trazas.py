"""
Lab 04 — Resume un archivo de spans: tokens, costo, latencia por corrida y dónde se va el tiempo.

    python resumir_trazas.py trazas.jsonl
    python resumir_trazas.py trazas.jsonl --precio propietario_economico   # ¿y si fuera de pago?

El Taller 4 acepta trazas locales «si documentas su estructura». Esta es una estructura
mínima que basta para las preguntas de la Parte 1 —una línea JSON por **span**—, y este
script es la prueba de que basta: si tus trazas no se pueden resumir así, les falta algo.

    {"traza": "id de la corrida",           # todos los spans de una corrida lo comparten
     "span": "corrida | llm | herramienta | guardrail",
     "nombre": "consultar_sql",             # la herramienta, el validador, o el modelo
     "duracion_ms": 912.4,                  # medida en un `finally`: también si falló
     "modelo": "…", "tokens_entrada": 1500, "tokens_salida": 93,   # solo en los `llm`
     "error": null,                         # el texto de la excepción, si la hubo
     "prompt_version": "v1"}                # en el span `corrida`

Lo que sale: por corrida, la duración del span `corrida` (p50 y p95), los tokens y el costo;
por nombre de span, cuántas veces aparece, el tiempo total y su parte del total —el cuello de
botella es el de la mayor parte, no el de la mayor media—; y los errores.

**El costo lleva la fila y su fecha, o dice que es local.** Con la H200 o con Ollama el costo
por llamada es cero; `--precio <fila>` responde a otra pregunta, la de cuánto costaría el
mismo tráfico con un modelo de pago, y la respuesta vale lo que vale la fecha de esa fila.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from evaluar_llmops import _percentil, precio


def leer(ruta: Path) -> list[dict]:
    spans = []
    for n, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
        if linea.strip():
            try:
                spans.append(json.loads(linea))
            except json.JSONDecodeError as e:
                raise SystemExit(f"{ruta}:{n} no es JSON: {e}")
    return spans


def resumir(spans: list[dict], fila_precio: str = "local") -> dict:
    p_ent, p_sal, origen = precio(fila_precio)
    corridas = defaultdict(lambda: {"ms": None, "ent": 0, "sal": 0, "errores": 0})
    por_nombre = defaultdict(lambda: {"n": 0, "ms": 0.0, "errores": 0})
    for s in spans:
        c = corridas[s.get("traza")]
        if s.get("span") == "corrida":
            c["ms"] = s.get("duracion_ms")
            continue
        c["ent"] += s.get("tokens_entrada") or 0
        c["sal"] += s.get("tokens_salida") or 0
        c["errores"] += bool(s.get("error"))
        clave = f"{s.get('span')}:{s.get('nombre')}"
        por_nombre[clave]["n"] += 1
        por_nombre[clave]["ms"] += s.get("duracion_ms") or 0.0
        por_nombre[clave]["errores"] += bool(s.get("error"))
    sin_corrida = [t for t, c in corridas.items() if c["ms"] is None]
    duraciones = [c["ms"] for c in corridas.values() if c["ms"] is not None]
    total_ms = sum(v["ms"] for v in por_nombre.values()) or 1.0
    ent = sum(c["ent"] for c in corridas.values())
    sal = sum(c["sal"] for c in corridas.values())
    return {
        "corridas": len(corridas),
        "corridas_sin_span_corrida": sin_corrida,
        "latencia_p50_ms": _percentil(duraciones, 0.50),
        "latencia_p95_ms": _percentil(duraciones, 0.95),
        "tokens_entrada": ent, "tokens_salida": sal,
        "costo_usd": round((ent * p_ent + sal * p_sal) / 1e6, 6), "precio": origen,
        "errores": sum(c["errores"] for c in corridas.values()),
        "por_span": {k: {"n": v["n"], "ms_total": round(v["ms"], 1),
                         "ms_medio": round(v["ms"] / v["n"], 1),
                         "parte_del_total": round(v["ms"] / total_ms, 3), "errores": v["errores"]}
                     for k, v in sorted(por_nombre.items(), key=lambda kv: -kv[1]["ms"])},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trazas")
    ap.add_argument("--precio", default="local")
    a = ap.parse_args()
    r = resumir(leer(Path(a.trazas)), a.precio)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    if r["corridas_sin_span_corrida"]:
        print(f"⚠ {len(r['corridas_sin_span_corrida'])} corridas sin span `corrida`: "
              "¿se escribe la traza también cuando la corrida falla?")


if __name__ == "__main__":
    main()
