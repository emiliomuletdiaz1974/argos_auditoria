"""Run the golden sets against the served model: the quality gate of a release (ARG-059).

    uv run --env-file .env.example python tools/ai_eval/run_goldens.py

Uses the served model and embedder (ADR-0009), so it needs the weights of F06-05. Prints one JSON
line per suite, for the quality panel, and exits 1 if any suite is below its threshold.

The same harness runs in `make check` with an oracle in place of the model, inside
`tests/integration/test_ai_goldens.py` and on a throwaway database. The oracle is deliberately not
offered here: it indexes the corpus with the test embedder, and doing that in a real database would
leave vectors of another space in the index.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "ai-gateway"))

from argos_ai.backends.openai_compatible import OpenAiCompatibleBackend  # noqa: E402
from argos_ai.evaluation.harness import evaluate_all  # noqa: E402
from argos_ai.evaluation.metrics import gate  # noqa: E402
from argos_ai.rag.embeddings import ServedEmbedder  # noqa: E402

from argos_common.config import get_config  # noqa: E402


def main() -> int:
    cfg = get_config()
    endpoint = str(cfg.LLM_LOCAL_ENDPOINT)
    backend = OpenAiCompatibleBackend(endpoint, cfg.LLM_MODEL)
    embedder = ServedEmbedder(endpoint, cfg.LLM_MODEL)
    reports = asyncio.run(
        evaluate_all(cfg.DATABASE_URL, embedder, lambda suite: lambda case: backend)
    )
    for report in reports:
        print(json.dumps(report.as_dict(), ensure_ascii=False))
    return gate(reports)


if __name__ == "__main__":
    raise SystemExit(main())
