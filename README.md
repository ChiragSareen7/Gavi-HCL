# Scam-Engagement LLM Fine-tuning Kit (Hackathon-grade)

This repo contains:
- A **JSONL instruction-tuning dataset** for scam detection + conversational engagement (Indian persona).
- A **QLoRA/LoRA** fine-tuning script using **HuggingFace Transformers + PEFT**.
- A **strict JSON-only classifier prompt**, plus **evaluation + calibration** utilities.
- A minimal **backend+frontend** to compare base vs fine-tuned outputs side-by-side.
- Notes for later combining the fine-tuned model with **RAG** (retrieval-augmented generation).

## Folder structure

```
.
├─ data/
│  ├─ scam_finetune_train.jsonl
│  └─ scam_finetune_eval.jsonl
│  ├─ classifier_finetune_train.jsonl
│  └─ classifier_test_labeled.jsonl
├─ scripts/
│  └─ train_qlora.py
│  └─ eval_classifier.py
├─ configs/
│  └─ train_qlora.yaml
├─ prompts/
│  └─ classifier_system_prompt.txt
├─ backend/
│  ├─ app.py
│  └─ README.md
└─ frontend/
   ├─ app/
   │  ├─ layout.tsx
   │  └─ page.tsx
   ├─ package.json
   ├─ next.config.js
   └─ README.md
└─ requirements.txt
```

## Dataset format (JSONL)

Each line is one training sample:

```json
{
  "messages": [
    { "role": "system", "content": "<system persona / rules>" },
    { "role": "user", "content": "<incoming message>" },
    { "role": "assistant", "content": "<ideal response>" }
  ]
}
```

### Categories included (5+ examples each)
- Scam vs Non-Scam classification
- Conversational scam engagement (multi-turn packed into the user message)
- Intelligence extraction (assistant must output **ONLY** strict JSON)
- False-positive avoidance (legit but scam-adjacent messages)
- Edge cases (polite scams, delayed scams, “soft” social engineering)

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Train (QLoRA default)

Edit `configs/train_qlora.yaml` (model + paths), then:

```bash
python scripts/train_qlora.py --config configs/train_qlora.yaml
```

Outputs are saved to the configured `output_dir` (LoRA adapters + tokenizer files).

## RAG combination notes (post fine-tune)

After fine-tuning, you typically:
- Keep **scam-engagement behavior** in the fine-tuned model (LoRA adapters).
- Add RAG at inference time to ground the assistant with:
  - Known scam patterns / updated fraud IOCs
  - Bank/UPI validation heuristics
  - URL reputation feeds / allowlists
  - Prior conversation context + extracted intel history

Recommended split:
- **Model (fine-tuned)**: “how to talk” (persona, probing, not revealing detection, structured extraction behavior).
- **RAG + policy layer**: “what’s true today” (fresh intel, threat feeds, blocklists, playbooks).

At inference time:
- Run a **lightweight classifier prompt** (or a separate small classifier) for routing.
- If “extraction requested”, enforce **strict JSON-only** output and validate schema.
- Store extracted intel to a database; RAG can pull it back on later turns for continuity.

## Confidence calibration strategy (concise)

For your requirement “**SCAM only when confidence ≥ 0.92**” (high-precision mode):
- **Model output**: train the model to emit a calibrated `confidence` scalar alongside `label`.
- **Runtime gating**: enforce `label="SCAM"` only if `confidence>=0.92`; otherwise coerce to `UNCERTAIN`.
- **Calibration (recommended)**:
  - Collect a held-out labeled set representative of your traffic (including borderline cases).
  - Fit a post-hoc calibrator on top of the model score (temperature scaling or isotonic regression).
  - Evaluate Expected Calibration Error (ECE) and precision/coverage at threshold 0.92.
- **Penalize uncertainty**:
  - Optimize for **precision@0.92** with a coverage constraint.
  - Add training examples where borderline scams must output `UNCERTAIN` (not SCAM) to reduce false positives.



