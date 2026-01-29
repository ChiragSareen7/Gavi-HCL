import argparse
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


"""
Evaluation goals:
- Compare base vs fine-tuned model on a labeled test JSONL
- Compute:
  - accuracy (on label)
  - high-confidence accuracy (confidence >= 0.92)
  - false positive rate (predict SCAM when gold is NOT_SCAM)

Assumptions:
- Models are called via Groq-compatible OpenAI-style Chat Completions.
- The model returns strict JSON:
  {"label":"SCAM|NOT_SCAM|UNCERTAIN","confidence":0-1,"reply":"..."}
"""


@dataclass
class ModelSpec:
    name: str
    model: str


def load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def safe_parse_model_json(s: str) -> Dict[str, Any]:
    """
    Be strict: we want the model to output pure JSON. In eval, tolerate accidental whitespace.
    """
    s = s.strip()
    return json.loads(s)


def call_chat_openai_style(base_url: str, api_key: str, model: str, messages: List[Dict[str, str]], timeout_s: float) -> str:
    """
    Uses the `openai` python client if installed; otherwise instructs user to install it.
    This keeps Groq-compatibility by relying on OpenAI-style APIs + configurable base_url.
    """
    try:
        from openai import OpenAI  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Missing dependency `openai`. Add `openai` to requirements and `pip install openai`."
        ) from e

    client = OpenAI(base_url=base_url, api_key=api_key)
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.0,
        max_tokens=256,
        timeout=timeout_s,
    )
    return resp.choices[0].message.content or ""


def compute_metrics(preds: List[Dict[str, Any]], golds: List[str]) -> Dict[str, float]:
    assert len(preds) == len(golds)
    n = len(golds)

    correct = 0
    hc_total = 0
    hc_correct = 0

    fp = 0
    tn = 0
    n_not_scam = 0

    for p, g in zip(preds, golds):
        label = p.get("label")
        conf = float(p.get("confidence", 0.0))

        if label == g:
            correct += 1

        if conf >= 0.92:
            hc_total += 1
            if label == g:
                hc_correct += 1

        if g == "NOT_SCAM":
            n_not_scam += 1
            if label == "SCAM":
                fp += 1
            else:
                tn += 1

    return {
        "accuracy": correct / n if n else 0.0,
        "high_conf_coverage": hc_total / n if n else 0.0,
        "high_conf_accuracy": hc_correct / hc_total if hc_total else 0.0,
        "false_positive_rate": fp / n_not_scam if n_not_scam else 0.0,
    }


def run_eval(test_rows: List[Dict[str, Any]], spec: ModelSpec, base_url: str, api_key: str, timeout_s: float) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
    preds: List[Dict[str, Any]] = []
    golds: List[str] = []

    for r in test_rows:
        gold = r["label"]
        golds.append(gold)

        content = call_chat_openai_style(
            base_url=base_url,
            api_key=api_key,
            model=spec.model,
            messages=r["messages"],
            timeout_s=timeout_s,
        )
        preds.append(safe_parse_model_json(content))

    return preds, compute_metrics(preds, golds)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test_jsonl", required=True, help="Labeled test set JSONL (each row: {label, messages}).")
    ap.add_argument("--base_model", required=True)
    ap.add_argument("--ft_model", required=True)
    ap.add_argument("--base_url", default=os.environ.get("GROQ_BASE_URL", ""))
    ap.add_argument("--api_key", default=os.environ.get("GROQ_API_KEY", ""))
    ap.add_argument("--timeout_s", type=float, default=30.0)
    args = ap.parse_args()

    if not args.base_url:
        raise SystemExit("Missing --base_url (or env GROQ_BASE_URL).")
    if not args.api_key:
        raise SystemExit("Missing --api_key (or env GROQ_API_KEY).")

    test_rows = load_jsonl(args.test_jsonl)
    # Expect each row: {"label":"SCAM|NOT_SCAM|UNCERTAIN","messages":[...]}
    for i, r in enumerate(test_rows):
        if "label" not in r or "messages" not in r:
            raise SystemExit(f"Row {i} missing label/messages.")

    base_spec = ModelSpec(name="base", model=args.base_model)
    ft_spec = ModelSpec(name="finetuned", model=args.ft_model)

    _, base_m = run_eval(test_rows, base_spec, args.base_url, args.api_key, args.timeout_s)
    _, ft_m = run_eval(test_rows, ft_spec, args.base_url, args.api_key, args.timeout_s)

    def fmt(m: Dict[str, float]) -> str:
        return (
            f"accuracy={m['accuracy']:.3f} | "
            f"high_conf_coverage={m['high_conf_coverage']:.3f} | "
            f"high_conf_accuracy={m['high_conf_accuracy']:.3f} | "
            f"FPR={m['false_positive_rate']:.3f}"
        )

    print("=== Classification Eval (SCAM gating at >=0.92) ===")
    print(f"Base:      {fmt(base_m)}")
    print(f"Fine-tuned:{fmt(ft_m)}")


if __name__ == "__main__":
    main()


