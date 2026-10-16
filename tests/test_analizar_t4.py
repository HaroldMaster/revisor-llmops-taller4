import csv
import json

from evaluacion.analizar_t4 import contra_verificador, filtraciones, hoja, por_agente


def fila(id_, tipo, acierto, juez):
    return {"id": id_, "tipo": tipo, "acierto": acierto, "juez_veredicto": juez, "respuesta": "r"}


def test_el_juez_se_compara_solo_donde_el_verificador_opina():
    filas = [fila("C01", "simple", "True", "aprueba"), fila("C02", "simple", "False", "aprueba"),
             fila("Q01", "negativa", "True", "aprueba"), fila("M01", "ambigua", "", "falla")]
    r = contra_verificador(filas)
    assert r["pares"] == 3 and r["acuerdo"] == 0.667
    assert r["discrepancias"] == [{"id": "C02", "tipo": "simple", "verificador": "falla", "juez": "aprueba"}]
    assert r["sin_par"] == ["M01"]


def test_un_juez_que_aprueba_todo_tiene_kappa_indefinido_o_cero():
    filas = [fila("C01", "simple", "True", "aprueba"), fila("C02", "simple", "True", "aprueba")]
    assert contra_verificador(filas)["kappa"] == "indefinido: una sola clase"


def span(traza, tipo, nombre, ms, **extra):
    return {"traza": traza, "span": tipo, "nombre": nombre, "duracion_ms": ms, **extra}


def test_la_fase_de_reviewers_dura_lo_que_el_mas_lento_y_no_la_suma():
    spans = [span("t", "corrida", "revisor", 10_000),
             span("t", "agent", "reviewer_bugs", 6_000), span("t", "agent", "reviewer_reglas", 4_000),
             span("t", "agent", "verificador", 3_000),
             span("t", "llm", "reviewer_bugs", 900, tokens_entrada=1000, tokens_salida=100),
             span("t", "llm", "verificador", 500, tokens_entrada=300, tokens_salida=100)]
    r = por_agente(spans)
    assert r["fase_parte_media_de_la_corrida"]["reviewers_en_paralelo"] == 0.6
    assert r["fase_parte_media_de_la_corrida"]["verificador"] == 0.3
    assert r["por_agente"]["reviewer_bugs"]["tokens_entrada"] == 1000
    assert r["por_agente"]["reviewer_bugs"]["parte_de_los_tokens"] == round(1100 / 1500, 3)


def test_la_hoja_no_trae_las_columnas_del_juez(tmp_path):
    destino = tmp_path / "hoja.csv"
    hoja([{**fila("M01", "ambigua", "", "aprueba"), "juez_motivo": "x"}], destino)
    with destino.open(encoding="utf-8") as archivo:
        filas = list(csv.DictReader(archivo))
    assert not any(c.startswith("juez") for c in filas[0])
    assert filas[0]["criterio"].startswith("Tres parches tocan descuentos")


def test_filtraciones_encuentra_el_dato_y_la_clave_pero_ignora_la_pregunta(tmp_path):
    spans = tmp_path / "spans.jsonl"
    spans.write_text(json.dumps({"x": "contacto ana.perez@mail.com, sk-lf-0000aaaa11112222bbbb"}) + "\n", encoding="utf-8")
    resultados = tmp_path / "r.csv"
    resultados.write_text("id,pregunta,respuesta\nP01,Soy ana.perez@mail.com,ok\n", encoding="utf-8")
    r = filtraciones([spans, resultados])["hallado"]
    assert r["spans.jsonl"] == {"pii": ["ana.perez@mail.com"], "claves": ["sk-lf-0000aaaa11112222bbbb"]}
    assert r["r.csv"] == {"pii": [], "claves": []}

