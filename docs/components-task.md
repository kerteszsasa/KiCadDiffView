# Components task

Implement only app/sexpr.py, app/components.py, tests/test_components.py in KiCadDiffView, a standalone local KiCad review app. Do not edit other files. Existing ../kiri and ../sksat-kicadiff are READ ONLY references, never modify. The project is tracked in its own Git repository. Python standard library only; no third party packages installed or network. Use unittest/TDD. Temporary files belong under this project's data/test-tmp, not original hardware repos. Backend parent builds repo/export/UI independently.

## Interfaces (exact)

sexpr.py exports loads(text: str) -> list (root s-expression), children(node, tag) -> list[list], first(node, tag, default=None) -> list|None. Parse KiCad strings, escaped quotes/backslashes, comments, Unicode, numbers as strings, nested structures efficiently (files11MB). Errors clear ValueError. Parent will use this for layers and sheet metadata.

components.py exports extract_components(snapshot: pathlib.Path, project_rel: str, kind: str) -> list[dict] and compare_components(before: list, after: list) -> list[dict]. snapshot is a full revision archive, project_rel relative .kicad_pro path, kind='sch' or 'pcb'. Return [] if corresponding root file absent at this revision. Detect missing/cyclic subsheets with useful error, do not escape snapshot via paths or symlinks.

Each component record: {id: str, reference: str, sheet: str, fields: dict[str,str], flags: dict[str,bool], placement: dict}. Stable IDs include schematic instance path and symbol UUID(s). Merge physical multi-unit components, preserve repeated hierarchical sheet instances and instance-specific refs using KiCad instances/project/path sections. Include all standard/custom properties (and lib_id/footprint identity as appropriate). Include real DNP and excluded-from-BOM components; omit power/# virtual symbols. Flags keys dnp,bom_excluded,board_excluded. PCB placement keys x,y,rotation (numbers normalized such that missing rotation=0) and side ('F'/'B' or layer token). Use stable PCB footprint UUID with legacy tstamp fallback, schematic hierarchical identity; fallback reference+sheet when missing. Instance/property values must come from the supplied snapshot only.

Compare returns list of {id,reference,status,before,after,changes}. status='added'|'removed'|'changed'|'unchanged'. before/after records or None. changes: list of {field,before,after,category}, category='placement' for placement keys else 'field'. Field path names 'fields.Value','flags.dnp','reference',etc. Preserve absent vs empty field as None vs ''. Match stable identity first (reference renumber is changed, not added+removed), unique same reference+sheet fallback for identities changed. Do not conflate unrelated repeated references across sheets. Natural sort refs R2 before R10.

## Tests

Synthetic schematic/PCB cases: all properties incl added/deleted/empty/custom Unicode fields; DNP/BOM flags; placement missing angle=0; UUID reference rename; repeated sheets; multiunit physical component not duplicated; add/remove; stable shapes. Read-only real project smoke possible /home/kerteszs/hw/idata/hardware/Armfed/Armfed and lea6s_to_maxm10s (do not write). Report implementation and test results to parent; do not spawn further agents.
