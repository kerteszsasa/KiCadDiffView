const fs=require('fs'), vm=require('vm'), assert=require('assert/strict'), path=require('node:path');
const load=name=>require(require.resolve(name,{paths:[path.resolve(__dirname,'../frontend')]}));
const babel=load('@babel/core'), tsPlugin=load('@babel/plugin-transform-typescript'), cjsPlugin=load('@babel/plugin-transform-modules-commonjs');
const file=require('path').resolve(__dirname,'../frontend/src/app.ts');
let api={};
if(fs.existsSync(file)) { const code=babel.transformSync(fs.readFileSync(file,'utf8'),{filename:file,plugins:[tsPlugin,cjsPlugin]}).code; const ctx={exports:api,console,URLSearchParams,Set,Map,setTimeout,clearTimeout}; vm.runInNewContext(code,ctx); }
assert.equal(typeof api.assetUrl,'function','safe asset URL helper exists');
assert.equal(api.assetUrl('job 1','folder/a #?.svg'),'/results/job%201/folder/a%20%23%3F.svg');
const old={id:'1',reference:'R1',sheet:'Main',fields:{Value:'10k','Custom key':'special'},flags:{dnp:false,bom_excluded:false,board_excluded:false},placement:{x:1,y:2,rotation:0,side:'F'}};
const moved={id:'1',reference:'R1',status:'changed',before:old,after:old,changes:[{field:'x',before:1,after:2,category:'placement'}]};
const options={query:'',status:'all',includeDnp:true,includeBom:true,placement:false};
assert.equal(api.componentMatches(moved,options),false,'placement-only changes can be hidden');
assert.equal(api.componentMatches({...moved,changes:[...moved.changes,{field:'Value',before:'10k',after:'1k',category:'field'}]},options),true,'field+placement changes remain');
assert.equal(api.componentMatches({...moved,status:'unchanged',changes:[]},{...options,query:'special'}),true,'search indexes arbitrary fields');
assert.equal(api.componentMatches({...moved,after:{...old,flags:{...old.flags,dnp:true}}},{...options,placement:true,includeDnp:false}),false,'DNP filter uses either record');
assert.equal(api.componentMatches({...moved,after:{...old,flags:{...old.flags,bom_excluded:true}}},{...options,placement:true,includeBom:false}),false,'BOM filter uses either record');
assert.equal(api.componentMatches({...moved,status:'removed',after:null},{...options,placement:true,status:'added'}),false,'status filtering');
console.log('PASS: asset encoding and component filter behaviors');
const source=fs.readFileSync(file,'utf8');
const testable=babel.transformSync(source+'\nexport function _graphicItems(data,currentTab,fileId,page,visible,active){manifest=data;tab=currentTab;selectedFiles={sch:fileId,pcb:fileId};pageId=page;visibleLayers=new Set(visible);activeLayer=active;return getItems();}',{filename:file,plugins:[tsPlugin,cjsPlugin]}).code;
const graphics={};vm.runInNewContext(testable,{exports:graphics,console,URLSearchParams,Set,Map,setTimeout,clearTimeout});
const pages=[{id:'main',name:'Main',before:'main-old.svg',after:'main-new.svg',colored:'main-diff.svg'},{id:'added',name:'Added',before:null,after:'added.svg',colored:'added-diff.svg'}];
let items=graphics._graphicItems({files:[{id:'sch',type:'sch',pages}]},'sch','sch','added',[], '');
assert.equal(items.length,1);assert.equal(items[0].before,null,'added page retains empty old side');assert.equal(items[0].after,'added.svg');
items=graphics._graphicItems({files:[{id:'sch',type:'sch',pages}]},'sch','sch','missing',[], '');assert.equal(items.length,0,'missing selection never falls back to another page');
const layers=[{id:'cu',name:'F.Cu'},{id:'custom',name:'My fabrication layer'},{id:'edge',name:'Edge.Cuts'}];
items=graphics._graphicItems({files:[{id:'pcb',type:'pcb',layers}]},'pcb','pcb','',['cu','custom','edge'],'custom');
assert.equal(items.length,3,'custom manifest layers retained');assert.equal(items[2].id,'custom','active layer rendered last');
console.log('PASS: schematic page identity and complete PCB layer ordering');

const initCode=babel.transformSync(source+'\nexport function _initialLayers(data){manifest=data;tab="pcb";selectedFiles={sch:"",pcb:"pcb"};fileViews.clear();activeFileId="";renderFileControls=()=>{};renderGraphics=()=>{};selectFile();return [...visibleLayers];}',{filename:file,plugins:[tsPlugin,cjsPlugin]}).code;
const initial={};vm.runInNewContext(initCode,{exports:initial,console,URLSearchParams,Set,Map,setTimeout,clearTimeout});
const chosen=initial._initialLayers({files:[{id:'pcb',type:'pcb',layers:[{id:'F.Cu',name:'Top Layer'},{id:'B.Cu',name:'Bottom Layer'},{id:'Edge.Cuts',name:'Edge.Cuts'},{id:'User.1',name:'Mechanical'}]}]});
assert.equal(chosen.join(','),'F.Cu,B.Cu,Edge.Cuts','default visibility must use stable IDs, not custom display labels');
console.log('PASS: default visibility supports custom PCB layer names');

assert.equal(typeof api.swipeClips,'function','Swipe needs complementary clipping for transparent SVGs');
assert.equal(api.swipeClips(35).before,'inset(0 65% 0 0)');
assert.equal(api.swipeClips(35).after,'inset(0 0 0 35%)');
assert.equal(api.swipeClips(-10).before,'inset(0 100% 0 0)');
assert.equal(api.swipeClips(110).after,'inset(0 0 0 100%)');
console.log('PASS: transparent Swipe halves are complementary');

const detailCode=babel.transformSync(source+'\nexport function _detail(c){return detailsTable(c);}',{filename:file,plugins:[tsPlugin,cjsPlugin]}).code;
const detailApi={};const detailContext={exports:detailApi,console,URLSearchParams,Set,Map,setTimeout,clearTimeout};
vm.runInNewContext(detailCode,detailContext);
detailContext.document={createElement(tag){return {tag,children:[],textContent:'',append(...items){this.children.push(...items);}};},getElementById(id){return {checked:id==='include-placement'};}};
const changedValue={id:'1',reference:'R1',status:'changed',before:old,after:{...old,fields:{...old.fields,Value:'4k7'}},changes:[{field:'fields.Value',before:'10k',after:'4k7',category:'field'}]};
const detail=detailApi._detail(changedValue);
const body=detail.children[0].children.find(node=>node.tag==='tbody');
assert.equal(body.children.length,1,'a changed property must appear once, not once per key representation');
console.log('PASS: component detail fields are not duplicated');
require('./theme.test.cjs');

require('./remote_frontend.test.cjs');
