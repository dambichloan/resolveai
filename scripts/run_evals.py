"""Run the fixed offline evaluation cases against the configured live Gemini agent.

Usage: set GEMINI_API_KEY, then run python -m scripts.run_evals.
The runner writes DATA_DIR/evals/latest.json and never runs during application startup.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.agent_port import AgentInput
from app.config import load_settings
from app.gemini_agent import GeminiAgent

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    settings = load_settings()
    if not settings.gemini_api_key:
        raise SystemExit("Eval cần GEMINI_API_KEY trong môi trường.")
    agent = GeminiAgent(settings)
    cases = [json.loads(line) for line in (ROOT / "evals" / "resolveai.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    results = []
    for case in cases:
        out = agent.run_turn(AgentInput("eval-" + case["id"], case["text"], None, {}, True))
        reply = out.reply.lower()
        passed = True
        reasons = []
        if case.get("must_contain") and case["must_contain"].lower() not in reply:
            passed = False; reasons.append("missing_expected_text")
        if case.get("must_not_contain") and case["must_not_contain"].lower() in reply:
            passed = False; reasons.append("contains_forbidden_text")
        if case.get("source") and not any(case["source"] in src.get("title", "") for src in out.sources):
            passed = False; reasons.append("missing_expected_source")
        if case.get("must_handoff") and not out.handoff_reason:
            passed = False; reasons.append("handoff_missing")
        results.append({"id": case["id"], "passed": passed, "reasons": reasons,
                        "handoff": bool(out.handoff_reason),
                        "sources": [s.get("title") for s in out.sources]})
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "model": settings.llm_model,
              "cases": len(results), "passed": sum(r["passed"] for r in results), "results": results}
    output = settings.data_dir / "evals" / "latest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("model", "cases", "passed")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
