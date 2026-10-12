import { createContext, useContext, useId, useState, useRef, useEffect, type CSSProperties, type ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { X, BookOpen } from "lucide-react";
import type { EvidenceSource } from "../../types";
import "./evidence-sources.css";

type Source = EvidenceSource & {number:number};
const SourcesContext=createContext<{sources:Source[];open:(n:number)=>void}>({sources:[],open:()=>{}});
export function SourcesProvider({sources=[],children}:{sources?:EvidenceSource[];children:ReactNode}) {
  const normalized=sources.map((source,i)=>({...source,number:source.number??i+1}));
  const [selected,setSelected]=useState<number|null>(null);
  const opener=useRef<HTMLElement|null>(null);
  const source=normalized.find(s=>s.number===selected);
  return <SourcesContext.Provider value={{sources:normalized,open:n=>{opener.current=document.activeElement as HTMLElement;setSelected(n);}}}>
    {children}
    <Dialog.Root open={selected!==null} onOpenChange={open=>{if(!open)setSelected(null);}}>
      <Dialog.Portal><Dialog.Overlay className="source-overlay"/>
        <Dialog.Content className="source-drawer" onCloseAutoFocus={event=>{event.preventDefault();opener.current?.focus();}}>
          <header><div><small>Nguồn [{source?.number}] · {source?.kind==='model'?'Đầu ra mô hình':'Văn bản bằng chứng'}</small>
            <Dialog.Title>{source?.title||"Tài liệu truy xuất"}</Dialog.Title></div>
            <Dialog.Close className="icon-button" aria-label="Đóng nguồn"><X size={20}/></Dialog.Close></header>
          <Dialog.Description>Đọc trích đoạn và ngữ cảnh được cung cấp để kiểm tra câu trả lời.</Dialog.Description>
          {source?.section&&<p className="source-section">{source.section}</p>}
          <blockquote className="source-full-text">{source?.text||"Chưa có trích đoạn văn bản cho nguồn này."}</blockquote>
          {source?.kind==='model'&&<p className="source-note">Đây là đầu ra mô hình hỗ trợ đánh giá, không phải bằng chứng tài liệu y khoa hoặc chẩn đoán xác định.</p>}
          <nav aria-label="Chuyển nguồn">{normalized.map(s=><button key={s.number} aria-pressed={selected===s.number} onClick={()=>setSelected(s.number)}>[{s.number}]</button>)}</nav>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  </SourcesContext.Provider>;
}
export function SourceCitation({number}:{number:number}) {
  const {sources,open}=useContext(SourcesContext);const id=useId();const [hover,setHover]=useState(false);
  const button=useRef<HTMLButtonElement>(null);const [position,setPosition]=useState<CSSProperties>({});
  const [below,setBelow]=useState(false);
  const show=()=>{
    const rect=button.current?.getBoundingClientRect();
    if(rect){
      const width=Math.min(330,window.innerWidth-24);const lower=rect.top<280;
      setBelow(lower);setPosition({left:Math.max(12,Math.min(rect.left,window.innerWidth-width-12)),right:"auto",width,
        top:lower?rect.bottom+8:"auto",bottom:lower?"auto":window.innerHeight-rect.top+8,
        maxHeight:Math.max(100,lower?window.innerHeight-rect.bottom-20:rect.top-20)});
    }
    setHover(true);
  };
  useEffect(()=>{
    if(!hover)return;
    const hide=()=>setHover(false);
    window.addEventListener('scroll',hide,true);window.addEventListener('resize',hide);
    return ()=>{window.removeEventListener('scroll',hide,true);window.removeEventListener('resize',hide);};
  },[hover]);
  const source=sources.find(s=>s.number===number);
  if(!source)return <span>[{number}]</span>;
  const excerpt=source.text ? source.text.slice(0,320)+(source.text.length>320?'…':'') : 'Chưa có trích đoạn văn bản.';
  return <span className="source-citation-wrap" onMouseEnter={show} onMouseLeave={()=>setHover(false)}>
    <button ref={button} className="source-citation" aria-label={`Nguồn ${number}`} aria-describedby={hover?id:undefined}
      onFocus={show} onBlur={()=>setHover(false)} onKeyDown={e=>{if(e.key==='Escape')setHover(false);}}
      onClick={()=>{setHover(false);open(number);}}>[{number}]</button>
    {hover&&<span className="source-tooltip" role="tooltip" id={id} style={position} data-placement={below?"below":"above"}>
      <strong>{source.title||'Tài liệu truy xuất'}</strong>
      {source.section&&<span className="source-section">{source.section}</span>}
      <span>{excerpt}</span><small>{source.kind==='model'?'Đầu ra mô hình · ':''}Bấm để đọc đầy đủ</small>
    </span>}
  </span>;
}
export function SourcesList() {
  const {sources}=useContext(SourcesContext);
  if(!sources.length)return null;
  return <details className="answer-sources"><summary><BookOpen size={15}/>Nguồn tham khảo ({sources.length})</summary>
    <ol>{sources.map(s=><li key={s.number}><SourceCitation number={s.number}/><span><strong>{s.title||'Tài liệu truy xuất'}</strong>
      <small>{s.kind==='model'?'Đầu ra mô hình':s.section||'Văn bản bằng chứng'}</small></span></li>)}</ol>
  </details>;
}
export function FactCitations({evidence}:{evidence:EvidenceSource[]}) {
  const {sources}=useContext(SourcesContext);
  const matches=sources.filter(s=>evidence.some(e=>
    s.text?.trim()===e.text?.trim() && s.origins?.some(o=>(o.doc_id??o.document_id)===(e.doc_id??e.document_id))));
  return <>{matches.map(s=><SourceCitation key={s.number} number={s.number}/>)}</>;
}

type Node={type:string;value?:string;url?:string;children?:Node[]};
// Replace plain [n] references only. Leave code, images and existing links untouched.
export function numberedCitations(sources:EvidenceSource[]) {
  const valid=new Set(sources.map((s,i)=>s.number??i+1));
  return () => (tree:unknown) => {
    const visit=(node:Node)=>{
      if(['code','inlineCode','link','image'].includes(node.type)||!node.children)return;
      const children:Node[]=[];
      for(const child of node.children){
        if(child.type==='text'&&child.value){
          const value=child.value;let start=0;
          for(const match of value.matchAll(/\[(\d{1,3})\]/g)){
            if(!valid.has(Number(match[1])))continue;
            const index=match.index!;
            if(index>start)children.push({type:'text',value:value.slice(start,index)});
            children.push({type:'link',url:`#source-${match[1]}`,children:[{type:'text',value:match[0]}]});start=index+match[0].length;
          }
          if(start<value.length)children.push({type:'text',value:value.slice(start)});
        }else{visit(child);children.push(child);}
      }
      node.children=children;
    };
    visit(tree as Node);
  };
}
