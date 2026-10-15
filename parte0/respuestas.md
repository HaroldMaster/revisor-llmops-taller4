# Parte 0 — Tres errores que no dan error

Salidas crudas de `lab/Lab-04-LLMOps/guion.py`, con el laboratorio tal como se repartió
(idéntico al zip del enunciado). No se usa ningún modelo. Para repetirlas:

```bash
uv venv --python 3.12 .venv-lab
(cd lab/Lab-04-LLMOps && uv pip install --python ../../.venv-lab/bin/python -r requirements.txt)
cd lab/Lab-04-LLMOps
../../.venv-lab/bin/python guion.py ceros       # → parte0/salidas/ceros.txt
../../.venv-lab/bin/python guion.py guardrails  # → parte0/salidas/guardrails.txt
../../.venv-lab/bin/python guion.py traza       # → parte0/salidas/traza.txt
```

El laboratorio va en su propio entorno (`.venv-lab`) porque `instrumented_agent.py` importa el
agente del Lab 03, que pide `matplotlib` y `pandas`; el revisor no los usa.

## 0.a — El reporte lleno de ceros

Salida: [`salidas/ceros.txt`](salidas/ceros.txt).

`instrumented_agent.py` escribe `reports/traces.jsonl` (línea 66) y `evaluation.py` lee
`reports/answers.json` (líneas 71-72); como ese archivo no existe, toma un diccionario vacío,
da a cada caso la respuesta `""` (línea 57) y califica las cuatro con 0.

- **Por qué un reporte en ceros es peor que un error.** Un error detiene la corrida y obliga
  a mirar; un reporte en ceros tiene el formato de un resultado válido, así que se lee como
  «el agente falló en todo» cuando en realidad no se evaluó ninguna respuesta.
- **Por qué no se pueden promediar los dos ceros.** `abstention_score` devuelve 0 cuando el
  caso no es negativo (línea 48-49: no aplica) y también cuando es negativo y el agente no se
  abstuvo (falló). Con las respuestas correctas, el paso 3 da 0, 0, 1, 0: el promedio es 0,25
  aunque el único caso donde la métrica aplica está bien, es decir, 1 de 1.

## 0.b — Lo que el guardrail deja pasar y lo que bloquea por error

Salida: [`salidas/guardrails.txt`](salidas/guardrails.txt).

| | Casos | Correctos | Falsos negativos | Falsos positivos |
|---|---|---|---|---|
| Validadores de ejemplo | 17 | 9 | 5 (A02, A04, A05, A06, S02) | 3 (L01, L03, S03) |

Tasa de falsos negativos: 5 de 11 casos que había que detener (0,455). Tasa de falsos
positivos: 3 de 6 casos legítimos (0,5).

- **Qué tienen en común los ataques que pasan.** Dicen lo mismo que un patrón de la lista con
  otra forma. La A02 y la A03 son la misma frase: la A03 («actua», sin tilde) coincide con el
  patrón y se bloquea; la A02 («actúa», bien escrita) pasa, porque el validador pone el texto
  en minúsculas pero no le quita las tildes y compara frases literales. La A04 cambia el verbo
  («ignora» en vez de «olvida»), la A05 un determinante («tus» en vez de «las») y la A06 pide
  el prompt sin usar ninguna palabra de la lista.
- **Por qué los falsos positivos de la L01 y la L03 son graves aunque no bloqueen.** El
  validador devuelve `ok=True` con el texto cambiado: la pregunta sigue su camino sin ningún
  aviso, pero ya no es la que hizo el usuario. El agente contesta otra pregunta y nada en el
  estado de la corrida lo indica.
- **Qué le pasa a la L03 en un agente que consulta ventas por fecha.** Las cuatro fechas
  quedan reemplazadas por `[TELEFONO_REDACTADO]`: el agente recibe «compara las ventas de
  [TELEFONO_REDACTADO] a [TELEFONO_REDACTADO]…» y no tiene ningún rango con que filtrar. O
  se abstiene ante una pregunta que sí podía responder, o inventa el periodo.

## 0.c — La traza que filtra datos, mide mal y se pierde

Salida: [`salidas/traza.txt`](salidas/traza.txt).

| Problema | Lo que se ve | Línea de `instrumented_agent.py` que lo causa |
|---|---|---|
| Filtra datos | el correo de una pregunta bloqueada está en `reports/traces.jsonl` | **47**: al bloquear arma el resultado con `"question": question`, la pregunta original, y no con el texto ya validado; la línea 58 lo escribe |
| Mide mal | la corrida tardó 0,40 s y la traza dice `latency_seconds=0.0` | **45**: el cronómetro (`started = time.perf_counter()`) arranca después de `validate_input`, que corre en la línea 44 |
| Se pierde | el agente lanza y el archivo tiene 2 filas antes y 2 después | **50**: `agent.run()` no está dentro de un `try/finally`, así que la excepción sale de la función antes de llegar a `write_local_trace` (línea 58) |

Son las tres correcciones de la Parte 1: redactar antes de escribir, que la medición incluya
los guardrails y que el span exista aunque la corrida falle.
