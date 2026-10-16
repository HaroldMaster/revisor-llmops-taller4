from evaluacion.alertas import evaluar, medir, umbrales


def corrida(traza, segundos, tokens):
    return [{"traza": traza, "span": "corrida", "duracion_ms": segundos * 1000},
            *([{"traza": traza, "span": "llm", "tokens_entrada": tokens}] if tokens else [])]


def test_los_umbrales_salen_de_la_base_con_su_regla():
    spans = [s for i, (seg, tok) in enumerate([(10, 100), (12, 120), (14, 80), (0, 0)]) for s in corrida(f"t{i}", seg, tok)]
    filas = [{"guardrail_entrada": g} for g in ("ok", "ok", "ok", "bloqueada")]
    base = medir(spans, filas)
    assert base["corridas"] == 4 and base["corridas_con_revision"] == 3 and base["tokens_media"] == 100
    u = umbrales(base)
    assert u["latencia"] == 15                      # p95 = 13,7 s, redondeado hacia arriba a 5 s
    assert u["tokens"] == round(100 + 3 * 20 / 3 ** 0.5)
    assert u["bloqueos"] == 0.5                     # (1 + 1) / 4: un caso por encima de la base


def test_la_base_no_hace_saltar_sus_propias_alertas_y_un_cambio_grande_si():
    limites = {"latencia": 55, "tokens": 91437, "bloqueos": 0.125}
    normal = {"latencia_p95_s": 50.4, "tokens_media": 74679, "bloqueos": 2, "preguntas": 24}
    assert not any(a["salta"] for a in evaluar(normal, limites).values())
    peor = {**normal, "bloqueos": 4}
    assert evaluar(peor, limites)["bloqueos"]["salta"]
