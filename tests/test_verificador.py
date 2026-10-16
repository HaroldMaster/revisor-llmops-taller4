import pytest

from revisor.agentes.sintetizador import sin_procedencia
from revisor.agentes.verificador import comprobar_en_codigo, unir
from revisor.contexto import Contexto
from revisor.estado import Hallazgo
from revisor.traza import Traza

LINEA_REAL = "export class ErrorValidacion extends ErrorDominio {}"


def hallazgo(**cambios) -> Hallazgo:
    base = dict(
        id="h1", dimension="correctness", archivo="src/errores.ts", linea=8, severidad="medio",
        afirmacion="algo", evidencia=LINEA_REAL,
    )
    return Hallazgo(**{**base, **cambios})


@pytest.fixture()
def contexto(perfil, tmp_path):
    return Contexto(perfil, None, Traza(tmp_path, "prueba"), citas_devueltas={"R3"})


def test_unir_deja_uno_por_linea_y_dimension_y_prefiere_el_que_cita_regla():
    unidos = unir([
        hallazgo(id="a", severidad="critico"),
        hallazgo(id="b", cita_regla="R3"),
        hallazgo(id="c", linea=40),
    ])
    assert [h.id for h in unidos] == ["b", "c"]


def test_unir_no_mezcla_lineas_vecinas_ni_dimensiones_distintas():
    unidos = unir([
        hallazgo(id="any", linea=52, dimension="reglas"),
        hallazgo(id="console", linea=53, dimension="reglas"),
        hallazgo(id="lento", linea=53, dimension="eficiencia"),
    ])
    assert {h.id for h in unidos} == {"any", "console", "lento"}


def test_una_evidencia_literal_pasa_y_corrige_la_linea(contexto):
    comprobado = comprobar_en_codigo(hallazgo(linea=3), contexto)
    assert comprobado.veredicto == "pendiente"
    assert comprobado.linea == 8


def test_una_evidencia_inventada_se_descarta_sin_preguntar_a_un_modelo(contexto):
    comprobado = comprobar_en_codigo(hallazgo(evidencia="const total = precio * 1.15;"), contexto)
    assert comprobado.veredicto == "descartado"
    assert "copia literal" in comprobado.motivo_veredicto


DIFF_QUE_BORRA = """diff --git a/src/errores.ts b/src/errores.ts
--- a/src/errores.ts
+++ b/src/errores.ts
@@ -10,3 +10,2 @@
-export function viejo(): void {}
diff --git a/src/borrado.test.ts b/src/borrado.test.ts
--- a/src/borrado.test.ts
+++ /dev/null
@@ -1,1 +0,0 @@
-  it('rechaza cantidades que no son enteros positivos', () => {
"""


def test_la_evidencia_de_una_linea_que_el_diff_borra_pasa_y_conserva_la_linea(contexto):
    comprobado = comprobar_en_codigo(hallazgo(linea=10, evidencia="export function viejo(): void {}"),
                                     contexto, diff=DIFF_QUE_BORRA)
    assert (comprobado.veredicto, comprobado.linea) == ("pendiente", 10)


def test_un_archivo_borrado_entero_se_comprueba_contra_el_diff(contexto):
    test_borrado = hallazgo(archivo="src/borrado.test.ts", linea=1,
                            evidencia="it('rechaza cantidades que no son enteros positivos', () => {")
    assert comprobar_en_codigo(test_borrado, contexto, diff=DIFF_QUE_BORRA).veredicto == "pendiente"
    assert comprobar_en_codigo(test_borrado, contexto).veredicto == "descartado"


def test_lo_que_el_diff_borra_de_otro_archivo_no_vale_como_evidencia(contexto):
    otro = hallazgo(evidencia="it('rechaza cantidades que no son enteros positivos', () => {")
    assert comprobar_en_codigo(otro, contexto, diff=DIFF_QUE_BORRA).veredicto == "descartado"


def test_un_archivo_que_no_existe_se_descarta(contexto):
    assert comprobar_en_codigo(hallazgo(archivo="src/utilidades/x.ts"), contexto).veredicto == "descartado"


def test_un_hallazgo_de_reglas_con_una_cita_que_el_rag_no_devolvio_se_descarta(contexto):
    inventada = comprobar_en_codigo(hallazgo(dimension="reglas", cita_regla="MON-001"), contexto)
    real = comprobar_en_codigo(hallazgo(dimension="reglas", cita_regla="R3"), contexto)
    assert inventada.veredicto == "descartado"
    assert real.veredicto == "pendiente"


def test_en_otra_dimension_una_cita_invalida_se_borra_pero_el_hallazgo_sigue(contexto):
    comprobado = comprobar_en_codigo(hallazgo(cita_regla="R99"), contexto)
    assert (comprobado.veredicto, comprobado.cita_regla) == ("pendiente", None)


def test_el_informe_no_puede_mencionar_ubicaciones_ni_reglas_ajenas():
    hallazgos = [hallazgo(cita_regla="R3")]
    assert sin_procedencia("Problema en `src/errores.ts:8` (R3).", hallazgos) == []
    assert sin_procedencia("Ver src/errores.ts:8, src/otro.ts:5 y la regla R7.", hallazgos) == [
        "R7",
        "src/otro.ts:5",
    ]


def test_en_la_ablacion_sin_rag_ningun_prompt_nombra_la_herramienta_que_no_existe():
    from revisor.agentes.prompts import REVIEWERS, sin_rag

    for definicion in REVIEWERS.values():
        assert "buscar_reglas" not in sin_rag(definicion["sistema"])
