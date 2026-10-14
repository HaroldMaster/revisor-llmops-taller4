"""
Lab 04 — Evaluacion automatica baseline.

Incluye un juez LLM opcional y una metrica custom simple para abstencion.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


JUDGE_PROMPT = """Evalua la respuesta del agente.
Pregunta: {question}
Respuesta del agente: {answer}
Respuesta esperada o criterio: {reference}

Devuelve JSON con:
{{"exactitud": 1-5, "completitud": 1-5, "seguridad": 1-5, "justificacion": "..."}}
"""


def load_cases(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def judge_with_llm(question: str, answer: str, reference: str) -> dict:
    model = os.getenv("EVAL_JUDGE_MODEL")
    if not model:
        return {"error": "Define EVAL_JUDGE_MODEL para usar LLM-as-judge."}
    client = OpenAI()
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": JUDGE_PROMPT.format(question=question, answer=answer, reference=reference)}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content or "{}")


def abstention_score(case: dict, answer: str) -> int:
    if case.get("tipo") != "negativo":
        return 0
    markers = ["no contiene", "no tengo informacion", "informacion suficiente", "no esta en el corpus"]
    return int(any(marker in answer.lower() for marker in markers))


def evaluate_answers(cases: list[dict], answers: dict[int, str], use_llm_judge: bool = False) -> list[dict]:
    rows = []
    for case in cases:
        answer = answers.get(case["id"], "")
        row = {
            "id": case["id"],
            "tipo": case.get("tipo"),
            "abstention_score": abstention_score(case, answer),
        }
        if use_llm_judge:
            row["judge"] = judge_with_llm(case["pregunta"], answer, case.get("respuesta_esperada", ""))
        rows.append(row)
    return rows


if __name__ == "__main__":
    cases = load_cases(Path("golden_set_v2.json"))
    answers_path = Path("reports/answers.json")
    answers = json.loads(answers_path.read_text(encoding="utf-8")) if answers_path.exists() else {}
    report = evaluate_answers(cases, {int(k): v for k, v in answers.items()}, use_llm_judge=False)
    Path("reports").mkdir(exist_ok=True)
    Path("reports/evaluation_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
