"""Registro de cada corrida. Cada evento se escribe en disco en el momento,
así que una corrida que falla a la mitad también deja su traza."""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .frenos import PresupuestoAgotado
from .guardrails import redactar_pii


MAX_EXTRACTO = 700  # caracteres que se guardan de cada respuesta y de cada observación


def extracto(texto: str | None) -> str | None:
    if texto is None or len(texto) <= MAX_EXTRACTO:
        return texto
    return texto[:MAX_EXTRACTO] + f"… (+{len(texto) - MAX_EXTRACTO} caracteres)"


class Traza:
    def __init__(
        self,
        carpeta: str | Path,
        corrida_id: str | None = None,
        limite_tokens: int | None = None,
        reserva_tokens: int = 0,
    ):
        self.limite_tokens = limite_tokens
        self.reserva_tokens = reserva_tokens
        self.corrida_id = corrida_id or datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        self.ruta = Path(carpeta) / f"traza-{self.corrida_id}.jsonl"
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.eventos: list[dict] = []
        self._inicio = time.perf_counter()
        self._candado = threading.Lock()  # varios agentes escriben a la vez

    def _escribir(self, evento: dict) -> None:
        evento = {"t_ms": round((time.perf_counter() - self._inicio) * 1000), **evento}
        # Lo que queda en disco va sin datos personales: el parche y el código revisado pueden traerlos.
        linea = redactar_pii(json.dumps(evento, ensure_ascii=False))
        with self._candado:
            self.eventos.append(evento)
            with self.ruta.open("a", encoding="utf-8") as archivo:
                archivo.write(linea + "\n")

    def llamada(
        self,
        agente: str,
        modelo: str,
        tokens_entrada: int,
        tokens_salida: int,
        latencia_ms: int,
        error: str | None = None,
        respuesta: str | None = None,
        pide: list | None = None,
    ) -> None:
        """`respuesta` es lo que el modelo contestó y `pide`, las herramientas que pidió."""
        self._escribir(
            {
                "tipo": "llamada",
                "agente": agente,
                "modelo": modelo,
                "tokens_entrada": tokens_entrada,
                "tokens_salida": tokens_salida,
                "latencia_ms": latencia_ms,
                "error": error,
                "pide": pide or [],
                "respuesta": extracto(respuesta),
            }
        )

    def herramienta(
        self,
        agente: str,
        nombre: str,
        argumentos: dict,
        tamano_resultado: int,
        latencia_ms: int,
        error: str | None = None,
        resultado: str | None = None,
    ) -> None:
        """`resultado` es lo que el modelo observó: el inicio de lo que devolvió la herramienta."""
        self._escribir(
            {
                "tipo": "herramienta",
                "agente": agente,
                "nombre": nombre,
                "argumentos": argumentos,
                "tamano_resultado": tamano_resultado,
                "latencia_ms": latencia_ms,
                "error": error,
                "resultado": extracto(resultado),
            }
        )

    def evento(self, tipo: str, **datos) -> None:
        self._escribir({"tipo": tipo, **datos})

    def exigir_presupuesto(self, con_reserva: bool = False) -> None:
        """Se llama antes de cada llamada al modelo. El trabajo normal puede gastar
        hasta límite − reserva; los pasos de cierre, hasta el límite completo."""
        if self.limite_tokens is None:
            return
        uso = self.uso()
        gastado = uso["tokens_entrada"] + uso["tokens_salida"]
        tope = self.limite_tokens if con_reserva else self.limite_tokens - self.reserva_tokens
        if gastado >= tope:
            raise PresupuestoAgotado(f"gastados {gastado} tokens de {tope} disponibles")

    def uso(self) -> dict[str, int]:
        llamadas = [e for e in self.eventos if e["tipo"] == "llamada"]
        return {
            "tokens_entrada": sum(e["tokens_entrada"] for e in llamadas),
            "tokens_salida": sum(e["tokens_salida"] for e in llamadas),
        }

    def uso_por_agente(self) -> dict[str, dict[str, int]]:
        por_agente: dict[str, dict[str, int]] = defaultdict(
            lambda: {"llamadas": 0, "tokens_entrada": 0, "tokens_salida": 0}
        )
        for e in self.eventos:
            if e["tipo"] == "llamada":
                por_agente[e["agente"]]["llamadas"] += 1
                por_agente[e["agente"]]["tokens_entrada"] += e["tokens_entrada"]
                por_agente[e["agente"]]["tokens_salida"] += e["tokens_salida"]
        return dict(por_agente)

    def cerrar(self, status: str, error: str | None = None) -> None:
        self._escribir(
            {
                "tipo": "cierre",
                "status": status,
                "error": error,
                "uso": self.uso(),
                "uso_por_agente": self.uso_por_agente(),
            }
        )
