"""KG chat presentation and server-owned clarification validation."""
from __future__ import annotations

from fastapi import HTTPException


def query_metadata(result):
    return {**result.get('query', {}), 'status': result.get('status'),
            'fact_count': result.get('retrieval', {}).get('fact_count', 0),
            'elapsed_ms': result.get('elapsed_ms'), 'timings_ms': result.get('timings_ms', {}),
            'warnings': result.get('warnings', [])}


def comparison_metadata(result):
    context = result.get('llm_context', {})
    comparison = context.get('comparison')
    return {**comparison, 'facts': context.get('facts', [])} if comparison is not None else None


def confirmed_request(store, conversation_id, confirmation):
    """Bind choices to the latest clarification in this conversation, never client JSON facts."""
    conversation = store.get_conversation(conversation_id)
    messages = (conversation or {}).get('messages', [])
    if not messages or messages[-1]['id'] != confirmation.message_id:
        raise HTTPException(409, 'Lượt xác nhận đã thay đổi. Vui lòng tải lại hội thoại hoặc hỏi lại.')
    message = messages[-1]
    metadata = message.get('metadata', {})
    clarification = metadata.get('kg_clarification') or {}
    groups = clarification.get('groups', [])
    ids = confirmation.entity_ids
    if (message.get('role') != 'assistant' or not clarification.get('can_confirm')
            or not 1 <= len(groups) <= 2 or len(ids) != len(groups)
            or len(set(ids)) != len(ids)
            or any(eid not in {c['id'] for c in group.get('candidates', [])} for eid, group in zip(ids, groups))):
        raise HTTPException(422, 'Lựa chọn không thuộc danh sách thực thể cần xác nhận.')
    question = metadata.get('resolved_question')
    route = metadata.get('kg_route')
    if not question or route not in ('RELATIONAL_QUERY', 'CLINICAL_EXPLANATION_MANAGEMENT'):
        raise HTTPException(409, 'Không còn câu hỏi KG để tiếp tục. Vui lòng hỏi lại.')
    return {'question': question, 'entity_ids': ids, 'classification': metadata.get('classifier') or {'label': route}}


def no_facts_text(result):
    mode = result.get('query', {}).get('mode')
    if mode in ('compare', 'common', 'difference'):
        comparison = result.get('llm_context', {}).get('comparison', {})
        reason = comparison.get('no_result_reason')
        if reason == 'result_limit':
            return 'Giới hạn kết quả không đủ để hiển thị một hàng đối chiếu đầy đủ. Bạn hãy thu hẹp tiêu chí hoặc tăng giới hạn truy vấn.'
        if reason == 'no_data':
            return 'Chưa tìm thấy dữ liệu phù hợp để so sánh hai thực thể theo tiêu chí đã hỏi. Điều này không có nghĩa hai bệnh/thuốc giống nhau hoặc khác nhau.'
        if mode == 'common':
            return 'Chưa tìm thấy điểm chung đáp ứng cùng quan hệ và thuộc tính nguồn trong phần dữ liệu đã truy xuất. Điều này không khẳng định hai bệnh/thuốc không có điểm chung.'
        if mode == 'difference':
            return 'Chưa tìm thấy khác biệt trong phần dữ liệu đã đối chiếu. Điều này không khẳng định hai bệnh/thuốc tương đương về y khoa.'
        return 'Chưa đủ dữ liệu đối chiếu theo tiêu chí đã hỏi. Vui lòng kiểm tra nguồn hoặc chọn tiêu chí khác.'
    if result.get('retrieval', {}).get('truncated'):
        return 'Giới hạn kết quả hiện tại không đủ để trả một chuỗi bằng chứng hoàn chỉnh. Bạn hãy thu hẹp câu hỏi hoặc tăng giới hạn truy vấn.'
    if mode == 'path':
        depth = result.get('query', {}).get('max_hops', 3)
        return f'Chưa tìm thấy đường liên kết trong giới hạn {depth} bước của KG hiện tại. Điều này không có nghĩa hai thực thể không liên quan.'
    if mode == 'multi_hop':
        return 'Chưa tìm thấy chuỗi bằng chứng hoàn chỉnh để trả lời câu hỏi này trong KG hiện tại. Điều này không khẳng định quan hệ đó không tồn tại.'
    return 'Chưa tìm thấy quan hệ phù hợp để trả lời trong KG hiện tại. Điều này không khẳng định quan hệ đó không tồn tại.'
