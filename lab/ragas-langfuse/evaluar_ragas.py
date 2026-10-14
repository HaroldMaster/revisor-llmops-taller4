"""RAGAS + Langfuse sobre el golden set del Lab 02 — el ejemplo de la sesión 19.

Tres cosas se versionan en Langfuse, y cada corrida queda atada a las tres:

    el golden set   → un *dataset* (`golden-nimbus`), un ítem por caso, con su id del JSON
    el prompt       → `rag-nimbus`, v1 y v2, con etiquetas (`production`, `candidata`)
    la medición     → un *experimento* por configuración: su nombre lleva top_k y versión de
                      prompt, y sus metadatos el juez, su versión de RAGAS y el generador

    python evaluar_ragas.py subir                       # dataset + las dos versiones del prompt
    python evaluar_ragas.py correr --top-k 1 --prompt 1 # un experimento (≈ 1 min por caso)
    python evaluar_ragas.py correr --top-k 3 --prompt 2
    python evaluar_ragas.py verificar                   # juez a la vista == ragas.ascore, en 1 caso
    python evaluar_ragas.py prompts                     # los 5 prompts del juez → prompts_del_juez.md
    python evaluar_ragas.py csv resultados.csv --golden golden_set.json   # RAGAS del Taller 4

Las negativas del golden set (tipo «negativo») no se puntúan con RAGAS: su referencia es la frase
de abstención y no hay afirmación que buscar en el contexto. Se puntúan con la comprobación
determinística del Lab 02 (`abstencion`), y RAGAS mide solo las respondibles —el mismo criterio
que `Lab-02/evaluation.py` sigue para el Hit Rate—.

Necesita `.env` (ver `.env.example`): LANGFUSE_* (el servidor de `demo-langfuse/`),
OPENAI_BASE_URL + OPENAI_API_KEY (el generador, vLLM de la H200) y JUEZ_BASE_URL (el Ollama de
la H200: el juez y los embeddings). Probado el 2026-10-07 con ragas 0.4.3, langfuse 4.17.0
(servidor 4.50.0) y la H200 por VPN.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import sys
import unicodedata
from importlib.metadata import version
from pathlib import Path

from dotenv import load_dotenv

AQUI = Path(__file__).resolve().parent
load_dotenv(AQUI / ".env")

from langfuse import Evaluation, get_client                   # noqa: E402
from openai import AsyncOpenAI                                 # noqa: E402
from ragas.embeddings.base import embedding_factory            # noqa: E402
from ragas.llms import llm_factory                             # noqa: E402

from juez_ragas import JuezRAGAS                               # noqa: E402
from rag_nimbus import ABSTENCION, GOLDEN, RAGNimbus, modelo_embeddings  # noqa: E402

DATASET = "golden-nimbus"
PROMPT = "rag-nimbus"
PROMPTS = {
    1: ("Eres el asistente de RR. HH. de NimbusSoft. Responde la pregunta usando este "
        "contexto:\n{{contexto}}",
        "v1: el contexto, sin regla de abstención"),
    2: ("Eres el asistente de RR. HH. de NimbusSoft. Responde en una o dos frases, en español, "
        "usando SOLO este contexto. Si el contexto no contiene la respuesta, responde "
        f"exactamente «{ABSTENCION}»\nContexto:\n{{{{contexto}}}}",
        "v2: solo el contexto; frase de abstención del Lab 02"),
}
METRICAS = ["fidelidad", "relevancia_respuesta", "precision_contexto", "recall_contexto"]


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", (t or "").casefold())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join("".join(c if c.isalnum() or c.isspace() else " " for c in t).split())


def se_abstuvo(respuesta: str) -> bool:                 # la de Lab-02/rag_pipeline.py
    return _norm(ABSTENCION) in _norm(respuesta)


# ─────────────────────────────────────────────────────────────── 1 · subir (versionar)
def subir() -> None:
    lf = get_client()
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    try:
        lf.get_dataset(DATASET)
    except Exception:
        lf.create_dataset(name=DATASET, description="golden_ejemplo.json del Lab 02 (NimbusSoft)",
                          metadata={"fuente": "curso/labs/Lab-02-RAG-VectorSearch/golden_ejemplo.json"})
    for c in golden:
        # id fijo → volver a subir ACTUALIZA el ítem en vez de duplicarlo, y Langfuse guarda
        # la versión anterior: get_dataset(..., version=<fecha>) la recupera.
        lf.create_dataset_item(
            dataset_name=DATASET, id=f"nimbus-{c['id']}",
            input={"pregunta": c["pregunta"]},
            expected_output={"respuesta": c["respuesta_esperada"]},
            metadata={"tipo": c["tipo"], "documentos_fuente": c["documentos_fuente"]})
    existentes = {}
    try:
        for v in (1, 2):
            existentes[v] = lf.get_prompt(PROMPT, version=v, cache_ttl_seconds=0).prompt
    except Exception:
        pass
    for v, (texto, mensaje) in PROMPTS.items():
        if existentes.get(v) == texto:
            continue
        lf.create_prompt(name=PROMPT, type="text", prompt=texto, commit_message=mensaje,
                         labels=["production"] if v == 1 else ["candidata"])
    lf.flush()
    print(f"dataset «{DATASET}»: {len(golden)} ítems · prompt «{PROMPT}»: v1 production, v2 candidata")


# ─────────────────────────────────────────────────────────────── 2 · el juez
def juez(modelo: str) -> JuezRAGAS:
    cli = AsyncOpenAI(base_url=os.environ["JUEZ_BASE_URL"], api_key="ollama")
    return JuezRAGAS(llm_factory(modelo, client=cli),
                     embedding_factory("openai", model=modelo_embeddings(), client=cli))


# ─────────────────────────────────────────────────────────────── 3 · correr (medir)
def correr(top_k: int, version_prompt: int, modelo_juez: str) -> None:
    lf = get_client()
    rag = RAGNimbus(os.environ["JUEZ_BASE_URL"])
    prompt = lf.get_prompt(PROMPT, version=version_prompt, cache_ttl_seconds=0)
    j = juez(modelo_juez)

    def tarea(*, item, **_):                       # una llamada al RAG por ítem: es la traza
        return rag.responder(item.input["pregunta"], top_k=top_k, prompt=prompt)

    async def ragas(*, input, output, expected_output, metadata, **_):
        if metadata["tipo"] == "negativo":         # la verdad la da una regla, no un juez
            ok = se_abstuvo(output["respuesta"])
            return [Evaluation(name="abstencion", value=float(ok),
                               comment="se abstuvo" if ok else "respondió algo que no está")]
        r = await j.todas(input["pregunta"], output["respuesta"],
                          expected_output["respuesta"], output["contextos"])
        return [Evaluation(name=m, value=v, comment=c[:1000])
                for m, (v, c) in r.items() if not math.isnan(v)]

    def promedios(*, item_results, **_):           # una fila por métrica en la corrida
        salida = []
        for m in METRICAS + ["abstencion"]:
            vals = [e.value for r in item_results for e in r.evaluations if e.name == m]
            if vals:
                salida.append(Evaluation(name=f"media_{m}", value=sum(vals) / len(vals),
                                         comment=f"n = {len(vals)}"))
        return salida

    nombre = f"k{top_k}-prompt-v{version_prompt}"
    res = lf.get_dataset(DATASET).run_experiment(
        name=nombre, run_name=nombre,
        description=f"top_k={top_k}, prompt {PROMPT} v{version_prompt}, juez {modelo_juez}",
        task=tarea, evaluators=[ragas], run_evaluators=[promedios], max_concurrency=3,
        metadata={"top_k": str(top_k), "prompt_version": str(version_prompt),
                  "generador": rag.generador, "juez": modelo_juez,
                  "embeddings": modelo_embeddings(), "ragas": version("ragas")})
    lf.flush()
    _guardar(res, nombre, top_k, version_prompt, rag.generador, modelo_juez)


def _guardar(res, nombre, top_k, v, generador, modelo_juez) -> None:
    """El CSV es lo que lee el generador de diagramas: ninguna cifra del deck se teclea."""
    (AQUI / "resultados").mkdir(exist_ok=True)
    ruta = AQUI / "resultados" / f"{nombre}.csv"
    with ruta.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["corrida", "top_k", "prompt_version", "generador", "juez", "ragas", "id",
                    "tipo", "pregunta", "respuesta", "ids_recuperados", "metrica", "valor",
                    "comentario", "trace_id"])
        for r in res.item_results:
            it = r.item
            for e in r.evaluations:
                w.writerow([nombre, top_k, v, generador, modelo_juez, version("ragas"), it.id,
                            it.metadata["tipo"], it.input["pregunta"], r.output["respuesta"],
                            " ".join(r.output["ids"]), e.name, round(e.value, 4), e.comment,
                            r.trace_id])
    print(res.format())
    print(f"\n→ {ruta.relative_to(AQUI)}")
    if res.dataset_run_url:
        print(f"→ {res.dataset_run_url}")


# ─────────────────────────────────────────────────────────────── 4 · verificar
async def verificar(modelo_juez: str) -> None:
    """El juez a la vista calcula lo mismo que ragas.ascore. Un juez de LLM no es determinista
    ni con temperature=0, así que se comparan los dos números y se imprimen los dos."""
    j = juez(modelo_juez)
    q = "¿Cuántos días de vacaciones puedo transferir al año siguiente?"
    ctx = ["Política de vacaciones de NimbusSoft: Los días no utilizados pueden transferirse al "
           "año siguiente hasta un máximo de 5 días.",
           "Política de reembolso de gastos de NimbusSoft: El límite diario de alimentación en "
           "viajes es de 45 USD."]
    resp = "Puedes transferir hasta 5 días; la solicitud se hace al jefe antes de diciembre."
    ref = "Hasta un máximo de 5 días."
    a_mano = await j.todas(q, resp, ref, ctx)
    lib = {"fidelidad": await j.f.ascore(user_input=q, response=resp, retrieved_contexts=ctx),
           "relevancia_respuesta": await j.ar.ascore(user_input=q, response=resp),
           "precision_contexto": await j.cp.ascore(user_input=q, reference=ref, retrieved_contexts=ctx),
           "recall_contexto": await j.cr.ascore(user_input=q, reference=ref, retrieved_contexts=ctx)}
    for m in METRICAS:
        print(f"{m:22s} a la vista {a_mano[m][0]:.3f} · ascore {lib[m].value:.3f} · {a_mano[m][1][:140]}")
    # El caso y lo que el juez hizo con él: lo leen las láminas de la sesión 19.
    (AQUI / "resultados").mkdir(exist_ok=True)
    (AQUI / "resultados" / "verificar.json").write_text(json.dumps({
        "juez": modelo_juez, "ragas": version("ragas"), "pregunta": q, "respuesta": resp,
        "referencia": ref, "contextos": ctx,
        "metricas": {m: {"a_la_vista": a_mano[m][0], "ascore": lib[m].value,
                         "detalle": a_mano[m][1]} for m in METRICAS}},
        ensure_ascii=False, indent=2), encoding="utf-8")


# ─────────────────────────────────────────────────────────────── 5 · prompts
def prompts() -> None:
    """Escribe `prompts_del_juez.md`: los cinco prompts que el juez recibe, tal cual, armados
    sobre el caso de `verificar`. No llama a ningún modelo: `to_string()` es lo que `ragas`
    0.4.3 envía, con su esquema JSON de salida y sus ejemplos (few-shot) dentro."""
    from ragas.metrics.collections.answer_relevancy.util import AnswerRelevanceInput
    from ragas.metrics.collections.context_precision.util import ContextPrecisionInput
    from ragas.metrics.collections.context_recall.util import ContextRecallInput
    from ragas.metrics.collections.faithfulness.util import (NLIStatementInput,
                                                             StatementGeneratorInput)
    caso = json.loads((AQUI / "resultados" / "verificar.json").read_text(encoding="utf-8"))
    q, resp, ref, ctx = caso["pregunta"], caso["respuesta"], caso["referencia"], caso["contextos"]
    afirmaciones = [s.split("] ", 1)[1] for s in
                    caso["metricas"]["fidelidad"]["detalle"].split(" · ", 1)[1].split("; ")]
    # Un juez sin servidor: los prompts se arman sin llamarlo, pero las métricas exigen un
    # InstructorLLM al construirse.
    cli = AsyncOpenAI(base_url=os.getenv("JUEZ_BASE_URL", "http://localhost:11434/v1"), api_key="ollama")
    j = JuezRAGAS(llm_factory(os.getenv("JUEZ", "gemma3:27b"), client=cli),
                  embedding_factory("openai", model=modelo_embeddings(), client=cli))
    piezas = [
        ("Fidelidad, paso 1 — extraer afirmaciones de la respuesta",
         j.f.statement_generator_prompt, StatementGeneratorInput(question=q, answer=resp)),
        ("Fidelidad, paso 2 — verificar cada afirmación contra el contexto",
         j.f.nli_statement_prompt, NLIStatementInput(context="\n".join(ctx), statements=afirmaciones)),
        ("Relevancia de la respuesta — una pregunta desde la respuesta (se repite n = 3 veces)",
         j.ar.prompt, AnswerRelevanceInput(response=resp)),
        ("Precisión del contexto — un juicio por fragmento (aquí, el primero)",
         j.cp.prompt, ContextPrecisionInput(question=q, context=ctx[0], answer=ref)),
        ("Recall del contexto — las afirmaciones de la referencia contra el contexto",
         j.cr.prompt, ContextRecallInput(question=q, context="\n".join(ctx), answer=ref)),
    ]
    salida = [f"# Los prompts del juez de RAGAS — `ragas` {version('ragas')}\n",
              "Generado por `python evaluar_ragas.py prompts` a partir de la librería instalada: es "
              "**exactamente** el texto que recibe el juez, con la instrucción, el esquema JSON de "
              "salida, los ejemplos *few-shot* de la librería y el caso de `resultados/verificar.json` "
              "como entrada. Las afirmaciones del paso 2 son las que el juez extrajo en el paso 1 "
              "de esa corrida. Licencia de `ragas`: Apache-2.0.\n"]
    for titulo, prompt, entrada in piezas:
        salida += [f"\n## {titulo}\n", f"Clase: `{type(prompt).__name__}` · salida: "
                   f"`{prompt.output_model.__name__}`\n", "```text", prompt.to_string(entrada), "```"]
    (AQUI / "prompts_del_juez.md").write_text("\n".join(salida) + "\n", encoding="utf-8")
    print(f"→ prompts_del_juez.md ({len(piezas)} prompts)")


# ─────────────────────────────────────────────────────────────── 6 · csv (Taller 4)
async def desde_csv(resultados: Path, golden: Path, salida: Path, modelo_juez: str) -> None:
    """RAGAS sobre el `resultados.csv` que escribe `evaluar_llmops.py --modo general` (Taller 4,
    rutas B y C). Lee la pregunta, la respuesta y los `contextos` de cada fila; la referencia,
    del `respuesta_esperada` del caso en el golden set. Fidelidad y relevancia corren en toda
    respondible con contextos; precisión y recall del contexto, solo donde hay referencia."""
    casos = {c["id"]: c for c in json.loads(golden.read_text(encoding="utf-8"))["preguntas"]}
    with open(resultados, encoding="utf-8") as f:
        filas = [r for r in csv.DictReader(f)
                 if r.get("contextos") and r["tipo"] in {"simple", "multi"} and r.get("respuesta")]
    if not filas:
        sys.exit(f"{resultados} no tiene filas respondibles con `contextos`: ¿tu .run() los devuelve?")
    j = juez(modelo_juez)
    salida_filas = []
    for r in filas:
        ctx = json.loads(r["contextos"])
        ref = casos.get(r["id"], {}).get("respuesta_esperada", "")
        res = {"fidelidad": await j.fidelidad(r["pregunta"], r["respuesta"], ctx),
               "relevancia_respuesta": await j.relevancia_respuesta(r["pregunta"], r["respuesta"])}
        if ref:
            res["precision_contexto"] = await j.precision_contexto(r["pregunta"], ref, ctx)
            res["recall_contexto"] = await j.recall_contexto(r["pregunta"], ref, ctx)
        for m, (v, c) in res.items():
            salida_filas.append({"id": r["id"], "tipo": r["tipo"], "metrica": m,
                                 "valor": "" if math.isnan(v) else round(v, 4), "comentario": c[:500],
                                 "juez": modelo_juez, "ragas": version("ragas")})
        print(f"  {r['id']:5s} " + " · ".join(f"{m} {v:.2f}" for m, (v, _) in res.items() if not math.isnan(v)))
    with salida.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(salida_filas[0]))
        w.writeheader()
        w.writerows(salida_filas)
    medias = {}
    for s in salida_filas:
        if s["valor"] != "":
            medias.setdefault(s["metrica"], []).append(s["valor"])
    print(json.dumps({m: round(sum(v) / len(v), 3) for m, v in medias.items()} | {"n_filas": len(filas)},
                     ensure_ascii=False))
    print(f"→ {salida}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("subir")
    sub.add_parser("prompts")
    cs = sub.add_parser("csv", help="RAGAS sobre el resultados.csv de evaluar_llmops.py (Taller 4)")
    cs.add_argument("resultados")
    cs.add_argument("--golden", required=True, help="el golden_set.json del Taller 4")
    cs.add_argument("--salida", default="ragas_resultados.csv")
    c = sub.add_parser("correr")
    c.add_argument("--top-k", type=int, default=3)
    c.add_argument("--prompt", type=int, default=2, choices=sorted(PROMPTS))
    for s in (c, sub.add_parser("verificar"), cs):
        s.add_argument("--juez", default=os.getenv("JUEZ", "gemma3:27b"),
                       help="modelo del Ollama de la H200; de otra familia que el generador")
    a = p.parse_args()
    if a.cmd == "prompts":                   # no necesita red: solo arma los textos
        return prompts()
    if a.cmd == "csv":                       # solo el juez: no hace falta Langfuse ni el vLLM
        if not os.getenv("JUEZ_BASE_URL"):
            sys.exit(f"Falta JUEZ_BASE_URL en {AQUI / '.env'} (plantilla: .env.example)")
        return asyncio.run(desde_csv(Path(a.resultados), Path(a.golden), Path(a.salida), a.juez))
    for v in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL",
              "OPENAI_BASE_URL", "OPENAI_API_KEY", "JUEZ_BASE_URL"):
        if not os.getenv(v):
            sys.exit(f"Falta {v} en {AQUI / '.env'} (plantilla: .env.example)")
    if a.cmd == "subir":
        subir()
    elif a.cmd == "correr":
        correr(a.top_k, a.prompt, a.juez)
    else:
        asyncio.run(verificar(a.juez))


if __name__ == "__main__":
    main()
