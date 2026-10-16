"""Capa 1: cinco reviewers en paralelo, un verificador y un sintetizador.

                ┌→ reviewer_bugs ───────┐
                ├→ reviewer_reglas ─────┤
    preparar ───┼→ reviewer_clean_code ─┼→ unir → comprobar ─┬→ verificar ─┬→ sintetizar → fin
                ├→ reviewer_eficiencia ─┤   (código)(código)  │   (modelo)  │
                └→ reviewer_impacto ────┘                     └─────────────┘
                                                        sin pendientes, o sin verificador
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from langgraph.graph import END, START, StateGraph

from .agentes.prompts import REVIEWERS, sin_rag
from .agentes.reviewer import revisar
from .agentes.sintetizador import sintetizar
from .agentes.verificador import comprobar_en_codigo, unir, verificar_con_modelo
from .baseline import RevisorBase, archivos_del_diff
from .contexto import Contexto
from .estado import Estado
from .observabilidad import en_hilo, observacion

MAX_PASOS_REVIEWER = 10
VERIFICACIONES_EN_PARALELO = 4


class RevisorMultiagente(RevisorBase):
    nombre = "multiagente"
    con_verificador = True
    con_rag = True

    def grafo(self, contexto: Contexto):
        def preparar(estado: Estado) -> dict:
            return {"archivos": archivos_del_diff(estado["diff"])}

        def crear_reviewer(nombre: str, definicion: dict):
            herramientas = [
                h for h in definicion["herramientas"] if self.con_rag or h != "buscar_reglas"
            ]

            sistema = definicion["sistema"] if self.con_rag else sin_rag(definicion["sistema"])

            def reviewer(estado: Estado) -> dict:
                with observacion(nombre, "agent", input={"archivos": estado["archivos"]}) as span:
                    hallazgos, corte = revisar(
                        nombre, sistema, estado["diff"], herramientas, contexto,
                        max_pasos=MAX_PASOS_REVIEWER,
                    )
                    span.update(output={"hallazgos": len(hallazgos), "corte": corte})
                avisos = [f"{nombre} se detuvo por {corte}; su revisión puede estar incompleta."] if corte else []
                return {"candidatos": hallazgos, "avisos": avisos}

            return reviewer

        def nodo_unir(estado: Estado) -> dict:
            candidatos = estado.get("candidatos", [])
            with observacion("unir", "chain", input={"candidatos": len(candidatos)}) as span:
                unidos = unir(candidatos)
                span.update(output={"unidos": len(unidos)})
            contexto.traza.evento("unir", candidatos=len(candidatos), unidos=len(unidos))
            return {"hallazgos": unidos}

        def comprobar(estado: Estado) -> dict:
            with observacion("comprobar_en_codigo", "chain", input={"hallazgos": len(estado["hallazgos"])}) as span:
                comprobados = [
                    comprobar_en_codigo(h, contexto, exigir_cita=self.con_rag, diff=estado["diff"])
                    for h in estado["hallazgos"]
                ]
                descartados = [h for h in comprobados if h.veredicto == "descartado"]
                span.update(output={"descartados": len(descartados)})
            contexto.traza.evento(
                "comprobar_en_codigo",
                descartados=[{"id": h.id, "motivo": h.motivo_veredicto} for h in descartados],
            )
            return {"hallazgos": comprobados}

        def verificar(estado: Estado) -> dict:
            pendientes = [h for h in estado["hallazgos"] if h.veredicto == "pendiente"]
            with observacion("verificador", "agent", input={"pendientes": len(pendientes)}) as span:
                with ThreadPoolExecutor(VERIFICACIONES_EN_PARALELO) as hilos:
                    tareas = [hilos.submit(*en_hilo(verificar_con_modelo, h, estado["diff"], contexto))
                              for h in pendientes]
                    verificados = [t.result() for t in tareas]
                span.update(output={v: sum(h.veredicto == v for h in verificados)
                                    for v in {h.veredicto for h in verificados}})
            por_id = {h.id: h for h in verificados}
            for h in verificados:
                contexto.traza.evento("veredicto", id=h.id, veredicto=h.veredicto, motivo=h.motivo_veredicto)
            sin_verificar = sum((h.motivo_veredicto or "").startswith("Sin verificar") for h in verificados)
            avisos = (
                [f"{sin_verificar} hallazgos quedaron sin verificar por presupuesto de tokens."]
                if sin_verificar
                else []
            )
            return {"hallazgos": [por_id.get(h.id, h) for h in estado["hallazgos"]], "avisos": avisos}

        def nodo_sintetizar(estado: Estado) -> dict:
            with observacion("sintetizador", "agent", input={"hallazgos": len(estado["hallazgos"])}) as span:
                informe = sintetizar(estado["hallazgos"], estado.get("avisos", []), contexto)
                span.update(output={"caracteres": len(informe or "")})
            return {"informe": informe}

        def tras_comprobar(estado: Estado) -> str:
            hay_pendientes = any(h.veredicto == "pendiente" for h in estado["hallazgos"])
            return "verificar" if self.con_verificador and hay_pendientes else "sintetizar"

        grafo = StateGraph(Estado)
        grafo.add_node("preparar", preparar)
        grafo.add_node("unir", nodo_unir)
        grafo.add_node("comprobar", comprobar)
        grafo.add_node("verificar", verificar)
        grafo.add_node("sintetizar", nodo_sintetizar)
        grafo.add_edge(START, "preparar")
        for nombre, definicion in REVIEWERS.items():
            grafo.add_node(nombre, crear_reviewer(nombre, definicion))
            grafo.add_edge("preparar", nombre)
        grafo.add_edge(list(REVIEWERS), "unir")
        grafo.add_edge("unir", "comprobar")
        grafo.add_conditional_edges("comprobar", tras_comprobar, ["verificar", "sintetizar"])
        grafo.add_edge("verificar", "sintetizar")
        grafo.add_edge("sintetizar", END)
        return grafo.compile()


class SinVerificador(RevisorMultiagente):
    """Ablación: se publica lo que digan los reviewers, sin el verificador con modelo."""

    nombre = "sin_verificador"
    con_verificador = False


class SinRAG(RevisorMultiagente):
    """Ablación: ningún agente tiene buscar_reglas."""

    nombre = "sin_rag"
    con_rag = False
