from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class RuleSpec:
    label: str
    phrase: str
    canonical: str | None = None
    confidence: float = 0.78


PHRASE_RULES: tuple[RuleSpec, ...] = (
    # Symptoms
    RuleSpec("SYMPTOM", "khó thở", confidence=0.92),
    RuleSpec("SYMPTOM", "đau ngực", confidence=0.90),
    RuleSpec("SYMPTOM", "đau lói ngực", canonical="đau ngực", confidence=0.90),
    RuleSpec("SYMPTOM", "đau lói", canonical="đau", confidence=0.84),
    RuleSpec("SYMPTOM", "ho ra máu", confidence=0.94),
    RuleSpec("SYMPTOM", "ho khan", confidence=0.90),
    RuleSpec("SYMPTOM", "ho đàm", confidence=0.88),
    RuleSpec("SYMPTOM", "ho khạc đàm", canonical="ho đàm", confidence=0.90),
    RuleSpec("SYMPTOM", "khò khè", confidence=0.90),
    RuleSpec("SYMPTOM", "đau họng", confidence=0.88),
    RuleSpec("SYMPTOM", "chóng mặt", confidence=0.88),
    RuleSpec("SYMPTOM", "buồn nôn", confidence=0.90),
    RuleSpec("SYMPTOM", "nôn ói", confidence=0.90),
    RuleSpec("SYMPTOM", "nhợn ói", canonical="buồn nôn", confidence=0.88),
    RuleSpec("SYMPTOM", "ói", canonical="nôn", confidence=0.78),
    RuleSpec("SYMPTOM", "tiêu lỏng", confidence=0.88),
    RuleSpec("SYMPTOM", "tiêu phân đỏ", confidence=0.84),
    RuleSpec("SYMPTOM", "ăn uống kém", confidence=0.85),
    RuleSpec("SYMPTOM", "ăn kém", canonical="ăn uống kém", confidence=0.82),
    RuleSpec("SYMPTOM", "nặng ngực", confidence=0.88),
    RuleSpec("SYMPTOM", "đau quặn bụng", confidence=0.88),
    RuleSpec("SYMPTOM", "quặn bụng", canonical="đau quặn bụng", confidence=0.84),
    RuleSpec("SYMPTOM", "đau bụng", confidence=0.86),
    RuleSpec("SYMPTOM", "lói ngực", canonical="đau ngực", confidence=0.84),
    RuleSpec("SYMPTOM", "tiêu phân lỏng", canonical="tiêu lỏng", confidence=0.88),
    RuleSpec("SYMPTOM", "táo bón", confidence=0.86),
    RuleSpec("SYMPTOM", "khó khè", canonical="khò khè", confidence=0.78),
    RuleSpec("SYMPTOM", "lạnh run", confidence=0.84),
    RuleSpec("SYMPTOM", "mệt", confidence=0.72),
    RuleSpec("SYMPTOM", "ho", confidence=0.68),
    RuleSpec("SYMPTOM", "sốt", confidence=0.72),
    # Signs
    RuleSpec("SIGN", "ran nổ", confidence=0.94),
    RuleSpec("SIGN", "rale nổ", canonical="ran nổ", confidence=0.94),
    RuleSpec("SIGN", "ran ẩm", confidence=0.94),
    RuleSpec("SIGN", "rale ẩm", canonical="ran ẩm", confidence=0.94),
    RuleSpec("SIGN", "ran rít", confidence=0.94),
    RuleSpec("SIGN", "rale rít", canonical="ran rít", confidence=0.94),
    RuleSpec("SIGN", "giảm thông khí", confidence=0.90),
    RuleSpec("SIGN", "giảm âm", confidence=0.82),
    RuleSpec("SIGN", "thở co kéo", confidence=0.92),
    RuleSpec("SIGN", "co kéo cơ hô hấp phụ", canonical="thở co kéo", confidence=0.92),
    RuleSpec("SIGN", "co lõm ngực", canonical="thở co lõm ngực", confidence=0.90),
    RuleSpec("SIGN", "co kéo", canonical="thở co kéo", confidence=0.78),
    RuleSpec("SIGN", "thở nhanh", confidence=0.88),
    RuleSpec("SIGN", "thở đều", confidence=0.80),
    RuleSpec("SIGN", "rung thanh đều", confidence=0.84),
    RuleSpec("SIGN", "tím tái", confidence=0.94),
    RuleSpec("SIGN", "tím môi", confidence=0.92),
    RuleSpec("SIGN", "môi tím", canonical="tím môi", confidence=0.92),
    RuleSpec("SIGN", "môi hồng nhạt", confidence=0.86),
    RuleSpec("SIGN", "báng bụng", confidence=0.90),
    RuleSpec("SIGN", "vàng da", confidence=0.88),
    RuleSpec("SIGN", "da niêm hồng nhạt", confidence=0.88),
    RuleSpec("SIGN", "da niêm trắng bệt", confidence=0.90),
    RuleSpec("SIGN", "lơ mơ", confidence=0.88),
    RuleSpec("SIGN", "tiếp xúc chậm", confidence=0.88),
    RuleSpec("SIGN", "không tỉnh", canonical="giảm ý thức", confidence=0.84),
    RuleSpec("SIGN", "đừ", confidence=0.80),
    RuleSpec("SIGN", "bức rức", canonical="bứt rứt", confidence=0.82),
    RuleSpec("SIGN", "bứt rứt", confidence=0.84),
    RuleSpec("SIGN", "nốt hồng ban", confidence=0.88),
    RuleSpec("SIGN", "hồng ban", confidence=0.82),
    RuleSpec("SIGN", "âm thổi", confidence=0.86),
    RuleSpec("SIGN", "huyết áp cao", confidence=0.86),
    RuleSpec("SIGN", "bụng mềm", confidence=0.82),
    RuleSpec("SIGN", "ấn đau", confidence=0.88),
    RuleSpec("SIGN", "phản ứng thành bụng", confidence=0.90),
    RuleSpec("SIGN", "chi lạnh", confidence=0.88),
    RuleSpec("SIGN", "mạch khó bắt", confidence=0.88),
    RuleSpec("SIGN", "nhịp nhanh xoang", confidence=0.90),
    RuleSpec("SIGN", "phù chân", confidence=0.90),
    RuleSpec("SIGN", "phù", confidence=0.70),
    # Conditions
    RuleSpec("CONDITION", "đái tháo đường type 2", canonical="đái tháo đường type 2", confidence=0.97),
    RuleSpec("CONDITION", "đái tháo đường type 1", canonical="đái tháo đường type 1", confidence=0.97),
    RuleSpec("CONDITION", "đái tháo đường tuýp 2", canonical="đái tháo đường type 2", confidence=0.97),
    RuleSpec("CONDITION", "đái tháo đường", confidence=0.96),
    RuleSpec("CONDITION", "tăng huyết áp", confidence=0.97),
    RuleSpec("CONDITION", "tăng HA", canonical="tăng huyết áp", confidence=0.92),
    RuleSpec("CONDITION", "suy tim", confidence=0.96),
    RuleSpec("CONDITION", "suy hô hấp", confidence=0.97),
    RuleSpec("CONDITION", "viêm phổi", confidence=0.97),
    RuleSpec("CONDITION", "lao phổi", confidence=0.97),
    RuleSpec("CONDITION", "tràn dịch màng phổi", confidence=0.98),
    RuleSpec("CONDITION", "tràn khí màng phổi", confidence=0.98),
    RuleSpec("CONDITION", "xẹp phổi", confidence=0.97),
    RuleSpec("CONDITION", "phù phổi", confidence=0.97),
    RuleSpec("CONDITION", "u phổi", confidence=0.96),
    RuleSpec("CONDITION", "bệnh thận mạn", confidence=0.96),
    RuleSpec("CONDITION", "suy thận mạn", confidence=0.97),
    RuleSpec("CONDITION", "suy thận", confidence=0.92),
    RuleSpec("CONDITION", "viêm gan virus B mạn", canonical="viêm gan B mạn", confidence=0.97),
    RuleSpec("CONDITION", "viêm gan virus B", canonical="viêm gan B", confidence=0.97),
    RuleSpec("CONDITION", "viêm gan B", confidence=0.96),
    RuleSpec("CONDITION", "viêm gan C", confidence=0.96),
    RuleSpec("CONDITION", "xơ gan", confidence=0.96),
    RuleSpec("CONDITION", "u gan", confidence=0.94),
    RuleSpec("CONDITION", "sỏi thận", confidence=0.94),
    RuleSpec("CONDITION", "viêm phế quản", confidence=0.96),
    RuleSpec("CONDITION", "nhồi máu cơ tim", confidence=0.96),
    RuleSpec("CONDITION", "thoái hóa cột sống", confidence=0.94),
    RuleSpec(
        "CONDITION",
        "tràn khí-dịch màng phổi",
        canonical="tràn khí dịch màng phổi",
        confidence=0.97,
    ),
    RuleSpec("CONDITION", "tràn khí dịch màng phổi", confidence=0.97),
    RuleSpec("CONDITION", "suy van tĩnh mạch", confidence=0.94),
    RuleSpec("CONDITION", "dãn tĩnh mạch", confidence=0.92),
    RuleSpec("CONDITION", "hẹp động mạch", confidence=0.92),
    RuleSpec("CONDITION", "tràn khí", canonical="tràn khí màng phổi", confidence=0.88),
    RuleSpec("CONDITION", "hen phế quản", canonical="hen", confidence=0.94),
    RuleSpec("CONDITION", "rung nhĩ", confidence=0.95),
    RuleSpec("CONDITION", "COPD", canonical="bệnh phổi tắc nghẽn mạn tính", confidence=0.98),
    RuleSpec("CONDITION", "hen", confidence=0.80),
    # Tests
    RuleSpec("TEST", "X-quang", canonical="X-quang", confidence=0.94),
    RuleSpec("TEST", "X quang", canonical="X-quang", confidence=0.92),
    RuleSpec("TEST", "Xquang", canonical="X-quang", confidence=0.92),
    RuleSpec("TEST", "XQ ngực", canonical="X-quang ngực", confidence=0.92),
    RuleSpec("TEST", "XQ", canonical="X-quang", confidence=0.86),
    RuleSpec("TEST", "CT-scan", canonical="CT", confidence=0.94),
    RuleSpec("TEST", "CT scan", canonical="CT", confidence=0.94),
    RuleSpec("TEST", "CT", canonical="CT", confidence=0.88),
    RuleSpec("TEST", "SA", canonical="siêu âm", confidence=0.82),
    RuleSpec("TEST", "điện tim", confidence=0.92),
    RuleSpec("TEST", "ECG", canonical="điện tim", confidence=0.95),
    RuleSpec("TEST", "siêu âm", confidence=0.92),
    RuleSpec("TEST", "đường huyết mao mạch", confidence=0.95),
    RuleSpec("TEST", "đường máu mao mạch", canonical="đường huyết mao mạch", confidence=0.95),
    RuleSpec("TEST", "Glucose máu mao mạch", canonical="đường huyết mao mạch", confidence=0.96),
    RuleSpec("TEST", "ĐHMM", canonical="đường huyết mao mạch", confidence=0.94),
    RuleSpec("TEST", "ĐMMM", canonical="đường huyết mao mạch", confidence=0.94),
    RuleSpec("TEST", "Định nhóm máu ABO", confidence=0.94),
    RuleSpec("TEST", "Định nhóm Rh", confidence=0.94),
    RuleSpec("TEST", "Bilirubin", confidence=0.92),
    RuleSpec("TEST", "Urobilinogen", confidence=0.92),
    RuleSpec("TEST", "Thể Cetonic", confidence=0.92),
    RuleSpec("TEST", "ASC", confidence=0.88),
    RuleSpec("TEST", "Protein", confidence=0.88),
    RuleSpec("TEST", "Hồng cầu", confidence=0.88),
    RuleSpec("TEST", "Nitrit", confidence=0.90),
    RuleSpec("TEST", "Bạch cầu", confidence=0.88),
    RuleSpec("TEST", "Tỷ trọng", confidence=0.90),
    # Qualitative results
    RuleSpec("RESULT", "dương tính", confidence=0.86),
    RuleSpec("RESULT", "âm tính", confidence=0.82),
    RuleSpec("RESULT", "thâm nhiễm", confidence=0.80),
    RuleSpec("RESULT", "đông đặc", confidence=0.86),
    RuleSpec("RESULT", "mờ phế nang lan tỏa", confidence=0.86),
    RuleSpec("RESULT", "mờ phế nang", confidence=0.82),
    # Anatomy
    RuleSpec("ANATOMY", "hai phế trường", confidence=0.94),
    RuleSpec("ANATOMY", "2 phế trường", canonical="hai phế trường", confidence=0.94),
    RuleSpec("ANATOMY", "phổi bên phải", canonical="phổi phải", confidence=0.95),
    RuleSpec("ANATOMY", "phổi bên trái", canonical="phổi trái", confidence=0.95),
    RuleSpec("ANATOMY", "phổi phải", confidence=0.95),
    RuleSpec("ANATOMY", "phổi trái", confidence=0.95),
    RuleSpec("ANATOMY", "phổi (P)", canonical="phổi phải", confidence=0.96),
    RuleSpec("ANATOMY", "phổi (T)", canonical="phổi trái", confidence=0.96),
    RuleSpec("ANATOMY", "đáy phổi (P)", canonical="đáy phổi phải", confidence=0.97),
    RuleSpec("ANATOMY", "đáy phổi (T)", canonical="đáy phổi trái", confidence=0.97),
    RuleSpec("ANATOMY", "đáy phổi", confidence=0.88),
    RuleSpec("ANATOMY", "đỉnh phổi", confidence=0.88),
    RuleSpec("ANATOMY", "màng phổi", confidence=0.88),
    RuleSpec("ANATOMY", "phế quản", confidence=0.86),
    RuleSpec("ANATOMY", "lồng ngực", confidence=0.88),
    RuleSpec("ANATOMY", "chi dưới", confidence=0.90),
    RuleSpec("ANATOMY", "ngực", confidence=0.70),
    RuleSpec("ANATOMY", "thượng vị", confidence=0.86),
    RuleSpec("ANATOMY", "bụng", confidence=0.78),
    RuleSpec("ANATOMY", "gan", confidence=0.72),
    RuleSpec("ANATOMY", "thận", confidence=0.72),
    RuleSpec("ANATOMY", "lách", confidence=0.76),
    RuleSpec("ANATOMY", "tim", confidence=0.74),
    RuleSpec("ANATOMY", "phổi", confidence=0.72),
    # Treatments
    RuleSpec("TREATMENT", "thở oxy", confidence=0.94),
    RuleSpec("TREATMENT", "oxy mask", canonical="thở oxy qua mask", confidence=0.92),
    RuleSpec("TREATMENT", "oxy canula", canonical="thở oxy qua canula", confidence=0.92),
    RuleSpec("TREATMENT", "đặt nội khí quản", confidence=0.96),
    RuleSpec("TREATMENT", "nội khí quản", confidence=0.84),
    RuleSpec("TREATMENT", "dẫn lưu màng phổi", confidence=0.96),
    RuleSpec("TREATMENT", "đặt stent", confidence=0.94),
    RuleSpec("TREATMENT", "chạy thận", canonical="lọc máu chu kỳ", confidence=0.92),
    RuleSpec("TREATMENT", "thuốc giãn phế quản", confidence=0.88),
    RuleSpec("TREATMENT", "thuốc dãn phế quản", canonical="thuốc giãn phế quản", confidence=0.88),
    RuleSpec("TREATMENT", "thuốc xịt họng", canonical="thuốc xịt", confidence=0.82),
    RuleSpec("TREATMENT", "thở oxy túi", canonical="thở oxy qua mask túi", confidence=0.92),
    RuleSpec("TREATMENT", "oxy mask túi", canonical="thở oxy qua mask túi", confidence=0.94),
    RuleSpec("TREATMENT", "glucose 10%", confidence=0.92),
    RuleSpec("TREATMENT", "hạ sốt", confidence=0.82),
    RuleSpec("TREATMENT", "điều trị tư", canonical="điều trị trước nhập viện", confidence=0.76),
    RuleSpec("TREATMENT", "uống thuốc", canonical="điều trị bằng thuốc", confidence=0.76),
    RuleSpec("TREATMENT", "dùng thuốc", canonical="điều trị bằng thuốc", confidence=0.76),
    RuleSpec("TREATMENT", "ARV", confidence=0.94),
    RuleSpec("TREATMENT", "Amlodipin", confidence=0.95),
    RuleSpec("TREATMENT", "Captopril", confidence=0.95),
    RuleSpec("TREATMENT", "Ceftriaxon", canonical="Ceftriaxone", confidence=0.95),
    RuleSpec("TREATMENT", "Cefotaxim", confidence=0.95),
    RuleSpec("TREATMENT", "Dexamethasone", confidence=0.95),
    RuleSpec("TREATMENT", "Remdesivir", confidence=0.96),
    RuleSpec("TREATMENT", "Enoxaparin", confidence=0.96),
    RuleSpec("TREATMENT", "Insulin", confidence=0.92),
)

MEASUREMENT_PATTERN = re.compile(
    r"(?P<test>SpO[₂2]|SPO[₂2]|WBC|NEU#?|LYM#?|MONO#?|EOS#?|BASO#?|RBC|HGB|HCT|"
    r"MCV|MCHC?|RDW|PLT|MPV|PCT|PDW|CRP|ProBNP|Procalcitonin|Troponin\s*T|"
    r"Albumin|ALT(?:\s*\(GPT\))?|SGOT(?:\s*\(AST\))?|CPK-MB|Creatinin|"
    r"eGFR(?:\s*\(MDRD\))?|Na\+|K\+|Cl-|HbA1C|Ur[eê]|Bạch\s+cầu|Hồng\s+cầu|Glucose|HA|"
    r"huyết\s*áp|nhiệt(?:\s*độ)?|(?<!tĩnh\s)(?<!động\s)(?<!mao\s)mạch|"
    r"\bM(?=[ \t]*:)|pCO2(?:\s+động\s+mạch)?|pO2(?:\s+động\s+mạch)?|"
    r"pH(?:\s+động\s+mạch)?|nhịp\s*thở|ĐHMM|ĐMMM|"
    r"(?:Glucose|đường)\s+máu\s+mao\s+mạch|"
    r"đường\s*huyết(?:\s*mao\s*mạch)?)"
    r"[ \t]*(?:tại[ \t]+giường[ \t]*)?(?:\(\s*một\s+lần\s*\)[ \t]*)?"
    r"(?:\d+(?:[.,]\d+)?h[ \t]*)?[:=]?[ \t]*"
    r"(?P<result>(?:[<>]=?[ \t]*)?\d+(?:[.,]\d+)?(?:\s*/\s*\d+(?:[.,]\d+)?)?"
    r"[ \t]*(?:%|mmHg|mg%|mg/d[lL]|mmol/[lL]|pg/m[lL]|"
    r"lần[ \t]*/?[ \t]*(?:phút|ph)|l[ \t]*/[ \t]*(?:phút|ph|p)|°C|oC|độ[ \t]*C)?)",
    re.IGNORECASE,
)

TROPONIN_VARIANT_PATTERN = re.compile(
    r"(?P<test>Troponin)[ \t]*:[ \t]*T?[ \t]*(?P<result>\d+(?:[.,]\d+)?[ \t]*(?:pg/m[lL])?)",
    re.IGNORECASE,
)

QUALITATIVE_LAB_PATTERN = re.compile(
    r"(?P<test>Định\s+nhóm\s+máu\s+ABO|Định\s+nhóm\s+Rh(?:\s*\(Anti-D\))?)"
    r"[ \t]*:[ \t]*(?P<result>AB|A|B|O|DƯƠNG|ÂM)(?!\w)",
    re.IGNORECASE,
)

POST_INTERVENTION_RESULT_PATTERN = re.compile(
    r"(?:->|→)[ \t]*(?P<result>\d+(?:[.,]\d+)?[ \t]*(?:%|mmHg|mg%|mg/d[lL]|mmol/[lL]))",
    re.IGNORECASE,
)

PH_TEST_PATTERN = re.compile(r"(?P<test>pH)(?=[ \t]*:)", re.IGNORECASE)

TIME_PATTERN = re.compile(
    r"(?<![\w.,])(?:cách\s+(?:ngày\s+)?nhập\s+viện\s+(?:khoảng\s+)?)?#?\s*(?:hơn\s+|khoảng\s+)?\d+(?:[.,]\d+)?(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?"
    r"\s*(?:giờ|h|ngày|tuần|tháng|năm)(?!\w)|"
    r"(?<!\w)(?:cùng\s+ngày|sáng\s+nay|chiều\s+nay|hôm\s+nay)(?!\w)|"
    r"(?<![\w.,])(?:\d+(?:[.,]\d+)?(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?\s*)?lần\s*/\s*(?:ngày|giờ|phút)(?!\w)|"
    r"(?<!\w)(?:từng\s+cơn|liên\s+tục|thường\s+xuyên|gần\s+đây|"
    r"(?:lúc|khi)\s+nhập\s+viện|ban\s+đêm|về\s+đêm)(?!\w)",
    re.IGNORECASE,
)

NEGATION_PATTERN = re.compile(
    r"(?:không|chưa|chưa\s+ghi\s+nhận|không\s+ghi\s+nhận|không\s+thấy|không\s+có)\s+$",
    re.IGNORECASE,
)
POSSIBLE_PATTERN = re.compile(
    r"(?:nghi|theo\s+dõi|có\s+thể|khả\s+năng|không\s+rõ)\s+$",
    re.IGNORECASE,
)
HISTORY_PATTERN = re.compile(r"(?:tiền\s+sử|tiền\s+căn|đã\s+từng)\s*[:\-]?\s*$", re.IGNORECASE)
HISTORY_MARKER_PATTERN = re.compile(r"\b(?:tiền\s+sử|tiền\s+căn|TS)\s*:", re.IGNORECASE)
CURRENT_MARKER_PATTERN = re.compile(r"\b(?:hiện\s+khám(?:\s+ghi\s+nhận)?|khám)\s*:", re.IGNORECASE)

SEVERITY_PATTERNS = {
    "MILD": re.compile(r"\b(?:nhẹ|ít)\b", re.IGNORECASE),
    "MODERATE": re.compile(r"\b(?:vừa)\b", re.IGNORECASE),
    "SEVERE": re.compile(r"\b(?:nặng|nhiều)\b", re.IGNORECASE),
}
COURSE_PATTERNS = {
    "STABLE": re.compile(r"\b(?:không\s+giảm|ổn|ổn\s+định|không\s+đổi)\b", re.IGNORECASE),
    "IMPROVING": re.compile(r"\b(?:giảm|đỡ|hết|cải\s+thiện)\b", re.IGNORECASE),
    "WORSENING": re.compile(r"\b(?:tăng\s+dần|nặng\s+dần|xấu\s+dần)\b", re.IGNORECASE),
}

CASE_RELATIONS = {
    "SYMPTOM": "HAS_SYMPTOM",
    "SIGN": "HAS_SIGN",
    "CONDITION": "HAS_CONDITION",
    "TEST": "HAS_TEST",
    "TREATMENT": "HAS_TREATMENT",
}


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    escaped = re.escape(phrase).replace(r"\ ", r"\s+")
    return re.compile(r"(?<!\w)" + escaped + r"(?!\w)", re.IGNORECASE)


COMPILED_PHRASES = tuple((spec, _phrase_pattern(spec.phrase)) for spec in PHRASE_RULES)


def _candidate(
    text: str,
    start: int,
    end: int,
    label: str,
    canonical: str | None,
    confidence: float,
    priority: int,
) -> dict:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return {
        "start": start,
        "end": end,
        "text": text[start:end],
        "label": label,
        "canonical": canonical or text[start:end],
        "confidence": confidence,
        "priority": priority,
    }


def _resolve_overlaps(candidates: Iterable[dict]) -> list[dict]:
    ordered = sorted(
        candidates,
        key=lambda item: (-(item["end"] - item["start"]), -item["priority"], item["start"]),
    )
    accepted: list[dict] = []
    for candidate in ordered:
        overlaps = any(
            candidate["start"] < item["end"] and item["start"] < candidate["end"]
            for item in accepted
        )
        if not overlaps:
            accepted.append(candidate)
    return sorted(accepted, key=lambda item: (item["start"], item["end"]))


def _qualifiers(text: str, entity: dict, section: str) -> dict[str, str]:
    start, end = entity["start"], entity["end"]
    left = text[max(0, start - 80):start]
    clause_left = re.split(r"[,;.!?\n]|(?:->|=>|\+)", left)[-1]
    attribute_left = re.split(r"[,;.!?\n]|(?:->|=>|\+)", text[max(0, start - 20):start])[-1]
    attribute_right = re.split(
        r"[,;.!?\n]|(?:->|=>|\+)",
        text[end:min(len(text), end + 28)],
    )[0]
    attribute_context = f"{attribute_left} {attribute_right}"

    assertion = "PRESENT"
    suffix_negated = bool(
        re.match(
            r"\s*(?:(?:chi|chân|tay)\s*)?\(\s*-\s*\)",
            text[end:min(len(text), end + 24)],
            re.IGNORECASE,
        )
    )
    dependency_negated = bool(
        entity["label"] == "TREATMENT"
        and re.search(r"không\s+phụ\s+thuộc\s+$", clause_left, re.IGNORECASE)
    )
    if NEGATION_PATTERN.search(clause_left) or suffix_negated or dependency_negated:
        assertion = "NEGATED"
    elif POSSIBLE_PATTERN.search(clause_left):
        assertion = "POSSIBLE"

    temporality = "HISTORY" if section == "tiensubenh_banthan" else "CURRENT"
    if HISTORY_PATTERN.search(clause_left):
        temporality = "HISTORY"
    prefix = text[:start]
    history_markers = [match.start() for match in HISTORY_MARKER_PATTERN.finditer(prefix)]
    current_markers = [match.start() for match in CURRENT_MARKER_PATTERN.finditer(prefix)]
    if history_markers and max(history_markers) > max(current_markers, default=-1):
        temporality = "HISTORY"
    if entity["label"] in {"CONDITION", "TREATMENT"} and (
        re.search(r"\b(?:đã|cũ)\b", attribute_context, re.IGNORECASE)
    ):
        temporality = "HISTORY"

    qualifiers: dict[str, str] = {
        "assertion": assertion,
        "temporality": temporality,
    }
    if entity["label"] in {"SYMPTOM", "SIGN", "CONDITION"}:
        for value, pattern in SEVERITY_PATTERNS.items():
            if pattern.search(attribute_context):
                qualifiers["severity"] = value
                break
        for value, pattern in COURSE_PATTERNS.items():
            if pattern.search(attribute_context):
                qualifiers["course"] = value
                break

    laterality_right = re.split(
        r"[,;.!?\n]|(?:->|=>|\+)",
        text[end:min(len(text), end + 24)],
    )[0]
    laterality_context = f"{entity['text']} {laterality_right}".casefold()
    if re.search(r"(?:\(p\)|\bbên\s+phải\b|\bphổi\s+phải\b)", laterality_context):
        qualifiers["laterality"] = "RIGHT"
    elif re.search(r"(?:\(t\)|\bbên\s+trái\b|\bphổi\s+trái\b)", laterality_context):
        qualifiers["laterality"] = "LEFT"
    elif re.search(
        r"(?:hai\s+bên|2\s+bên|hai\s+phế\s+trường|2\s+phế\s+trường)",
        laterality_context,
    ):
        qualifiers["laterality"] = "BILATERAL"
    return qualifiers


def infer_qualifiers(text: str, entity: dict, section: str) -> dict[str, str]:
    """Attach the rule-based clinical qualifiers to a model entity.

    Model inference and silver annotation share this public wrapper so that
    assertion, temporality, severity, course, and laterality stay consistent.
    Entity offsets must be local to ``text`` and use an exclusive end index.
    """
    return _qualifiers(text, entity, section)


def extract_entities(text: str, section: str) -> list[dict]:
    candidates: list[dict] = []
    for pattern in (MEASUREMENT_PATTERN, TROPONIN_VARIANT_PATTERN, QUALITATIVE_LAB_PATTERN):
        for match in pattern.finditer(text):
            candidates.append(
                _candidate(text, match.start("test"), match.end("test"), "TEST", None, 0.96, 120)
            )
            candidates.append(
                _candidate(text, match.start("result"), match.end("result"), "RESULT", None, 0.95, 120)
            )

    for match in POST_INTERVENTION_RESULT_PATTERN.finditer(text):
        candidates.append(
            _candidate(text, match.start("result"), match.end("result"), "RESULT", None, 0.90, 115)
        )

    for match in PH_TEST_PATTERN.finditer(text):
        candidates.append(
            _candidate(text, match.start("test"), match.end("test"), "TEST", None, 0.90, 90)
        )

    for match in TIME_PATTERN.finditer(text):
        start = match.start()
        while start < match.end() and text[start].isspace():
            start += 1
        if start < match.end() and text[start] == "#":
            start += 1
        candidates.append(_candidate(text, start, match.end(), "TIME", None, 0.90, 100))

    for spec, pattern in COMPILED_PHRASES:
        for match in pattern.finditer(text):
            candidates.append(
                _candidate(
                    text,
                    match.start(),
                    match.end(),
                    spec.label,
                    spec.canonical,
                    spec.confidence,
                    80,
                )
            )

    resolved = _resolve_overlaps(candidates)
    entities: list[dict] = []
    for index, entity in enumerate(resolved, start=1):
        clean = {key: value for key, value in entity.items() if key != "priority"}
        clean["id"] = f"E{index}"
        clean["qualifiers"] = _qualifiers(text, clean, section)
        clean["source"] = "rule"
        entities.append(clean)
    return entities


def _distance(left: dict, right: dict) -> int:
    if left["end"] <= right["start"]:
        return right["start"] - left["end"]
    if right["end"] <= left["start"]:
        return left["start"] - right["end"]
    return 0


def _between(text: str, left: dict, right: dict) -> str:
    first, second = sorted((left, right), key=lambda item: item["start"])
    return text[first["end"]:second["start"]]


def _relation_key(relation: dict) -> tuple[str, str, str]:
    return relation["subject"], relation["predicate"], relation["object"]


def extract_relations(text: str, section: str, doc_id: str, entities: list[dict]) -> tuple[list[dict], list[dict]]:
    relations: list[dict] = []

    def add(subject: str, predicate: str, obj: str, confidence: float, source: str) -> None:
        relations.append(
            {
                "subject": subject,
                "predicate": predicate,
                "object": obj,
                "confidence": confidence,
                "source": source,
            }
        )

    for entity in entities:
        predicate = CASE_RELATIONS.get(entity["label"])
        if entity["label"] == "CONDITION" and entity.get("qualifiers", {}).get("temporality") == "HISTORY":
            predicate = "HAS_HISTORY"
        if predicate:
            add(doc_id, predicate, entity["id"], 1.0, "derived_from_entity_type")

    relation_candidates: list[dict] = []

    def add_candidate(head: dict, tail: dict, label: str, confidence: float) -> None:
        relation_candidates.append(
            {
                "subject": head["id"],
                "object": tail["id"],
                "allowed_labels": [label, "NO_RELATION"],
                "suggested_label": label,
                "confidence": confidence,
            }
        )
        add(head["id"], label, tail["id"], confidence, "rule")

    def has_intervening_entity(left: dict, right: dict) -> bool:
        first, second = sorted((left, right), key=lambda item: item["start"])
        return any(
            entity["id"] not in {left["id"], right["id"]}
            and entity["start"] >= first["end"]
            and entity["end"] <= second["start"]
            for entity in entities
        )

    def same_clause(left: dict, right: dict) -> bool:
        connector = _between(text, left, right)
        return not (
            re.search(r"[,;.!?\n/+>]|[-–—]", connector)
            or re.search(r"\b(?:thì|sau\s+đó|rồi)\b", connector, re.IGNORECASE)
        )

    def location_compatible(head: dict, anatomy: dict) -> bool:
        head_text = head["text"].casefold()
        anatomy_text = anatomy["text"].casefold()
        connector = _between(text, head, anatomy)

        if head["label"] == "TEST":
            return (
                head["end"] <= anatomy["start"]
                and _distance(head, anatomy) <= 10
                and bool(re.search(r"x[ -]?quang|\bxq\b|\bct(?:[ -]?scan)?\b|siêu\s+âm|\bsa\b", head_text))
            )
        if head["label"] == "SYMPTOM":
            return bool(re.search(r"đau|lói|quặn", head_text))
        if head["label"] == "SIGN":
            if re.search(r"ran|rale|giảm\s+âm|giảm\s+thông\s+khí|co\s+kéo|co\s+lõm", head_text):
                return bool(re.search(r"phổi|phế|ngực", anatomy_text))
            if re.search(r"ấn\s+đau|phản\s+ứng\s+thành\s+bụng|chướng", head_text):
                return bool(re.search(r"bụng|thượng\s+vị|gan|hạ\s+sườn", anatomy_text))
            if re.search(r"hồng\s+ban|phù", head_text):
                return head["end"] <= anatomy["start"]
            return False
        if head["label"] == "CONDITION":
            return ":" not in connector
        if head["label"] == "TREATMENT":
            return bool(re.search(r"dẫn\s+lưu|phẫu\s+thuật|can\s+thiệp", head_text))
        return False

    # Numeric measurements belong to nearby test expressions. Qualitative imaging
    # findings may span a longer phrase, but only belong to an imaging test. This
    # prevents an unrelated lab test from absorbing a later X-ray or infectious-
    # disease result merely because it is the nearest preceding test.
    tests = [entity for entity in entities if entity["label"] == "TEST"]
    results = [entity for entity in entities if entity["label"] == "RESULT"]
    for result in results:
        is_numeric = bool(re.search(r"\d", result["text"]))
        is_imaging_finding = bool(
            re.search(
                r"thâm\s+nhiễm|đông\s+đặc|mờ\s+phế\s+nang",
                result["text"],
                re.IGNORECASE,
            )
        )
        choices = [
            test
            for test in tests
            if 0 <= result["start"] - test["end"] <= (25 if is_numeric else 180)
            and "\n" not in text[test["end"]:result["start"]]
            and (
                is_numeric
                or (
                    bool(re.search(r"định\s+nhóm\s+(?:máu\s+)?(?:abo|rh)", test["text"], re.IGNORECASE))
                    and result["start"] - test["end"] <= 5
                )
                or (
                    is_imaging_finding
                    and bool(
                        re.search(
                            r"x[ .-]?quang|\bxq\b|\bct(?:[ -]?scan)?\b|siêu\s+âm|\bsa\b",
                            test["text"],
                            re.IGNORECASE,
                        )
                    )
                )
            )
        ]
        if choices:
            test = min(choices, key=lambda item: result["start"] - item["end"])
            predicate = "REVEALS" if is_imaging_finding else "HAS_RESULT"
            add_candidate(test, result, predicate, 0.95)

    # Imaging findings expressed as a sign or diagnosis (rather than a generic
    # RESULT) are linked explicitly to the imaging test that revealed them.
    imaging_tests = [
        test
        for test in tests
        if re.search(r"x[ q.-]?(?:quang)?|ct(?:[ -]?scan)?|siêu\s+âm|\bsa\b", test["text"], re.IGNORECASE)
    ]
    for finding in entities:
        if finding["label"] not in {"SIGN", "CONDITION"}:
            continue
        choices = [
            test
            for test in imaging_tests
            if 0 <= finding["start"] - test["end"] <= 220
            and "\n" not in text[test["end"]:finding["start"]]
            and not any(
                other["label"] == "TEST"
                and other["id"] != test["id"]
                and test["end"] <= other["start"] < finding["start"]
                for other in entities
            )
            and (
                ":" in text[test["end"]:finding["start"]]
                or re.search(
                    r"(?:cho\s+thấy|ghi\s+nhận|phát\s+hiện|hình\s+ảnh|kết\s+quả)",
                    text[test["end"]:finding["start"]],
                    re.IGNORECASE,
                )
            )
        ]
        if choices:
            test = min(choices, key=lambda item: finding["start"] - item["end"])
            add_candidate(test, finding, "REVEALS", 0.82)

    # Keep at most one nearest anatomy and one nearest time per clinical entity.
    anatomies = [entity for entity in entities if entity["label"] == "ANATOMY"]
    times = [entity for entity in entities if entity["label"] == "TIME"]
    for head in entities:
        if head["label"] in {"SYMPTOM", "SIGN", "CONDITION", "TEST", "TREATMENT"}:
            nearby_anatomies = [
                anatomy
                for anatomy in anatomies
                if _distance(head, anatomy) <= 28
                and same_clause(head, anatomy)
                and not has_intervening_entity(head, anatomy)
                and location_compatible(head, anatomy)
            ]
            if nearby_anatomies:
                generic_anatomies = {"phổi", "tim", "ngực", "lồng ngực", "bụng", "gan", "lách"}
                anatomy = min(
                    nearby_anatomies,
                    key=lambda item: (
                        item["text"].casefold() in generic_anatomies,
                        _distance(head, item),
                        item["start"] < head["end"],
                    ),
                )
                confidence = 0.80 if _distance(head, anatomy) <= 12 else 0.68
                add_candidate(head, anatomy, "LOCATED_AT", confidence)

        if head["label"] in {"SYMPTOM", "SIGN", "CONDITION", "TEST", "RESULT", "TREATMENT"}:
            nearby_times = [
                time
                for time in times
                if _distance(head, time) <= 45
                and head.get("qualifiers", {}).get("assertion") != "NEGATED"
                and time.get("qualifiers", {}).get("assertion") != "NEGATED"
                and same_clause(head, time)
                and not any(
                    entity["id"] not in {head["id"], time["id"]}
                    and entity["label"] != "ANATOMY"
                    and entity["start"] >= min(head["end"], time["end"])
                    and entity["end"] <= max(head["start"], time["start"])
                    for entity in entities
                )
            ]
            if nearby_times:
                time = min(nearby_times, key=lambda item: _distance(head, item))
                time_text = time["text"]
                if re.search(r"lần\s*/|từng\s+cơn|liên\s+tục|thường\s+xuyên", time_text, re.IGNORECASE):
                    if head["label"] not in {"SYMPTOM", "CONDITION"}:
                        continue
                    temporal_predicate = "HAS_FREQUENCY"
                elif re.search(r"cách\s+(?:ngày\s+)?nhập\s+viện|cùng\s+ngày|sáng\s+nay|chiều\s+nay|hôm\s+nay", time_text, re.IGNORECASE):
                    temporal_predicate = "ONSET_AT"
                elif re.search(r"\d+(?:[.,]\d+)?(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?\s*(?:giờ|h|ngày|tuần|tháng|năm)", time_text, re.IGNORECASE):
                    temporal_predicate = "HAS_DURATION"
                else:
                    temporal_predicate = "OCCURS_AT"
                add_candidate(head, time, temporal_predicate, 0.74)

    for head in entities:
        for tail in entities:
            if head["id"] == tail["id"]:
                continue
            distance = _distance(head, tail)
            allowed: list[str] = []
            suggested = "NO_RELATION"
            confidence = 0.0

            if (
                head["label"] in {"SYMPTOM", "CONDITION"}
                and tail["label"] == "TREATMENT"
                and tail.get("qualifiers", {}).get("assertion") != "NEGATED"
                and head["start"] < tail["start"]
                and distance <= 100
                and same_clause(head, tail)
                and not any(
                    entity["id"] not in {head["id"], tail["id"]}
                    and entity["label"] != "TIME"
                    and entity["start"] >= head["end"]
                    and entity["end"] <= tail["start"]
                    for entity in entities
                )
            ):
                allowed = ["TREATED_WITH"]
                connector = _between(text, head, tail)
                blocked_context = bool(
                    re.search(
                        r"không\s+phụ\s+thuộc|thuốc\s+đã\s+sử\s+dụng",
                        connector,
                        re.IGNORECASE,
                    )
                )
                if not blocked_context and (distance <= 20 or re.search(
                    r"\b(?:điều\s+trị|dùng|uống|truyền|thở|chích|tiêm)\b",
                    connector,
                    re.IGNORECASE,
                )):
                    suggested = "TREATED_WITH"
                    confidence = 0.70

            if not allowed:
                continue
            relation_candidates.append(
                {
                    "subject": head["id"],
                    "object": tail["id"],
                    "allowed_labels": allowed + ["NO_RELATION"],
                    "suggested_label": suggested,
                    "confidence": confidence,
                }
            )
            if suggested != "NO_RELATION":
                add(head["id"], suggested, tail["id"], confidence, "rule")

    # Treatment response is different from treatment assignment. Link it only
    # when an explicit response cue is present close to the treatment mention.
    response_negative = re.compile(
        r"(?:không|chưa)\s+(?:giảm|đỡ|cải\s+thiện|đáp\s+ứng)", re.IGNORECASE
    )
    response_positive = re.compile(
        r"(?:có\s+đáp\s+ứng|cải\s+thiện|(?:thấy|có|đã|thì|nên)\s+(?:đỡ|giảm)|đỡ)",
        re.IGNORECASE,
    )
    treatments = [entity for entity in entities if entity["label"] == "TREATMENT"]
    clinical_heads = [
        entity for entity in entities if entity["label"] in {"SYMPTOM", "CONDITION"}
    ]
    for treatment in treatments:
        choices = [
            head
            for head in clinical_heads
            if head["start"] < treatment["start"]
            and head.get("qualifiers", {}).get("assertion") != "NEGATED"
            and _distance(head, treatment) <= 120
            and not re.search(r"[;.!?\n]", _between(text, head, treatment))
        ]
        if not choices:
            continue
        head = min(choices, key=lambda item: _distance(item, treatment))
        response_context = text[treatment["end"]:min(len(text), treatment["end"] + 45)]
        if response_negative.search(response_context):
            add_candidate(head, treatment, "NOT_IMPROVED_BY", 0.86)
        elif response_positive.search(response_context) or (
            treatment["text"].casefold() == "điều trị tư"
            and re.match(r"\s*(?:[,()]\s*)?(?:đã\s+)?giảm\b", response_context, re.IGNORECASE)
        ):
            add_candidate(head, treatment, "IMPROVED_BY", 0.82)

    unique: dict[tuple[str, str, str], dict] = {}
    for relation in relations:
        key = _relation_key(relation)
        if key not in unique or relation["confidence"] > unique[key]["confidence"]:
            unique[key] = relation
    final_relations = sorted(unique.values(), key=lambda item: _relation_key(item))
    for index, relation in enumerate(final_relations, start=1):
        relation["id"] = f"R{index}"

    entity_by_id = {entity["id"]: entity for entity in entities}
    for relation in final_relations:
        if relation["predicate"] != "LOCATED_AT":
            continue
        subject = entity_by_id.get(relation["subject"])
        anatomy = entity_by_id.get(relation["object"])
        if not subject or not anatomy:
            continue
        laterality = anatomy.get("qualifiers", {}).get("laterality")
        if laterality and "laterality" not in subject.get("qualifiers", {}):
            subject["qualifiers"]["laterality"] = laterality

    return final_relations, relation_candidates


def preannotate_segment(segment: dict) -> dict:
    annotated = dict(segment)
    entities = extract_entities(segment["text"], segment["section"])
    relations, relation_candidates = extract_relations(
        segment["text"], segment["section"], segment["doc_id"], entities
    )
    confidence_values = [entity["confidence"] for entity in entities]
    confidence_values.extend(
        relation["confidence"] for relation in relations if relation["source"] == "rule"
    )
    minimum_confidence = min(confidence_values, default=1.0)
    annotated.update(
        {
            "annotation_status": "PREANNOTATED",
            "entities": entities,
            "relations": relations,
            "relation_candidates": relation_candidates,
            "needs_review": minimum_confidence < 0.80 or bool(relation_candidates),
            "review_notes": "",
            "preannotation_confidence": round(minimum_confidence, 4),
        }
    )
    return annotated
