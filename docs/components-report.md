# Component extraction and comparison report

Implemented the agreed interfaces in `app/sexpr.py` and `app/components.py`, with 26 standard-library unittest cases in `tests/test_components.py`.

## Interfaces and record behavior

- `loads(text)` returns one nested-list expression, with strings for all atoms including numbers. It handles Unicode, semicolon comments, escaped quotes/backslashes/newlines, and reports malformed input as `ValueError`. Parsing uses an explicit stack and streamed regex tokens; a 1,500-level input is tested.
- `children(node, tag)` and `first(node, tag, default=None)` select direct children only.
- `extract_components(snapshot, project_rel, kind)` accepts `sch` / `pcb`, returning an empty list when the corresponding revision root is absent. Missing subsheets, cycles, invalid documents, and paths/symlinks escaping the snapshot raise `ValueError`.
- Each record has exactly `id`, `reference`, `sheet`, `fields`, `flags`, and `placement`. Fields include all properties; schematic records additionally expose `fields.lib_id`, PCB records `fields.Footprint` (plus legacy fp_text Reference/Value and description/tags).
- Schematic sheets are human-readable paths such as `/Left`. Stable IDs include every member’s full root/sheet/symbol UUID path, sorted and joined. Annotated units with the same reference/library/footprint in one sheet instance merge into one physical component. Complementary units split across distinct sheet files also merge when all unit numbers are explicit and disjoint; the merged sheet display joins member sheet paths with `; `. Repeated source-sheet copies or overlapping unit numbers remain separate to avoid conflating unrelated instances. Repeated sheet files are traversed separately. Modern `instances/project/path` and KiCad 6 `symbol_instances` supply per-instance references. Project-name matching is preferred, with the empty project name as fallback.
- PCB UUID is preferred, then legacy tstamp, then reference+sheet. Placement has numeric x/y/rotation, default rotation 0, and side `F` / `B` for outer copper or the original layer token otherwise. Schematic placement is `{}`.
- Flags always have `dnp`, `bom_excluded`, `board_excluded`. Actual DNP and BOM-excluded components remain in the output. `#` references and `power:` schematic library symbols are omitted. A PCB `board_only` footprint remains included on the board.
- `compare_components(before, after)` matches unique IDs first and unique reference+sheet among unmatched records next. ID-only changes after fallback are metadata and do not produce a semantic field change. Returns all four statuses, before/after records, and dotted field changes with placement/field categories. Missing properties remain `None` in changes, distinct from explicit empty strings. Reference sorting is natural (`R2` before `R10`).

## Verification

`python3 -m unittest discover -s tests -p test_components.py -v`: **26 passed**.

Read-only smoke against the supplied working projects:

| Project | Schematic | PCB | DNP | BOM excluded | Duplicate IDs |
| --- | ---: | ---: | ---: | ---: | ---: |
| Armfed | 429 | 429 | 14 each | 14 each | 0 |
| lea6s_to_maxm10s | 12 | 12 | 1 each | 1 each | 0 |

Armfed extraction took approximately 0.31 seconds for the schematic hierarchy and 0.79 seconds for the PCB on this host. No original hardware or reference checkout files were changed. Synthetic fixtures use `data/test-tmp` and are cleaned after each test.

## Limits

The supported inputs are modern `.kicad_sch` / `.kicad_pcb` S-expression documents (legacy PCB module/tstamp/fp_text and KiCad 6 instance blocks are supported). Legacy non-S-expression `.sch` files are outside this interface. `${KIPRJMOD}` in sheet file paths resolves inside the supplied project snapshot; no host environment-variable expansion occurs. Equal multiunit properties remain ordinary scalar fields. When units disagree (including a property missing from only some units), the normal property contains the first available value in stable member-path order, and every present member value is also retained as `fields["unit[/root/sheet/symbol].fields.Property"]`. Missing members have no provenance entry, preserving missing versus empty. Flags retain their boolean logical-OR summary, and disagreements additionally produce string-valued `fields["unit[/root/sheet/symbol].flags.dnp"]` entries (`yes` / `no`). Thus changes to any non-first unit remain visible even when the component summary is unchanged. Provenance names that collide with an actual custom property are prefixed with `@` until distinct; original properties remain intact. Unannotated `?` units remain separate because they lack a reliable physical-component reference. Ambiguous cross-sheet groups (duplicate unit numbers, missing unit numbers, or repeated source files) remain separate rather than guessing which physical packages they belong to.

Cross-sheet review regression: verified the original U1 logic-unit-at-root / power-unit-on-`/Power` case first failed with two records, then passed with one record preserving both full UUID paths, combined fields/flags, and stable identity after reference renumbering. Guard tests retain same-reference same-unit parts on distinct sheets and repeated same-reference multiunit subsheet instances.

Final all-fields regression: added same-sheet and cross-sheet non-first-unit property-change tests, an individual DNP change hidden by an already-true combined flag, and a missing-versus-empty unit-property case. All four failed before the provenance implementation and passed afterward. Record keys remain unchanged and all `fields` values, including flag provenance, remain strings.
