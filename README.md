# Revisor de código multiagente: evaluado, observado y protegido

Sistema en LangGraph que recibe un diff de un repositorio y devuelve un informe de review con hallazgos verificados:
cinco reviewers en paralelo, un verificador y un sintetizador, con RAG sobre las reglas del repositorio. Hecho en el
Taller 03 de MMIA 6013 IA Generativa y Agentes (USFQ, opción libre) y llevado a operación en el **Taller 04**: spans en
Langfuse, golden set de 24 casos con verificador, juez calibrado y RAGAS, guardrails medidos como clasificadores, una
mejora medida antes y después, y tres alertas.

## Carpetas

- `repo-prueba/`: el repositorio que se revisa. Mini tienda en TypeScript con sus reglas (`CLAUDE.md`) y su perfil (`perfil.toml`).
- `revisor/`: el sistema. `sistema.py` es la puerta del Taller 4 (`Sistema().run(pregunta)`), `guardrails.py` los tres
  guardrails, `observabilidad.py` los spans de Langfuse y `agentes/prompts.py` los prompts con su `VERSION` y `CHANGELOG`.
- `evaluacion/`: golden set (`construir_golden_t4.py` → `golden_set.json`), banco de ataques (`ataques.json`),
  análisis (`analizar_t4.py`), RAGAS caso por caso, alertas y registro de prompts en Langfuse.
- `lab/`: los laboratorios del enunciado (Lab-03, Lab-04 y ragas-langfuse), **idénticos al zip**. Sus herramientas (`evaluar_llmops.py`, `probar_guardrails.py`,
  `exportar_trazas.py`, `resumir_trazas.py`, `evaluar_ragas.py`) se usan sin modificar.
- `parte0/`: las tres salidas de `guion.py` y sus respuestas.
- `resultados/`: los archivos crudos de cada medición (ver abajo).
- `entregable/`: los archivos crudos que pide el enunciado, con los nombres del enunciado.
- `tests/`: pruebas del sistema; no llaman a ningún modelo.

## Preparación

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
(cd repo-prueba && npm ci)
cp .env.example .env          # y completar: H200, juez y claves de Langfuse
.venv/bin/python -m revisor.rag.ingesta
# Langfuse propio: langfuse/levantar_langfuse.sh del zip del taller (Docker), y sus claves en .env
# Parte 0 y RAGAS van en sus propios entornos (.venv-lab y .venv-ragas): ver parte0/respuestas.md y lab/ragas-langfuse/README.md
```

Con la H200 de la USFQ hace falta la VPN GlobalProtect. El id del modelo no se escribe: se lee de `/v1/models`.

## Taller 4: cómo se midió

```bash
# 1. Golden set y prompts en Langfuse
.venv/bin/python -m evaluacion.construir_golden_t4
.venv/bin/python -m evaluacion.registrar_prompts

# 2. Una medición (base: LANGFUSE_SESION=harold-flores-base; mejora: harold-flores-mejora-v21)
date -u +%Y-%m-%dT%H:%M:%S+00:00 > resultados/.inicio_base
PYTHONPATH=. LANGFUSE_SESION=harold-flores-base .venv/bin/python lab/Lab-04-LLMOps/evaluar_llmops.py \
  --modo general --agente revisor.sistema:Sistema --golden golden_set.json --juez gemma3 --salida resultados/resultados_base.csv
.venv/bin/python lab/Lab-04-LLMOps/exportar_trazas.py --sesion harold-flores-base --desde "$(cat resultados/.inicio_base)" -o resultados/spans_base.jsonl
(cd lab/Lab-04-LLMOps && ../../.venv/bin/python resumir_trazas.py ../../resultados/spans_base.jsonl --precio propietario_economico)
.venv/bin/python -m evaluacion.analizar_t4 agentes resultados/spans_base.jsonl
.venv/bin/python -m evaluacion.analizar_t4 filtraciones resultados/spans_base.jsonl resultados/resultados_base.csv

# 3. Calibración: juez contra verificador y contra la persona
.venv/bin/python -m evaluacion.analizar_t4 verificador resultados/resultados_base.csv
.venv/bin/python lab/Lab-04-LLMOps/evaluar_llmops.py --calibrar resultados/resultados_base.csv --etiquetas resultados/etiquetas.csv
.venv/bin/python -m evaluacion.analizar_t4 recalificar resultados/resultados_base.csv -o resultados/resultados_base_v3.csv
.venv/bin/python -m evaluacion.analizar_t4 tres resultados/resultados_base_v3.csv resultados/etiquetas.csv

# 4. RAGAS (respondibles con RAG), caso por caso
.venv/bin/python -m evaluacion.ragas_por_caso resultados/resultados_base.csv -o resultados/ragas_base.csv

# 5. Antes y después, y alertas
.venv/bin/python -m evaluacion.analizar_t4 comparar resultados/resultados_base_v3.csv resultados/resultados_mejora_v21.csv
.venv/bin/python -m evaluacion.alertas --base resultados/spans_base.jsonl resultados/resultados_base.csv \
  --revisar resultados/spans_mejora_v21.jsonl resultados/resultados_mejora_v21.csv -o resultados/alertas.json

# 6. Guardrails como clasificadores (los míos y los del laboratorio, sobre el mismo banco)
(cd lab/Lab-04-LLMOps && PYTHONPATH=../.. ../../.venv/bin/python probar_guardrails.py \
  --entrada revisor.guardrails:validar_entrada --salida revisor.guardrails:validar_salida \
  --casos ../../evaluacion/ataques.json --csv ../../resultados/guardrails.csv)
```

### Archivos de `resultados/` del Taller 4

| Archivo | Qué es |
|---|---|
| `resultados_base.csv` · `resultados_base_v3.csv` | la medición base (prompts v1), calificada con el golden set v1 y con el vigente (v3) |
| `resultados_mejora.csv` · `resultados_mejora_v21.csv` | la mejora: v2 (prompt) y v2.1 (respuesta corta y evidencia borrada) |
| `spans_*.jsonl` · `resumen_spans_*.json` · `agentes_*.json` | los spans exportados de Langfuse, su tabla y el reparto por agente y fase |
| `filtraciones_*.json` | datos personales y claves encontrados en spans y CSV: cero |
| `etiquetas.csv` | las 24 etiquetas de la persona, escritas antes de ver el juez |
| `calibracion_*.json` · `desacuerdos_base.md` | las calibraciones del juez y la revisión de cada desacuerdo |
| `ragas_base.csv` · `ragas_mejora_v21.csv` | RAGAS por caso y métrica |
| `antes_despues.json` · `antes_despues_v21.json` | la comparación caso por caso, objetivo contra azar |
| `guardrails.csv` · `guardrails_ejemplo.csv` | el banco de ataques con mis guardrails y con los del laboratorio |
| `alertas.json` | umbrales de las tres alertas y su aplicación a cada corrida |
| `trazas_peores/` | la traza local de los tres peores casos de la base |

El resto de `resultados/` (`resultados_baseline*`, `resultados_multiagente*`, `trazas/`, `frenos/`…) es del Taller 3.

## Taller 3

Lo que sigue es del Taller 3: el revisor por ruta de parche, sus sistemas y ablaciones.

### Uso

```bash
.venv/bin/python -m revisor evaluacion/parte0/a_impuesto.patch --sistema multiagente
```

Recibe la ruta de un parche, lo aplica sobre una copia temporal de `repo-prueba/` y devuelve el informe. La traza de la corrida queda en `corridas/`.

Desde código, el contrato es `RevisorUnico().run(ruta_del_parche)`, que devuelve `answer`, `trace`, `status`, `model` y `usage`.

### Parte 0

```bash
.venv/bin/python -m evaluacion.parte0.a_revisor_sin_herramientas
.venv/bin/python -m evaluacion.parte0.b_rag_plano
.venv/bin/python -m evaluacion.parte0.c_tests_en_verde
```

La salida cruda de cada uno está en `evaluacion/parte0/salidas/`.

### Golden set y medición

```bash
.venv/bin/python -m evaluacion.construir_casos        # regenera los parches y golden_set.json
.venv/bin/python -m evaluacion.evaluar --verificar    # demuestra en código la verdad de cada caso
.venv/bin/python -m evaluacion.evaluar --sistema baseline
.venv/bin/python -m evaluacion.evaluar --sistema multiagente
```

Sistemas disponibles (`revisor/sistemas.py`):

| nombre | qué es |
|---|---|
| `baseline` | un solo agente con un prompt general |
| `baseline_con_pistas` | control: el agente único con las instrucciones de los cinco reviewers |
| `multiagente` | cinco reviewers, verificador y sintetizador |
| `sin_verificador`, `sin_rag` | ablaciones del multiagente |
| `baseline_razonamiento_alto`, `multiagente_razonamiento_alto` | extensión: `reasoning_effort` alto |

El modelo no es determinista. Para medir otra vez sin pisar lo anterior: `--repeticion 2`. Para los dos PR grandes y el caso complejo, que van aparte del examen de 14 casos: `--conjunto grande` (se generan con `python -m evaluacion.construir_casos --grandes`).

Los resultados crudos quedan en `resultados/`: una fila por caso en `resultados_<sistema>.csv`, una fila por sistema en `resumen.csv` y la traza de cada corrida en `trazas/`.

### Frenos

```bash
.venv/bin/python -m evaluacion.forzar_frenos
```

Fuerza los cuatro frenos con un modelo de guion, sin gastar: tope de pasos, presupuesto de tokens, detector de repetición y tiempo máximo de un check. La salida y una traza por freno quedan en `resultados/frenos/`. Los límites se ajustan en `.env` (`REVISOR_MAX_PASOS`, `REVISOR_LIMITE_TOKENS`, `REVISOR_RESERVA_TOKENS`).

## Pruebas

```bash
.venv/bin/python -m pytest -q
```

## Cambiar de proveedor o de repositorio

- **Proveedor:** editar `.env`. Para dar a un solo rol otro modelo, copiar `modelos.toml.example` a `modelos.toml`.
- **Repositorio revisado:** escribir un `perfil.toml` en ese repo con sus comandos de lint, tests y tipos.
