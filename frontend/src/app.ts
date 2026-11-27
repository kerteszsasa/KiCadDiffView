type Kind = 'sch' | 'pcb';
type MainTab = Kind | 'components';
type Mode = 'overlay' | 'side' | 'swipe' | 'colored';
type Source = {repo?:string;path?:string;remote_repo_id?:string;source_url?:string};
type Remote = {id:string;url:string;path:string;status:'queued'|'running'|'ready'|'error';usable:boolean;progress:string;error:string|null;updated:string;last_refreshed:string|null;size_bytes:number;comparison_count:number;delete_bytes:number;busy:boolean};
type Job = {id:string;input:Source & {repo:string;project:string;base:string;head:string};status:'queued'|'running'|'ready'|'error';progress:string;error:string|null;created:string;updated:string;result?:Manifest};
type Item = {id:string;name:string;before:string|null;after:string|null;colored:string;changed:boolean};
type GraphicFile = {id:string;type:Kind;name:string;path:string;canvas:[number,number,number,number];pages?:Item[];layers?:Item[]};
type ComponentRecord = {id:string;reference:string;sheet:string;fields:Record<string,string>;flags:{dnp:boolean;bom_excluded:boolean;board_excluded:boolean};placement:{x:number;y:number;rotation:number;side:string}};
type ComponentDiff = {id:string;reference:string;status:'added'|'removed'|'changed'|'unchanged';before:ComponentRecord|null;after:ComponentRecord|null;changes:{field:string;before:unknown;after:unknown;category:'field'|'placement'}[]};
type Manifest = Source & {id:string;repo:string;project:string;base:string;head:string;files:GraphicFile[];components:Record<Kind,ComponentDiff[]>;created:string;revisions?:Partial<Record<'base'|'head',Commit>>};
type Commit = {sha:string;date:string;author:string;subject:string;message:string};
type Project = {path:string;name:string};
type Browse = {path:string;parent:string|null;directories:{name:string;path:string;is_repo:boolean}[];repo:string|null};
type ComponentOptions = {query:string;status:string;includeDnp:boolean;includeBom:boolean;placement:boolean};

export function assetUrl(id:string,path:string):string {
  return `/results/${encodeURIComponent(id)}/${path.split('/').map(segment=>encodeURIComponent(segment)).join('/')}`;
}
export function swipeClips(amount:number):{before:string;after:string} {
  const value=Math.min(100,Math.max(0,Number.isFinite(amount)?amount:50));
  return {before:`inset(0 ${100-value}% 0 0)`,after:`inset(0 0 0 ${value}%)`};
}
export function componentMatches(component:ComponentDiff,options:ComponentOptions):boolean {
  if(options.status!=='all' && component.status!==options.status) return false;
  const records=[component.before,component.after].filter((value):value is ComponentRecord=>value!==null);
  if(!options.includeDnp && records.some(record=>record.flags?.dnp)) return false;
  if(!options.includeBom && records.some(record=>record.flags?.bom_excluded)) return false;
  if(!options.placement && component.status==='changed' && component.changes.length>0 && component.changes.every(change=>change.category==='placement')) return false;
  const query=options.query.trim().toLocaleLowerCase();
  if(!query) return true;
  return [component.reference,...records.flatMap(record=>[record.reference,record.sheet,...Object.entries(record.fields??{}).flat(),...Object.entries(record.flags??{}).flat().map(String),...Object.values(record.placement??{}).map(String)])].join(' ').toLocaleLowerCase().includes(query);
}

function element<K extends keyof HTMLElementTagNameMap>(tag:K,className='',text?:string):HTMLElementTagNameMap[K] {
  const node=document.createElement(tag); if(className) node.className=className; if(text!==undefined)node.textContent=text; return node;
}
function get<T extends HTMLElement=HTMLElement>(id:string):T { const node=document.getElementById(id); if(!node)throw new Error(`Missing control: ${id}`); return node as T; }
function show(id:string,visible:boolean):void {get(id).hidden=!visible;}
function value(id:string):string{return get<HTMLInputElement>(id).value;}
function checked(id:string):boolean{return get<HTMLInputElement>(id).checked;}
function errorMessage(error:unknown):string {return error instanceof Error?error.message:String(error);}
function commitTooltip(commit:Commit):string {return `${commit.message||commit.subject}\n\n${commit.sha}\n${commit.author} · ${commit.date}`;}
function store(key:string,data:string):void {try{localStorage.setItem(key,data);}catch{/* Private browser storage can be unavailable. */}}
function recall(key:string):string {try{return localStorage.getItem(key)??'';}catch{return '';}}
async function api<T>(path:string,options:RequestInit={}):Promise<T> {
  let response:Response;
  try {response=await fetch(path,{...options,headers:{'Content-Type':'application/json',...options.headers}});}catch{throw new Error('The local server is unavailable. Check the connection and try again.');}
  let result:unknown;
  try{result=await response.json();}catch{throw new Error(`Invalid server response (${response.status}).`);}
  if(!response.ok)throw new Error((result as {error?:string}).error??`Server error (${response.status}).`);
  return result as T;
}
function notify(message=''):void {get('global-error').textContent=message;show('global-error',!!message);}
function option(text:string,value:string):HTMLOptionElement {const node=element('option','',text);node.value=value;return node;}
function button(text:string,action:()=>void,className=''):HTMLButtonElement {const node=element('button',className,text);node.type='button';node.addEventListener('click',action);return node;}
const statusNames:Record<string,string>={added:'Added',removed:'Removed',changed:'Changed',unchanged:'Unchanged',queued:'Queued',running:'Processing',ready:'Ready',error:'Error'};
const defaults=new Set(['F.Cu','B.Cu','F.SilkS','B.SilkS','Edge.Cuts']);
let roots:string[]=[],repo='',projects:Project[]=[],commits:Commit[]=[],commitMore=false,commitLoading=false;
const refreshingRemotes=new Set<string>();
const recentSources=new Map<string,Source>();
let remoteRequest=0,remoteMutation=0,recentRequest=0;
let remoteRepos:Remote[]=[],pendingRemote='',sourceInfo:Source={},remoteSubmitting=false;
let repoRequest=0,commitRequest=0,jobRequest=0,browseRequest=0;
let jobs:Job[]=[],selectedJob='',manifest:Manifest|null=null,tab:MainTab='sch',mode:Mode='overlay',componentType:Kind='sch';
let selectedFiles:Record<Kind,string>={sch:'',pcb:''},pageId='',visibleLayers=new Set<string>(),activeLayer='';
const fileViews=new Map<string,{page:string;layers:Set<string>;active:string}>();
let activeFileId='';
let zoom=1,pan={x:0,y:0},browseData:Browse|null=null,pollTimer:ReturnType<typeof setTimeout>|undefined;
let selectionLoading=false,lastJobStamp='';
const expanded=new Set<string>();
let resizeObserver:ResizeObserver|undefined;

function workflowStatus(message:string,isError=false):void {get('workflow-status').textContent=message;get('workflow-status').classList.toggle('error-text',isError);}
function updateGenerate():void {get<HTMLButtonElement>('generate').disabled=!repo||!value('project')||!value('base-ref').trim()||!value('head-ref').trim();}
async function refreshRepos():Promise<void>{
  const request=++recentRequest,mutation=remoteMutation;
  const result=await api<{repos:(Source & {path:string;used:string})[]}>('/api/repos');
  if(request!==recentRequest||mutation!==remoteMutation)return;
  recentSources.clear();result.repos.forEach(item=>recentSources.set(item.path,item));
  const select=get<HTMLSelectElement>('recent-repos');select.replaceChildren(option('Select a repository…',''));
  result.repos.forEach(item=>select.append(option(repositoryLabel(item),item.path)));
}
async function openRepo(path:string,preserveProject=false):Promise<void>{
  if(!path.trim())return;
  if(path.trim()===sourceInfo.source_url&&repo)path=repo;
  const previousProject=preserveProject?value('project'):'';
  const request=++repoRequest;++commitRequest;repo='';sourceInfo={};projects=[];commits=[];
  get<HTMLSelectElement>('project').replaceChildren(option('Loading projects…',''));get<HTMLSelectElement>('project').disabled=true;
  get<HTMLButtonElement>('repo-load').disabled=true;get('commit-list').replaceChildren(element('p','empty-small','Loading commits…'));updateGenerate();workflowStatus('Opening repository…');
  try {
    const result=await api<Source & {path:string;projects:Project[]}>('/api/repos',{method:'POST',body:JSON.stringify({path:path.trim()})});
    if(request!==repoRequest)return;
    repo=result.path;sourceInfo=result;projects=result.projects;get<HTMLInputElement>('repo-path').value=repositoryLabel(result);store('kicaddiffview.repo',repo);
    const select=get<HTMLSelectElement>('project');select.replaceChildren();projects.forEach(project=>select.append(option(project.path,project.path)));
    if(!projects.length)select.append(option('No KiCad projects in this repository',''));
    if(previousProject&&projects.some(project=>project.path===previousProject))select.value=previousProject;
    select.disabled=!projects.length;
    workflowStatus(projects.length?'Select two revisions to continue.':'No KiCad projects found in this repository.',!projects.length);
    updateGenerate();void refreshRepos().catch(error=>notify(errorMessage(error)));await loadCommits(false);
  } catch(error){if(request===repoRequest){workflowStatus(errorMessage(error),true);get('commit-list').replaceChildren(element('p','empty-small','Unable to load commits.'));get<HTMLSelectElement>('project').replaceChildren(option('Open a repository',''));}}
  finally{if(request===repoRequest)get<HTMLButtonElement>('repo-load').disabled=false;}
}
async function loadCommits(append=false):Promise<void>{
  const request=++commitRequest;
  if(!repo||!value('project')){commitLoading=false;commits=[];renderCommits();return;}
  commitLoading=true;
  if(!append){commits=[];get('commit-list').replaceChildren(element('p','empty-small','Loading commits…'));}
  get<HTMLButtonElement>('commits-more').disabled=true;
  const query=new URLSearchParams({repo,project:value('project'),all:checked('all-commits')?'1':'0',q:value('commit-query'),offset:String(append?commits.length:0)});
  try {
    const result=await api<{commits:Commit[];more:boolean}>(`/api/commits?${query}`);
    if(request!==commitRequest)return;
    commits=append?[...commits,...result.commits]:result.commits;commitMore=result.more;renderCommits();
  }catch(error){if(request===commitRequest){workflowStatus(errorMessage(error),true);if(!append)get('commit-list').replaceChildren(button('Reload commits',()=>void loadCommits(false),'secondary wide'));}}
  finally{if(request===commitRequest){commitLoading=false;get<HTMLButtonElement>('commits-more').disabled=false;}}
}
function renderCommits():void {
  const list=get('commit-list');list.replaceChildren();
  if(!commits.length)list.append(element('p','empty-small','No matching commits.'));
  commits.forEach(commit=>{
    const row=element('div','commit-row'),info=element('div','commit-info');
    row.title=commitTooltip(commit);
    info.append(element('span','commit-subject',commit.subject));const meta=element('span','commit-meta',`${commit.sha.slice(0,8)} · ${commit.author} · ${commit.date.slice(0,10)}`);info.append(meta);row.append(info);
    const choices=element('div','commit-choices');(['base','head'] as const).forEach(side=>{const input=element('input');input.type='radio';input.name=`commit-${side}`;input.value=commit.sha;input.checked=value(`${side}-ref`)===commit.sha;input.setAttribute('aria-label',`${side==='base'?'Old':'New'} revision: ${commit.subject}, ${commit.sha.slice(0,8)}`);input.addEventListener('change',()=>{get<HTMLInputElement>(`${side}-ref`).value=commit.sha;updateGenerate();});choices.append(input);});row.append(choices);list.append(row);
  });show('commits-more',commitMore);
}
async function generate():Promise<void>{
  if(!repo||!value('project'))return;
  const input={repo,...(sourceInfo.remote_repo_id?{remote_repo_id:sourceInfo.remote_repo_id,source_url:sourceInfo.source_url}:{}),project:value('project'),base:value('base-ref').trim(),head:value('head-ref').trim()};
  get<HTMLButtonElement>('generate').disabled=true;workflowStatus('Starting comparison…');notify();
  try{const job=await api<Job>('/api/comparisons',{method:'POST',body:JSON.stringify(input)});jobs=[job,...jobs.filter(item=>item.id!==job.id)];renderHistory();await selectJob(job.id);workflowStatus('The comparison has started. You can continue changing the settings.');}
  catch(error){workflowStatus(errorMessage(error),true);}finally{updateGenerate();}
}
async function retrySelectedJob():Promise<void>{
  const original=jobs.find(job=>job.id===selectedJob);
  if(!original||original.status!=='error'){if(selectedJob)await selectJob(selectedJob);return;}
  const retry=get<HTMLButtonElement>('job-retry');retry.disabled=true;notify();
  try{const job=await api<Job>('/api/comparisons',{method:'POST',body:JSON.stringify(original.input)});jobs=[job,...jobs.filter(item=>item.id!==job.id)];renderHistory();await selectJob(job.id);}
  catch(error){notify(errorMessage(error));}finally{retry.disabled=false;}
}
function renderHistory():void{
  const list=get('history-list');list.replaceChildren();
  if(!jobs.length)list.append(element('p','empty-small','No saved comparisons yet.'));
  jobs.forEach(job=>{
    const row=element('div',`history-row${job.id===selectedJob?' selected':''}`);
    const open=button('',()=>void selectJob(job.id),'history-open');
    open.append(element('strong','',job.input.project.split('/').pop()||job.input.project));
    open.append(element('span','history-source',repositoryLabel(job.input)));
    open.append(element('span','history-refs',`${job.input.base.slice(0,10)} → ${job.input.head.slice(0,10)}`));
    const meta=element('span','history-meta');meta.append(element('span',`job-state state-${job.status}`,statusNames[job.status]),element('span','',new Date(job.created).toLocaleString('en-GB',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})));open.append(meta);
    row.append(open);const remove=button('×',()=>void deleteJob(job),'history-delete');remove.setAttribute('aria-label',`Delete comparison: ${job.input.project}`);remove.title='Delete comparison';remove.disabled=job.status==='queued'||job.status==='running';row.append(remove);list.append(row);
  });
}
async function deleteJob(job:Job):Promise<void>{
  if(job.status==='running'||job.status==='queued')return;
  if(!window.confirm(`Delete this saved comparison?\n${job.input.project}\n${job.input.base} → ${job.input.head}`))return;
  try{await api(`/api/comparisons/${encodeURIComponent(job.id)}`,{method:'DELETE'});jobs=jobs.filter(item=>item.id!==job.id);if(selectedJob===job.id){++jobRequest;selectedJob='';manifest=null;lastJobStamp='';store('kicaddiffview.job','');history.replaceState(null,'',location.pathname+location.search);show('welcome',true);show('job-progress',false);show('result',false);}renderHistory();}
  catch(error){notify(errorMessage(error));}
}
async function selectJob(id:string,background=false):Promise<void>{
  const request=++jobRequest;selectedJob=id;selectionLoading=true;renderHistory();
  if(!background){manifest=null;show('welcome',false);show('result',false);show('job-progress',true);get('job-title').textContent='Loading comparison';get('job-message').textContent='';show('job-spinner',true);show('job-retry',false);store('kicaddiffview.job',id);history.replaceState(null,'',`#comparison=${encodeURIComponent(id)}`);}
  try{
    const job=await api<Job>(`/api/comparisons/${encodeURIComponent(id)}`);
    if(request!==jobRequest||selectedJob!==id)return;
    jobs=[job,...jobs.filter(item=>item.id!==id)].sort((a,b)=>b.created.localeCompare(a.created));lastJobStamp=`${job.status}:${job.updated}`;renderHistory();
    if(job.status==='ready'&&job.result){if(!manifest||manifest.id!==job.result.id){manifest=job.result;selectedFiles={sch:'',pcb:''};activeFileId='';fileViews.clear();pageId='';visibleLayers.clear();expanded.clear();zoom=1;pan={x:0,y:0};}show('welcome',false);show('job-progress',false);show('result',true);renderResult();}
    else{manifest=null;show('result',false);show('job-progress',true);show('job-spinner',job.status!=='error');get('job-title').textContent=job.status==='error'?'Comparison failed':job.status==='queued'?'Comparison queued':'Generating comparison';get('job-message').textContent=job.error||job.progress||'Processing…';show('job-retry',job.status==='error');}
    if(job.status==='ready'&&!job.result){get('job-message').textContent='The result is not available yet. Retrying…';lastJobStamp='';}
  }catch(error){if(request===jobRequest){notify(errorMessage(error));lastJobStamp='';if(!manifest){get('job-title').textContent='Loading failed';get('job-message').textContent=errorMessage(error);show('job-spinner',false);show('job-retry',true);}}}
  finally{if(request===jobRequest)selectionLoading=false;}
}
async function poll():Promise<void>{
  try{
    if(shouldPollRemotes())await refreshRemotes().catch(error=>{get('remote-error').textContent=errorMessage(error);});
    const mutation=remoteMutation;
    const result=await api<{comparisons:Job[]}>('/api/comparisons');if(mutation!==remoteMutation)return;jobs=result.comparisons;renderHistory();
    const selected=jobs.find(job=>job.id===selectedJob);
    if(selected&&!selectionLoading&&`${selected.status}:${selected.updated}`!==lastJobStamp)await selectJob(selected.id,true);
  }catch(error){notify(errorMessage(error));}
  finally{pollTimer=setTimeout(()=>void poll(),2500);}
}


export function repositoryLabel(source:Source):string {return source.source_url||remoteRepos.find(item=>item.id===source.remote_repo_id||item.path===(source.repo||source.path))?.url||recentSources.get(source.repo||source.path||'')?.source_url||source.repo||source.path||'';}
function formatBytes(bytes:number):string {if(bytes<1024)return `${bytes} B`;const units=['KiB','MiB','GiB','TiB'];let size=bytes/1024,index=0;while(size>=1024&&index<units.length-1){size/=1024;index++;}return `${size.toFixed(1)} ${units[index]}`;}
function setBrowseTab(tab:'local'|'remote'):void {
  show('browse-local',tab==='local');show('browse-remote',tab==='remote');
  document.querySelectorAll<HTMLButtonElement>('[data-browse-tab]').forEach(node=>{const active=node.dataset.browseTab===tab;node.classList.toggle('active',active);node.setAttribute('aria-selected',String(active));});
}
function shouldPollRemotes():boolean {return get<HTMLDialogElement>('browse-dialog').open||!!pendingRemote||refreshingRemotes.size>0;}
async function refreshRemotes():Promise<void>{
  const request=++remoteRequest,mutation=remoteMutation;
  const result=await api<{repos:Remote[]}>('/api/remote-repos');if(request!==remoteRequest||mutation!==remoteMutation)return;remoteRepos=result.repos;renderRemotes();
  const pending=remoteRepos.find(item=>item.id===pendingRemote);
  if(pending?.usable&&pending.status!=='queued'&&pending.status!=='running'){pendingRemote='';get<HTMLDialogElement>('browse-dialog').close();await openRepo(pending.path);}
  else if(pending?.status==='error'){pendingRemote='';}
  for(const id of [...refreshingRemotes]){
    const refreshed=remoteRepos.find(item=>item.id===id);
    if(!refreshed||refreshed.status==='error'){refreshingRemotes.delete(id);continue;}
    if(refreshed.status==='ready'&&!refreshed.busy){refreshingRemotes.delete(id);if(refreshed.usable&&repo===refreshed.path)await openRepo(refreshed.path,true);}
  }
}
async function cloneRemote():Promise<void>{
  if(remoteSubmitting)return;
  const url=value('remote-url').trim();get('remote-error').textContent='';
  if(!/^https:\/\/[^\s]+$/i.test(url)){get('remote-error').textContent='Enter a public HTTPS Git repository URL.';return;}
  remoteSubmitting=true;get<HTMLButtonElement>('remote-clone').disabled=true;
  try{const remote=await api<Remote>('/api/remote-repos',{method:'POST',body:JSON.stringify({url})});pendingRemote=remote.id;await refreshRemotes();}
  catch(error){get('remote-error').textContent=errorMessage(error);}
  finally{remoteSubmitting=false;get<HTMLButtonElement>('remote-clone').disabled=false;}
}
async function refreshRemote(remote:Remote):Promise<void>{
  if(remote.busy)return;
  get('remote-error').textContent='';
  let started=false;
  try{await api<Remote>(`/api/remote-repos/${encodeURIComponent(remote.id)}/refresh`,{method:'POST'});started=true;refreshingRemotes.add(remote.id);await refreshRemotes();}
  catch(error){if(!started)refreshingRemotes.delete(remote.id);get('remote-error').textContent=errorMessage(error);}
}
function belongsToRemote(source:Source|undefined,remote:Remote):boolean {return !!source&&(source.remote_repo_id===remote.id||source.repo===remote.path||source.path===remote.path);}
function clearDeletedRemote(remote:Remote):void {
  ++remoteMutation;refreshingRemotes.delete(remote.id);
  if(pendingRemote===remote.id)pendingRemote='';
  if(repo===remote.path||sourceInfo.remote_repo_id===remote.id){
    ++repoRequest;++commitRequest;repo='';sourceInfo={};projects=[];commits=[];commitMore=false;commitLoading=false;
    get<HTMLInputElement>('repo-path').value='';get<HTMLSelectElement>('project').replaceChildren(option('Open a repository first',''));get<HTMLSelectElement>('project').disabled=true;
    get('commit-list').replaceChildren(element('p','empty-small','Repository commits will appear here.'));get<HTMLButtonElement>('repo-load').disabled=false;show('commits-more',false);workflowStatus('');updateGenerate();
  }
  if(recall('kicaddiffview.repo')===remote.path)store('kicaddiffview.repo','');
  const removed=jobs.filter(job=>belongsToRemote(job.input,remote));
  if(removed.some(job=>job.id===recall('kicaddiffview.job')))store('kicaddiffview.job','');
  if(removed.some(job=>job.id===selectedJob)||belongsToRemote(manifest??undefined,remote)){
    ++jobRequest;selectedJob='';manifest=null;lastJobStamp='';selectionLoading=false;store('kicaddiffview.job','');history.replaceState(null,'',location.pathname+location.search);show('welcome',true);show('job-progress',false);show('result',false);
  }
  jobs=jobs.filter(job=>!belongsToRemote(job.input,remote));renderHistory();
}
async function deleteRemote(remote:Remote):Promise<void>{
  if(remote.busy)return;
  if(!window.confirm(`Delete this downloaded repository and its saved comparisons?\n${remote.url}\n${remote.comparison_count} saved comparison(s)\nApproximately ${formatBytes(remote.delete_bytes)} will be deleted.`))return;
  get('remote-error').textContent='';
  try{await api(`/api/remote-repos/${encodeURIComponent(remote.id)}`,{method:'DELETE'});clearDeletedRemote(remote);await Promise.all([refreshRemotes(),refreshRepos()]);}
  catch(error){get('remote-error').textContent=errorMessage(error);}
}
function renderRemotes():void {
  const list=get('remote-list');list.replaceChildren();
  if(!remoteRepos.length)list.append(element('p','empty-small','No downloaded repositories yet.'));
  remoteRepos.forEach(remote=>{
    const row=element('article','remote-row'),heading=element('strong','remote-url',remote.url);row.append(heading);
    const refreshed=remote.last_refreshed?new Date(remote.last_refreshed).toLocaleString():'Never';
    row.append(element('p','remote-meta',`${statusNames[remote.status]||remote.status} · ${formatBytes(remote.size_bytes)} · Last refreshed: ${refreshed}`));
    if(remote.progress&&remote.busy)row.append(element('p','help',remote.progress));
    if(remote.error)row.append(element('p','error-text',remote.error));
    const actions=element('div','remote-actions');
    const open=button('Open',()=>{pendingRemote='';get<HTMLDialogElement>('browse-dialog').close();void openRepo(remote.path);},'secondary');open.disabled=!remote.usable||remote.busy;actions.append(open);
    const refresh=button(remote.status==='error'?'Retry':'Refresh',()=>void refreshRemote(remote),'secondary');refresh.disabled=remote.busy;actions.append(refresh);
    const remove=button('Delete repository',()=>void deleteRemote(remote),'text-button');remove.disabled=remote.busy;actions.append(remove);row.append(actions);list.append(row);
  });
}

async function browse(path:string):Promise<void>{
  const request=++browseRequest;get('browse-error').textContent='';get('browse-directories').replaceChildren(element('p','empty-small','Loading directory…'));get<HTMLButtonElement>('browse-select').disabled=true;
  try{const result=await api<Browse>(`/api/browse?${new URLSearchParams({path})}`);if(request!==browseRequest)return;browseData=result;renderBrowse();}
  catch(error){if(request===browseRequest){browseData=null;get('browse-directories').replaceChildren();get('browse-error').textContent=errorMessage(error);}}
}
function renderBrowse():void{
  if(!browseData)return;const data=browseData,list=get('browse-directories'),crumbs=get('browse-breadcrumbs');list.replaceChildren();crumbs.replaceChildren();
  const root=roots.filter(item=>data.path===item||data.path.startsWith(item.replace(/\/$/,'')+'/')).sort((a,b)=>b.length-a.length)[0];
  if(root){crumbs.append(button(root,()=>void browse(root),'breadcrumb'));let path=root.replace(/\/$/,'');const rest=data.path.slice(path.length).split('/').filter(Boolean);rest.forEach(part=>{path+='/'+part;const target=path;crumbs.append(element('span','','/'),button(part,()=>void browse(target),'breadcrumb'));});}
  else crumbs.append(element('span','',data.path));
  if(data.parent)list.append(button('↑ Parent directory',()=>void browse(data.parent!),'directory-row parent-directory'));
  data.directories.forEach(directory=>{const row=button('',()=>void browse(directory.path),'directory-row');row.append(element('span','folder-icon','▱'),element('span','',directory.name));if(directory.is_repo)row.append(element('span','repo-tag','Git'));list.append(row);});
  if(!data.directories.length)list.append(element('p','empty-small','No subdirectories.'));
  get('browse-current').textContent=data.repo?`Git repository: ${data.repo}`:'Select a directory containing a Git repository.';get<HTMLButtonElement>('browse-select').disabled=!data.repo;
}

function currentFile():GraphicFile|undefined {const kind=tab;if(!manifest||kind==='components')return;return manifest.files.find(file=>file.type===kind&&file.id===selectedFiles[kind]);}
function selectFile(reset=true):void {
  if(activeFileId)fileViews.set(activeFileId,{page:pageId,layers:new Set(visibleLayers),active:activeLayer});
  const file=currentFile();activeFileId=file?.id??'';if(reset){zoom=1;pan={x:0,y:0};}
  const saved=fileViews.get(activeFileId);
  pageId=saved?.page??file?.pages?.[0]?.id??'';visibleLayers=saved?new Set(saved.layers):new Set((file?.layers??[]).filter(layer=>defaults.has(layer.id)).map(layer=>layer.id));
  if(!saved&&!visibleLayers.size)visibleLayers=new Set((file?.layers??[]).map(layer=>layer.id));
  activeLayer=saved?.active??file?.layers?.[0]?.id??'';renderFileControls();renderGraphics();
}
function renderResult():void {
  if(!manifest)return;
  get('result-project').textContent=manifest.project;get('result-repo').textContent=repositoryLabel(manifest);
  for(const side of ['base','head'] as const){
    const node=get(`result-${side}`),commit=manifest.revisions?.[side];
    node.textContent=commit?.subject||manifest[side];node.title=commit?commitTooltip(commit):manifest[side];
  }
  get('sch-count').textContent=String(manifest.files.filter(file=>file.type==='sch').length);get('pcb-count').textContent=String(manifest.files.filter(file=>file.type==='pcb').length);
  get('component-count').textContent=String((manifest.components.sch?.length??0)+(manifest.components.pcb?.length??0));
  renderTab();
}
function renderTab():void {
  document.querySelectorAll<HTMLButtonElement>('[data-tab]').forEach(node=>{const active=node.dataset.tab===tab;node.classList.toggle('active',active);node.setAttribute('aria-pressed',String(active));});
  show('graphic-panel',tab!=='components');show('components-panel',tab==='components');
  if(tab==='components'){renderComponents();return;}
  const files=manifest?.files.filter(file=>file.type===tab)??[],select=get<HTMLSelectElement>('file-select');select.replaceChildren();
  files.forEach(file=>select.append(option(file.name,file.id)));select.disabled=!files.length;
  if(!files.length)select.append(option('No graphics of this type',''));
  if(!files.some(file=>file.id===selectedFiles[tab as Kind])){selectedFiles[tab]=files[0]?.id??'';select.value=selectedFiles[tab];selectFile();}
  else{select.value=selectedFiles[tab];if(activeFileId!==selectedFiles[tab])selectFile();else{renderFileControls();renderGraphics();}}
}
function renderFileControls():void {
  const file=currentFile(),select=get<HTMLSelectElement>('page-select');select.replaceChildren();show('page-select',tab==='sch'&&!!file?.pages?.length);
  file?.pages?.forEach(page=>select.append(option(`${page.changed?'● ':''}${page.name}`,page.id)));select.value=pageId;
  show('layers-panel',tab==='pcb'&&!!file);renderLayers();
}
function renderLayers():void {
  const layers=currentFile()?.layers??[],list=get('layer-list');list.replaceChildren();get('layers-count').textContent=`${layers.filter(layer=>visibleLayers.has(layer.id)).length}/${layers.length}`;
  layers.forEach(layer=>{
    const row=element('div',`layer-row${activeLayer===layer.id?' active':''}`),input=element('input');input.type='checkbox';input.checked=visibleLayers.has(layer.id);input.setAttribute('aria-label',`${layer.name} visible`);input.addEventListener('change',()=>{if(input.checked)visibleLayers.add(layer.id);else visibleLayers.delete(layer.id);renderLayers();renderGraphics();});
    const select=button(layer.name,()=>{activeLayer=layer.id;renderLayers();renderGraphics();},'layer-name');select.title=layer.name;select.setAttribute('aria-pressed',String(activeLayer===layer.id));row.append(input,select);if(layer.changed){const dot=element('span','layer-changed','●');dot.title='Changed layer';row.append(dot);}list.append(row);
  });
}
function getItems():Item[]{const file=currentFile();if(!file)return [];if(tab==='sch'){const item=file.pages?.find(page=>page.id===pageId);return item?[item]:[];}return (file.layers??[]).filter(layer=>visibleLayers.has(layer.id)).sort((a,b)=>Number(a.id===activeLayer)-Number(b.id===activeLayer));}
function resetView():void{zoom=1;pan={x:0,y:0};applyTransform();}
function planeSize():void {
  const file=currentFile();if(!file)return;
  const ratio=(file.canvas[2]>0&&file.canvas[3]>0)?file.canvas[2]/file.canvas[3]:1;
  document.querySelectorAll<HTMLElement>('.viewport').forEach(viewport=>{const plane=viewport.querySelector<HTMLElement>('.image-plane');if(!plane)return;const width=Math.max(1,viewport.clientWidth-36),height=Math.max(1,viewport.clientHeight-36),fittedWidth=Math.min(width,height*ratio);plane.style.width=`${fittedWidth}px`;plane.style.height=`${fittedWidth/ratio}px`;});
  applyTransform();
}
function applyTransform():void {document.querySelectorAll<HTMLElement>('.image-plane').forEach(node=>node.style.transform=`translate(calc(-50% + ${pan.x}px), calc(-50% + ${pan.y}px)) scale(${zoom})`);get('zoom-level').textContent=`${Math.round(zoom*100)}%`;}
function changeZoom(factor:number,anchor?:{x:number;y:number}):void{
  const next=Math.min(32,Math.max(.1,zoom*factor)),ratio=next/zoom;
  if(anchor){pan.x=anchor.x-(anchor.x-pan.x)*ratio;pan.y=anchor.y-(anchor.y-pan.y)*ratio;}zoom=next;applyTransform();
}
function addImage(parent:HTMLElement,path:string,opacity:number):void {
  if(!manifest)return;const image=element('img','layer-image');image.alt='';image.draggable=false;image.decoding='async';image.src=assetUrl(manifest.id,path);image.style.opacity=String(opacity);
  image.addEventListener('error',()=>{if(image.isConnected){get('graphic-status').textContent='An SVG file could not be loaded. Check the server log.';image.classList.add('image-failed');}});parent.append(image);
}
function imageSide(parent:HTMLElement,items:Item[],side:'before'|'after',opacity=1):boolean {
  let any=false;for(const item of items){const path=item[side];if(path){addImage(parent,path,opacity*(tab==='pcb'?.65:1));any=true;}}return any;
}
function makeViewport(items:Item[],side?:'before'|'after'):HTMLElement {
  const viewport=element('div','viewport'),plane=element('div','image-plane');viewport.tabIndex=0;viewport.setAttribute('aria-label',side==='before'?'Old revision drawing':side==='after'?'New revision drawing':'Comparison drawing');
  if(side){viewport.append(element('div',`viewport-label ${side==='before'?'label-old':'label-new'}`,side==='before'?'OLD':'NEW'));if(!imageSide(plane,items,side))viewport.append(element('div','missing-side',side==='before'?'This sheet or layer is absent from the old revision.':'This sheet or layer is absent from the new revision.'));}
  else if(mode==='colored'){items.forEach(item=>{if(item.colored)addImage(plane,item.colored,1);});if(!items.some(item=>item.colored))viewport.append(element('div','missing-side','No colored graphics to display.'));}
  else if(mode==='swipe'){
    const older=element('div','swipe-before');imageSide(older,items,'before');const newer=element('div','swipe-after');imageSide(newer,items,'after');plane.append(older,newer);const divider=element('div','swipe-divider');plane.append(divider);viewport.append(element('div','viewport-label label-old','OLD'),element('div','viewport-label label-new right-label','NEW'));
  }else{
    const alpha=Number(value('blend'))/100;imageSide(plane,items,'before',1-alpha);imageSide(plane,items,'after',alpha);
  }
  viewport.append(plane);
  viewport.addEventListener('wheel',event=>{event.preventDefault();const bounds=viewport.getBoundingClientRect();changeZoom(Math.exp(-event.deltaY*.0015),{x:event.clientX-bounds.left-bounds.width/2,y:event.clientY-bounds.top-bounds.height/2});},{passive:false});
  let drag:{id:number;x:number;y:number;px:number;py:number}|null=null;
  viewport.addEventListener('pointerdown',event=>{if(event.button!==0)return;drag={id:event.pointerId,x:event.clientX,y:event.clientY,px:pan.x,py:pan.y};viewport.setPointerCapture(event.pointerId);viewport.classList.add('dragging');});
  viewport.addEventListener('pointermove',event=>{if(!drag||drag.id!==event.pointerId)return;pan={x:drag.px+event.clientX-drag.x,y:drag.py+event.clientY-drag.y};applyTransform();});
  const stop=()=>{drag=null;viewport.classList.remove('dragging');};viewport.addEventListener('pointerup',stop);viewport.addEventListener('pointercancel',stop);viewport.addEventListener('lostpointercapture',stop);
  viewport.addEventListener('keydown',event=>{if(event.key==='+'||event.key==='='){event.preventDefault();changeZoom(1.2);}else if(event.key==='-'){event.preventDefault();changeZoom(1/1.2);}else if(event.key==='0'){event.preventDefault();resetView();}});
  return viewport;
}
function updateSwipe():void {
  const amount=value('swipe');get('swipe-value').textContent=`${amount}%`;
  const clips=swipeClips(Number(amount));
  document.querySelectorAll<HTMLElement>('.swipe-before').forEach(node=>node.style.clipPath=clips.before);
  document.querySelectorAll<HTMLElement>('.swipe-after').forEach(node=>node.style.clipPath=clips.after);
  document.querySelectorAll<HTMLElement>('.swipe-divider').forEach(node=>node.style.left=`${amount}%`);
}
function renderGraphics():void {
  document.querySelectorAll<HTMLButtonElement>('[data-mode]').forEach(node=>{node.classList.toggle('active',node.dataset.mode===mode);node.setAttribute('aria-pressed',String(node.dataset.mode===mode));});
  show('blend-control',mode==='overlay');show('swipe-control',mode==='swipe');show('color-legend',mode==='colored');
  const viewer=get('viewer');viewer.replaceChildren();viewer.classList.toggle('side-by-side',mode==='side');resizeObserver?.disconnect();
  const file=currentFile(),items=getItems();
  if(!file){viewer.append(element('div','empty-view','This comparison has no graphics of this type.'));get('graphic-status').textContent='';return;}
  if(!items.length){viewer.append(element('div','empty-view',tab==='pcb'?'Select at least one layer to display.':'No sheet to display.'));get('graphic-status').textContent=file.path;return;}
  if(mode==='side')viewer.append(makeViewport(items,'before'),makeViewport(items,'after'));else viewer.append(makeViewport(items));
  const missingOld=items.every(item=>!item.before),missingNew=items.every(item=>!item.after);
  get('graphic-status').textContent=`${file.path}${tab==='sch'?` · ${items[0].name}`:` · Layers: ${items.length}`}${missingOld?' · Old revision: sheet or layer absent':''}${missingNew?' · New revision: sheet or layer absent':''}`;
  updateSwipe();planeSize();if(typeof ResizeObserver!=='undefined'){resizeObserver=new ResizeObserver(planeSize);resizeObserver.observe(viewer);}
}

function componentOptions():ComponentOptions{return {query:value('component-query'),status:value('component-status'),includeDnp:checked('include-dnp'),includeBom:checked('include-bom'),placement:checked('include-placement')};}
function displayValue(value:unknown):string {if(value===null||value===undefined)return '—';if(typeof value==='boolean')return value?'yes':'no';return typeof value==='object'?JSON.stringify(value):String(value);}
function componentFields(record:ComponentRecord|null):Map<string,unknown>{
  const fields=new Map<string,unknown>();if(!record)return fields;
  fields.set('id',record.id);fields.set('reference',record.reference);fields.set('sheet',record.sheet);
  Object.entries(record.fields??{}).forEach(([key,val])=>fields.set(`fields.${key}`,val));
  Object.entries(record.flags??{}).forEach(([key,val])=>fields.set(`flags.${key}`,val));
  Object.entries(record.placement??{}).forEach(([key,val])=>fields.set(`placement.${key}`,val));return fields;
}
function fieldLabel(key:string):string {
  if(key==='id')return 'Identifier';if(key==='reference')return 'Reference';if(key==='sheet')return 'Sheet';
  if(key.startsWith('fields.'))return `Field · ${key.slice(7)}`;
  if(key.startsWith('flags.'))return `Flag · ${key.slice(6)}`;
  if(key.startsWith('placement.'))return `Placement · ${key.slice(10)}`;
  return key;
}
function detailsTable(component:ComponentDiff):HTMLElement {
  const container=element('div','component-details'),table=element('table','field-table'),head=element('thead'),headRow=element('tr');
  ['Field','Old','New'].forEach(text=>{const th=element('th','',text);th.scope='col';headRow.append(th);});head.append(headRow);table.append(head);
  const old=componentFields(component.before),newer=componentFields(component.after),body=element('tbody');let shown=0;
  for(const key of new Set([...old.keys(),...newer.keys()])){
    if(key.startsWith('placement.')&&!checked('include-placement'))continue;
    const before=old.get(key),after=newer.get(key),equal=JSON.stringify(before)===JSON.stringify(after);
    if(equal&&!checked('equal-fields'))continue;
    const row=element('tr',equal?'field-equal':'field-changed');row.append(element('th','',fieldLabel(key)),element('td','field-old',displayValue(before)),element('td','field-new',displayValue(after)));body.append(row);shown++;
  }
  // Preserve any supplied diff keys that are not present in either record.
  for(const change of component.changes??[]){if(old.has(change.field)||newer.has(change.field)||(change.category==='placement'&&!checked('include-placement')))continue;const row=element('tr','field-changed');row.append(element('th','',fieldLabel(change.field)),element('td','field-old',displayValue(change.before)),element('td','field-new',displayValue(change.after)));body.append(row);shown++;}
  table.append(body);container.append(table);if(!shown)container.append(element('p','empty-small','No differing fields. Use the checkbox above to show equal fields.'));return container;
}
function componentSummary(component:ComponentDiff):string {
  const fieldChanges=component.changes.filter(change=>change.category!=='placement'),placements=checked('include-placement')?component.changes.filter(change=>change.category==='placement'):[];
  const parts:string[]=[];
  if(fieldChanges.length)parts.push(fieldChanges.slice(0,3).map(change=>`${change.field}: ${displayValue(change.before)} → ${displayValue(change.after)}`).join(' · ')+(fieldChanges.length>3?` · +${fieldChanges.length-3} more`:''));
  if(placements.length)parts.push(`Placement changes: ${placements.length}`);
  if(!parts.length){const record=component.after??component.before;parts.push(Object.entries(record?.fields??{}).slice(0,3).map(([key,val])=>`${key}: ${val}`).join(' · ')||'No field changes');}
  return parts.join(' · ');
}
function renderComponents():void {
  document.querySelectorAll<HTMLButtonElement>('[data-component-type]').forEach(node=>{node.classList.toggle('active',node.dataset.componentType===componentType);node.setAttribute('aria-pressed',String(node.dataset.componentType===componentType));});
  const records=manifest?.components[componentType]??[],filtered=records.filter(record=>componentMatches(record,componentOptions())),body=get('component-body');body.replaceChildren();
  get('component-total').textContent=`${filtered.length} / ${records.length} components`;show('component-empty',!filtered.length);
  const fragment=document.createDocumentFragment();
  filtered.forEach(component=>{
    const key=`${componentType}:${component.id}`,row=element('tr',`component-row status-${component.status}`),reference=element('td'),toggle=button('',()=>{if(expanded.has(key))expanded.delete(key);else expanded.add(key);toggle.setAttribute('aria-expanded',String(expanded.has(key)));toggle.firstElementChild!.textContent=expanded.has(key)?'▾':'▸';let detail=row.nextElementSibling;if(expanded.has(key)){if(!detail?.classList.contains('detail-row')){const detailRow=element('tr','detail-row'),cell=element('td');cell.colSpan=3;cell.append(detailsTable(component));detailRow.append(cell);row.after(detailRow);}}else if(detail?.classList.contains('detail-row'))detail.remove();},'component-expand');
    toggle.setAttribute('aria-expanded',String(expanded.has(key)));toggle.append(element('span','expand-caret',expanded.has(key)?'▾':'▸'),element('strong','',component.reference));reference.append(toggle);
    const record=component.after??component.before,flags=element('span','component-flags');if(record?.flags.dnp)flags.append(element('span','flag','DNP'));if(record?.flags.bom_excluded)flags.append(element('span','flag','BOM−'));if(record?.flags.board_excluded)flags.append(element('span','flag','PCB−'));reference.append(flags);
    const status=element('td');status.append(element('span',`status-pill status-${component.status}`,statusNames[component.status]));const summary=element('td','component-summary',componentSummary(component));summary.title=summary.textContent??'';row.append(reference,status,summary);fragment.append(row);
    if(expanded.has(key)){const detailRow=element('tr','detail-row'),cell=element('td');cell.colSpan=3;cell.append(detailsTable(component));detailRow.append(cell);fragment.append(detailRow);}
  });body.append(fragment);
}

function debounce(action:()=>void,delay=220):()=>void{let timer:ReturnType<typeof setTimeout>;return ()=>{clearTimeout(timer);timer=setTimeout(action,delay);};}
function bind():void {
  get('repo-load').addEventListener('click',()=>void openRepo(value('repo-path')));get('repo-path').addEventListener('keydown',event=>{if(event.key==='Enter')void openRepo(value('repo-path'));});
  get('recent-repos').addEventListener('change',()=>{if(value('recent-repos'))void openRepo(value('recent-repos'));});
  get('project').addEventListener('change',()=>{++commitRequest;updateGenerate();void loadCommits();});get('all-commits').addEventListener('change',()=>{++commitRequest;void loadCommits();});
  const commitSearch=debounce(()=>void loadCommits());get('commit-query').addEventListener('input',()=>{++commitRequest;commitLoading=false;commitMore=false;show('commits-more',false);commitSearch();});
  get('commits-more').addEventListener('click',()=>{if(!commitLoading)void loadCommits(true);});
  ['base-ref','head-ref'].forEach(id=>get(id).addEventListener('input',()=>{updateGenerate();document.querySelectorAll<HTMLInputElement>(`input[name="commit-${id==='base-ref'?'base':'head'}"]`).forEach(input=>input.checked=input.value===value(id));}));
  get('generate').addEventListener('click',()=>void generate());get('job-retry').addEventListener('click',()=>void retrySelectedJob());
  get('browse-open').addEventListener('click',()=>{get<HTMLDialogElement>('browse-dialog').showModal();setBrowseTab('local');void browse(repo||(!value('repo-path').startsWith('https://')?value('repo-path'):'')||roots[0]||'');void refreshRemotes().catch(error=>{get('remote-error').textContent=errorMessage(error);});});get('browse-close').addEventListener('click',()=>get<HTMLDialogElement>('browse-dialog').close());get('browse-select').addEventListener('click',()=>{if(!browseData?.repo)return;get<HTMLDialogElement>('browse-dialog').close();void openRepo(browseData.repo);});
  document.querySelectorAll<HTMLButtonElement>('[data-browse-tab]').forEach(node=>node.addEventListener('click',()=>setBrowseTab(node.dataset.browseTab==='remote'?'remote':'local')));
  get('remote-clone').addEventListener('click',()=>void cloneRemote());get('remote-url').addEventListener('keydown',event=>{if(event.key==='Enter')void cloneRemote();});
  document.querySelectorAll<HTMLButtonElement>('[data-tab]').forEach(node=>node.addEventListener('click',()=>{tab=node.dataset.tab as MainTab;renderTab();}));
  document.querySelectorAll<HTMLButtonElement>('[data-mode]').forEach(node=>node.addEventListener('click',()=>{mode=node.dataset.mode as Mode;renderGraphics();}));
  get('file-select').addEventListener('change',()=>{if(tab==='components')return;selectedFiles[tab]=value('file-select');selectFile();});get('page-select').addEventListener('change',()=>{pageId=value('page-select');resetView();renderGraphics();});
  get('layers-all').addEventListener('click',()=>{visibleLayers=new Set((currentFile()?.layers??[]).map(layer=>layer.id));renderLayers();renderGraphics();});get('layers-none').addEventListener('click',()=>{visibleLayers.clear();renderLayers();renderGraphics();});
  get('blend').addEventListener('input',()=>{get('blend-value').textContent=`${value('blend')}%`;renderGraphics();});get('swipe').addEventListener('input',updateSwipe);
  get('zoom-in').addEventListener('click',()=>changeZoom(1.25));get('zoom-out').addEventListener('click',()=>changeZoom(.8));get('zoom-fit').addEventListener('click',resetView);
  document.querySelectorAll<HTMLButtonElement>('[data-component-type]').forEach(node=>node.addEventListener('click',()=>{componentType=node.dataset.componentType as Kind;renderComponents();}));
  get('component-query').addEventListener('input',debounce(renderComponents,120));['component-status','include-dnp','include-bom','include-placement','equal-fields'].forEach(id=>get(id).addEventListener('change',renderComponents));
  window.addEventListener('resize',planeSize);window.addEventListener('hashchange',()=>{const id=new URLSearchParams(location.hash.slice(1)).get('comparison');if(id&&id!==selectedJob)void selectJob(id);});
}
async function init():Promise<void>{
  bind();
  const config=api<{roots:string[];version:string}>('/api/config').then(result=>{roots=result.roots;get('version').textContent=`v${result.version}`;const list=get('browse-roots');list.replaceChildren();roots.forEach(root=>list.append(button(root,()=>void browse(root),'root-button')));});
  const repos=refreshRepos();
  const results=await Promise.allSettled([config,repos]);results.forEach(result=>{if(result.status==='rejected')notify(errorMessage(result.reason));});
  const storedRepo=recall('kicaddiffview.repo');if(storedRepo){get<HTMLInputElement>('repo-path').value=repositoryLabel({path:storedRepo});void openRepo(storedRepo);}
  const initialId=new URLSearchParams(location.hash.slice(1)).get('comparison')||recall('kicaddiffview.job');if(initialId)void selectJob(initialId);
  await poll();
}
if(typeof document!=='undefined')void init();
