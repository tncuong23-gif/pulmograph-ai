"""Three explicit clinical input paths. No routing classifier or implicit patient facts."""
import asyncio
import hashlib
import json
import logging
from pathlib import Path
from uuid import uuid4, uuid5, NAMESPACE_URL
import httpx
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from .schemas import iso_now
from .services.evidence import prepare_evidence, validate_answer
from .services.clinical_inputs import MAX_FILE, decode_txt, validate_modalities, validate_image

log = logging.getLogger('uvicorn.error')


def format_analysis(result):
    data = result['data']
    modality = {'text':'văn bản', 'xray':'ảnh X-quang', 'text_xray':'văn bản kết hợp ảnh X-quang'}.get(data.get('modality'), 'dữ liệu đã gửi')
    lines = [f'Đã phân tích {modality}.']
    facts = data.get('extracted_facts') or {}
    entities = facts.get('entities') or []
    if entities:
        lines += ['\n**Dữ kiện trích xuất**', '```json', json.dumps(entities[:30], ensure_ascii=False, indent=2), '```']
        if len(entities)>30: lines.append(f'Hiển thị 30/{len(entities)} thực thể; kết quả JSON lưu đầy đủ tại backend.')
    top = data.get('top5') or []
    if top:
        lines += ['\n**Xếp hạng của mô hình**']
        for item in top:
            label = str(item.get('label', ''))
            score = item.get('calibrated_score', item.get('decision_score', item.get('score')))
            lines.append(f"- {label}" + (f" — điểm {score:.4f}" if isinstance(score, (int, float)) else ''))
        lines.append('Điểm dùng để xếp hạng, không phải xác suất mắc bệnh hay kết luận chẩn đoán.')
    else: lines.append('Chưa đủ thông tin để trả xếp hạng. Bạn có thể bổ sung dữ kiện trước chẩn đoán.')
    if data.get('modality') == 'xray': lines.append('Luồng này chỉ phân lớp ảnh; không sinh báo cáo tổn thương hoặc thực thể lâm sàng từ ảnh.')
    if data.get('missing_information_questions'):
        lines += ['\n**Thông tin có thể bổ sung**', *['- '+str(q) for q in data['missing_information_questions']]]
    if data.get('warnings'):
        lines += ['\n**Lưu ý từ module**', *['- '+str(w) for w in data['warnings']]]
    return '\n'.join(lines)


def create_router(settings):
    router = APIRouter()
    submit_lock = asyncio.Lock()

    def response(row):
        data = json.loads(row['clinical_input']) if row.get('clinical_input') else {}
        return {'id':row['id'],'serverId':row['id'],'type':row.get('attachment_type','medical_record'),
            'fileName':row['file_name'],'fileSize':row['file_size'],'mimeType':row['mime_type'],
            'status':row['status'],'progress':100,'error':row.get('error'),
            'analysisAnswer':row.get('analysis_answer'),'sources':json.loads(row.get('analysis_sources') or '[]'),'modality':data.get('modality')}

    async def process(app, job_id):
        row = app.state.store.get_attachment(job_id)
        payload = json.loads(row['clinical_input'])
        result = None
        stage = 'clinical'
        try:
            if row.get('analysis_json'):
                result = json.loads(row['analysis_json'])
            else:
                image = await asyncio.to_thread(Path(payload['image_path']).read_bytes) if payload.get('image_path') else None
                result = await app.state.modules.clinical_analyze(text=payload.get('text'), image=image, same_case=payload['same_case'])
            data = result.get('data')
            if not isinstance(data, dict) or data.get('modality') != payload['modality'] or not isinstance(data.get('top5'), list):
                result = None
                raise ValueError('Clinical modality/result mismatch')
            app.state.store.set_attachment_analysis(job_id,'processing',result=result)
            stage = 'presentation'
            pack = prepare_evidence({'route':'CLINICAL_ANALYSIS','module_results':{'clinical_ie':result}})
            answer = await app.state.llm.generate('Trình bày kết quả phân tích đã cung cấp. Tách dữ kiện trích xuất khỏi xếp hạng mô hình; điểm không phải xác suất mắc bệnh. Với chỉ ảnh, không tự tạo mô tả tổn thương hoặc dữ kiện người dùng chưa khai.',pack.payload)
            answer = validate_answer(answer,pack.sources)
            if not answer.strip():raise ValueError('Empty clinical answer')
            now = iso_now()
            app.state.store.save_exchange(row['conversation_id'],
                {'id':row['user_message_id'],'role':'user','content':payload['description'],'createdAt':payload['created_at'],
                 'metadata':{'route':'CLINICAL_ANALYSIS','clinical_job_id':job_id,'modality':payload['modality']}},
                {'id':'clinical-'+job_id,'role':'assistant','content':answer,'createdAt':now,
                 'metadata':{'route':'CLINICAL_ANALYSIS','clinical_job_id':job_id,'modality':payload['modality'],'sources':pack.sources}})
            app.state.store.set_attachment_analysis(job_id,'processed',result=result,answer=answer,sources=pack.sources)
            log.info('clinical.analysis_done job_id=%s modality=%s', job_id, payload['modality'])
        except Exception as exc:
            message = 'Clinical IE đã phân tích nhưng Ollama chưa tạo được câu trả lời. Kết quả phân tích được giữ để thử lại.' if stage == 'presentation' else 'Clinical IE chưa xử lý được dữ liệu. Kiểm tra dịch vụ tại cổng 8002.'
            if isinstance(exc, httpx.TimeoutException): message = 'Ollama tạo câu trả lời quá thời gian chờ; có thể thử lại với kết quả Clinical IE đã lưu.' if stage == 'presentation' else 'Clinical IE xử lý quá thời gian chờ. Kiểm tra tiến trình dịch vụ trước khi thử lại.'
            elif isinstance(exc, httpx.HTTPStatusError):
                message = f'{"Ollama" if stage == "presentation" else "Clinical IE"} trả HTTP {exc.response.status_code}.'
                try:
                    detail=exc.response.json().get('detail')
                    if isinstance(detail,str): message += ' '+detail[:1200]
                except (ValueError, AttributeError): pass
            app.state.store.set_attachment_analysis(job_id,'error',result=result,error=message)
            log.error('clinical.analysis_failed job_id=%s error_type=%s',job_id,type(exc).__name__)

    async def read(upload):
        if upload is None: return None
        content = await upload.read(min(settings.max_upload_bytes,MAX_FILE)+1)
        if len(content)>min(settings.max_upload_bytes,MAX_FILE): raise HTTPException(413,'File vượt giới hạn 20 MB.')
        return content

    @router.post('/api/v1/clinical/analyze',status_code=202)
    async def analyze(request: Request, background_tasks: BackgroundTasks,
            conversationId: str = Form(..., min_length=1, max_length=128),
            clientId: str = Form(..., min_length=1, max_length=128),
            text: str | None = Form(None), file: UploadFile | None = File(None),
            image: UploadFile | None = File(None)):
        try:
            if file is not None:
                if text and text.strip(): raise HTTPException(422,'Chọn văn bản hoặc file TXT, không gửi cả hai.')
                if Path(file.filename or '').suffix.lower()!='.txt': raise HTTPException(415,'Chỉ hỗ trợ file TXT UTF-8.')
                text=decode_txt(await read(file))
            if text is not None and not text.strip(): text=None
            content=await read(image)
            # Luồng suy ra từ dữ liệu thực tế, không cần checkbox hoặc cờ thủ công ở client.
            same_case = text is not None and content is not None
            modality=validate_modalities(text,content,same_case)
            if image and Path(image.filename or '').suffix.lower() not in {'.jpg','.jpeg','.png'}:
                raise HTTPException(415,'Chỉ hỗ trợ X-quang JPEG/PNG.')
            # Client id scopes idempotency to this conversation; changed input must use a new id.
            job_id=str(uuid5(NAMESPACE_URL, json.dumps([conversationId,clientId])))
            fingerprint=hashlib.sha256(json.dumps([text,hashlib.sha256(content).hexdigest() if content is not None else None,modality],ensure_ascii=False).encode()).hexdigest()
            async with submit_lock:
                previous=request.app.state.store.get_attachment(job_id)
                if previous:
                    prior=json.loads(previous['clinical_input'] or '{}')
                    if prior.get('fingerprint')!=fingerprint: raise HTTPException(409,'Mã lượt gửi đã dùng cho nội dung khác.')
                    if previous['status']=='error':
                        request.app.state.store.set_attachment_analysis(job_id,'processing',result=json.loads(previous['analysis_json']) if previous.get('analysis_json') else None)
                        background_tasks.add_task(process,request.app,job_id)
                    return response(request.app.state.store.get_attachment(job_id))
                state=request.app.state.store.latest_assessment(conversationId)
                if state and state['status'] not in {'completed','cancelled'}:
                    raise HTTPException(409,'Hãy hoàn tất hoặc hủy lượt đánh giá hiện tại trước khi gửi ca mới.')
                image_path=None
                if content is not None:
                    image_path=settings.upload_dir/(str(uuid4())+validate_image(content))
                    await asyncio.to_thread(image_path.write_bytes,content)
                names=[Path(x.filename or 'file').name for x in [file,image] if x]
                description='Phân tích '+ {'text':'văn bản/TXT','xray':'ảnh X-quang','text_xray':'văn bản và X-quang cùng ca'}[modality]
                payload={'text':text,'image_path':str(image_path) if image_path else None,'same_case':same_case,
                    'modality':modality,'fingerprint':fingerprint,'description':description,'created_at':iso_now()}
                try:
                    request.app.state.store.add_clinical_job({'id':job_id,'file_name':', '.join(names) or 'Văn bản',
                        'mime_type':'application/json','file_size':len(content or b'')+len((text or '').encode()),
                        'stored_path':str(image_path or '')},payload,conversationId,clientId,modality)
                except Exception:
                    if image_path:image_path.unlink(missing_ok=True)
                    raise
                background_tasks.add_task(process,request.app,job_id)
                return response(request.app.state.store.get_attachment(job_id))
        except ValueError as exc: raise HTTPException(422,str(exc)) from None
        finally:
            if file:await file.close()
            if image:await image.close()

    @router.get('/api/v1/clinical/jobs/{job_id}')
    async def result(job_id: str, request: Request):
        row=request.app.state.store.get_attachment(job_id)
        if not row or not row.get('clinical_input'): raise HTTPException(404,'Không có lượt phân tích này.')
        return {**response(row),'result':json.loads(row['analysis_json']) if row.get('analysis_json') else None}
    return router
