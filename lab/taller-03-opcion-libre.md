# Taller 03 — Las tres opciones, y la opción libre

> **Registro del 2026-10-09.** Durante el Taller 3 el profesor abrió tres opciones. Este archivo
> deja por escrito la tercera, que no tenía enunciado propio, y el contrato mínimo que el
> Taller 4 necesita para evaluar cualquiera de las tres. No cambia la evaluación del Taller 3,
> que ya se entregó.

**Materia:** MMIA 6013 IA Generativa y Agentes · **Semana:** 3 · **Peso:** 25 % de la nota final

---

## Las tres opciones (se elige una sola)

La instrucción del profesor, tal como se dio en clase:

> En este taller pueden realizar cualquiera de las siguientes opciones (solo una):
>
> - El taller 03 propuesto para agentes (`taller-03-agentes.pdf`).
> - El taller 03 de agentes para resolver tareas (`taller-03-solver-multiagentes.pdf`).
> - O, un taller 03 donde ustedes propongan el tema de forma libre:
>   - al menos 5 agentes;
>   - usando LangGraph y pegándose a la H200 (a menos que quieran hacer algo con otro proveedor);
>   - que use 3–4 herramientas;
>   - una de ellas sea RAG o un esquema de *augmented generation*.
>
> Les adjunto un ejemplo de una tarea de pregrado.

| Ruta | Enunciado | Lo que se construyó |
|---|---|---|
| **A** — el agente analista | [`taller-03-agentes.md`](taller-03-agentes.md) | un agente con tres herramientas sobre la base SQLite del `Lab-03` |
| **B** — el solver multiagente | [`taller-03-v2-solver-multiagente.md`](taller-03-v2-solver-multiagente.md) | un orquestador con al menos cinco roles y GraphRAG que resuelve tareas en PDF |
| **C** — la opción libre | este archivo | un sistema de al menos cinco agentes en LangGraph, con 3–4 herramientas y una de ellas RAG |

---

## Opción C — lo que pide

1. **Al menos cinco agentes** con responsabilidades distintas, orquestados como **grafo de
   estados en LangGraph** (`langgraph==1.2.12`, la versión del `Lab-03`), con sus aristas
   condicionales y un **tope de pasos** que garantice que el grafo termina.
2. **El modelo de la H200** (el vLLM del 12555, el id que devuelve `/v1/models`), o el de otro
   proveedor si se declara con su fila de `fuentes/modelos/modelos-2026-1.json` y su fecha.
3. **Tres o cuatro herramientas**, cada una con su esquema y su manejo de error, y **una de ellas
   RAG** —o un esquema de *augmented generation*— sobre un corpus propio, con cita de los
   fragmentos que usa.
4. **El tema lo propone el grupo**, con un caso de uso que se pueda evaluar: preguntas cuya
   respuesta correcta se puede escribir o comprobar.

## El contrato mínimo (para el Taller 4)

Sea cual sea la ruta, el Taller 4 mide el sistema a través de una sola puerta. Para la opción
C es esta:

    Sistema().run(pregunta: str) -> dict
        answer      la respuesta final
        status      "ok" | "abstencion" | "error" | "tope_de_pasos" | …
        model       el id del modelo, leído del endpoint
        usage       {"tokens_entrada": int, "tokens_salida": int}, sumados sobre todos los agentes
        trace       [ {"agente": str, "tool": str | None, "observation": …}, … ]   un paso por acción
        contextos   [str, …]   los fragmentos que recuperó el RAG para esa respuesta (si lo usó)

Que cada paso de la traza diga **qué agente** lo dio y **qué herramienta** invocó es lo que le
permite al evaluador del Taller 4 contar agentes, comprobar herramientas esperadas y prohibidas,
y a RAGAS medir la recuperación. Si tu sistema del Taller 3 no lo devuelve así, el Taller 4 empieza
por un adaptador, y eso no resta: es la primera corrección de su Parte 1.
