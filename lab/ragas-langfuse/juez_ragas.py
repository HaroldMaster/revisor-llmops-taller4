"""Las cuatro métricas de RAGAS, con el trabajo del juez a la vista.

`ragas` 0.4.3 calcula cada métrica con `metric.ascore(...)` y devuelve solo el número. Aquí se
usan **los mismos prompts y el mismo juez** de la librería (`m.statement_generator_prompt`,
`m.nli_statement_prompt`, `m.prompt`, `m.llm`) y la fórmula se escribe a mano, para que el
comentario de cada score en Langfuse diga qué afirmaciones extrajo el juez y qué decidió de cada
una. `python evaluar_ragas.py verificar` comprueba sobre un caso que el número es el mismo que
el de `ascore`. Las fórmulas son las de `ragas/metrics/collections/*/metric.py` en esa versión:
si se actualiza la librería, se vuelve a verificar.

    métrica             pide                                        el juez hace
    fidelidad           pregunta, respuesta, contextos             afirmaciones de la RESPUESTA → ¿se infiere del contexto?
    relevancia_resp     pregunta, respuesta (+ embeddings)          n preguntas desde la respuesta → coseno con la original
    precision_contexto  pregunta, referencia, contextos             ¿cada fragmento, en su rango, sirve para la referencia?
    recall_contexto     pregunta, referencia, contextos             afirmaciones de la REFERENCIA → ¿se atribuyen al contexto?
"""

from __future__ import annotations

import math

import numpy as np
from ragas.metrics.collections import (AnswerRelevancy, ContextPrecision, ContextRecall,
                                       Faithfulness)
from ragas.metrics.collections.answer_relevancy.util import (AnswerRelevanceInput,
                                                             AnswerRelevanceOutput)
from ragas.metrics.collections.context_precision.util import (ContextPrecisionInput,
                                                              ContextPrecisionOutput)
from ragas.metrics.collections.context_recall.util import ContextRecallInput, ContextRecallOutput


class JuezRAGAS:
    def __init__(self, llm, embeddings, n_preguntas: int = 3):
        self.f = Faithfulness(llm=llm)
        self.ar = AnswerRelevancy(llm=llm, embeddings=embeddings, strictness=n_preguntas)
        self.cp = ContextPrecision(llm=llm)
        self.cr = ContextRecall(llm=llm)
        self.llm, self.emb, self.n = llm, embeddings, n_preguntas

    # ── 1 · Fidelidad: F = |V| / |S| ─────────────────────────────────────────────────────
    async def fidelidad(self, pregunta, respuesta, contextos):
        S = await self.f._create_statements(pregunta, respuesta)          # paso 1: afirmaciones
        if not S:
            return math.nan, "el juez no extrajo ninguna afirmación"
        v = await self.f._create_verdicts(S, "\n".join(contextos))        # paso 2: veredictos
        V = sum(1 for s in v.statements if s.verdict)
        detalle = "; ".join(f"[{'sí' if s.verdict else 'no'}] {s.statement}" for s in v.statements)
        return V / len(v.statements), f"{V}/{len(v.statements)} · {detalle}"

    # ── 2 · Relevancia de la respuesta: AR = (1/n) Σ cos(E(q), E(q_i)) ────────────────────
    async def relevancia_respuesta(self, pregunta, respuesta):
        qs, evasivas = [], []
        for _ in range(self.n):
            prompt = self.ar.prompt.to_string(AnswerRelevanceInput(response=respuesta))
            r = await self.llm.agenerate(prompt, AnswerRelevanceOutput)
            if r.question:
                qs.append(r.question)
                evasivas.append(r.noncommittal)
        if not qs:
            return 0.0, "el juez no generó preguntas"
        q = np.asarray(await self.emb.aembed_text(pregunta))
        Q = np.asarray(await self.emb.aembed_texts(qs))
        cos = Q @ q / (np.linalg.norm(Q, axis=1) * np.linalg.norm(q))
        evasiva = all(evasivas)                    # «no lo sé» en las n → la métrica vale 0
        valor = float(cos.mean()) * (not evasiva)
        detalle = "; ".join(f"{c:.2f} «{x}»" for c, x in zip(cos, qs))
        return valor, f"{'EVASIVA → 0 · ' if evasiva else ''}{detalle}"

    # ── 3 · Precisión del contexto: Σ_k (Precision@k · v_k) / Σ_k v_k ────────────────────
    async def precision_contexto(self, pregunta, referencia, contextos):
        v = []
        for c in contextos:                        # un juicio por fragmento, en su rango
            prompt = self.cp.prompt.to_string(
                ContextPrecisionInput(question=pregunta, context=c, answer=referencia))
            v.append(int((await self.llm.agenerate(prompt, ContextPrecisionOutput)).verdict))
        num = sum(sum(v[:k + 1]) / (k + 1) * v[k] for k in range(len(v)))
        valor = num / (sum(v) + 1e-10)
        return valor, f"v = {v}"

    # ── 4 · Recall del contexto: afirmaciones de la referencia atribuidas / total ────────
    async def recall_contexto(self, pregunta, referencia, contextos):
        prompt = self.cr.prompt.to_string(
            ContextRecallInput(question=pregunta, context="\n".join(contextos), answer=referencia))
        r = await self.llm.agenerate(prompt, ContextRecallOutput)
        if not r.classifications:
            return math.nan, "el juez no extrajo afirmaciones de la referencia"
        a = [c.attributed for c in r.classifications]
        detalle = "; ".join(f"[{'sí' if c.attributed else 'no'}] {c.statement}"
                            for c in r.classifications)
        return sum(a) / len(a), f"{sum(a)}/{len(a)} · {detalle}"

    async def todas(self, pregunta, respuesta, referencia, contextos) -> dict:
        return {
            "fidelidad": await self.fidelidad(pregunta, respuesta, contextos),
            "relevancia_respuesta": await self.relevancia_respuesta(pregunta, respuesta),
            "precision_contexto": await self.precision_contexto(pregunta, referencia, contextos),
            "recall_contexto": await self.recall_contexto(pregunta, referencia, contextos),
        }
