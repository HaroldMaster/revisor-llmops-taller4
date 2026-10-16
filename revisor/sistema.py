"""La puerta del Taller 4: Sistema().run(pregunta) con el contrato de la opción C.

La pregunta es texto libre que nombra el parche que se quiere revisar
("Revisa casos/C01.patch, por favor"). El revisor del Taller 3 recibe la ruta;
este adaptador la resuelve, corre el sistema y devuelve:

    answer     una línea por hallazgo, corta: el evaluador califica sus 600 primeros caracteres
    informe    el informe completo del sintetizador
    status     ok | abstencion | aclaracion | bloqueado | incompleto | error
    model      el id del modelo, leído del endpoint
    usage      tokens de entrada y salida, sumados sobre todos los agentes
    trace      un paso por acción: {"agente", "tool", "observation"}
    contextos  los fragmentos que devolvió buscar_reglas, completos
    guardrail  {"entrada": "ok|redactada|bloqueada", "salida": "ok|redactada|bloqueada"}
    traza_id   el id de la traza en Langfuse, para ir de una fila del CSV a sus spans
    prompt_version  la versión de los prompts con que corrió

La pregunta pasa por validar_entrada antes de buscar el parche, y la respuesta y el informe
por validar_salida antes de devolverse. Cada decisión es además un paso de la traza.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .agentes.prompts import VERSION as PROMPT_VERSION
from .config import RAIZ
from .guardrails import redactar_pii, validar_entrada, validar_salida
from .multiagente import RevisorMultiagente
from .observabilidad import atributos_de_corrida, flush, observacion

ABSTENCION = "No puedo responder con los datos disponibles."
CARPETA_PARCHES = RAIZ / "evaluacion"
MAX_RESPUESTA = 600
# El evaluador guarda json.dumps(contextos)[:8000]: si se pasa, el JSON queda cortado
# y RAGAS no lo puede leer. Se entregan fragmentos enteros hasta este tope.
MAX_CONTEXTOS = 7500

_PARCHE = re.compile(r"[\w./-]+\.patch\b")
_STATUS = {"completed": "ok", "incompleto": "incompleto", "failed": "error"}
_ORDEN = {"critico": 0, "alto": 1, "medio": 2}
_REGLA_DEL_REPO = re.compile(r"R\d+")


def parches_de(pregunta: str) -> list[Path]:
    """Los parches que la pregunta nombra y que existen dentro de evaluacion/."""
    encontrados = []
    for nombre in dict.fromkeys(_PARCHE.findall(pregunta or "")):
        ruta = (CARPETA_PARCHES / nombre).resolve()
        if ruta.is_relative_to(CARPETA_PARCHES) and ruta.is_file() and ruta not in encontrados:
            encontrados.append(ruta)
    return encontrados


def por_regla(grupo: list[dict]) -> list[list[dict]]:
    """Los hallazgos de una ubicación, uno por regla del repo citada; los que no citan una regla
    del repo van con el primero. Cada parte conserva el orden de severidad del grupo."""
    partes: dict[str, list[dict]] = {}
    sin_regla = []
    for h in grupo:
        cita = h.get("cita_regla") or ""
        if _REGLA_DEL_REPO.fullmatch(cita):
            partes.setdefault(cita, []).append(h)
        else:
            sin_regla.append(h)
    if not partes:
        return [sin_regla]
    divididas = list(partes.values())
    divididas[0] = sorted(divididas[0] + sin_regla, key=grupo.index)
    return sorted(divididas, key=lambda parte: grupo.index(parte[0]))


def respuesta_corta(hallazgos: list[dict], status: str, limite: int = MAX_RESPUESTA) -> str:
    """Una línea por problema con hallazgos vigentes, de más a menos grave.

    Los hallazgos de una misma ubicación se juntan, salvo que citen reglas distintas del repo: R10
    (código sin uso) y R6 (falta el test) en la misma línea son dos problemas, y juntarlos dejaba
    solo la explicación del primero (C09 en la medición base)."""
    vigentes = [h for h in hallazgos if h.get("veredicto") != "descartado"]
    if not vigentes:
        return "Sin hallazgos." if status == "ok" else "La revisión se cortó antes de terminar y no dejó hallazgos."
    por_lugar: dict[tuple, list[dict]] = {}
    for h in sorted(vigentes, key=lambda h: (_ORDEN.get(h["severidad"], 9), h["archivo"], h["linea"])):
        por_lugar.setdefault((h["archivo"], h["linea"]), []).append(h)
    grupos = [((archivo, linea), parte) for (archivo, linea), del_lugar in por_lugar.items() for parte in por_regla(del_lugar)]
    lineas = []
    for (archivo, linea), grupo in grupos:
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
        elif e["tipo"] == "guardrail":
            pasos.append({"agente": e.get("agente"), "tool": None, "observation": {
                "guardrail": e["nombre"], "decision": e["decision"], "motivo": e["motivo"],
                "latencia_ms": e["latencia_ms"]}})
        elif e["tipo"] == "freno":
            pasos.append({"agente": e.get("agente"), "tool": None, "observation": {"freno": e["freno"]}})
    return pasos


def aplicar_guardrail(validador, canal: str, texto: str) -> tuple[bool, str, str, dict]:
    """Corre un validador y devuelve (ok, texto, decisión para el evaluador, paso de la traza)."""
    with observacion(f"validar_{canal}", "guardrail", input=texto) as span:
        inicio = time.perf_counter()
        ok, resultado = validador(texto)
        decision = "bloqueada" if not ok else ("redactada" if resultado != texto else "ok")
        span.update(output={"decision": decision, "texto": resultado})
    # agente=None: el paso existe, pero el evaluador no lo cuenta como un agente más.
    paso = {"agente": None, "tool": None, "observation": {
        "guardrail": canal, "decision": decision, "motivo": None if ok else resultado,
        "latencia_ms": round((time.perf_counter() - inicio) * 1000, 3)}}
    return ok, resultado, decision, paso


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

    def _sin_revision(self, answer: str, status: str, entrada: str, paso: dict) -> dict:
        return {"answer": answer, "informe": None, "status": status,
                "model": self._revisor._modelo_de("default"),
                "usage": {"tokens_entrada": 0, "tokens_salida": 0}, "trace": [paso], "contextos": [],
                "guardrail": {"entrada": entrada, "salida": "ok"}}

    def run(self, pregunta: str) -> dict:
        """La raíz de la traza envuelve los guardrails, y se cierra aunque algo adentro lance."""
        try:
            with atributos_de_corrida(PROMPT_VERSION), observacion("revisor", "agent", input=pregunta) as raiz:
                r = self._revisar(pregunta)
                raiz.update(output=r["answer"], metadata={
                    "status": r["status"], "guardrail": r["guardrail"], "modelo": r["model"], "usage": r["usage"],
                })
        finally:
            flush()
        return {**r, "traza_id": raiz.trace_id, "prompt_version": PROMPT_VERSION}

    def _revisar(self, pregunta: str) -> dict:
        ok, pregunta, entrada, paso_entrada = aplicar_guardrail(validar_entrada, "entrada", pregunta)
        if not ok:
            return self._sin_revision(f"{ABSTENCION} {pregunta}", "bloqueado", entrada, paso_entrada)
        parches = parches_de(pregunta)
        if not parches:
            return self._sin_revision(ABSTENCION, "abstencion", entrada, paso_entrada)
        if len(parches) > 1:
            nombres = ", ".join(str(p.relative_to(CARPETA_PARCHES)) for p in parches)
            return self._sin_revision(
                f"Nombraste más de un parche ({nombres}): ¿cuál reviso?", "aclaracion", entrada, paso_entrada
            )
        r = self._revisor.run(str(parches[0]))
        status = _STATUS.get(r["status"], r["status"])
        if status == "error":
            answer = r["answer"][:MAX_RESPUESTA]
        else:
            answer = respuesta_corta(r.get("hallazgos", []), status)
        ok_respuesta, answer, salida, paso_salida = aplicar_guardrail(validar_salida, "salida", answer)
        ok_informe, informe, _, _ = aplicar_guardrail(validar_salida, "informe", r["answer"])
        if not ok_informe and ok_respuesta:
            salida = "bloqueada"
        return {
            "answer": answer,
            "informe": informe,
            "hallazgos": json.loads(redactar_pii(json.dumps(r.get("hallazgos", []), ensure_ascii=False)))
            if ok_respuesta and ok_informe else [],
            "status": status,
            "model": r["model"],
            "usage": r["usage"],
            "trace": [paso_entrada, *pasos_de(r["trace"]), paso_salida],
            "contextos": contextos_de(r.get("contextos", []), answer) if ok_respuesta else [],
            "guardrail": {"entrada": entrada, "salida": salida},
        }
