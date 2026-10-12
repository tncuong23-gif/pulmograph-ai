import {readFileSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {afterEach,expect,it,vi} from 'vitest';

const root=resolve(process.cwd(),'../backend/app/bulk_import/web');
const source=readFileSync(join(root,'app.js'),'utf8');
function boot(module='kg'){
  window.history.replaceState({},'',`/imports?module=${module}`);
  document.body.innerHTML=new DOMParser().parseFromString(readFileSync(join(root,'index.html'),'utf8'),'text/html').body.innerHTML;
  const dialog=document.querySelector<HTMLDialogElement>('#reviewDialog')!;
  dialog.showModal=vi.fn();dialog.close=vi.fn();
  new Function(source)();
}
const button=(id:string)=>document.querySelector<HTMLButtonElement>('#'+id)!;
const tick=(id:string)=>document.querySelector<HTMLInputElement>('#'+id)!;
function fileInput(files:File[]){Object.defineProperty(tick('files'),'files',{value:files,configurable:true});tick('files').dispatchEvent(new Event('change'));}
const job={job_id:'PREVIEW',mode:'preview',status:'completed',started_at:'2026-10-10T00:00:00Z',total:1,processed:1,
  completed:1,failed:0,skipped:0,partial:0,needs_review:0,items:[{position:0,filename:'patient.json',status:'completed',record_id:'P:S'}]};
const response=(data:unknown,ok=true)=>({ok,json:async()=>data}) as Response;
afterEach(()=>{window.dispatchEvent(new Event('beforeunload'));vi.clearAllTimers();vi.useRealTimers();vi.unstubAllGlobals();document.body.innerHTML='';window.history.replaceState({},'','/');});

it('requires explicit patient confirmation and selection; loading the page never writes',async()=>{
  const posts:unknown[]=[];
  const fetch=vi.fn(async(url:string,options?:RequestInit)=>{
    if(options?.method==='POST'){const body=JSON.parse(options.body as string);posts.push(body);return response({...job,job_id:'COMMIT',mode:'commit'});}
    if(url.endsWith('/jobs'))return response({active_job_id:null,items:[job]});
    if(url.endsWith('/jobs/PREVIEW'))return response(job);
    throw Error(url);
  });vi.stubGlobal('fetch',fetch);boot('context');
  await vi.waitFor(()=>expect(document.querySelector('#rows')?.textContent).toContain('patient.json'));
  expect(posts).toEqual([]);expect(button('commit').disabled).toBe(true);
  tick('selectAll').click();expect(button('commit').disabled).toBe(true);
  tick('confirm').click();expect(button('commit').disabled).toBe(false);
  button('commit').click();await vi.waitFor(()=>expect(posts).toHaveLength(1));
  expect(posts[0]).toEqual({mode:'commit',previous_job_id:'PREVIEW',confirmed:true,files:['patient.json']});
  expect(document.querySelector('#confirmText')?.textContent).toContain('đúng bệnh nhân');
});

it('uploads many files and reports upload failures without importing an old saved source',async()=>{
  let posted:Record<string,unknown>|null=null;
  vi.stubGlobal('fetch',vi.fn(async(url:string,options?:RequestInit)=>{
    if(url.includes('/uploads/'))return url.endsWith('bad.json')?response({detail:'Không thể lưu'},false):response({saved:true});
    if(options?.method==='POST'){posted=JSON.parse(options.body as string);return response({...job,failed:1,total:2,processed:2,items:[job.items[0],{position:1,filename:'bad.json',status:'failed',error:'Không thể lưu'}]});}
    return response({active_job_id:null,items:[]});
  }));boot();
  await vi.waitFor(()=>expect(tick('files').disabled).toBe(false));
  fileInput([new File(['{}'],'good.json'),new File(['{'],'bad.json')]);button('previewFiles').click();
  await vi.waitFor(()=>expect(posted).not.toBeNull());
  expect(posted).toEqual({source:'files',mode:'preview',files:['good.json','bad.json'],file_errors:{'bad.json':'Không thể lưu'}});
  expect(document.querySelector('#rows')?.textContent).toContain('Không thể lưu');
  expect(document.querySelector('a[href$="kind=errors"]')).not.toBeNull();
});

it('resumes a running task after reload and preserves partial status and retry approval',async()=>{
  vi.useFakeTimers();let reads=0;
  const active={...job,mode:'commit',status:'running',processed:0,completed:0};
  vi.stubGlobal('fetch',vi.fn(async(url:string,options?:RequestInit)=>{
    expect(options?.method).not.toBe('POST');
    if(url.endsWith('/jobs'))return response({active_job_id:'PREVIEW',items:[active]});
    reads++;return response(reads===1?active:{...active,status:'completed',processed:1,partial:1,items:[{...job.items[0],status:'partial',error:'Qdrant chưa đồng bộ',stage:'vector'}]});
  }));boot();
  await vi.waitFor(()=>expect(button('folderPreview').disabled).toBe(true));
  await vi.advanceTimersByTimeAsync(1300);
  await vi.waitFor(()=>expect(document.querySelector('#rows')?.textContent).toContain('Ghi một phần'));
  expect(button('retry').hidden).toBe(false);expect(button('retry').disabled).toBe(true);
  tick('confirm').click();expect(button('retry').disabled).toBe(false);
});

it('keeps all candidates across pages, allows an override, and enables the reviewed row without repreview',async()=>{
  const candidateJob={...job,completed:0,needs_review:1,items:[{...job.items[0],status:'needs_review',candidate_count:105}]};
  const candidates=Object.fromEntries(Array.from({length:105},(_,i)=>[`E${i}`,[{entity_id:'OLD',canonical_name:'Tên cũ',score:.9}]]));
  const posts:Record<string,any>[]=[];
  vi.stubGlobal('fetch',vi.fn(async(url:string,options?:RequestInit)=>{
    if(options?.method==='POST'){
      posts.push(JSON.parse(options.body as string));
      return response({message:'Đã duyệt và lưu tài liệu.',item:{...job.items[0],review_status:'reviewed',reviewed_at:'2026-10-11T00:00:00Z',candidate_count:0}});
    }
    if(url.endsWith('/preview'))return response({module:'kg',document_id:'DOC',entities:[],plan:{entity_candidates:candidates}});
    if(url.endsWith('/jobs'))return response({active_job_id:null,items:[candidateJob]});
    return response(candidateJob);
  }));boot();
  await vi.waitFor(()=>expect(document.querySelector('#rows')?.textContent).toContain('Cần duyệt'));
  expect(tick('selectAll').disabled).toBe(true);
  document.querySelector<HTMLButtonElement>('#rows button')!.click();
  await vi.waitFor(()=>expect(document.querySelectorAll('#reviewBody select')).toHaveLength(100));
  const save=document.querySelector<HTMLButtonElement>('[data-action="save-review"]')!;
  save.click();expect(posts).toHaveLength(0);
  document.querySelector<HTMLButtonElement>('[data-action="keep-all"]')!.click();
  const select=document.querySelector<HTMLSelectElement>('#choice-E0')!;select.value='OLD';select.dispatchEvent(new Event('change'));
  expect(posts).toHaveLength(0);save.click();
  await vi.waitFor(()=>expect(posts).toHaveLength(1));
  expect(Object.keys(posts[0].choices)).toHaveLength(105);
  expect(posts[0].choices.E0).toBe('OLD');expect(posts[0].choices.E104).toBe('new');
  await vi.waitFor(()=>expect(document.querySelector('#rows')?.textContent).toContain('Đã duyệt'));
  expect(tick('selectAll').disabled).toBe(false);expect(button('commit').disabled).toBe(true);
  expect(button('previewFiles').disabled).toBe(true);
});

it('does not mark a no-candidate document reviewed when save fails and allows retry',async()=>{
  let calls=0;
  vi.stubGlobal('fetch',vi.fn(async(url:string,options?:RequestInit)=>{
    if(options?.method==='POST'){calls++;expect(JSON.parse(options.body as string)).toEqual({choices:{}});return response({detail:'Lỗi lưu thử nghiệm'},false);}
    if(url.endsWith('/preview'))return response({module:'kg',document_id:'DOC',entities:[],plan:{entity_candidates:{}}});
    if(url.endsWith('/jobs'))return response({active_job_id:null,items:[job]});
    return response(job);
  }));boot();
  await vi.waitFor(()=>expect(document.querySelector('#rows button')).not.toBeNull());
  document.querySelector<HTMLButtonElement>('#rows button')!.click();
  await vi.waitFor(()=>expect(document.querySelector('[data-action="save-review"]')).not.toBeNull());
  const save=document.querySelector<HTMLButtonElement>('[data-action="save-review"]')!;save.click();
  await vi.waitFor(()=>expect(document.querySelector('#reviewFeedback')?.textContent).toContain('Lỗi lưu'));
  expect(calls).toBe(1);expect(save.disabled).toBe(false);
  expect(document.querySelector('#rows')?.textContent).not.toContain('Đã duyệt');
});
