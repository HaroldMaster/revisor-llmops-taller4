"""
Lab 04 — Wrapper de observabilidad para el agente del Lab 03.

Usa trazas locales por defecto. Si USE_LANGFUSE=true y hay credenciales, tambien
envia un trace simple a Langfuse.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

from dotenv import load_dotenv

from guardrails import validate_input, validate_output

LAB03_PATH = Path(__file__).resolve().parents[1] / "Lab-03-Agentes"
sys.path.append(str(LAB03_PATH))

from agent import AnalystAgent  # noqa: E402

load_dotenv()


def maybe_langfuse_trace(name: str, payload: dict) -> None:
    if os.getenv("USE_LANGFUSE", "false").lower() != "true":
        return
    try:
        from langfuse import Langfuse

        langfuse = Langfuse()
        trace = langfuse.trace(name=name, input=payload.get("question"))
        trace.update(output=payload.get("answer"), metadata=payload)
        langfuse.flush()
    except Exception as exc:  # noqa: BLE001
        print(f"Langfuse no disponible, se conserva traza local: {exc}")


def run_instrumented(question: str) -> dict:
    ok, cleaned_question = validate_input(question)
    started = time.perf_counter()
    if not ok:
        result = {"question": question, "answer": cleaned_question, "status": "blocked_input"}
    else:
        agent = AnalystAgent()
        result = agent.run(cleaned_question)
        output_ok, safe_answer = validate_output(result["answer"])
        if not output_ok:
            result["answer"] = safe_answer
            result["status"] = "blocked_output"

    result["latency_seconds"] = round(time.perf_counter() - started, 3)
    result["observed_at"] = datetime.now(timezone.utc).isoformat()
    write_local_trace(result)
    maybe_langfuse_trace("lab04-agent-run", result)
    return result


def write_local_trace(result: dict) -> None:
    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    with (reports_dir / "traces.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    question = "REEMPLAZAR por una pregunta de evaluacion."
    print(json.dumps(run_instrumented(question), indent=2, ensure_ascii=False))
