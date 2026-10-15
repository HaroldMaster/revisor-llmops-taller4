import json
from pathlib import Path

from evaluacion.guion import ModeloDeGuion, pide, responde
from revisor.baseline import RevisorUnico
from revisor.sistema import (
    ABSTENCION, MAX_CONTEXTOS, MAX_RESPUESTA, Sistema, contextos_de, parches_de, respuesta_corta,
)

HALLAZGO = {
    "dimension": "reglas",
    "archivo": "src/pedidos/pedidos.ts",
    "linea": 24,
    "severidad": "alto",
    "afirmacion": "El impuesto se calcula antes del descuento.",
    "evidencia": "const impuestoCentavos = Math.round(subtotalCentavos * 0.15);",
    "cita_regla": "R12",
}


def sistema(modelo, embeddings, tmp_path):
    revisor = RevisorUnico(
        llm_de=lambda rol: modelo, modelo_de=lambda rol: "guion",
        embeddings=embeddings, carpeta_trazas=tmp_path,
    )
    return Sistema(revisor=revisor)


def test_resuelve_el_parche_nombrado_dentro_de_evaluacion():
    assert [p.name for p in parches_de("Revisa casos/C01.patch, por favor")] == ["C01.patch"]
    assert parches_de("Revisa ../../etc/passwd.patch") == []
    assert parches_de("Revisa casos/NO_EXISTE.patch") == []
    assert parches_de("¿Cuánto vendió la tienda en marzo?") == []


def test_sin_parche_se_abstiene_sin_llamar_al_modelo(embeddings, tmp_path):
    modelo = ModeloDeGuion([])
    r = sistema(modelo, embeddings, tmp_path).run("¿Cuánto vendió la tienda en marzo?")
    assert r["answer"] == ABSTENCION
    assert r["status"] == "abstencion"
    assert [p["observation"]["guardrail"] for p in r["trace"]] == ["entrada"]
    assert r["usage"] == {"tokens_entrada": 0, "tokens_salida": 0}
    assert modelo.mensajes_recibidos == []


def test_dos_parches_piden_aclaracion(embeddings, tmp_path):
    r = sistema(ModeloDeGuion([]), embeddings, tmp_path).run("Revisa casos/C01.patch y casos/C02.patch")
    assert r["status"] == "aclaracion"
    assert "casos/C01.patch" in r["answer"] and "casos/C02.patch" in r["answer"]


def test_run_cumple_el_contrato_de_la_opcion_c(embeddings, tmp_path):
    modelo = ModeloDeGuion(
        [pide("buscar_reglas", pregunta="cómo se calcula el impuesto"), responde("Hay un problema.")],
        estructurados=[{"hallazgos": [HALLAZGO]}],
    )
    r = sistema(modelo, embeddings, tmp_path).run("Revisa casos/C01.patch")

    assert set(r) >= {"answer", "status", "model", "usage", "trace", "contextos"}
    assert r["status"] == "ok"
    assert "src/pedidos/pedidos.ts:24" in r["answer"] and "R12" in r["answer"]
    assert len(r["answer"]) <= MAX_RESPUESTA
    assert r["informe"].startswith("## Informe de review")

    herramientas = [p for p in r["trace"] if p["tool"]]
    assert herramientas[0] == {**herramientas[0], "agente": "reviewer_unico", "tool": "buscar_reglas"}
    assert all("agente" in p and "observation" in p for p in r["trace"])
    assert r["contextos"] and all(isinstance(c, str) for c in r["contextos"])
    json.dumps(r, ensure_ascii=False)


def test_sin_buscar_reglas_no_hay_contextos(embeddings, tmp_path):
    modelo = ModeloDeGuion([responde("Nada que decir.")], estructurados=[{"hallazgos": []}])
    r = sistema(modelo, embeddings, tmp_path).run("Revisa casos/N01.patch")
    assert r["answer"] == "Sin hallazgos."
    assert r["contextos"] == []


def test_un_fallo_devuelve_status_error_con_el_motivo(embeddings, tmp_path):
    r = sistema(ModeloDeGuion([]), embeddings, tmp_path).run("Revisa casos/C01.patch")
    assert r["status"] == "error"
    assert r["answer"].startswith("La revisión no terminó")


def test_respuesta_corta_une_por_ubicacion_y_no_pasa_del_limite():
    otro = {**HALLAZGO, "dimension": "clean_code"}
    descartado = {**HALLAZGO, "linea": 3, "veredicto": "descartado"}
    texto = respuesta_corta([HALLAZGO, otro, descartado], "ok")
    assert texto.count("pedidos.ts:24") == 1 and "pedidos.ts:3" not in texto
    assert "reglas · clean_code · R12" in texto

    muchos = [{**HALLAZGO, "linea": n, "afirmacion": "x" * 300} for n in range(1, 8)]
    largo = respuesta_corta(muchos, "ok")
    assert len(largo) <= MAX_RESPUESTA
    assert all(f"pedidos.ts:{n} " in largo for n in range(1, 8))


def test_contextos_unicos_primero_los_citados_y_json_entero():
    fragmentos = [{"id": f"R{n}", "fuente": "CLAUDE.md", "texto": "t" * 1200} for n in range(1, 12)]
    fragmentos.append(fragmentos[0])
    salida = contextos_de(fragmentos, "regla R9 incumplida")
    assert salida[0].startswith("[R9 ")
    assert len(salida) == len(set(salida))
    assert len(json.dumps(salida, ensure_ascii=False)) <= MAX_CONTEXTOS
