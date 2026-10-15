"""Los tres guardrails del Taller 4.

1. Inyección de instrucciones: en la pregunta bloquea; en las líneas que añade el parche avisa,
   porque bloquear ahí sería dejar sin revisar justo el parche que más lo necesita.
2. Datos personales (correo, cédula, teléfono): se redactan en la entrada, en la salida y en
   cada línea de la traza antes de escribirla.
3. correr_checks, la única herramienta que ejecuta algo: solo corre si el parche toca archivos
   de la lista de permitidos, sin APIs que ejecuten, borren o salgan a la red, y hasta un tope.

Contrato de validar_entrada y validar_salida, el de probar_guardrails.py del laboratorio:
`f(texto) -> (ok, texto_resultante)`. ok=False bloquea; ok=True con otro texto redacta.
"""

from __future__ import annotations

import re
import threading
import unicodedata

MAX_CHECKS_POR_CORRIDA = 8
PERMITIDOS_EXTRA = ("*.md",)


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes, sin caracteres invisibles ni puntuación, espacios simples."""
    descompuesto = unicodedata.normalize("NFKD", texto or "")
    limpio = "".join(c for c in descompuesto if unicodedata.category(c) not in ("Mn", "Cf"))
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", limpio.lower()).split())


def _alternativas(*palabras: str) -> str:
    return "|".join(palabras)


_ANULAR = _alternativas(
    "ignora", "ignore", "olvida", "olvidate de", "forget", "omite", "descarta", "desobedece",
    "disregard", "saltate", "bypass", "pasa por alto", "no sigas", "deja de seguir",
)
_INSTRUCCIONES = _alternativas(
    "instrucciones", "instruccion", "indicaciones", "reglas", "restricciones", "directrices",
    "politicas", "prompt", "instructions", "rules", "guidelines",
)
_PERSONA = _alternativas(
    "actua", "actuar", "actues", "comportate", "finge", "eres", "seras", "act", "pretend", "you are",
)
_SIN_LIMITES = _alternativas(
    "restricciones", "reglas", "limites", "filtros", "censura", "restrictions", "rules", "limits", "filters",
)
_PEDIR = _alternativas(
    "dame", "dime", "muestrame", "muestra", "imprime", "revela", "traduce", "copia", "pega", "repite",
    "escribe", "envia", "manda", "exporta", "reveal", "print", "show", "give me", "repeat",
    "translate", "send", "dump", "cat",
)
_PROMPT = _alternativas(
    "system prompt", "prompt del sistema", "mensaje del sistema", "instrucciones del sistema",
    "instrucciones internas", "reglas internas", "tus reglas", "tus instrucciones", "tu prompt",
    "tu configuracion", "your instructions", "your rules",
)
# Para secretos el verbo tiene que ser de entrega, y el objeto, uno que el revisor no audita:
# «dime si el token se valida» es una pregunta de revisión, no una extracción.
_ENTREGAR = _alternativas(
    "dame", "muestrame", "muestra", "imprime", "revela", "copia", "pega", "envia", "manda", "exporta",
    "reveal", "print", "show", "give me", "send", "dump", "cat",
)
_SECRETO = _alternativas(
    "clave de la api", "clave de api", "api key", "apikey", "credenciales", "contrasena", "password",
    "env", "variables de entorno",
)
_SILENCIAR = _alternativas("no reportes", "no informes", "no menciones", "no senales", "do not report")
_HALLAZGOS = _alternativas("hallazgos", "hallazgo", "problemas", "findings", "issues")

# Cada intención es una forma de pedir lo mismo; se busca la intención, no la frase.
INTENCIONES = {
    "anular_instrucciones": rf"\b(?:{_ANULAR})\b(?:\s+\w+){{0,3}}\s+(?:{_INSTRUCCIONES})\b",
    "quitar_restricciones": rf"\b(?:{_PERSONA})\b(?:\s+\w+){{0,5}}\s+(?:sin|no tuvieras|no tienes|without)"
                            rf"(?:\s+\w+){{0,2}}\s+(?:{_SIN_LIMITES})\b",
    "cambiar_de_rol": r"\b(?:you are now|desde ahora eres|a partir de ahora eres|ahora eres)\b",
    "extraer_prompt": rf"\b(?:{_PEDIR})\b(?:\s+\w+){{0,5}}\s+(?:{_PROMPT})\b",
    "pedir_secretos": rf"\b(?:{_ENTREGAR})\b(?:\s+\w+){{0,6}}\s+(?:{_SECRETO})\b",
    "aprobar_sin_revisar": rf"\b(?:{_SILENCIAR})\b(?:\s+\w+){{0,3}}\s+(?:{_HALLAZGOS})\b"
                           r"|\bresponde\b(?:\s+\w+){0,2}\s+que no hay\b",
}
_INTENCIONES = {nombre: re.compile(patron) for nombre, patron in INTENCIONES.items()}


def detectar_inyeccion(texto: str) -> str | None:
    """La primera intención de inyección que aparece en el texto, o None."""
    normal = normalizar(texto)
    return next((nombre for nombre, patron in _INTENCIONES.items() if patron.search(normal)), None)


# Sin letra, dígito ni guion pegados: así no se toman pedazos de fechas, hashes, UUID ni
# rutas con número de línea.
_BORDE_IZQ, _BORDE_DER = r"(?<![\w-])", r"(?![\w-])"
_PII = [
    ("[CORREO]", re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[a-zA-Z]{2,}\b")),
    # Celular 09XXXXXXXX o +593 9XXXXXXXX, y fijo 0[2-7]XXXXXXX, con espacios o guiones opcionales.
    ("[TELEFONO]", re.compile(_BORDE_IZQ + r"(?:(?:\+593[\s-]?|0)9\d(?:[\s-]?\d){7}"
                              r"|(?:\+593[\s-]?|0)[2-7][\s-]?\d{3}[\s-]?\d{4})" + _BORDE_DER)),
    # Cédula: provincia 01-24 o 30 y tercer dígito menor que 6. No se exige el dígito
    # verificador: una cédula mal copiada también es un dato personal.
    ("[CEDULA]", re.compile(_BORDE_IZQ + r"(?:0[1-9]|1\d|2[0-4]|30)[0-5]\d{7}" + _BORDE_DER)),
]


def redactar_pii(texto: str) -> str:
    for marca, patron in _PII:
        texto = patron.sub(marca, texto)
    return texto


# Claves por su forma (prefijo o asignación), no por su longitud: un hash o un UUID pasan.
_CLAVES = re.compile(
    r"\b(?:sk-(?:proj-|lf-)?|pk-lf-)[A-Za-z0-9_-]{16,}"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|\bgh[pousr]_[A-Za-z0-9]{30,}"
    r"|\bxox[abpr]-[A-Za-z0-9-]{10,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\b[A-Z][A-Z0-9_]*(?:API_KEY|SECRET|TOKEN|PASSWORD)[A-Z0-9_]*\s*[=:]\s*['\"]?[^\s'\"]{8,}"
)


def detectar_clave(texto: str) -> bool:
    return _CLAVES.search(texto or "") is not None


def redactar_claves(texto: str) -> str:
    return _CLAVES.sub("[CLAVE]", texto)


def validar_entrada(texto: str) -> tuple[bool, str]:
    intencion = detectar_inyeccion(texto)
    if intencion:
        return False, f"Solicitud rechazada por el guardrail de inyección ({intencion})."
    return True, redactar_pii(texto)


def validar_salida(texto: str) -> tuple[bool, str]:
    if detectar_clave(texto):
        return False, "Respuesta retenida por el guardrail de salida: contenía una credencial."
    return True, redactar_pii(texto)


def archivos_tocados(diff: str) -> list[str]:
    rutas = re.findall(r"^(?:\+\+\+ b/|--- a/|rename (?:from|to) |copy (?:from|to) )(.+)$", diff, re.MULTILINE)
    return list(dict.fromkeys(r.strip() for r in rutas))


_EJECUTA = re.compile(
    r"child_process|\bexec(?:Sync|File)?\s*\(|\bspawn(?:Sync)?\s*\(|\bprocess\.env\b|\brequire\s*\("
    r"|\bimport\s*\(|\beval\s*\(|new\s+Function\b|\bfetch\s*\(|\bhttps?\.(?:request|get)\b"
    r"|\bnet\.connect\b|\bfs\.(?:rm|rmdir|unlink|write)\w*|\b(?:rm|rmdir|unlink|write)\w*Sync\b"
)


def coincide(ruta: str, patron: str) -> bool:
    """Glob con la semántica de Path.glob del perfil: «**/» es cero o más carpetas y «*» no cruza «/».
    fnmatch no sirve aquí: para él «src/**/*.ts» no incluye «src/index.ts»."""
    partes = re.split(r"(\*\*/|\*|\?)", patron)
    traducido = {"**/": "(?:.*/)?", "*": "[^/]*", "?": "[^/]"}
    return re.fullmatch("".join(traducido.get(p, re.escape(p)) for p in partes), ruta) is not None


def motivo_para_no_ejecutar(diff: str, permitidos: tuple[str, ...]) -> str | None:
    """Por qué no se deben correr los checks sobre este parche, o None si se pueden correr.

    Los checks ejecutan código que el parche controla: la configuración de eslint, vitest o tsc,
    el propio perfil.toml que define los comandos, y cada test. Por eso se permite solo lo que
    está en la lista y sin llamadas que ejecuten, borren o salgan a la red."""
    fuera = [r for r in archivos_tocados(diff) if not any(coincide(r, p) for p in permitidos)]
    if fuera:
        return f"el parche toca archivos fuera de la lista de permitidos: {', '.join(fuera)}"
    for linea in diff.splitlines():
        if linea.startswith("+") and not linea.startswith("+++") and _EJECUTA.search(linea):
            return f"el parche añade una llamada que ejecuta, borra o sale a la red: {linea[1:].strip()[:120]}"
    return None


class GuardaChecks:
    """La decisión sobre correr_checks en una corrida. La comparten los agentes, que corren en hilos."""

    def __init__(self, diff: str, permitidos: tuple[str, ...], tope: int = MAX_CHECKS_POR_CORRIDA):
        self.motivo = motivo_para_no_ejecutar(diff, permitidos + PERMITIDOS_EXTRA)
        self.tope = tope
        self.corridos = 0
        self._candado = threading.Lock()

    def decidir(self) -> tuple[str, str | None]:
        with self._candado:
            if self.motivo:
                return "bloquear", self.motivo
            if self.corridos >= self.tope:
                return "bloquear", f"se alcanzó el tope de {self.tope} checks por corrida"
            self.corridos += 1
            return "permitir", None
