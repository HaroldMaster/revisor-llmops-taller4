import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from evaluacion.guion import ModeloDeGuion, pide, responde
from revisor import observabilidad
from revisor.agentes.prompts import VERSION
from revisor.baseline import RevisorUnico
from revisor.observabilidad import en_hilo, observacion
from revisor.sistema import Sistema


@pytest.fixture(scope="module")
def exportador():
    exportador = InMemorySpanExporter()
    observabilidad.configurar(public_key="pk-lf-prueba", secret_key="sk-lf-prueba",
                              base_url="http://127.0.0.1:9", span_exporter=exportador)
    yield exportador
    observabilidad._cliente = None  # los demás tests vuelven al no-op


@pytest.fixture()
def spans(exportador):
    exportador.clear()

    def finalizados():
        observabilidad.flush()
        return exportador.get_finished_spans()

    return finalizados


def tipo(span):
    return span.attributes.get("langfuse.observation.type")


def sistema(modelo, embeddings, tmp_path):
    return Sistema(revisor=RevisorUnico(llm_de=lambda rol: modelo, modelo_de=lambda rol: "guion",
                                        embeddings=embeddings, carpeta_trazas=tmp_path))


def hallazgo(afirmacion):
    return {"dimension": "reglas", "archivo": "src/pedidos/pedidos.ts", "linea": 24, "severidad": "alto",
            "afirmacion": afirmacion, "evidencia": "const impuestoCentavos = 0;", "cita_regla": None}


def correr(embeddings, tmp_path, pregunta="Revisa casos/C01.patch", afirmacion="El impuesto va antes."):
    modelo = ModeloDeGuion(
        [pide("buscar_reglas", pregunta="impuesto"), pide("leer_archivo", ruta="src/nada.ts"), responde("listo")],
        estructurados=[{"hallazgos": [hallazgo(afirmacion)]}],
    )
    return sistema(modelo, embeddings, tmp_path).run(pregunta)


def test_una_corrida_es_una_traza_con_su_raiz_y_un_span_por_cada_cosa(spans, embeddings, tmp_path):
    r = correr(embeddings, tmp_path)
    todos = spans()
    raices = [s for s in todos if s.parent is None]
    assert [s.name for s in raices] == ["revisor"]
    assert {format(s.context.trace_id, "032x") for s in todos} == {r["traza_id"]}
    por_tipo = {}
    for s in todos:
        por_tipo.setdefault(tipo(s), []).append(s.name)
    assert por_tipo["agent"] == ["reviewer_unico", "revisor"]
    assert por_tipo["retriever"] == ["buscar_reglas"]
    assert por_tipo["tool"] == ["leer_archivo"]
    assert set(por_tipo["generation"]) == {"reviewer_unico"} and len(por_tipo["generation"]) == 4
    assert por_tipo["guardrail"] == [
        "validar_entrada", "lista_de_permitidos", "inyeccion_en_parche", "validar_salida", "validar_informe",
    ]


def test_la_raiz_lleva_sesion_etiqueta_y_version_de_prompt(spans, embeddings, tmp_path, monkeypatch):
    monkeypatch.setenv("LANGFUSE_SESION", "harold-flores-prueba")
    monkeypatch.setenv("LANGFUSE_ETIQUETA", "taller-04")
    r = correr(embeddings, tmp_path)
    raiz = next(s for s in spans() if s.parent is None)
    assert raiz.attributes["session.id"] == "harold-flores-prueba"
    assert tuple(raiz.attributes["langfuse.trace.tags"]) == ("taller-04",)
    assert raiz.attributes["langfuse.trace.metadata.prompt_version"] == r["prompt_version"] == VERSION


def test_la_duracion_de_la_raiz_incluye_los_guardrails(spans, embeddings, tmp_path):
    correr(embeddings, tmp_path)
    todos = {s.name: s for s in spans()}
    raiz = todos["revisor"]
    assert raiz.start_time <= todos["validar_entrada"].start_time
    assert raiz.end_time >= todos["validar_informe"].end_time


def test_la_raiz_se_escribe_aunque_el_agente_lance(spans):
    class Revienta:
        def run(self, _):
            raise RuntimeError("el modelo no responde")

        def _modelo_de(self, _):
            return "guion"

    with pytest.raises(RuntimeError):
        Sistema(revisor=Revienta()).run("Revisa casos/C01.patch")
    raiz = next(s for s in spans() if s.parent is None)
    assert raiz.attributes["langfuse.observation.level"] == "ERROR"
    assert "el modelo no responde" in raiz.attributes["langfuse.observation.status_message"]


def test_un_error_de_herramienta_deja_su_span_en_error(spans, embeddings, tmp_path):
    correr(embeddings, tmp_path)
    herramienta = next(s for s in spans() if s.name == "leer_archivo")
    assert herramienta.attributes["langfuse.observation.level"] == "ERROR"
    assert "No existe el archivo" in herramienta.attributes["langfuse.observation.status_message"]


def test_ni_datos_personales_ni_claves_llegan_a_los_spans(spans, embeddings, tmp_path):
    clave = "sk-proj-EJEMPLO-NO-ES-UNA-CLAVE-000000000000"
    correr(embeddings, tmp_path, pregunta="Soy ana.perez@mail.com, cédula 1712345678: revisa casos/C01.patch",
           afirmacion=f"Llama al 0991234567; quedó la clave {clave}")
    exportado = json.dumps([dict(s.attributes) for s in spans()], ensure_ascii=False, default=str)
    for prohibido in ("ana.perez@mail.com", "1712345678", "0991234567", clave):
        assert prohibido not in exportado
    assert "[CORREO]" in exportado and "[CLAVE]" in exportado


def test_la_mascara_recorre_tuplas():
    assert observabilidad.enmascarar(data={"args": ("ana.perez@mail.com",)}) == {"args": ["[CORREO]"]}


def test_en_hilo_cuelga_el_span_del_que_lo_lanzo(spans):
    def hijo(nombre):
        with observacion(nombre):
            pass

    with observacion("padre") as padre, ThreadPoolExecutor(2) as hilos:
        hilos.submit(*en_hilo(hijo, "con_contexto")).result()
        hilos.submit(hijo, "sin_contexto").result()
    por_nombre = {s.name: s for s in spans()}
    assert format(por_nombre["con_contexto"].parent.span_id, "016x") == padre.id
    assert por_nombre["sin_contexto"].parent is None  # sin copiar el contexto, una traza suelta


def test_sin_cliente_todo_es_un_no_op(embeddings, tmp_path, monkeypatch):
    monkeypatch.setattr(observabilidad, "_cliente", None)
    monkeypatch.setattr(observabilidad, "_configurado", True)
    r = correr(embeddings, tmp_path)
    assert r["traza_id"] is None and r["status"] == "ok"


def test_el_prompt_se_liga_solo_si_su_texto_es_el_que_usa_el_agente(monkeypatch):
    class Prompt:
        def __init__(self, texto):
            self.prompt = texto

    class Cliente:
        def get_prompt(self, nombre, label, cache_ttl_seconds):
            assert (nombre, label) == ("revisor-reviewer_bugs", "v9")
            return Prompt("texto registrado")

    monkeypatch.setattr(observabilidad, "_prompts", {})
    monkeypatch.setattr(observabilidad, "cliente", lambda: Cliente())
    assert observabilidad.prompt_ligado("reviewer_bugs", "texto registrado", "v9").prompt == "texto registrado"
    monkeypatch.setattr(observabilidad, "_prompts", {})
    assert observabilidad.prompt_ligado("reviewer_bugs", "otro texto", "v9") is None
