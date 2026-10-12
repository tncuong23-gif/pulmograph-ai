import {readFileSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {JSDOM} from 'jsdom';
import {afterEach,expect,it,vi} from 'vitest';

const backend=resolve(process.cwd(),'../backend/app');
const web=join(backend,'data_workspace/web');
const html=readFileSync(join(web,'index.html'),'utf8');
const script=readFileSync(join(web,'app.js'),'utf8');
const embed=readFileSync(join(web,'embed.js'),'utf8');
const opened:JSDOM[]=[];
const reply=(data:unknown)=>({ok:true,json:async()=>data,text:async()=>JSON.stringify(data)});
const overview={checked_at:'2026-10-10T00:00:00Z',modules:{rag:{state:'ready',mode:'live',stats:{documents:7,chunks:20,propositions:9,vectors:29},chunking:'semantic',message:'MongoDB và Qdrant'},kg:{state:'unavailable',message:'Chưa kết nối',vector:{state:'missing',message:'Chưa có collection'}},context:{state:'ready',mode:'memory',stats:{patients:1,sessions:2,turns:5,facts:3},message:'Bộ nhớ tạm'}}};
const job={job_id:'KG_PARTIAL',module:'kg',mode:'commit',status:'completed',started_at:'2026-10-10T01:00:00Z',total:2,processed:2,completed:1,failed:0,skipped:0,partial:1,needs_review:0};
const jobs={items:[job,{...job,job_id:'CONTEXT_PREVIEW',module:'context',mode:'preview',partial:0}],errors:{},active:{}};
function domFor(source:string,url:string){const dom=new JSDOM(source,{url,runScripts:'outside-only',pretendToBeVisual:true});opened.push(dom);return dom;}
function boot(hash='#overview',query='',mobile=false){
  const dom=domFor(html,'http://localhost/data'+query+hash),w=dom.window;
  w.matchMedia=vi.fn().mockReturnValue({matches:mobile});
  w.fetch=vi.fn(async(url:string,options?:RequestInit)=>{expect(options?.method).toBeUndefined();if(url.endsWith('/overview'))return reply(overview);if(url.endsWith('/jobs'))return reply(jobs);if(url.endsWith('/config'))return reply({frontend_origins:['http://localhost:5174']});throw Error(url);});
  w.eval(script);return {dom,w,d:w.document,fetch:w.fetch};
}
function route(w:JSDOM['window'],hash:string){w.history.replaceState({},'',hash);w.dispatchEvent(new w.HashChangeEvent('hashchange'));}
function ready(w:JSDOM['window'],frame:HTMLIFrameElement,origin='http://localhost',source=frame.contentWindow){w.dispatchEvent(new w.MessageEvent('message',{origin,source,data:{type:'medical-data:ready'}}));}
afterEach(()=>{for(const dom of opened.splice(0)){dom.window.dispatchEvent(new dom.window.Event('beforeunload'));dom.window.close();}vi.restoreAllMocks();});

it('shows live metrics, unknown counts and memory mode without writing',async()=>{
  const {d,fetch}=boot();
  await vi.waitFor(()=>expect(d.querySelectorAll('.module-card')).toHaveLength(3));
  expect(d.querySelector('[data-module=rag] .metric strong')?.textContent).toBe('7');
  expect(d.querySelector('[data-module=kg] .metric strong')?.textContent).toBe('—');
  expect(d.querySelector('[data-module=context] .badge')?.textContent).toBe('Bộ nhớ tạm');
  expect(fetch).toHaveBeenCalledTimes(2);
});

it('keeps module frames and selected inputs alive across tabs and module switches',()=>{
  const {w,d}=boot('#rag/import');
  const frame=d.querySelector('iframe')!;
  frame.contentDocument!.open();frame.contentDocument!.write('<html data-workspace-embedded="true"><body></body></html>');frame.contentDocument!.close();
  const post=vi.spyOn(frame.contentWindow!,'postMessage');ready(w,frame);
  const input=frame.contentDocument!.createElement('input');input.value='selected-state';frame.contentDocument!.body.append(input);
  route(w,'#rag/search');expect(d.querySelectorAll('iframe')).toHaveLength(1);
  expect(post).toHaveBeenLastCalledWith({type:'medical-data:view',view:'search',job:null},'http://localhost');
  route(w,'#kg/import');expect(d.querySelectorAll('iframe')).toHaveLength(2);expect(frame.hidden).toBe(true);
  route(w,'#rag/documents');expect(d.querySelector('iframe')).toBe(frame);expect(frame.hidden).toBe(false);expect(input.value).toBe('selected-state');
});

it('filters attention jobs and opens the exact selected report without importing',async()=>{
  const {w,d}=boot('#reports');
  await vi.waitFor(()=>expect(d.querySelectorAll('#jobsTable tbody tr')).toHaveLength(2));
  const filter=d.getElementById('statusFilter') as HTMLSelectElement;filter.value='attention';filter.dispatchEvent(new w.Event('change'));
  expect(d.querySelectorAll('#jobsTable tbody tr')).toHaveLength(1);
  expect(d.querySelector<HTMLAnchorElement>('#jobsTable a[href$="kind=errors"]')?.pathname).toBe('/api/v1/imports/kg/jobs/KG_PARTIAL/report');
  d.querySelector<HTMLButtonElement>('#jobsTable button')!.click();
  await vi.waitFor(()=>expect(w.location.hash).toBe('#kg/import?job=KG_PARTIAL'));
  await vi.waitFor(()=>expect(d.querySelector<HTMLIFrameElement>('iframe')?.src).toContain('job=KG_PARTIAL'));
});

it('ignores invalid job paths and messages from other origins or windows',()=>{
  const {w,d}=boot('#kg/import?job=bad%2Fid'),frame=d.querySelector('iframe')!;
  expect(frame.src).not.toContain('job=');
  ready(w,frame,'https://untrusted.example');expect(d.getElementById('frameStatus')!.hidden).toBe(false);
  ready(w,frame,'http://localhost',w);expect(d.getElementById('frameStatus')!.hidden).toBe(false);
  ready(w,frame);expect(d.getElementById('frameStatus')!.hidden).toBe(true);
});

it('makes the mobile menu keyboard-accessible and closes it with Escape',()=>{
  const {w,d}=boot('#rag/import','',true),button=d.getElementById('toggleNav')!;
  expect(button.getAttribute('aria-expanded')).toBe('false');button.click();expect(button.getAttribute('aria-expanded')).toBe('true');
  d.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape'}));expect(button.getAttribute('aria-expanded')).toBe('false');expect(d.activeElement).toBe(button);
});

it('returns only to a configured frontend origin',async()=>{
  const good=boot('#rag/import','?return_to='+encodeURIComponent('http://localhost:5174/ignored?x=1'));
  await vi.waitFor(()=>expect(good.d.querySelector<HTMLAnchorElement>('#backToChat')!.href).toBe('http://localhost:5174/chat'));
  const bad=boot('#rag/import','?return_to='+encodeURIComponent('https://untrusted.example'));
  await vi.waitFor(()=>expect(bad.fetch).toHaveBeenCalledTimes(1));expect(bad.d.querySelector<HTMLAnchorElement>('#backToChat')!.href).toBe('http://localhost/');
});

it('shows a retry action when an embedded module returns an unavailable page',()=>{
  const {w,d}=boot('#kg/explore'),frame=d.querySelector('iframe')!;
  frame.dispatchEvent(new w.Event('load'));
  expect(d.getElementById('frameMessage')!.textContent).toContain('Chưa mở được module');expect(d.getElementById('retryFrame')!.hidden).toBe(false);
  ready(w,frame);expect(d.getElementById('frameStatus')!.hidden).toBe(true);
});

it('embedded RAG tabs accept navigation only from their own parent',async()=>{
  const dom=domFor('<!doctype html><button data-view="search"></button><button data-view="documents"></button>','http://localhost/modules/rag/?embed=1&view=search');const w=dom.window,d=w.document;
  const parent={postMessage:vi.fn()};Object.defineProperty(w,'parent',{value:parent});const search=vi.fn(),docs=vi.fn();
  d.querySelector('[data-view=search]')!.addEventListener('click',search);d.querySelector('[data-view=documents]')!.addEventListener('click',docs);
  w.eval(embed);await vi.waitFor(()=>expect(search).toHaveBeenCalledTimes(1));expect(d.documentElement.dataset.workspaceEmbedded).toBe('true');
  w.dispatchEvent(new w.MessageEvent('message',{origin:'https://untrusted.example',source:parent,data:{type:'medical-data:view',view:'documents'}}));expect(docs).not.toHaveBeenCalled();
  w.dispatchEvent(new w.MessageEvent('message',{origin:'http://localhost',source:parent,data:{type:'medical-data:view',view:'documents'}}));expect(docs).toHaveBeenCalledTimes(1);
});

it('clears example patient IDs and requires identity before context writes',async()=>{
  const source=readFileSync(join(backend,'modules/context/ui/index.html'),'utf8');const dom=domFor(source,'http://localhost/modules/context/ui?embed=1&view=history'),w=dom.window,d=w.document;
  const parent={postMessage:vi.fn()};Object.defineProperty(w,'parent',{value:parent});
  const fetch=vi.fn(async(_url:string,options?:RequestInit)=>{expect(options?.method).not.toBe('POST');return reply({status:'ok'});});w.fetch=fetch;
  w.eval(embed);const inline=[...d.querySelectorAll('script')].find(s=>!s.src)!.textContent!;w.eval(inline);
  await vi.waitFor(()=>expect(d.documentElement.dataset.contextView).toBe('history'));
  const patient=d.getElementById('patientId') as HTMLInputElement,session=d.getElementById('sessionId') as HTMLInputElement;
  expect(patient.value).toBe('');expect(session.value).toBe('');
  d.getElementById('sendBtn')!.click();d.getElementById('saveTurnBtn')!.click();expect(d.getElementById('toast')!.textContent).toContain('Patient ID và Session ID');
  patient.value='P1';session.value='S1';
  w.dispatchEvent(new w.MessageEvent('message',{origin:'http://localhost',source:parent,data:{type:'medical-data:view',view:'tools'}}));
  expect(patient.value).toBe('P1');expect(session.value).toBe('S1');expect(d.documentElement.dataset.contextView).toBe('tools');
});

it.each(['rag','context'])('opens an explicitly selected %s job instead of the most recent one',async(module)=>{
  const path=module==='rag'?'modules/rag/static':'bulk_import/web';const source=readFileSync(join(backend,path,'index.html'),'utf8');
  const dom=domFor(source,'http://localhost/'+(module==='rag'?'modules/rag/':'imports?module=context')+(module==='rag'?'?':'&')+'job=SELECTED'),w=dom.window,d=w.document;
  const selected={...job,job_id:'SELECTED',mode:'preview',partial:0,items:[{position:0,filename:'selected.json',document_id:'DOC',record_id:'P:S',status:'completed'}]};
  const fetch=vi.fn(async(url:string,options?:RequestInit)=>{
    expect(options?.method).not.toBe('POST');expect(url).not.toContain('/LATEST');
    if(url.endsWith('/jobs'))return reply({active_job_id:null,items:[{...selected,job_id:'LATEST'}]});
    if(url.endsWith('/jobs/SELECTED'))return reply(selected);
    if(url.endsWith('/health'))return reply({mode:'demo',chunking:{method:'semantic'}});
    if(url.endsWith('/stats'))return reply({documents:1,chunks:1,propositions:1,vectors:1});
    if(url.includes('/documents?'))return reply({items:[],total:0});throw Error(url);
  });w.fetch=fetch;w.eval(readFileSync(join(backend,path,'app.js'),'utf8'));
  await vi.waitFor(()=>expect(d.querySelector(module==='rag'?'#report':'#rows')?.textContent).toContain('selected.json'));
  if(module==='context')expect((d.getElementById('commit') as HTMLButtonElement).disabled).toBe(true);
  expect(fetch.mock.calls.some(([url])=>url.endsWith('/jobs/SELECTED'))).toBe(true);
});
