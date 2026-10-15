"""Lo que comparte una corrida: el repo, el índice, la traza y cómo pedir un modelo."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .config import get_llm, id_modelo
from .frenos import MAX_PASOS
from .guardrails import GuardaChecks
from .perfil import Perfil
from .rag.indice import Indice
from .traza import Traza


@dataclass
class Contexto:
    perfil: Perfil
    indice: Indice | None
    traza: Traza
    llm_de: Callable[[str], object] = get_llm
    modelo_de: Callable[[str], str] = id_modelo
    # Modelo para reintentar tras una respuesta vacía; si falta, se reintenta con el mismo.
    llm_reintento_de: Callable[[str], object] | None = None
    citas_devueltas: set[str] = field(default_factory=set)
    # Fragmentos que buscar_reglas entregó, completos y en orden: los contextos de RAGAS.
    contextos: list[dict] = field(default_factory=list)
    max_pasos: int = MAX_PASOS
    # Guardrail de correr_checks: decide con el diff de la corrida y lleva la cuenta del tope.
    guarda_checks: GuardaChecks | None = None
