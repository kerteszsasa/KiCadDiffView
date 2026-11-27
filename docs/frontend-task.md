# Frontend task

Build complete browser UI for new local KiCad diff app. Own only frontend/index.html, frontend/src/app.ts, frontend/src/style.css, frontend/package.json and frontend/tsconfig.json if needed. No edits ../kiri or ../sksat-kicadiff (READ ONLY). Parent builds Python API/export. No framework/runtime dependencies; TypeScript DOM code, Vite planned for optional dev/build (Node22 in Docker). No CDN/fonts/images network. Local node18 + Babel TypeScript transform available; parent handles offline build script. Implement self-contained app.ts no nonlocal imports other than own module if needed. Do not spawn agents.

## UI

Professional compact engineering workstation, dark navy/slate panels, restrained cyan accent, readable>=14px controls/16 body, no decorative stock imagery. App name 'KiCadDiffView'. English UI, exact English main tabs Schematics / PCB / Components and graphic modes Overlay / Side by Side / Swipe / Colored. Existing reference viewer is sksat-kicadiff/output/review-IcJlV3Xd/index.html (only read as idea). All functionality fully wired, not mockup.

Workflow sidebar: source repo path text + browse dialog/breadcrumbs within allowed roots, recent repos; project select; two SHA/ref inputs ('Régi','Új') plus commit list radio/select controls to populate both, project-only/all checkbox, message search, load more commits. Generate comparison -> job progress/error -> render results. Saved comparison list opens/deletes (delete confirmation; no running deletion), selected job persistent URL hash/localStorage okay. Handle request races (commit selection/input/file loads should not show stale results) and network errors gracefully. Keep job polling running even if user updates input forms; history updates. Initial empty state with clear workflow, no fake data. Top result metadata refs and project. No hidden offscreen controls.

Graphic file selector for selected tab: result.files type sch/pcb. Schematic page selector union; added/deleted page missing side -> empty placeholder, never fall back to different sheet. PCB layer list EVERY manifest layer (names custom), checkbox eye per layer, all/none controls, active layer selection/z-order, shared visible state across4modes. Default visible F.Cu B.Cu F.SilkS B.SilkS Edge.Cuts (fallback all if none). Zoom buttons+wheel, reset/fit and drag pan, both sides sync. Render normalized SVG images directly (crisp zoom), common same aspect ratio. Overlay opacity slider, Side by Side, Swipe slider, Colored uses per-layer prebuilt colored SVG (no further color conversion). Colored opacity1 so isolated exact RGB colors; legend new#40FF40/old#880808/unchanged#807F7F. Normal PCB layers opacity .65. Don't hide unknown layers. Changing modes keeps selection/zoom; changing files can reset zoom.

Components: inner Schematic/PCB toggle, text search, status filter all/changed/added/removed/unchanged; include/hide DNP or BOM-excluded controls; placement changes checkbox filter; toggle equal fields. Table one row per component, reference, status and summary, expandable shows old/new fields. ALL arbitrary field keys/values via textContent safe, flags displayed. DNP/BOM indicator. Placement-only changes can be hidden; data+placement changes remain. Search should match refs + fields. All provided diff records can be huge (Armfed429): render sensibly details only on expand. Avoid XSS: Git/user/property strings never raw innerHTML.

## API (same-origin JSON)

GET /api/config -> {roots:string[],version:string}
GET /api/browse?path=... -> {path,parent:string|null,directories:[{name,path,is_repo}],repo:string|null}
GET /api/repos -> {repos:[{path,used}]}
POST /api/repos JSON{path} -> {path,projects:[{path,name}]}
GET /api/projects?repo=... -> {projects:[{path,name}]}
GET /api/commits?repo=...&project=...&all=0|1&q=...&offset=0 -> {commits:[{sha,date,author,subject}],more:boolean}
GET /api/comparisons -> {comparisons:[Job]}
POST /api/comparisons {repo,project,base,head} -> Job
GET /api/comparisons/ID -> Job plus result:Manifest when ready
DELETE /api/comparisons/ID -> {deleted:true}
Errors JSON{error:string}, non2xx.

Job={id,input:{repo,project,base,head},status:'queued'|'running'|'ready'|'error',progress:string,error:string|null,created,updated}.
Manifest={id,repo,project,base,head,files:File[],components:{sch:ComponentDiff[],pcb:ComponentDiff[]},created}.
File={id,type:'sch'|'pcb',name,path,canvas:[x,y,width,height],pages?:Item[],layers?:Item[]}.
Item={id,name,before:string|null,after:string|null,colored:string,changed:boolean}. Image relative paths -> `/results/ID/` + encodeURI(path) (encode each segment to handle spaces/#/? safely).
ComponentDiff={id,reference,status:'added'|'removed'|'changed'|'unchanged',before:Record|null,after:Record|null,changes:[{field,before,after,category:'field'|'placement'}]}.
Record={id,reference,sheet,fields:{[key]:string},flags:{dnp,bom_excluded,board_excluded},placement:{x,y,rotation,side}}.

## Test/finish

Use JS syntax checks via installed Babel transform available (require '@babel/core', '@babel/plugin-transform-typescript'); no npm dependencies install network here. Parent runs build/API integration and browser. Provide concise report docs/frontend-report.md, note any limitations, do not claim browser tests without actual browser. KiCadDiffView is tracked in its own Git repository.
