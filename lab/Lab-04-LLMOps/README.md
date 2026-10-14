# Lab 04 — LLMOps: Evaluación, Observabilidad y Guardrails

> **Revisión del 2026-10-02.** El laboratorio trae ahora un evaluador con juez y calibración
> (`evaluar_llmops.py`), un golden set de veinte casos (`casos_plantilla.json`), un banco de
> ataques con su clasificador (`ataques_plantilla.json`, `probar_guardrails.py`), la estructura
> mínima de un span con su resumen (`resumir_trazas.py`) y un guion para la Parte 0 del Taller 4
> (`guion.py`). **`evaluation.py`, `guardrails.py` e `instrumented_agent.py` no cambiaron**: son
> el andamiaje cuyas fallas la Parte 0 reproduce y las Partes 1 a 3 corrigen. Ver
> `curso/talleres/taller-04-llmops.md`.
>
> **Revisión del 2026-10-06.** La Parte 1 del Taller 4 se instrumenta con **Langfuse**
> (`langfuse==4.17.0`, ya en `requirements.txt`). Entra `exportar_trazas.py`, que baja de
> Langfuse los spans de tus corridas al JSONL que lee `resumir_trazas.py`: lo que se entrega
> sigue siendo ese archivo.
>
> **Revisión del 2026-10-09.** El Taller 4 mide las **tres rutas** del Taller 3: el agente
> analista (A), el solver multiagente (B) y la opción libre de cinco agentes o más en LangGraph
> con un RAG (C). `evaluar_llmops.py` gana un **modo general** —sin base, con comprobaciones
> declaradas en cada caso— que da los mismos resultados que antes en el modo `sql`; entra
> `juez_solver.py`, el juez de la ruta B. RAGAS de la ruta C corre con
> `curso/actividades/semana-4/ragas-langfuse/evaluar_ragas.py csv`.

## Setup

```bash
pip install -r requirements.txt               # incluye las del Lab 03, con sus versiones
python ../Lab-03-Agentes/crear_base.py        # la base de ejemplo, si vas a usar la plantilla
cp .env.example .env                          # y elige las rutas del agente y del juez
```

## Qué hay

```
Lab-04-LLMOps/
├── evaluation.py             # el evaluador del andamiaje: lee un archivo que nada escribe
├── guardrails.py             # los dos validadores del andamiaje
├── instrumented_agent.py     # el envoltorio de observabilidad del andamiaje
├── golden_set_v2_plantilla.json, reports/evaluation_report_template.md   # del andamiaje
│
├── evaluar_llmops.py         # tu agente sobre un golden set → resultados.csv, con juez (modos sql y general)
├── juez_solver.py            # ruta B: el juez de los entregables del solver → juez_solver.csv
├── casos_plantilla.json      # 20 casos sobre la base del Lab 03: cinco tipos y casos con PII
├── probar_guardrails.py      # unos validadores contra un banco → guardrails.csv
├── ataques_plantilla.json    # 17 casos: ataques, PII y legítimas que parecen ataques
├── resumir_trazas.py         # un archivo de spans → tokens, costo, p50/p95, cuello de botella
├── exportar_trazas.py        # Langfuse → ese archivo de spans (Parte 1)
├── guion.py                  # la Parte 0: tres fallas del andamiaje, sin ningún modelo
└── requirements.txt
```

## Con qué modelo corre

Dos modelos, y **de familias distintas**: el agente que se evalúa y el juez que lo califica.

| Ruta | Agente | Juez | Costo |
|---|---|---|---|
| H200 de la USFQ (GlobalProtect) | `OPENAI_BASE_URL=http://172.28.230.10:12555/v1` (vLLM), `AGENT_MODEL=` el id de `/v1/models` | `JUEZ_BASE_URL=http://172.28.230.10:11434/v1` (Ollama), `JUEZ_MODEL=` uno de otra familia | cero |
| Clave del curso | fila `propietario_economico` | fila `openai_razonamiento`: el mismo proveedor, y se declara | el de las filas, con su fecha |
| Ollama en tu máquina | un modelo que admita herramientas | otro modelo | cero |

Los ids **no se escriben de memoria**: salen de la tabla semestral o del endpoint, y el
`.env.example` trae la orden que los lista. `--juez gemma3` basta: el evaluador lo resuelve
contra lo que el servidor sirve, y falla diciendo qué hay si no lo encuentra.

## Observabilidad con Langfuse

Obligatoria en la Parte 1. Tres pasos, y los tres están en la sesión 17 (bloque 4, «Paso a
paso») con código para copiar:

1. **Un servidor.** El autoalojado de la demo —`../../actividades/semana-4/demo-langfuse/levantar_langfuse.sh`,
   Docker, servidor 4.50.0, proyecto y claves creados sin pasar por la interfaz— o Langfuse
   Cloud, plan Hobby. Copia las tres variables `LANGFUSE_*` a tu `.env`.
2. **Instrumentar tu agente.** La raíz de `.run()` con `@observe` (o `as_type="agent"`), cada
   llamada al modelo como `generation` —el cliente `langfuse.openai` lo hace solo—, cada
   herramienta como `tool` y cada validación como `guardrail`; la sesión y las etiquetas con
   `propagate_attributes`; la máscara en `Langfuse(mask=...)`, recorriendo tuplas; y `flush()`
   al terminar.
3. **Exportar y resumir.**

```bash
python exportar_trazas.py --sesion grupo-07-base -o spans_base.jsonl
python resumir_trazas.py spans_base.jsonl --precio propietario_economico
```

El exportador consulta las *observations* (el servidor 4.x responde 404 a la lista de trazas en
su modo *events_only*), suma a los tokens de salida los de razonamiento —el proveedor los cobra
como salida— y toma el error del `statusMessage` de las observations en nivel `ERROR`. La
solución de referencia comprueba sobre cinco casos que el archivo exportado y un testigo local
dan los mismos tokens, errores y corridas.

## Lo que el andamiaje hace mal a propósito

No es un descuido que esté en el código que se reparte: es lo que la Parte 0 del taller te
pide reproducir (`python guion.py ceros | guardrails | traza`). Están catalogados en
`curso/planificacion/plan.md` (`0.bc`, `0.bf`, `0.az`, `0.ax`):

- `instrumented_agent.py` escribe `reports/traces.jsonl` y `evaluation.py` lee
  `reports/answers.json`, que nada escribe: el reporte sale en ceros sin una excepción;
- `abstention_score` vale 0 para «no aplica» y para «falló»;
- `guardrails.py` no normaliza tildes, exige frases literales, toma fechas y números por
  teléfonos, no redacta la salida y bloquea cualquier cadena de 32 caracteres;
- `instrumented_agent.py` guarda la pregunta original solo cuando la bloquea, mide después del
  guardrail y no escribe nada si el agente lanza.

## Evaluar

```bash
python evaluar_llmops.py --agente mi_agente:MiAgente --golden golden_set.json --juez gemma3
python evaluar_llmops.py --modo general --agente mi_grafo:Sistema --golden golden_set.json --juez gemma3   # ruta C
python juez_solver.py --corridas ../mi-solver/corridas --juez gemma3                                        # ruta B
python evaluar_llmops.py --calibrar resultados.csv --etiquetas etiquetas.csv   # sin volver a correr
python probar_guardrails.py --entrada mis_guardas:validar_entrada --salida mis_guardas:validar_salida
python resumir_trazas.py spans.jsonl --precio propietario_economico
```

`evaluar_llmops.py` importa el evaluador del Taller 3 (`../Lab-03-Agentes/evaluar.py`) para lo
determinístico —la verdad de cada respondible es su `sql_verificacion`— y le añade el juez, el
costo, la latencia p50/p95, `pii_filtrada` y las columnas de guardrail, versión de prompt y
`traza_id` si tu agente las devuelve. El contrato con el agente es el del Taller 3:
`.run(pregunta)` devuelve un `dict` con `answer`, `trace`, `status`, `model` y `usage`.

**El modo general (ruta C).** Sin `sql_verificacion` en los casos —o con `--modo general`— no se
abre ninguna base: una respondible acierta si cumple **todas** las comprobaciones que declara
(`numero` con `tolerancia`, `debe_contener`, `patron`, `herramientas_esperadas`), y una negativa o
adversarial, si se abstiene y no invocó ninguna de sus `herramientas_prohibidas`. Los nombres de
herramienta y de agente se leen de cada paso de la traza (`tool` o `herramienta`, y `agente`), y
si `.run()` devuelve `contextos`, van al CSV para RAGAS. Un caso sin comprobaciones no tiene
acierto determinístico: lo decide el juez, como una ambigua.

**El juez del solver (ruta B).** `juez_solver.py` importa `evaluar_solver.py` del Taller 3 v2
(`../Lab-03-Agentes/solver-v2/`), lee el entregable de cada tarea y juzga las comprobaciones que
se pueden decidir leyéndolo —`cifra`, `cifra_presente`, `contiene`, `secciones` y la nueva
`juez`, con su `criterio`— sin ver el veredicto del determinístico. Escribe `juez_solver.csv`,
que `--calibrar` lee igual. Probado el 2026-10-09 sobre las corridas de la solución del Taller 3
v2 con `gemma3:27b`: 14 comprobaciones en común, acuerdo 0,929 y kappa 0,0, porque el juez lo
aprobó todo, incluida una que el determinístico rechaza. Es la lección de calibración de la
sesión 16, con datos.

La solución de referencia, que corre todo esto sobre el agente de referencia del Taller 3, está
en `curso/actividades/semana-4/solución_taller_04_profesor.ipynb`.

## Recursos

Documentación consultada con fecha en `fuentes/web/fuentes-web.md`, bloques «Consultadas el
2026-10-02» —Langfuse, LangSmith, RAGAS, Microsoft Presidio y OWASP Top 10 para aplicaciones de
LLM— y «Consultadas el 2026-10-06»: el SDK de Langfuse 4.17.0, su integración con OpenAI, la
gestión de prompts, la máscara y el autoalojamiento.

Desde el 2026-10-07, «Consultadas el 2026-10-07»: `ragas` 0.4.3 contrastado con su código, los
experimentos de Langfuse, NVIDIA RAG Blueprint con NeMo Guardrails, y OpenCode. Si tu agente
recupera texto, la plantilla de RAGAS + Langfuse de la sesión 19 está en
`curso/actividades/semana-4/ragas-langfuse/` (con los prompts que recibe el juez); el agente SQL de
la plantilla no recupera texto y RAGAS no le aplica.
