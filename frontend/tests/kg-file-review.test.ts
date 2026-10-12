import {readFileSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {afterEach,expect,it,vi} from 'vitest';
const root=resolve(process.cwd(),'../backend/app/modules/kg_query/web');
const button=(id:string)=>document.getElementById(id) as HTMLButtonElement;
afterEach(()=>{vi.unstubAllGlobals();vi.restoreAllMocks();document.body.innerHTML='';});
it.each([false,true])('saves choices and requires individual cross-type review (%s)',async(crossType)=>{
  document.body.innerHTML=new DOMParser().parseFromString(readFileSync(join(root,'duplicates.html'),'utf8'),'text/html').body.innerHTML;
  (window as any).KGGraph={render:()=>({resize:vi.fn(),destroy:vi.fn(),fit:vi.fn()})};
  const raw={document:{document_id:'DOC'},entities:[{id:'NEW',canonical_name:'Tên mới',type:'Disease'}],relations:[]};
  const reviewed={...raw,entity_link_decisions:{NEW:'new'}};
  const posts:{url:string,body:any}[]=[];
  vi.stubGlobal('fetch',vi.fn(async(url:string,options:RequestInit)=>{
    const body=JSON.parse(options.body as string);posts.push({url,body});
    const data=url.endsWith('/preview')?{status:'dry_run',document_id:'DOC',plan:{entities:{create:1},entity_candidates:{NEW:[{entity_id:'OLD',score:.9,...(crossType?{link_allowed:false,entity_type:'Symptom'}:{})}]}}}
      :url.endsWith('/decisions')?{status:'dry_run',document_id:'DOC',payload:reviewed,plan:{entities:{create:1},entity_candidates:{}},review_status:'reviewed',reviewed_at:'2026-10-11T00:00:00Z',preview_token:'TOKEN'}
      :{status:'completed',document_id:'DOC',import_id:'DONE'};
    return {ok:true,json:async()=>data};
  }));
  vi.spyOn(window,'confirm').mockReturnValue(true);
  new Function(readFileSync(join(root,'duplicates.js'),'utf8'))();
  Object.defineProperty(button('jsonFile'),'files',{value:[{name:'one.json',size:100,text:async()=>JSON.stringify(raw)}]});
  button('jsonFile').dispatchEvent(new Event('change'));
  await vi.waitFor(()=>expect(button('previewBtn').disabled).toBe(false));button('previewBtn').click();
  await vi.waitFor(()=>expect(document.querySelector('.decision-select')).not.toBeNull());
  button('saveFileReview').click();expect(posts).toHaveLength(1);
  button('keepAllFileEntities').click();expect(posts).toHaveLength(1);
  const select=document.querySelector('.decision-select') as HTMLSelectElement;
  if(crossType){
    expect(select.value).toBe('');
    expect([...select.options].some(o=>o.value==='OLD')).toBe(false);
    button('saveFileReview').click();expect(posts).toHaveLength(1);
    select.value='new';select.dispatchEvent(new Event('change'));
  }
  expect(select.value).toBe('new');
  button('saveFileReview').click();
  await vi.waitFor(()=>expect(button('fileReviewStatus').textContent).toContain('Đã duyệt'));
  expect(posts[1].body).toEqual({payload:raw,choices:{NEW:'new'}});
  expect(button('importBtn').disabled).toBe(false);button('importBtn').click();
  await vi.waitFor(()=>expect(posts).toHaveLength(3));
  expect(posts[2].body).toEqual({payload:reviewed,preview_token:'TOKEN'});
  expect(window.confirm).toHaveBeenCalledTimes(1);
});
