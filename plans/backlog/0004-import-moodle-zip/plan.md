---
id: "0004"
title: "Import Moodle submissions zip into entregas"
type: ticket
created: 2026-10-10
---

# 0004 — Import Moodle submissions zip into entregas

## Justification

Submissions are downloaded from MooVi/Moodle as a zip with one folder per
student (`Nombre Apellidos_12345_assignsubmission_file_`). Distributing them
into `entregas/<id>/original/` by hand is slow.

Idea: upload the zip on the exam page, match each folder to a roster student
by normalised full name (slug comparison), show the matching for
confirmation, then copy the files. Unmatched folders are reported.

Out of scope of plan 0001 by user decision.

## Plan

### Acceptance criteria

- [ ] Uploading a Moodle zip places each student's files in `entregas/<id>/original/` after confirmation.
- [ ] Unmatched folders are listed and nothing is written for them.

## Implementation

## Results

## Closure
