"""La puerta del Taller 4: Sistema().run(pregunta) con el contrato de la opción C.

La pregunta es texto libre que nombra el parche que se quiere revisar
("Revisa casos/C01.patch, por favor"). El revisor del Taller 3 recibe la ruta;
este adaptador la resuelve, corre el sistema y devuelve:

    answer     una línea por hallazgo, corta: el evaluador califica sus 600 primeros caracteres
    informe    el informe completo del sintetizador
    status     ok | abstencion | aclaracion | incompleto | error
    model      el id del modelo, leído del endpoint
    usage      tokens de entrada y salida, sumados sobre todos los agentes
    trace      un paso por acción: {"agente", "tool", "observation"}
    contextos  los fragmentos que devolvió buscar_reglas, completos
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .config import RAIZ
from .multiagente import RevisorMultiagente

ABSTENCION = "No puedo responder con los datos disponibles."
CARPETA_PARCHES = RAIZ / "evaluacion"
MAX_RESPUESTA = 600
# El evaluador guarda json.dumps(contextos)[:8000]: si se pasa, el JSON queda cortado
# y RAGAS no lo puede leer. Se entregan fragmentos enteros hasta este tope.
MAX_CONTEXTOS = 7500

_PARCHE = re.compile(r"[\w./-]+\.patch\b")
_STATUS = {"completed": "ok", "incompleto": "incompleto", "failed": "error"}
_ORDEN = {"critico": 0, "alto": 1, "medio": 2}


def parches_de(pregunta: str) -> list[Path]:
    """Los parches que la pregunta nombra y que existen dentro de evaluacion/."""
    encontrados = []
    for nombre in dict.fromkeys(_PARCHE.findall(pregunta or "")):
        ruta = (CARPETA_PARCHES / nombre).resolve()
        if ruta.is_relative_to(CARPETA_PARCHES) and ruta.is_file() and ruta not in encontrados:
            encontrados.append(ruta)
    return encontrados


def respuesta_corta(hallazgos: list[dict], status: str, limite: int = MAX_RESPUESTA) -> str:
    """Una línea por ubicación con hallazgos vigentes, de más a menos grave."""
    vigentes = [h for h in hallazgos if h.get("veredicto") != "descartado"]
    if not vigentes:
        return "Sin hallazgos." if status == "ok" else "La revisión se cortó antes de terminar y no dejó hallazgos."
    por_lugar: dict[tuple, list[dict]] = {}
    for h in sorted(vigentes, key=lambda h: (_ORDEN.get(h["severidad"], 9), h["archivo"], h["linea"])):
        por_lugar.setdefault((h["archivo"], h["linea"]), []).append(h)
    lineas = []
    for (archivo, linea), grupo in por_lugar.items():
        etiquetas = list(dict.fromkeys([h["dimension"] for h in grupo] + [h["cita_regla"] for h in grupo if h.get("cita_regla")]))
        lineas.append(f"- [{grupo[0]['severidad']} · {' · '.join(etiquetas)}] {archivo}:{linea} — {grupo[0]['afirmacion']}")
    texto = "\n".join(lineas)
    if len(texto) <= limite:
        return texto
    # Demasiado largo: se recorta cada afirmación por igual, sin perder ninguna ubicación.
    cabeceras = [l.split(" — ", 1) for l in lineas]
    sobra = max(0, (limite - sum(len(c) + 4 for c, _ in cabeceras)) // len(cabeceras))
    return "\n".join(f"{c} — {a[:sobra].rstrip()}…" if len(a) > sobra else f"{c} — {a}" for c, a in cabeceras)[:limite]


def pasos_de(ruta_traza: str | Path) -> list[dict]:
    """La traza en disco del Taller 3, como pasos con agente, herramienta y observación."""
    ruta = Path(ruta_traza)
    if not ruta.is_file():
        return []
    pasos = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        e = json.loads(linea)
        if e["tipo"] == "llamada":
            pasos.append({"agente": e["agente"], "tool": None, "observation": {
                "modelo": e["modelo"], "tokens_entrada": e["tokens_entrada"],
                "tokens_salida": e["tokens_salida"], "latencia_ms": e["latencia_ms"],
                "pide": [p["nombre"] for p in e.get("pide", [])],
                **({"error": e["error"]} if e.get("error") else {"respuesta": e.get("respuesta")}),
            }})
        elif e["tipo"] == "herramienta":
            pasos.append({"agente": e["agente"], "tool": e["nombre"], "argumentos": e["argumentos"],
                          "observation": {"error": e["error"]} if e.get("error") else e.get("resultado")})
        elif e["tipo"] == "freno":
            pasos.append({"agente": e.get("agente"), "tool": None, "observation": {"freno": e["freno"]}})
    return pasos


def contextos_de(fragmentos: list[dict], respuesta: str, limite: int = MAX_CONTEXTOS) -> list[str]:
    """Fragmentos únicos, primero los que la respuesta cita, enteros y hasta el tope."""
    unicos = list({f["id"]: f for f in fragmentos}.values())
    unicos.sort(key=lambda f: not re.search(rf"\b{re.escape(f['id'])}\b", respuesta))
    salida: list[str] = []
    for f in unicos:
        texto = f"[{f['id']} · {f['fuente']}] {f['texto']}"
        if len(json.dumps(salida + [texto], ensure_ascii=False)) > limite:
            break
        salida.append(texto)
    return salida


class Sistema:
    """Se instancia sin argumentos, como pide el evaluador del laboratorio."""

    def __init__(self, revisor=None, **opciones):
        self._revisor = revisor or RevisorMultiagente(**opciones)

    def _sin_revision(self, answer: str, status: str) -> dict:
        return {"answer": answer, "informe": None, "status": status,
                "model": self._revisor._modelo_de("default"),
                "usage": {"tokens_entrada": 0, "tokens_salida": 0}, "trace": [], "contextos": []}

    def run(self, pregunta: str) -> dict:
        parches = parches_de(pregunta)
        if not parches:
            return self._sin_revision(ABSTENCION, "abstencion")
        if len(parches) > 1:
            nombres = ", ".join(str(p.relative_to(CARPETA_PARCHES)) for p in parches)
            return self._sin_revision(f"Nombraste más de un parche ({nombres}): ¿cuál reviso?", "aclaracion")
        r = self._revisor.run(str(parches[0]))
        status = _STATUS.get(r["status"], r["status"])
        if status == "error":
            answer = r["answer"][:MAX_RESPUESTA]
        else:
            answer = respuesta_corta(r.get("hallazgos", []), status)
        return {
            "answer": answer,
            "informe": r["answer"],
            "hallazgos": r.get("hallazgos", []),
            "status": status,
            "model": r["model"],
            "usage": r["usage"],
            "trace": pasos_de(r["trace"]),
            "contextos": contextos_de(r.get("contextos", []), answer),
        }
