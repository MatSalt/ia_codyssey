import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {writeFile,unlink} from 'node:fs/promises';
const stubs={react:`export const useId=()=>"caption-test";export const useState=v=>globalThis.h.state(v);export const useRef=v=>globalThis.h.ref(v);export const useEffect=(f,d)=>globalThis.h.effect(f,d);`,
'react-router':`export const Link='a';export const useNavigate=()=>()=>{};export const useParams=()=>({albumId:'album'});`,
'@tanstack/react-query':`export const useQuery=()=>({data:globalThis.detail});export const useQueryClient=()=>({setQueryData(){},invalidateQueries:async()=>{}});`,
'useSignedMedia':`export const useSignedMedia=()=>({access:[],failed(){},refresh(){}});`,
'usePrivateRequest':`export const usePrivateRequest=()=>({current:{signal:new AbortController().signal}});`,
'useUnsavedGuard':`export const useUnsavedGuard=()=>{};`,
'client':`export class ApiError extends Error{};export const errorText=e=>e.message;export const api=(...a)=>globalThis.request(...a);`};
await build({entryPoints:['src/features/review/ReviewEditor.tsx'],bundle:true,platform:'node',format:'esm',packages:'external',jsx:'automatic',outfile:'review-check.mjs',plugins:[{name:'isolated-state',setup(b){b.onResolve({filter:/.*/},args=>{const k=Object.keys(stubs).find(k=>args.path===k||args.path.endsWith('/'+k));if(k)return {path:k,namespace:'test'};});b.onLoad({filter:/.*/,namespace:'test'},a=>({contents:stubs[a.path]}));}}]});
globalThis.window=new EventTarget();window.confirm=()=>true;window.location={origin:'http://localhost'};
const {ReviewEditor}=await import('../review-check.mjs');
function nodes(node,out=[]){if(!node||typeof node!=='object')return out;if(Array.isArray(node)){node.forEach(n=>nodes(n,out));return out;}out.push(node);nodes(node.props?.children,out);return out;}
function setup(){let cursor=0;const cells=[],effects=[];globalThis.h={state(v){const i=cursor++;if(!(i in cells))cells[i]=typeof v==='function'?v():v;return [cells[i],n=>cells[i]=typeof n==='function'?n(cells[i]):n];},ref(v){const i=cursor++;return cells[i]??={current:v};},effect(f,d){const i=cursor++;if(!cells[i]||d?.some((x,j)=>x!==cells[i][j])){cells[i]=d;effects.push(f);}}};
 globalThis.detail={detail:{album:{id:'album',status:'review_ready',version:1},generation_mode:'local_fake',pages:['a','b'].map((id,i)=>({id,position:i+1,caption_text:id,version:1,thumbnail:null,result:null}))},media_access:[]};
 function render(){cursor=0;const tree=ReviewEditor({userId:'u'});while(effects.length)effects.shift()();return nodes(tree);}
 render();return {render,find(name){return render().find(n=>n.type?.name===name);}};
}
test('switching photos preserves each draft and saving A never overwrites B',async()=>{
 const h=setup();let editor=h.find('CaptionEditor');assert.ok(editor,'one-page CaptionEditor is rendered');editor.props.onChange('A edited');
 let strip=h.find('ThumbnailStrip');strip.props.onSelect('b');assert.equal(h.find('CaptionEditor').props.value,'b');h.find('CaptionEditor').props.onChange('B edited');
 h.find('ThumbnailStrip').props.onSelect('a');assert.equal(h.find('CaptionEditor').props.value,'A edited');
 let finish;globalThis.request=()=>new Promise(r=>finish=r);
 const actions=nodes(h.find('CaptionEditor').props.actions);const save=actions.find(n=>n.props?.children==='이 글귀 저장');const pending=save.props.onClick();
 h.find('ThumbnailStrip').props.onSelect('b');finish({page:{...detail.detail.pages[0],caption_text:'A edited',version:2},album_version:2});await pending;await new Promise(r=>setTimeout(r,0));
 assert.equal(h.find('CaptionEditor').props.value,'B edited');
 const publish=h.render().find(n=>n.props?.children==='사진첩 완성');assert.equal(publish.props.disabled,true,'hidden dirty draft blocks completion');
});
test.after(()=>unlink('review-check.mjs'));
