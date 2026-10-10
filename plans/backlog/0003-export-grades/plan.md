---
id: "0003"
title: "Export effective grades to CSV/XLSX"
type: ticket
created: 2026-10-10
---

# 0003 — Export effective grades to CSV/XLSX

## Justification

After grading, the effective grades (final.csv plus revisions, NP for
absent students) must be copied by hand into the official records or Moodle.

Idea: an export button on the exam page that downloads CSV and XLSX with
id, apellidos, nombre, nota (or NP) using `effective_grades()` from 0001.

Out of scope of plan 0001 by user decision.

## Plan

### Acceptance criteria

- [ ] Exam page downloads `notas-<exam>.csv` and `.xlsx` with one row per roster student.

## Implementation

## Results

## Closure
