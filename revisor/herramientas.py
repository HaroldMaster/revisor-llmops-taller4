"""Las cuatro herramientas del revisor.

Los límites (líneas, coincidencias, comandos, tiempo) están fijados aquí y
no son parámetros: el modelo no puede pedir más de lo que este código da.
Ninguna lanza: un fallo vuelve al modelo como {"error": ...}.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import signal
import subprocess
import time
from functools import wraps
from typing import Literal

from langchain_core.tools import tool

from .guardrails import GuardaChecks
from .perfil import Perfil
from .rag.indice import Indice
from .traza import Traza

MAX_LINEAS = 200
MAX_COINCIDENCIAS = 40
MAX_LARGO_LINEA = 240
K_FRAGMENTOS = 4
MAX_TEXTO_FRAGMENTO = 1200
TIEMPO_CHECK_S = 120
MAX_SALIDA_CHECK = 3000


def _error(mensaje: str) -> str:
    return json.dumps({"error": mensaje}, ensure_ascii=False)


def crear_herramientas(
    perfil: Perfil,
    indice: Indice | None,
    traza: Traza | None = None,
    agente: str = "agente",
    citas_devueltas: set[str] | None = None,
    contextos: list[dict] | None = None,
    guarda_checks: GuardaChecks | None = None,
) -> dict:
    """Devuelve las herramientas por nombre. `citas_devueltas` acumula los ids
    que buscar_reglas entregó en esta corrida: es lo que permite comprobar en
    código que una cita de regla no fue inventada."""

    def registrada(funcion):
        @wraps(funcion)
        def envoltura(**argumentos):
            inicio = time.perf_counter()
            try:
                resultado = funcion(**argumentos)
            except Exception as error:  # un fallo es una observación, no un final
                resultado = _error(f"{type(error).__name__}: {error}")
            if traza is not None:
                fallo = resultado.startswith('{"error"')
                traza.herramienta(
                    agente,
                    funcion.__name__,
                    argumentos,
                    len(resultado),
                    round((time.perf_counter() - inicio) * 1000),
                    error=json.loads(resultado)["error"] if fallo else None,
                    resultado=resultado,
                )
            return resultado

        return envoltura

    def resolver(ruta: str):
        destino = (perfil.raiz / ruta).resolve()
        if not destino.is_relative_to(perfil.raiz):
            return None, _error(f"La ruta {ruta} sale del repositorio")
        if perfil.ignorado(destino) or destino.name.startswith(".env"):
            return None, _error(f"La ruta {ruta} no se puede leer")
        if not destino.is_file():
            return None, _error(f"No existe el archivo {ruta}. Usa grep_repo para ubicarlo")
        return destino, None

    @tool
    @registrada
    def leer_archivo(ruta: str, desde: int = 1, hasta: int = 0) -> str:
        """Lee un tramo de un archivo del repositorio y lo devuelve con números de línea.

        Úsala para ver el contexto de un cambio o de una coincidencia de grep_repo.
        No sirve para buscar: si no sabes en qué archivo está algo, usa grep_repo.

        Args:
            ruta: ruta relativa a la raíz del repo, por ejemplo "src/pedidos/pedidos.ts".
            desde: primera línea a leer, empezando en 1.
            hasta: última línea a leer; 0 lee hasta el máximo permitido.
        """
        destino, fallo = resolver(ruta)
        if fallo:
            return fallo
        lineas = destino.read_text(encoding="utf-8", errors="replace").splitlines()
        desde = max(1, desde)
        tope = desde + MAX_LINEAS - 1
        hasta = min(hasta if hasta >= desde else tope, tope, len(lineas))
        cuerpo = "\n".join(f"{n}: {lineas[n - 1]}" for n in range(desde, hasta + 1))
        resto = len(lineas) - hasta
        aviso = f"\n(quedan {resto} líneas; pide desde={hasta + 1})" if resto > 0 else ""
        return f"{ruta} líneas {desde}-{hasta} de {len(lineas)}\n{cuerpo}{aviso}"

    @tool
    @registrada
    def grep_repo(patron: str, carpeta: str = "") -> str:
        """Busca un texto o expresión regular en el código del repositorio y devuelve
        cada coincidencia como "ruta:línea: texto".

        Úsala para saber dónde se define o quién usa una función, clase o constante,
        también fuera del diff. No sirve para buscar normas: para eso usa buscar_reglas.

        Args:
            patron: texto exacto o expresión regular, por ejemplo "calcularDescuento\\(".
            carpeta: limita la búsqueda a rutas que empiezan así, por ejemplo "src/pedidos".
        """
        try:
            expresion = re.compile(patron)
        except re.error:
            expresion = re.compile(re.escape(patron))
        coincidencias: list[str] = []
        total = 0
        for archivo in perfil.archivos_de_codigo():
            relativa = archivo.relative_to(perfil.raiz).as_posix()
            if carpeta and not relativa.startswith(carpeta.strip("/")):
                continue
            texto = archivo.read_text(encoding="utf-8", errors="replace")
            for numero, linea in enumerate(texto.splitlines(), start=1):
                if expresion.search(linea):
                    total += 1
                    if len(coincidencias) < MAX_COINCIDENCIAS:
                        coincidencias.append(f"{relativa}:{numero}: {linea.strip()[:MAX_LARGO_LINEA]}")
        if total == 0:
            return f"Sin coincidencias para {patron!r}"
        aviso = (
            f"\n({total - MAX_COINCIDENCIAS} coincidencias más; afina el patrón o usa carpeta)"
            if total > MAX_COINCIDENCIAS
            else ""
        )
        return f"{total} coincidencias\n" + "\n".join(coincidencias) + aviso

    @tool
    @registrada
    def buscar_reglas(pregunta: str) -> str:
        """Recupera las reglas del repositorio y los fragmentos de documentación oficial
        más relacionados con una pregunta. Cada fragmento vuelve con su id y su origen.

        Úsala para saber qué norma aplica a un cambio antes de afirmar que la incumple.
        Pregunta por la intención ("cómo se calculan los importes de dinero"), no pegues
        código. El id que devuelve es el único valor válido para citar una regla.

        Args:
            pregunta: la duda en una frase, en lenguaje natural.
        """
        if indice is None:
            return _error("El índice de reglas no está disponible en esta corrida")
        resultados = indice.buscar(pregunta, K_FRAGMENTOS)
        if citas_devueltas is not None:
            citas_devueltas.update(f.id for f, _ in resultados)
        if contextos is not None:
            contextos.extend(
                {"id": f.id, "fuente": f.fuente, "texto": f.texto[:MAX_TEXTO_FRAGMENTO]} for f, _ in resultados
            )
        return json.dumps(
            [
                {
                    "id": fragmento.id,
                    "origen": fragmento.origen,
                    "fuente": fragmento.fuente,
                    "texto": fragmento.texto[:MAX_TEXTO_FRAGMENTO],
                }
                for fragmento, _ in resultados
            ],
            ensure_ascii=False,
        )

    @tool
    @registrada
    def correr_checks(tipo: Literal["lint", "tests", "tipos"]) -> str:
        """Ejecuta una comprobación del repositorio y devuelve su código de salida y el
        final de su salida. Código 0 significa que pasó.

        Úsala para confirmar con una ejecución lo que sospechas al leer el código.
        Es lenta: no la repitas con el mismo tipo si el código no cambió.

        Args:
            tipo: "lint", "tests" o "tipos".
        """
        if guarda_checks is not None:
            inicio = time.perf_counter()
            decision, motivo = guarda_checks.decidir()
            if traza is not None:
                traza.evento("guardrail", nombre="correr_checks", agente=agente, decision=decision, motivo=motivo,
                             latencia_ms=round((time.perf_counter() - inicio) * 1000, 3))
            if decision == "bloquear":
                return _error(f"Bloqueado por el guardrail de correr_checks: {motivo}")
        comando = perfil.checks.get(tipo)
        if comando is None:
            return _error(f"El perfil no define el check {tipo}")
        entorno = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""), "CI": "1"}
        proceso = subprocess.Popen(
            shlex.split(comando),
            cwd=perfil.raiz,
            env=entorno,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        try:
            salida, _ = proceso.communicate(timeout=TIEMPO_CHECK_S)
        except subprocess.TimeoutExpired:
            os.killpg(proceso.pid, signal.SIGKILL)
            proceso.communicate()
            return _error(f"El check {tipo} superó {TIEMPO_CHECK_S} s y se detuvo")
        return json.dumps(
            {"tipo": tipo, "codigo_salida": proceso.returncode, "salida": salida[-MAX_SALIDA_CHECK:]},
            ensure_ascii=False,
        )

    return {
        "leer_archivo": leer_archivo,
        "grep_repo": grep_repo,
        "buscar_reglas": buscar_reglas,
        "correr_checks": correr_checks,
    }
