"""Spans en Langfuse: uno por corrida, guardrail, agente, llamada al modelo, herramienta y consulta al RAG.

    revisor (agent, la raíz: el span «corrida»)
    ├── validar_entrada (guardrail)
    ├── lista_de_permitidos (guardrail)            ¿se pueden correr los checks sobre este parche?
    ├── inyeccion_en_parche (guardrail)
    ├── reviewer_bugs … reviewer_impacto (agent, en paralelo)
    │   ├── reviewer_bugs (generation)            una por llamada al modelo
    │   ├── leer_archivo · grep_repo (tool)
    │   ├── buscar_reglas (retriever)
    │   └── guarda_correr_checks (guardrail) → correr_checks (tool)
    ├── unir · comprobar_en_codigo (chain)
    ├── verificador (agent) → una generation por hallazgo, en hilos
    ├── sintetizador (agent)
    └── validar_salida (guardrail)

Las tres correcciones de la Parte 0.c:
- la máscara redacta datos personales y claves aquí, antes de enviar nada, y recorre tuplas;
- la raíz envuelve los guardrails, así que su duración los incluye;
- cada span es un `with`: se cierra, con nivel ERROR, también cuando lo de adentro lanza.

Sin LANGFUSE_PUBLIC_KEY y LANGFUSE_SECRET_KEY, o con REVISOR_LANGFUSE=0, todo es un no-op.
"""

from __future__ import annotations

import contextvars
import os
from contextlib import contextmanager, nullcontext

from .guardrails import redactar_claves, redactar_pii

MAX_TEXTO_SPAN = 4000

_cliente = None
_configurado = False


def enmascarar(*, data, **_):
    """Corre en esta máquina antes de exportar. @observe y el SDK guardan argumentos como
    tuplas: una máscara que solo mira listas y diccionarios deja pasar lo que viaja en ellas."""
    if isinstance(data, str):
        return redactar_claves(redactar_pii(data))
    if isinstance(data, dict):
        return {k: enmascarar(data=v) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [enmascarar(data=v) for v in data]
    return data


def configurar(**opciones):
    """Crea el cliente con la máscara. Los tests pasan aquí un exportador en memoria."""
    global _cliente, _configurado
    from langfuse import Langfuse

    _cliente = Langfuse(mask=enmascarar, **opciones)
    _configurado = True
    return _cliente


def cliente():
    global _configurado
    if not _configurado:
        _configurado = True
        activo = os.getenv("REVISOR_LANGFUSE", "1") != "0"
        if activo and os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):
            configurar()
    return _cliente


class _SpanNulo:
    trace_id = None
    id = None

    def update(self, **_):
        return self


@contextmanager
def observacion(nombre: str, tipo: str = "span", **campos):
    """Un span de Langfuse como `with`. Si lo de adentro lanza, el span queda en ERROR con el
    mensaje y se cierra igual; la excepción sigue su camino."""
    lf = cliente()
    if lf is None:
        yield _SpanNulo()
        return
    with lf.start_as_current_observation(name=nombre, as_type=tipo, **campos) as span:
        try:
            yield span
        except BaseException as error:
            span.update(level="ERROR", status_message=f"{type(error).__name__}: {error}"[:MAX_TEXTO_SPAN])
            raise


def atributos_de_corrida(prompt_version: str):
    """Sesión, etiqueta y versión de prompt para todos los spans de la corrida."""
    lf = cliente()
    if lf is None:
        return nullcontext()
    from langfuse import propagate_attributes

    sesion = os.getenv("LANGFUSE_SESION")
    etiqueta = os.getenv("LANGFUSE_ETIQUETA")
    return propagate_attributes(
        session_id=sesion or None, tags=[etiqueta] if etiqueta else None,
        metadata={"prompt_version": prompt_version},
    )


def en_hilo(funcion, *args):
    """Para ThreadPoolExecutor.submit: el hilo hereda el span actual, así que sus spans
    quedan colgados del agente que los lanzó y no como trazas sueltas."""
    return contextvars.copy_context().run, funcion, *args


_prompts: dict[str, object] = {}


def nombre_de_prompt(agente: str) -> str:
    return f"revisor-{agente}"


def prompt_ligado(agente: str, texto: str, version: str):
    """El prompt de Langfuse con la etiqueta `version` para este agente, si existe y su texto es el
    que el agente usa de verdad; si no, None y la generation queda sin ligar. Se pide una vez."""
    lf = cliente()
    if lf is None:
        return None
    clave = f"{agente}@{version}"
    if clave not in _prompts:
        try:
            prompt = lf.get_prompt(nombre_de_prompt(agente), label=version, cache_ttl_seconds=3600)
            _prompts[clave] = prompt if prompt.prompt == texto else None
        except Exception:
            _prompts[clave] = None
    return _prompts[clave]


def flush() -> None:
    if _cliente is not None:
        _cliente.flush()


def recortar(texto) -> str | None:
    if texto is None:
        return None
    texto = str(texto)
    return texto if len(texto) <= MAX_TEXTO_SPAN else texto[:MAX_TEXTO_SPAN] + f"… (+{len(texto) - MAX_TEXTO_SPAN})"
