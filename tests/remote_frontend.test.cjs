const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const load=name=>require(require.resolve(name,{paths:[path.resolve(__dirname,'../frontend')]}));
const babel=load('@babel/core'),plugins=[load('@babel/plugin-transform-typescript'),load('@babel/plugin-transform-modules-commonjs')];
const file=path.resolve(__dirname,'../frontend/src/app.ts');
const suffix=`
export function _setup(source, data, selected, current){repo=source;remoteRepos=data;jobs=selected?[{created:'2026-01-01',status:'ready',...selected,input:{project:'project',base:'old',head:'new',...selected.input}}]:[];selectedJob=selected?.id||'';manifest=current;}
export function _state(){return {repo,selectedJob,manifest,remoteRepos};}
export function _clear(remote){clearDeletedRemote(remote);}
export async function _refresh(){await refreshRemotes();}
export async function _recent(){await refreshRepos();}
export function _shouldPoll(){return shouldPollRemotes();}
export async function _manual(remote){await refreshRemote(remote);}
export function _render(data){remoteRepos=data;renderRemotes();}
export function _pending(id){pendingRemote=id;}
export function _stubOpen(action){openRepo=action;}
`;
const code=babel.transformSync(fs.readFileSync(file,'utf8')+suffix,{filename:file,plugins}).code;
const nodes=new Map(),values=new Map();
function node(){return {value:'',hidden:false,disabled:false,children:[],classList:{toggle(){}},replaceChildren(...items){this.children=items;},append(...items){this.children.push(...items);},setAttribute(){},addEventListener(){},close(){}};}
const ctx={exports:{},console,URLSearchParams,Set,Map,setTimeout,clearTimeout,localStorage:{getItem:key=>values.get(key)||'',setItem:(key,value)=>values.set(key,value)},history:{replaceState(...args){ctx.lastHistory=args;}},location:{pathname:'/',search:'',hash:'#comparison=job'},window:{confirm:()=>true}};
vm.runInNewContext(code,ctx);
ctx.document={getElementById(id){if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);},createElement:()=>node(),querySelectorAll:()=>[]};
const api=ctx.exports;
const remote={id:'abc',url:'https://example.com/design.git',path:'/managed/abc',status:'ready',usable:true,busy:false,size_bytes:123,comparison_count:1,delete_bytes:456};
(async()=>{
assert.equal(api.repositoryLabel({repo:remote.path,source_url:remote.url}),remote.url,'repository labels use public URL');
api._setup('/local/repo',[remote],{id:'local',input:{repo:'/local/repo'}},{id:'local',repo:'/local/repo'});
values.set('kicaddiffview.repo','/local/repo');values.set('kicaddiffview.job','local');
api._clear(remote);
assert.equal(api._state().repo,'/local/repo','deleting remote preserves unrelated source');
assert.equal(api._state().selectedJob,'local','deleting remote preserves unrelated result');
assert.equal(values.get('kicaddiffview.job'),'local');
api._setup(remote.path,[remote],{id:'job',input:{repo:remote.path,remote_repo_id:remote.id}},{id:'job',repo:remote.path,remote_repo_id:remote.id});
values.set('kicaddiffview.repo',remote.path);values.set('kicaddiffview.job','job');
api._clear(remote);
assert.equal(api._state().repo,'');assert.equal(api._state().selectedJob,'');assert.equal(api._state().manifest,null);
assert.equal(values.get('kicaddiffview.repo'),'');assert.equal(values.get('kicaddiffview.job'),'');
ctx.fetch=async()=>({ok:true,json:async()=>({repos:[{path:remote.path,source_url:remote.url,remote_repo_id:remote.id}]})});await api._recent();
api._setup('',[],null,null);assert.equal(api.repositoryLabel({path:remote.path}),remote.url,'restoring a recent remote shows its URL before opening');
api._render([{...remote,busy:true}]);assert.equal(nodes.get('remote-list').children[0].children.at(-1).children[0].disabled,true,'busy repository cannot open while refreshing');
let opened=[];api._stubOpen(async path=>opened.push(path));api._pending(remote.id);
ctx.fetch=async()=>({ok:true,json:async()=>({repos:[{...remote,status:'running',usable:false}]})});await api._refresh();assert.equal(opened.length,0,'running clone never opens');
ctx.fetch=async()=>({ok:true,json:async()=>({repos:[remote]})});await api._refresh();await api._refresh();assert.equal(opened.join(','),remote.path,'ready clone opens once across polls');
api._pending(remote.id);ctx.fetch=async()=>({ok:true,json:async()=>({repos:[{...remote,status:'error',error:'Refresh failed',usable:true}]})});await api._refresh();assert.equal(opened.length,2,'clone and open reuses usable cached repository after failed refresh');assert.equal(api._state().remoteRepos[0].error,'Refresh failed','opening cached data preserves refresh error');
api._pending('');nodes.get('browse-dialog').open=false;assert.equal(api._shouldPoll(),false,'closed dialog without pending work skips expensive repository listing');api._pending(remote.id);assert.equal(api._shouldPoll(),true);api._pending('');
api._setup(remote.path,[remote],null,null);opened=[];api._stubOpen(async (path,preserve)=>opened.push({path,preserve}));ctx.fetch=async path=>({ok:true,json:async()=>path.endsWith('/refresh')?{...remote,status:'running',busy:true}:{repos:[remote]}});await api._manual(remote);assert.equal(opened.length,1,'manual refresh reloads current repository after completion');assert.equal(opened[0].preserve,true,'refresh preserves current project and revision settings');await api._refresh();assert.equal(opened.length,1);
let finishPost;ctx.fetch=path=>path.endsWith('/refresh')?new Promise(resolve=>finishPost=resolve):Promise.resolve({ok:true,json:async()=>({repos:[remote]})});const pendingPost=api._manual(remote);await api._refresh();ctx.fetch=async()=>({ok:true,json:async()=>({repos:[{...remote,status:'running',busy:true}]})});finishPost({ok:true,json:async()=>({...remote,status:'running',busy:true})});await pendingPost;assert.equal(api._shouldPoll(),true,'old ready poll during refresh submission cannot stop completion tracking');
let finishStale;ctx.fetch=()=>new Promise(resolve=>finishStale=resolve);const stale=api._refresh();api._clear(remote);
ctx.fetch=async()=>({ok:true,json:async()=>({repos:[]})});await api._refresh();finishStale({ok:true,json:async()=>({repos:[remote]})});await stale;assert.equal(api._state().remoteRepos.length,0,'a stale pre-delete response cannot restore deleted repositories');
let finishRecent;ctx.fetch=()=>new Promise(resolve=>finishRecent=resolve);const staleRecent=api._recent();api._clear(remote);ctx.fetch=async()=>({ok:true,json:async()=>({repos:[]})});await api._recent();finishRecent({ok:true,json:async()=>({repos:[{path:remote.path,source_url:remote.url}]})});await staleRecent;assert.equal(nodes.get('recent-repos').children.length,1,'stale recent response cannot restore deleted source');
console.log('PASS: remote URL labels, selective deletion cleanup, and clone readiness polling');
})().catch(error=>{console.error(error);process.exitCode=1;});
