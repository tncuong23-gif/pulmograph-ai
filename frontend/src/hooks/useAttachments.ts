import { useCallback, useEffect, useRef, useState } from 'react';
import type { Attachment, AttachmentType, SelectedRecord } from '../types';
import { validateFile } from '../config/uploads';
import { createFileUrl, releaseFileUrl } from '../lib/files';

export function useAttachments() {
  const [attachments,setAttachments]=useState<Attachment[]>([]);
  const [error,setError]=useState('');
  const items=useRef<Attachment[]>([]);
  const files=useRef(new Map<string,File>());
  const update=(next:Attachment[])=>{items.current=next;setAttachments(next);};
  const reset=useCallback(()=>{
    items.current.forEach(a=>releaseFileUrl(a.url));items.current=[];files.current.clear();setAttachments([]);setError('');
  },[]);
  useEffect(()=>()=>{items.current.forEach(a=>releaseFileUrl(a.url));},[]);
  const add=(selection:FileList|File[],type:AttachmentType)=>{
    const errors:string[]=[];const next=[...items.current];
    for(const file of Array.from(selection)){
      if(next.some(a=>a.type===type)){errors.push('Mỗi lượt chỉ nhận một TXT và một ảnh X-quang cùng ca.');break;}
      const error=validateFile(file,type);if(error){errors.push(`${file.name}: ${error}`);continue;}
      const id=crypto.randomUUID();files.current.set(id,file);
      next.push({id,type,fileName:file.name,fileSize:file.size,mimeType:file.type,status:'pending',progress:0,
        url:type==='xray'?createFileUrl(file):undefined});
    }
    update(next);setError(errors.join(' '));
  };
  const remove=(id:string)=>{
    releaseFileUrl(items.current.find(a=>a.id===id)?.url);files.current.delete(id);update(items.current.filter(a=>a.id!==id));setError('');
  };
  const commit=()=>{const result=[...items.current];items.current=[];setAttachments([]);files.current.clear();setError('');return result;};
  const commitRecords=():SelectedRecord[]=>{
    const result=items.current.map(attachment=>({attachment,file:files.current.get(attachment.id)!}));
    commit();return result;
  };
  return {reset,attachments,error,setError,add,remove,retry:()=>{},commit,commitRecords,busy:false,hasErrors:false};
}
