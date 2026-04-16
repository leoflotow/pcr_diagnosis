# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PCR电泳异常智能诊断助手 — a Streamlit multi-page app for classroom demonstration. Students input PCR experiment parameters and observations, the system diagnoses likely causes using a rule-based scoring engine with optional AI text extraction (BigModel/智谱 API). Teachers can review and confirm diagnoses.

## Running the App

```bash
# Install dependencies
pip install -r requirements.txt

# Run (access at http://localhost:8501)
streamlit run app.py
```

Environment variables (in `.env` or shell):
- `BIGMODEL_API_KEY` — required for AI text extraction; system falls back to local keyword matching if unset
- `BIGMODEL_BASE_URL` — defaults to `https://open.bigmodel.cn/api/paas/v4`
- `BIGMODEL_MODEL` — defaults to `glm-5`

There are no tests, linting, or build steps.

## Architecture

**Streamlit multi-page app** with a shared business logic module:

```
app.py              → Entry point, initializes DB, shows navigation
core.py             → All shared logic (DB, diagnosis, AI extraction, UI helpers)
pages/
  1_学生端.py        → Student workflow: input params → diagnose → view results
  2_教师端.py        → Teacher workflow: review records → confirm cause → add notes
  3_开发调试端.py     → Debug: system self-check, API test, rules viewer, data reset
```

Every page imports from `core.py` — there is no cross-page import.

### Diagnosis Pipeline (core.py)

1. **Load rules** from `rules.csv` via `load_rules()`
2. **Extract text clues** from free-text description:
   - Primary: `extract_text_clues_with_bigmodel()` — calls BigModel API using OpenAI-compatible SDK
   - Fallback: `extract_text_clues_with_fallback()` — local keyword matching
   - Clues are normalized to 5 labels: 污染 / 模板量不足 / 引物问题 / PCR体系问题 / 退火温度问题
3. **Score each rule** via `calculate_score()` — additive scoring:
   - Base score (from `rules.csv`)
   - +10 per control match (positive control, negative control)
   - +8 per parameter range match (template amount, annealing temp)
   - +4 for cycle range match
   - +5 per text clue hit
4. **Return top 3** causes via `diagnose()`, saved to SQLite as formatted string

### Data Storage

- **SQLite** at `data/app.db`, table `diagnosis_records` — stores all diagnosis results, teacher confirmations, and image paths
- **rules.csv** — 22 diagnosis rules; editable to tune diagnostic logic. Required columns listed in `core.py:REQUIRED_RULE_COLUMNS`
- **uploads/** — saved gel electrophoresis images

### Key Constants in core.py

- `ABNORMALITY_OPTIONS` — the 6 abnormality types shown in the UI
- `ALLOWED_TEXT_CLUES` — the 5 normalized text clue labels
- `BIGMODEL_TIMEOUT_SECONDS = 20`, `BIGMODEL_TEMPERATURE = 1.0`

## Language

All UI text, comments, and variable names are in Chinese. Keep new UI text and comments in Chinese to stay consistent.
