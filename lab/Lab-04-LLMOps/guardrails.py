"""
Lab 04 — Guardrails baseline.

Estos controles son simples por diseño. Sirven como punto de partida para medir
falsos positivos, falsos negativos y costo operacional.
"""

from __future__ import annotations

import re


INJECTION_PATTERNS = [
    r"ignore (all )?(previous|prior) instructions",
    r"olvida (todas )?(las )?instrucciones",
    r"revela (el )?(system prompt|prompt del sistema)",
    r"you are now",
    r"actua como si no tuvieras restricciones",
]

EMAIL_RE = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s\-\(\)]{7,}\d)(?!\d)")
SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-]{20,}|[A-Za-z0-9_\-]{32,})")


def detect_prompt_injection(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in INJECTION_PATTERNS)


def redact_pii(text: str) -> str:
    text = EMAIL_RE.sub("[EMAIL_REDACTADO]", text)
    text = PHONE_RE.sub("[TELEFONO_REDACTADO]", text)
    return text


def detect_secret_leak(text: str) -> bool:
    return SECRET_RE.search(text) is not None


def validate_input(text: str) -> tuple[bool, str]:
    if detect_prompt_injection(text):
        return False, "Solicitud rechazada por posible prompt injection."
    return True, redact_pii(text)


def validate_output(text: str) -> tuple[bool, str]:
    if detect_secret_leak(text):
        return False, "Salida bloqueada por posible filtracion de credenciales."
    return True, text
