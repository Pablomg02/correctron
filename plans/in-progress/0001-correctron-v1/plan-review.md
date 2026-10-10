# Plan review — 0001

One independent critic (general-purpose subagent, no access to the planning
conversation) reviewed `plan.md` on 2026-10-10.

**Verdict:** ready with fixes. It recomputed the data model, the sample data
and most expected values and found them consistent. It found two serious
flaws in the htmx layer, plus gaps in verification and some ambiguities.

All 23 issues were applied. None changed scope or user-facing behaviour, so
no question went back to the user.

| # | Severity | Issue | Disposition |
| --- | --- | --- | --- |
| 1 | serious | The change banner fires after the web's own writes (the initial fingerprint is fixed at render). | Applied: `#huella-actual` hidden input, poll includes it, every htmx mutation refreshes it out of band (D14, T11, `_estado_oob.html`); tested in T12. |
| 2 | serious | Version tokens outside the swapped tbody go stale and give a 409 on the user's own next action. | Applied: one `#version-lista` per page inside a `panel-…` wrapper. Structural actions re-render the panel; inline edits refresh the version out of band (D26, T12, T13); tested. |
| 3 | moderate | An info banner before `<tr>` rows breaks the tbody swap. | Applied: notices go out of band to `#avisos` (`_aviso_oob.html`), and no bare tbody swaps remain (D26). |
| 4 | moderate | Row and tbody swaps overwrite the field being typed in. | Applied: inline edits use `hx-swap="none"` plus out-of-band computed cells; the full row is re-rendered only on a validation error via `HX-Retarget`/`HX-Reswap` (D26, T16). |
| 5 | moderate | `importar` and `marcar` are captured by the `{id}` routes. | Applied: distinct paths `/a/{s}/importar-alumnos` and `/a/{s}/e/{e}/marcar-presentados` (D27). |
| 6 | moderate | `x-data` with `|tojson` inside a double-quoted attribute breaks; Decimals are not serialisable. | Applied: `<script type="application/json" id="config-datos">` from `exam_config_to_dict`, read by `criterios.js` (T14). |
| 7 | moderate | "total ≠ computed" for revision delta rows is undefined. | Applied: computed on the merged result (Appendix A §Validation). |
| 8 | moderate | Δ with incomplete totals is undefined. | Applied: only complete totals count; blank when fewer than two (T17). |
| 9 | moderate | Raw cells copied or compared across files leak `7,5`; e2e expectations are vague. | Applied: canonicalisation rule (D23, Appendix A), numeric comparison in `save_revision_row`, literal e2e scenario and expected files (T19). |
| 10 | moderate | The `format_number` exponent bug (`1E+1`) is not tested. | Applied: tests for `10` and `100.50` (T4); literal CSV row asserted in T8. |
| 11 | moderate | cp1252 encoding is not kept on rewrite. | Applied: `Table.encoding`, written back in the same encoding, round-trip test (T4, D9). |
| 12 | moderate | `= {}` dataclass defaults fail on import. | Applied: `field(default_factory=…)` rule in task conventions and T6 signatures. |
| 13 | moderate | Running the app on `ejemplo/data` mutates the fixtures. | Applied: the README copies to `/tmp/correctron-demo` first (T19). |
| 14 | moderate | Some checks would pass with wrong work (NP not exercised, page-wide substrings, normalised `../..`). | Applied: a Diego row is added before the bulk copy; `row_html`/`fila-<id>` scoping; a symlink traversal test (T11, T13, T17, T18). |
| 15 | unclear | How the orphan-columns aviso survives the 303 redirect. | Applied: computed on every config GET via `repo.orphan_columns` (T10, T14). |
| 16 | unclear | Raw JSON saved verbatim or normalised; field name. | Applied: always normalised through `save_exam_config`; field `config_json` for both editors (T10, T14). |
| 17 | suggestion | The `suma` aviso fires on every new empty exam. | Applied: only with non-empty `criterios` (T5, Appendix A). |
| 18 | suggestion | `trash_file` can trash `config.json`; the area id pattern is unspecified. | Applied: `AREA_RE`, trash limited to upload areas, `rel_path` relative to the data root (T10, T15). |
| 19 | suggestion | `csv.Sniffer` is unreliable. | Applied: the most frequent candidate in the header line (T4, D9). |
| 20 | suggestion | The feedback `.md` link downloads instead of opening. | Applied: `.md`, `.csv` and `.txt` served inline as `text/plain` with `nosniff` (T11). |
| 21 | suggestion | Global `KeyError`/`ValueError` handlers hide bugs. | Applied: `repo.NotFound` and `repo.BadRequest` only (D28, T10, T11). |
| 22 | suggestion | The `.python-version` 3.12 pin contradicts the risk mitigation. | Applied: pinned to 3.14; fallback kept in Risks (T1). |
| 23 | suggestion | `uvicorn.run` takes host and port as keywords only. | Applied (T11). |
