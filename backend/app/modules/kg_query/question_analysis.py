"""Bounded, deterministic Vietnamese question planning. Never generates Cypher.

This is lexical coverage, not a learned semantic parser. Unsupported/ambiguous
plans are returned to the caller for clarification instead of being guessed.
"""
from __future__ import annotations

import re
import unicodedata

from .intents import PRESET_CHAINS, DRUG_TYPES

COMPARISON_MODES = ('compare', 'common', 'difference')
DISEASE_TYPES = {'Disease', 'DiseaseSubtype', 'Syndrome', 'AcuteCondition'}


def text_key(value: str, *, accents: bool = True) -> str:
    value = unicodedata.normalize('NFC', value).casefold()
    # COVID19, COVID-19 and COVID 19 have the same token boundary.
    value = re.sub(r'([^\W\d_])(\d)', r'\1 \2', value)
    value = re.sub(r'(\d)([^\W\d_])', r'\1 \2', value)
    if not accents:
        value = ''.join(c for c in unicodedata.normalize('NFD', value)
                        if not unicodedata.combining(c)).replace('đ', 'd')
    return ' '.join(re.findall(r'\w+', value))


RULES = {
    'symptom': ('triệu chứng', 'dấu hiệu', 'biểu hiện'),
    'treatment': ('điều trị', 'chữa', 'trị bệnh', 'chỉ định', 'dùng thuốc', 'thuốc nào', 'thuốc gì'),
    'membership': ('thành phần', 'chứa thuốc', 'chứa hoạt chất', 'gồm thuốc', 'gồm những thuốc', 'gồm các thuốc'),
    'drug_class': ('thuộc nhóm thuốc', 'thuộc nhóm nào', 'thuộc loại thuốc', 'nhóm của thuốc'),
    'dosage': ('liều dùng', 'liều lượng', 'đường dùng', 'liều thuốc', 'dụng cụ đưa thuốc', 'uống bao nhiêu'),
    'adverse_effect': ('tác dụng phụ', 'tác dụng không mong muốn', 'độc tính', 'biến cố bất lợi'),
    'contraindication': ('chống chỉ định', 'thận trọng', 'không được dùng', 'không nên dùng'),
    'interaction': ('tương tác', 'tăng tác dụng', 'giảm tác dụng'),
    'risk_factor': ('yếu tố nguy cơ', 'nguy cơ mắc', 'yếu tố khởi phát', 'làm nặng', 'dễ mắc'),
    'cause': ('nguyên nhân', 'gây ra', 'do đâu', 'bệnh sinh'),
    'prevention': ('phòng ngừa', 'dự phòng', 'phòng tránh', 'vắc xin', 'vaccine'),
    'diagnosis': ('chẩn đoán', 'xét nghiệm', 'tiêu chuẩn xác định', 'hình ảnh học', 'x quang', 'ngưỡng chẩn đoán'),
    'differential': ('chẩn đoán phân biệt', 'phân biệt với bệnh'),
    'assessment': ('thang điểm', 'đánh giá bằng', 'phép đo', 'đo lường'),
    'classification': ('phân loại', 'giai đoạn', 'mức độ nặng', 'phân nhóm', 'phân độ'),
    'comorbidity': ('biến chứng', 'bệnh đi kèm', 'bệnh kèm', 'đồng mắc', 'đợt cấp', 'nguy hiểm'),
    'monitoring': ('theo dõi', 'giám sát', 'lịch tái khám'),
    'prognosis': ('tiên lượng', 'kết cục', 'tử vong', 'đáp ứng điều trị', 'diễn tiến', 'nguy hiểm'),
    'recommendation': ('khuyến cáo', 'khuyến nghị', 'nhập viện', 'mục tiêu điều trị', 'phác đồ', 'hướng dẫn điều trị'),
    'transmission': ('lây', 'lây truyền', 'ủ bệnh', 'phơi nhiễm'),
    'resistance': ('kháng thuốc', 'nhạy thuốc', 'nhạy cảm thuốc', 'đột biến kháng'),
    'rehabilitation': ('phục hồi chức năng', 'bài tập', 'tập thở'),
    'population': ('nhóm bệnh nhân', 'đối tượng', 'quần thể', 'áp dụng cho ai'),
    'mechanism': ('cơ chế sinh học', 'cơ chế tác động', 'cơ chế tác dụng', 'thụ thể', 'cytokine', 'tế bào'),
    'anatomy': ('vị trí', 'cơ quan', 'giải phẫu', 'bộ phận', 'ảnh hưởng ở đâu'),
}


def has_cue(text: str, cues) -> bool:
    padded = f' {text_key(text, accents=False)} '
    return any(f' {text_key(c, accents=False)} ' in padded for c in cues)


def detect_intents(question: str, mentions=()) -> list[str]:
    # A disease named "Lao kháng thuốc" is not itself a request about resistance.
    text = f' {text_key(question, accents=False)} '
    for mention in sorted(mentions, key=len, reverse=True):
        text = text.replace(f' {text_key(mention, accents=False)} ', ' ')
    found = [key for key, cues in RULES.items() if has_cue(text, cues)]
    if 'differential' in found:
        found = [i for i in found if i != 'diagnosis']
    # "chỉ định" inside "chống chỉ định" does not ask about treatment.
    if 'contraindication' in found:
        stripped = text.replace('chong chi dinh', ' ')
        if not has_cue(stripped, RULES['treatment']):
            found = [i for i in found if i != 'treatment']
    return found or ['related']


def uses_context(question: str) -> bool:
    cues = ('nó', 'bệnh này', 'bệnh đó', 'thuốc này', 'thuốc đó', 'tình trạng này')
    text = text_key(question)
    return (any(f' {text_key(c)} ' in f' {text} ' for c in cues)
            or (text == text_key(question, accents=False) and has_cue(question, cues)))


def comparison_mode(question: str) -> str | None:
    common = has_cue(question, ('điểm chung', 'giống nhau', 'tương đồng', 'triệu chứng chung',
                                'dấu hiệu chung', 'cùng có', 'chung nào'))
    different = has_cue(question, ('điểm khác', 'khác nhau', 'khác biệt', 'khác gì'))
    if common and different:
        return 'compare'
    if common:
        return 'common'
    if different:
        return 'difference'
    if has_cue(question, ('so sánh', 'đối chiếu', 'phân biệt giữa')):
        return 'compare'
    return None


def choose_mode(question, anchors, intents, *, mode='auto', preset=None):
    """Return (mode, preset, clarification). All supplied entities were resolved first."""
    if mode != 'auto':
        return mode, preset, None
    if detected := comparison_mode(question):
        if preset:
            return detected, None, 'So sánh hiện đối chiếu các quan hệ trực tiếp. Hãy hỏi riêng từng bệnh nếu cần chuỗi thuốc điều trị.'
        return detected, None, None
    if preset:
        return 'multi_hop', preset, None
    if has_cue(question, ('mối liên hệ', 'mối liên quan', 'quan hệ giữa', 'liên kết giữa', 'đường liên kết', 'đường đi giữa',
                         'liên quan với', 'liên quan thế nào', 'liên quan như thế nào')):
        return 'path', None, None
    entities = [a.entity for group in anchors.values() for a in group]
    disease_types = {'Disease', 'DiseaseSubtype', 'Syndrome', 'AcuteCondition'}
    disease_only = bool(entities) and all(e.type in disease_types for e in entities)
    drug_cue = has_cue(question, ('thuốc', 'hoạt chất', 'nhóm thuốc'))
    if disease_only and drug_cue:
        if 'adverse_effect' in intents and 'contraindication' in intents:
            return 'one_hop', None, 'Bạn muốn tra tác dụng phụ hay chống chỉ định của thuốc điều trị? Vui lòng chọn một nội dung mỗi lượt.'
        if 'adverse_effect' in intents:
            return 'multi_hop', 'drug_adverse_effects', None
        if 'contraindication' in intents:
            return 'multi_hop', 'drug_contraindications', None
        if any(i in intents for i in ('dosage', 'interaction', 'monitoring', 'resistance')):
            return 'one_hop', None, 'Bạn vui lòng nêu tên thuốc cụ thể để tra cứu nội dung này.'
        if 'treatment' in intents or has_cue(question, ('thuốc nào', 'thuốc gì')):
            return 'multi_hop', 'drugs_for_disease', None
    return 'one_hop', None, None


def validate_mode(mode, preset, intents, anchors, service):
    if len(intents) > 6:
        return 'Câu hỏi chứa nhiều nội dung. Bạn hãy tách thành câu hỏi ngắn hơn.'
    if mode in COMPARISON_MODES:
        if len(anchors) != 2:
            return 'Bạn vui lòng nêu rõ hai bệnh hoặc hai thuốc cần so sánh.'
        entities = [a.entity for group in anchors.values() for a in group]
        if len({e.id for e in entities}) != 2:
            return 'Hai tên đang trỏ đến cùng một thực thể. Vui lòng chọn hai thực thể khác nhau.'
        if not (all(e.type in DISEASE_TYPES for e in entities) or all(e.type in DRUG_TYPES for e in entities)):
            return 'Hãy chọn hai bệnh hoặc hai thuốc/nhóm thuốc để so sánh cùng loại.'
        if not intents or 'related' in intents:
            return 'Bạn muốn so sánh theo tiêu chí nào: triệu chứng, nguy cơ, điều trị, tác dụng phụ hay chống chỉ định? Vui lòng nêu tiêu chí cùng tên hai bệnh/thuốc.'
        if all(e.type in DISEASE_TYPES for e in entities) and any(
                i in intents for i in ('adverse_effect', 'contraindication', 'dosage', 'interaction', 'drug_class', 'membership')):
            return 'Với tiêu chí về thuốc, hãy nêu hai tên thuốc cụ thể. So sánh hiện dùng các quan hệ trực tiếp của từng bệnh/thuốc.'
    if mode == 'path':
        if len(anchors) != 2:
            return 'Bạn vui lòng nêu rõ hai bệnh, thuốc hoặc thực thể cần tìm đường liên kết.'
        ids = [{a.entity.id for a in group} for group in anchors.values()]
        if ids[0] & ids[1]:
            return 'Hai tên đang trỏ đến cùng một thực thể. Vui lòng chọn hai thực thể khác nhau.'
    if mode == 'multi_hop':
        if preset not in PRESET_CHAINS:
            return 'Bạn vui lòng chọn chuỗi truy vấn thuốc, tác dụng phụ hoặc chống chỉ định của thuốc điều trị bệnh.'
        if any(a.entity.type not in {'Disease', 'DiseaseSubtype', 'Syndrome', 'AcuteCondition'}
               for group in anchors.values() for a in group):
            return 'Chuỗi này bắt đầu từ bệnh. Với tên thuốc cụ thể, hãy dùng truy vấn trực tiếp.'
        required = [s.intent for s in PRESET_CHAINS[preset] if not s.include_previous]
    elif mode == 'one_hop' or mode in COMPARISON_MODES:
        required = intents
    else:
        required = []
    missing = [i for i in required if i not in service.intents or not service.intents[i].relations]
    if missing:
        return 'Ontology hiện tại chưa có nhóm quan hệ cần thiết: ' + ', '.join(missing) + '.'
    return None
