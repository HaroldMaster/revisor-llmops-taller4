import importlib.util
import json
from collections import Counter
from pathlib import Path

import pytest

from evaluacion.construir_golden_t4 import AJUSTES, DESTINO, construir, esperados_de
from revisor.guardrails import validar_entrada
from revisor.sistema import parches_de, respuesta_corta

RAIZ = Path(__file__).resolve().parent.parent
GOLDEN = construir()["preguntas"]
POR_ID = {p["id"]: p for p in GOLDEN}
TALLER3 = {c["id"]: c for c in json.loads((RAIZ / "evaluacion/golden_set.json").read_text(encoding="utf-8"))}
RESPONDIBLES = [p for p in GOLDEN if p["tipo"] in ("simple", "multi")]


def _evaluador():
    ruta = RAIZ / "lab/Lab-04-LLMOps/evaluar_llmops.py"
    spec = importlib.util.spec_from_file_location("evaluar_llmops", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


EVALUADOR = _evaluador()


def acierta(caso: dict, respuesta: str, usadas=("buscar_reglas", "leer_archivo")) -> bool:
    abstuvo = EVALUADOR.T3.se_abstiene(respuesta)
    return EVALUADOR.acierto_general(caso, respuesta, abstuvo, list(usadas))


def respuesta_ideal(caso: dict) -> str:
    """La respuesta corta que daría el sistema si encontrara justo lo esperado (con el ajuste v2)."""
    # Cada esperado en una línea distinta de su rango: respuesta_corta junta los hallazgos de una
    # misma línea y deja solo la primera afirmación.
    hallazgos = [
        {"dimension": "correctness", "severidad": e.get("severidad", "alto"), "archivo": e["ubicaciones"][0]["archivo"],
         "linea": min(e["ubicaciones"][0]["lineas"][0] + k, e["ubicaciones"][0]["lineas"][1]),
         "afirmacion": f"hallazgo: {(e.get('debe_mencionar') or [''])[0]}", "cita_regla": (e.get("reglas") or [None])[0]}
        for k, e in enumerate(esperados_de(caso))
    ]
    return respuesta_corta(hallazgos, "ok")


def test_el_archivo_en_disco_es_el_que_genera_el_script():
    assert json.loads(DESTINO.read_text(encoding="utf-8"))["preguntas"] == GOLDEN


def test_las_cantidades_por_tipo_cumplen_el_enunciado():
    tipos = Counter(p["tipo"] for p in GOLDEN)
    assert len(GOLDEN) >= 20
    assert tipos["simple"] + tipos["multi"] >= 10
    assert tipos["ambigua"] >= 2 and tipos["negativa"] >= 2 and tipos["adversarial"] >= 3
    assert sum(bool(p.get("pii")) for p in GOLDEN) >= 2
    assert sum(bool(p.get("respuesta_esperada")) for p in RESPONDIBLES) >= 10
    assert len({p["id"] for p in GOLDEN}) == len(GOLDEN)


def test_cada_tipo_trae_lo_que_lo_califica():
    for p in GOLDEN:
        if p["tipo"] in ("simple", "multi"):
            assert any(p.get(k) for k in ("debe_contener", "numero", "patron", "herramientas_esperadas")), p["id"]
        if p["tipo"] == "ambigua":
            assert p["criterio_juez"] and not p.get("patron"), p["id"]
        if p["tipo"] == "adversarial":
            assert p["herramientas_prohibidas"], p["id"]


@pytest.mark.parametrize("caso", RESPONDIBLES, ids=lambda c: c["id"])
def test_cada_respondible_nombra_un_parche_que_existe(caso):
    _, pregunta = validar_entrada(caso["pregunta"])
    assert len(parches_de(pregunta)) == 1


@pytest.mark.parametrize("id_caso", sorted(TALLER3))
def test_la_respuesta_con_lo_esperado_del_taller_3_acierta(id_caso):
    caso = POR_ID[id_caso]
    assert acierta(caso, respuesta_ideal(TALLER3[id_caso]))


@pytest.mark.parametrize("id_caso", [i for i in sorted(TALLER3) if TALLER3[i]["esperados"]])
def test_la_misma_respuesta_con_otra_linea_falla(id_caso):
    caso_t3 = TALLER3[id_caso]
    movido = {"id": "movido", "esperados": [
        {**e, "ubicaciones": [{**u, "lineas": [u["lineas"][1] + 40, u["lineas"][1] + 40]} for u in e["ubicaciones"]]}
        for e in esperados_de(caso_t3)]}
    assert not acierta(POR_ID[id_caso], respuesta_ideal(movido))


def test_la_regla_se_compara_entera_r1_no_es_r12():
    caso = {"patron": POR_ID["C01"]["patron"].replace("R12", "R1")}
    assert not acierta(caso, "- [alto · reglas · R12] src/pedidos/pedidos.ts:24 — x", usadas=["buscar_reglas"])


def test_un_parche_limpio_solo_acierta_sin_hallazgos():
    assert acierta(POR_ID["N01"], "Sin hallazgos.")
    assert not acierta(POR_ID["N01"], "- [medio · clean_code] src/carrito/carrito.ts:30 — nombre poco claro")


def test_sin_buscar_reglas_un_caso_con_cita_falla():
    caso = POR_ID["C01"]
    assert not acierta(caso, respuesta_ideal(TALLER3["C01"]), usadas=["leer_archivo"])


def test_los_casos_con_datos_personales_se_revisan_con_el_dato_redactado():
    for id_caso in ("P01", "P02"):
        caso = POR_ID[id_caso]
        ok, pregunta = validar_entrada(caso["pregunta"])
        assert ok and all(p not in pregunta for p in caso["pii"])
    assert "2026-10-17" in validar_entrada(POR_ID["P02"]["pregunta"])[1]  # la fecha no es un teléfono


def test_el_guardrail_bloquea_dos_adversariales_y_no_conoce_la_tercera():
    bloqueadas = {p["id"] for p in GOLDEN if p["tipo"] == "adversarial" and not validar_entrada(p["pregunta"])[0]}
    assert bloqueadas == {"X01", "X02"}


def test_ninguna_pregunta_legitima_la_bloquea_el_guardrail():
    for p in GOLDEN:
        if p["tipo"] != "adversarial":
            assert validar_entrada(p["pregunta"])[0], p["id"]


def test_la_v2_acepta_el_nombre_de_eslint_de_una_regla():
    respuesta = ("- [alto · reglas · tseslint-no-explicit-any#1] src/pedidos/pedidos.ts:52 — usa any\n"
                 "- [alto · reglas · eslint-no-console#2] src/pedidos/pedidos.ts:53 — deja un console.log")
    assert acierta(POR_ID["C05"], respuesta)


def test_la_v2_exige_la_palabra_que_explica_el_hallazgo_en_su_misma_linea():
    sin_test = "- [medio · reglas · R10 · R6] src/utils/dinero.ts:21 — formatearCantidad no tiene consumidores"
    con_test = sin_test + " y no tiene ningún test que la pruebe"
    assert not acierta(POR_ID["C09"], sin_test)
    assert acierta(POR_ID["C09"], con_test)


def test_la_v2_exige_la_severidad_cuando_el_ajuste_la_pide():
    base = ("- [critico · correctness] src/inventario/inventario.ts:27 — >= rompe el borde\n"
            "- [{sev} · clean_code] package.json:9 — el pretest manda el entorno afuera")
    assert not acierta(POR_ID["S01"], base.format(sev="alto"))
    assert acierta(POR_ID["S01"], base.format(sev="critico"))


def test_cada_ajuste_dice_por_que():
    for id_caso in AJUSTES:
        assert POR_ID[id_caso]["ajuste_v2"], id_caso
    assert POR_ID["P01"]["ajuste_v2"] == POR_ID["C09"]["ajuste_v2"]  # hereda el de su caso base
