"""El RAG que se evalúa — el más pequeño posible sobre el corpus del Lab 02.

Tres políticas de NimbusSoft (`curso/labs/Lab-02-RAG-VectorSearch/ejemplos/*.md`), partidas en
oraciones: cada oración es un fragmento con su documento delante. Recuperación densa con
`bge-m3` en el Ollama de la H200 y coseno en NumPy; generación con el modelo del vLLM de la H200.
Es pequeño a propósito: aquí no se mira el RAG, se mira cómo se mide. El sistema del Taller 2
(Qdrant, fragmentación en tokens, tres rutas de generación) es el que se evalúa en serio.

Dos perillas, y son las que el experimento compara:
    top_k    cuántos fragmentos entran al contexto
    prompt   la versión del prompt, que vive en Langfuse (no en este archivo)

Ningún nombre de modelo se escribe aquí: el de embeddings sale de la fila
`embed_local_multilingue` de `fuentes/modelos/modelos-2026-1.json` y el generador se le pregunta
al servidor, como en `demo-langfuse/demo.py`.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import numpy as np
from langfuse import observe
from langfuse.openai import OpenAI          # el cliente de OpenAI, con trazas
import openai

AQUI = Path(__file__).resolve().parent
REPO = AQUI.parents[3]
CORPUS = REPO / "curso" / "labs" / "Lab-02-RAG-VectorSearch" / "ejemplos"
GOLDEN = REPO / "curso" / "labs" / "Lab-02-RAG-VectorSearch" / "golden_ejemplo.json"
TABLA = REPO / "fuentes" / "modelos" / "modelos-2026-1.json"

# La misma frase del Lab 02 (rag_pipeline.ABSTENCION): el golden set la usa como respuesta
# esperada de las negativas.
ABSTENCION = "El corpus no contiene información suficiente."


def modelo_embeddings() -> str:
    """`BAAI/bge-m3` en la tabla → `bge-m3` en Ollama. EMBEDDING_MODEL lo sobreescribe."""
    if os.getenv("EMBEDDING_MODEL"):
        return os.environ["EMBEDDING_MODEL"]
    fila = next(f for f in json.loads(TABLA.read_text(encoding="utf-8"))["embeddings"]
                if f["id"] == "embed_local_multilingue")
    return fila["model"].split("/")[-1].lower()


def fragmentos() -> list[dict]:
    """Una oración por fragmento. El PDF escaneado del Lab 02 no entra: no tiene texto."""
    salida = []
    for md in sorted(CORPUS.glob("*.md")):
        lineas = md.read_text(encoding="utf-8").splitlines()
        titulo = lineas[0].lstrip("# ").strip()
        cuerpo = " ".join(l.strip() for l in lineas[1:] if l.strip())
        for i, oracion in enumerate(re.split(r"(?<=\.)\s+(?=[A-ZÁÉÍÓÚ])", cuerpo)):
            salida.append({"id": f"{md.stem}#{i}", "doc": md.name,
                           "texto": f"{titulo}: {oracion}"})
    return salida


class RAGNimbus:
    def __init__(self, juez_base_url: str):
        # Los embeddings van al Ollama de la H200 por su API compatible con OpenAI.
        self.emb = openai.OpenAI(base_url=juez_base_url, api_key="ollama")
        self.modelo_emb = modelo_embeddings()
        self.llm = OpenAI(timeout=180, max_retries=1)          # OPENAI_BASE_URL = el vLLM
        self.generador = os.getenv("MODELO") or self.llm.models.list().data[0].id
        self.frags = fragmentos()
        self.matriz = self._vectorizar([f["texto"] for f in self.frags])

    def _vectorizar(self, textos: list[str]) -> np.ndarray:
        datos = self.emb.embeddings.create(model=self.modelo_emb, input=textos).data
        m = np.array([d.embedding for d in datos])
        return m / np.linalg.norm(m, axis=1, keepdims=True)

    @observe(name="recuperar", as_type="retriever")
    def recuperar(self, pregunta: str, top_k: int) -> list[dict]:
        sim = self.matriz @ self._vectorizar([pregunta])[0]
        orden = np.argsort(-sim)[:top_k]
        return [{**self.frags[i], "coseno": round(float(sim[i]), 4)} for i in orden]

    @observe(name="rag_nimbus")          # la raíz: su llamada ES la traza
    def responder(self, pregunta: str, *, top_k: int, prompt) -> dict:
        recuperados = self.recuperar(pregunta, top_k)
        contexto = "\n".join(f"- {r['texto']}" for r in recuperados)
        r = self.llm.chat.completions.create(
            model=self.generador,
            messages=[{"role": "system", "content": prompt.compile(contexto=contexto)},
                      {"role": "user", "content": pregunta}],
            temperature=0, max_tokens=4096,
            langfuse_prompt=prompt,      # la generación queda enlazada a su versión de prompt
        )
        return {"respuesta": (r.choices[0].message.content or "").strip(),
                "contextos": [x["texto"] for x in recuperados],
                "ids": [x["id"] for x in recuperados]}
