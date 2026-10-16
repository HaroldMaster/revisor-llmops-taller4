"""Toda llamada al modelo pasa por aquí: mide, registra en la traza y
reintenta cuando el modelo devuelve una respuesta vacía."""

from __future__ import annotations

import time

from .observabilidad import observacion, recortar
from .traza import Traza


def texto_de(mensaje) -> str:
    contenido = mensaje.content
    if isinstance(contenido, str):
        return contenido
    return "".join(b.get("text", "") for b in contenido if isinstance(b, dict))


def mensajes_para_span(mensajes) -> list[dict]:
    return [{"role": getattr(m, "type", "texto"), "content": recortar(texto_de(m) if hasattr(m, "content") else m)}
            for m in mensajes]


def invocar(
    llm, mensajes, *, agente: str, modelo: str, traza: Traza, con_reserva: bool = False,
    llm_reintento=None, prompt=None,
):
    """Llama al modelo. Si la respuesta llega vacía o la llamada falla (por ejemplo
    por tiempo), reintenta una vez con `llm_reintento`: repetir la misma llamada a
    un modelo que se quedó razonando suele fallar igual."""
    traza.exigir_presupuesto(con_reserva)
    respuesta = None
    intentos = [llm, llm_reintento or llm]
    for numero, actual in enumerate(intentos):
        with observacion(agente, "generation", model=modelo, input=mensajes_para_span(mensajes),
                         metadata={"intento": numero + 1}, prompt=prompt) as generacion:
            inicio = time.perf_counter()
            try:
                respuesta = actual.invoke(mensajes)
            except Exception as error:
                latencia = round((time.perf_counter() - inicio) * 1000)
                traza.llamada(agente, modelo, 0, 0, latencia, error=f"{type(error).__name__}: {error}")
                generacion.update(level="ERROR", status_message=f"{type(error).__name__}: {error}")
                if numero == len(intentos) - 1:
                    raise
                continue
            latencia = round((time.perf_counter() - inicio) * 1000)
            uso = respuesta.usage_metadata or {}
            vacia = not texto_de(respuesta).strip() and not respuesta.tool_calls
            pide = [{"nombre": l["name"], "argumentos": l["args"]} for l in respuesta.tool_calls]
            traza.llamada(
                agente,
                modelo,
                uso.get("input_tokens", 0),
                uso.get("output_tokens", 0),
                latencia,
                error="respuesta vacía" if vacia else None,
                respuesta=texto_de(respuesta),
                pide=pide,
            )
            generacion.update(
                output={"texto": recortar(texto_de(respuesta)), "pide": pide},
                usage_details={"input": uso.get("input_tokens", 0), "output": uso.get("output_tokens", 0)},
                **({"level": "ERROR", "status_message": "respuesta vacía"} if vacia else {}),
            )
        if not vacia:
            break
    return respuesta


def invocar_estructurado(
    llm, esquema, mensajes, *, agente: str, modelo: str, traza: Traza, con_reserva: bool = False,
    llm_reintento=None,
):
    """Como invocar, para una respuesta con esquema fijo. Devuelve el objeto
    validado, o None si tras el reintento el modelo no lo entregó."""
    from .config import estructurado

    traza.exigir_presupuesto(con_reserva)
    intentos = [llm, llm_reintento or llm]
    for numero, actual in enumerate(intentos):
        ejecutable = estructurado(actual, esquema)
        with observacion(agente, "generation", model=modelo, input=mensajes_para_span(mensajes),
                         metadata={"intento": numero + 1, "esquema": esquema.__name__}) as generacion:
            inicio = time.perf_counter()
            try:
                resultado = ejecutable.invoke(mensajes)
            except Exception as error:
                latencia = round((time.perf_counter() - inicio) * 1000)
                traza.llamada(agente, modelo, 0, 0, latencia, error=f"{type(error).__name__}: {error}")
                generacion.update(level="ERROR", status_message=f"{type(error).__name__}: {error}")
                if numero == len(intentos) - 1:
                    raise
                continue
            latencia = round((time.perf_counter() - inicio) * 1000)
            uso = resultado["raw"].usage_metadata or {}
            objeto = resultado["parsed"]
            motivo = None
            if objeto is None:
                fin = resultado["raw"].response_metadata.get("finish_reason")
                motivo = f"sin salida estructurada (finish_reason={fin}): {resultado['parsing_error']}"
            respuesta = objeto.model_dump_json() if objeto is not None else None
            traza.llamada(
                agente, modelo, uso.get("input_tokens", 0), uso.get("output_tokens", 0), latencia,
                error=motivo,
                respuesta=respuesta,
            )
            generacion.update(
                output=recortar(respuesta),
                usage_details={"input": uso.get("input_tokens", 0), "output": uso.get("output_tokens", 0)},
                **({"level": "ERROR", "status_message": recortar(motivo)} if motivo else {}),
            )
        if objeto is not None:
            return objeto
    return None
