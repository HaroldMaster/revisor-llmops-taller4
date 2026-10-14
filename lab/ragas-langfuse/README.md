# RAGAS + Langfuse sobre el golden set — el ejemplo de la sesión 19

El proceso entero en tres archivos: un RAG mínimo, un juez que calcula las cuatro métricas de
RAGAS **con su trabajo a la vista**, y un experimento de Langfuse que versiona el golden set, el
prompt y la medición. Es lo que la sesión 19 proyecta en sus dos láminas de código y lo que se
corre en la demo.

| Archivo | Qué hace |
|---|---|
| `rag_nimbus.py` | El RAG que se evalúa: el corpus del Lab 02 en oraciones, `bge-m3` en el Ollama de la H200, coseno en NumPy, generación en el vLLM de la H200, trazado con `@observe` |
| `juez_ragas.py` | Fidelidad, relevancia de la respuesta, precisión y recall del contexto, con los prompts y el juez de `ragas` 0.4.3 y la fórmula escrita a mano |
| `evaluar_ragas.py` | `subir` (dataset + prompts) · `correr` (un experimento) · `verificar` (juez a la vista = `ragas.ascore`) · `prompts` (escribe `prompts_del_juez.md`, sin red) |
| `prompts_del_juez.md` | Los cinco prompts que recibe el juez, **tal cual**: instrucción, esquema JSON de salida, ejemplo *few-shot* de la librería y nuestro caso |
| `resultados/` | Lo que dejaron las corridas del 2026-10-07: un CSV por experimento y `verificar.json`. Las láminas leen de aquí |

## Antes de clase (una vez)

Necesita el servidor de Langfuse de `../demo-langfuse/` levantado y la VPN de la H200.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env      # y rellénalo: las LANGFUSE_* son las de ../demo-langfuse/.env
.venv/bin/python evaluar_ragas.py subir
```

`requirements.txt` fija la rama 0.3 de LangChain a propósito: con `ragas==0.4.3`, pip trae hoy
`langchain-community` 0.4.2 y `import ragas` falla buscando
`langchain_community.chat_models.vertexai`. Python 3.12: con 3.14 no se probó.

## Correr

```bash
.venv/bin/python evaluar_ragas.py verificar                    # ≈ 3 min: un caso, dos cálculos
.venv/bin/python evaluar_ragas.py prompts                      # sin red: los 5 prompts del juez
.venv/bin/python evaluar_ragas.py csv resultados.csv --golden golden_set.json   # Taller 4, ruta C
.venv/bin/python evaluar_ragas.py correr --top-k 1 --prompt 1  # ≈ 25 min con gemma3:27b de juez
.venv/bin/python evaluar_ragas.py correr --top-k 3 --prompt 2
```

En Langfuse (<http://localhost:3000>, proyecto «Demo sesion 17»): **Datasets → `golden-nimbus`**
lista los seis ítems y las corridas; seleccionar dos corridas las compara métrica por métrica, y un
clic en un score abre su comentario —las afirmaciones que extrajo el juez y su veredicto, o los
$v_k$ de la precisión—. **Prompts → `rag-nimbus`** tiene la v1 (`production`) y la v2
(`candidata`); cada generación de una corrida enlaza a la suya.

## Qué se versiona, y dónde

| Qué | En Langfuse | Por qué importa |
|---|---|---|
| El golden set | dataset `golden-nimbus`, un ítem por caso con id `nimbus-<id>` | volver a subir actualiza el ítem; `get_dataset(nombre, version=<fecha>)` trae el de antes |
| El prompt | `rag-nimbus` v1 y v2, con etiqueta | la generación queda ligada a su versión (`langfuse_prompt=`) |
| La medición | un experimento por configuración: `k1-prompt-v1`, `k3-prompt-v2` | sus metadatos llevan juez, versión de `ragas`, generador, embeddings y `top_k` |

Una cifra de RAGAS sin las tres versiones no se puede comparar con otra: si cambia el juez, cambia
la medición aunque el RAG sea el mismo.

## Decisiones que conviene conocer

- **Las negativas no se miden con RAGAS.** Su referencia es la frase de abstención: no hay
  afirmación que buscar en el contexto, y la fidelidad de una abstención no tiene afirmaciones
  (NaN). Se miden con la regla del Lab 02 (`abstencion`: la frase, normalizada). RAGAS mide las
  cuatro respondibles, y con cuatro casos la resolución es 0,25 por caso.
- **El juez es de otra familia que el generador** (Gemma contra el modelo del vLLM), como en el
  Taller 4.
- **`juez_ragas.py` usa piezas internas de `ragas`** (los prompts y `_create_statements`) para
  poder mostrar el trabajo del juez. `verificar` comprueba que el número coincide con el de
  `ascore`; si se actualiza la librería, se vuelve a verificar.
- **Los prompts del juez están en inglés** y el juez escribe en inglés las afirmaciones y las
  preguntas aunque la respuesta esté en español. La relevancia compara entonces una pregunta en
  español con tres en inglés sobre un modelo multilingüe: su techo práctico no es 1.

## Lo que salió el 2026-10-07

Medias sobre las cuatro respondibles (RAGAS) y las dos negativas (`abstencion`), juez `gemma3:27b`:

| Corrida | fidelidad | relevancia | precisión ctx | recall ctx | abstención |
|---|---|---|---|---|---|
| `k1-prompt-v1` | 0,812 | 0,731 | 1,000 | 0,875 | 0/2 |
| `k3-prompt-v2` | 1,000 | 0,760 | 0,958 | 1,000 | 2/2 |

Lo que enseñan los casos, más que las medias (los comentarios de cada score lo muestran):

- **Correcta y poco fiel.** `k1`, caso 1: responde bien (5 días) y la fidelidad es 0,25, porque
  añadió tres consejos que el contexto no dice. La fidelidad mide respaldo, no exactitud.
- **El recall mira la referencia, y la referencia también se evalúa.** `k1`, caso 4: con un solo
  fragmento, recall 0,5 con fidelidad 1,0. Pero la referencia de `golden_ejemplo.json` junta dos
  «30 días» que no son el mismo trámite (las facturas se presentan *dentro de* 30 días, sin
  aprobación previa), así que el 0,5 midió la mitad equivocada.
- **La precisión solo castiga el ruido que queda por encima.** `k3`: con $v=[1,0,0]$ vale 1,0; con
  $v=[1,0,1]$, 0,833.
- **Ninguna de las cuatro compara la respuesta con la referencia.** `k3`, caso 4: recall 1,0 y
  fidelidad 1,0, y la respuesta dice lo que dice la política («Solo el trabajo desde el exterior…»;
  las facturas, dentro de los 30 días, sin aprobación previa), no lo que dice la referencia. Ahí
  falla el golden set, y ninguna métrica lo ve. Se corrige **después** de la clase: corregirlo
  antes deja los dos CSV sin su golden set.
- **Una abstención sin la frase exacta cuenta como fallo.** `k1`: las dos negativas se niegan a
  inventar («No tengo información…») y la regla les da 0. La v2 pide la frase y saca 2/2.
- **Con el juez a temperatura 0, las tres preguntas de la relevancia salen idénticas**, así que
  n = 3 es n = 1. Además salen en inglés.

## Los prompts del juez

`prompts_del_juez.md` es lo que el juez lee, y conviene abrirlo antes de fiarse de una cifra. Tres
cosas que se ven ahí y no en la documentación:

- **El juez no devuelve la métrica.** Devuelve veredictos en JSON (afirmaciones, `verdict` 0/1,
  `reason`) y la fórmula la aplica el código.
- **En precisión y recall, el campo `answer` es la referencia** del golden set
  (`answer=reference` en `context_precision/metric.py` y `context_recall/metric.py`), no la
  respuesta del sistema. Por eso esas dos no corren en producción.
- **Todo está en inglés, también el ejemplo resuelto** (sobre Einstein). `prompt.adapt(
  target_language="spanish", llm=…)` traduce los ejemplos (y la instrucción con
  `adapt_instruction=True`); no se probó en este ejemplo, y traducir el prompt es cambiar el juez:
  se vuelve a calibrar y se versiona.

## RAGAS sobre el CSV del Taller 4 (ruta C)

`evaluar_ragas.py csv` lee el `resultados.csv` que escribe `Lab-04-LLMOps/evaluar_llmops.py --modo
general` —la pregunta, la respuesta y los `contextos` que devolvió el sistema— y el golden set del
taller, de donde saca la `respuesta_esperada`. Calcula fidelidad y relevancia en toda respondible
con contextos, y precisión y recall del contexto donde hay referencia, con el mismo juez a la vista
de este ejemplo. Escribe `ragas_resultados.csv`. Solo necesita `JUEZ_BASE_URL` (el Ollama de la
H200): ni Langfuse ni el vLLM.
