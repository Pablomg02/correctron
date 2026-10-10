---
id: "0002"
title: "LLM grader kit: template CSV, prompt and validate CLI"
type: ticket
created: 2026-10-10
---

# 0002 — LLM grader kit: template CSV, prompt and validate CLI

## Justification

The user wants an LLM to act as one more grader (see 0001). Today they would
have to explain the CSV format to the LLM by hand and check its output by eye.

Idea: from the exam page, generate (1) a template `notas/<grader>.csv` with
the header and one row per present student, and (2) a prompt in Markdown with
the data format, the criteria from `config.json` and the paths of the
statement PDFs. Add a `correctron validar [path]` CLI command that runs the
validation engine from 0001 and prints the problems.

Out of scope of plan 0001 by user decision.

## Plan

### Acceptance criteria

- [ ] Exam page has a "Kit para LLM" action that downloads the template CSV and the prompt.
- [ ] `uv run correctron validar data/<subject>/<exam>` prints the issues and exits 1 if there are errors.

## Implementation

## Results

## Closure
