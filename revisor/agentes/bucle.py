"""El bucle de un agente, como grafo de LangGraph: modelo ↔ herramientas.

    inicio → modelo ──pidió herramientas y quedan pasos──→ herramientas ─┐
                ↑─────────────────────────────────────────────────────────┘
                └──respondió, o saltó un freno──→ fin

Frenos que cortan el bucle: tope de pasos, presupuesto de tokens y repetición.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from ..contexto import Contexto
from ..frenos import K_REPETICION, PresupuestoAgotado
from ..herramientas import crear_herramientas
from ..llamada import invocar
from ..observabilidad import prompt_ligado
from .prompts import VERSION


class EstadoAgente(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    pasos: int
    corte: str | None


def ejecutar_agente(
    nombre: str,
    sistema: str,
    tarea: str,
    nombres_herramientas: list[str],
    contexto: Contexto,
    rol: str = "default",
    max_pasos: int | None = None,
) -> EstadoAgente:
    max_pasos = max_pasos or contexto.max_pasos
    todas = crear_herramientas(
        contexto.perfil, contexto.indice, contexto.traza, nombre, contexto.citas_devueltas,
        contexto.contextos, contexto.guarda_checks,
    )
    herramientas = {n: todas[n] for n in nombres_herramientas}
    llm = contexto.llm_de(rol).bind_tools(list(herramientas.values()))
    llm_reintento = (contexto.llm_reintento_de or contexto.llm_de)(rol).bind_tools(list(herramientas.values()))
    modelo = contexto.modelo_de(rol)
    prompt = prompt_ligado(nombre, sistema, VERSION)

    vistas: Counter = Counter()

    def nodo_modelo(estado: EstadoAgente) -> dict:
        try:
            respuesta = invocar(
                llm,
                [SystemMessage(sistema), *estado["messages"]],
                agente=nombre,
                modelo=modelo,
                traza=contexto.traza,
                llm_reintento=llm_reintento,
                prompt=prompt,
            )
        except PresupuestoAgotado as agotado:
            contexto.traza.evento(
                "freno", freno="presupuesto_de_tokens", agente=nombre, detalle=str(agotado)
            )
            return {"corte": "presupuesto_de_tokens"}
        return {"messages": [respuesta], "pasos": estado["pasos"] + 1}

    def nodo_herramientas(estado: EstadoAgente) -> dict:
        observaciones = []
        corte = None
        for llamada in estado["messages"][-1].tool_calls:
            herramienta = herramientas.get(llamada["name"])
            clave = (llamada["name"], json.dumps(llamada["args"], sort_keys=True, ensure_ascii=False))
            vistas[clave] += 1
            if vistas[clave] > K_REPETICION:
                corte = "repeticion"
                contenido = json.dumps(
                    {"error": f"Llamada repetida {vistas[clave]} veces con los mismos argumentos: no se ejecutó"},
                    ensure_ascii=False,
                )
                contexto.traza.evento(
                    "freno", freno="repeticion", agente=nombre, herramienta=llamada["name"],
                    argumentos=llamada["args"], veces=vistas[clave],
                )
            elif herramienta is None:
                contenido = json.dumps(
                    {"error": f"No existe la herramienta {llamada['name']}. Disponibles: {sorted(herramientas)}"},
                    ensure_ascii=False,
                )
            else:
                try:
                    contenido = herramienta.invoke(llamada["args"])
                except Exception as error:  # argumentos que no cumplen el esquema
                    contenido = json.dumps(
                        {"error": f"Argumentos inválidos para {llamada['name']}: {error}"},
                        ensure_ascii=False,
                    )
            observaciones.append(ToolMessage(content=contenido, tool_call_id=llamada["id"]))
        return {"messages": observaciones, "corte": corte}

    def nodo_corte(estado: EstadoAgente) -> dict:
        # Cada llamada pendiente recibe su resultado: el historial queda coherente.
        pendientes = [
            ToolMessage(
                content=json.dumps({"error": "Tope de pasos alcanzado: no se ejecutó"}),
                tool_call_id=llamada["id"],
            )
            for llamada in estado["messages"][-1].tool_calls
        ]
        contexto.traza.evento("freno", freno="tope_de_pasos", agente=nombre, pasos=estado["pasos"])
        return {"messages": pendientes, "corte": "tope_de_pasos"}

    def siguiente(estado: EstadoAgente) -> str:
        if estado["corte"] or not estado["messages"][-1].tool_calls:
            return END
        return "herramientas" if estado["pasos"] < max_pasos else "corte"

    grafo = StateGraph(EstadoAgente)
    grafo.add_node("modelo", nodo_modelo)
    grafo.add_node("herramientas", nodo_herramientas)
    grafo.add_node("corte", nodo_corte)
    grafo.add_edge(START, "modelo")
    grafo.add_conditional_edges("modelo", siguiente, ["herramientas", "corte", END])
    grafo.add_conditional_edges(
        "herramientas", lambda estado: END if estado["corte"] else "modelo", ["modelo", END]
    )
    grafo.add_edge("corte", END)

    return grafo.compile().invoke(
        {"messages": [HumanMessage(tarea)], "pasos": 0, "corte": None},
        {"recursion_limit": 4 * max_pasos + 10},
    )
