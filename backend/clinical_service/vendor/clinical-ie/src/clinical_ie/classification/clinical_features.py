"""Clinical rule-based feature extractor for vitals, temporal cues, and risk factors."""
from __future__ import annotations

import re
from typing import Any

# Pre-compiled regex patterns for clinical numerical and temporal extraction
RE_SPO2 = re.compile(r"(?:sp[o0]2|độ bão hòa oxy)[^\d]{0,10}(\d{2,3})%?", re.IGNORECASE)
RE_TEMP = re.compile(r"(?:sốt\s*(?:cao|nhẹ)?|nhiệt độ|thân nhiệt)[^\d]{0,8}(\d{2}(?:[.,]\d+)?)\s*(?:độ|°c|c)?", re.IGNORECASE)
RE_ACUTE_DAYS = re.compile(r"(\d+)\s*ngày\s*(?:nay|trước|qua)?", re.IGNORECASE)
RE_CHRONIC_SYMPTOM = re.compile(
    r"(?:ho|sốt|khó thở|mệt|đau ngực|sụt cân|bệnh|khởi phát|diễn biến|tiền sử)[^\.,;]{0,30}(\d+)\s*(?:tháng|năm)"
    r"|(\d+)\s*(?:tháng|năm)\s*nay"
    r"|kéo dài|mạn tính|tái diễn|nhiều đợt|hàng năm",
    re.IGNORECASE,
)

# Risk factors & Specific hallmark signs
RE_SMOKING = re.compile(r"hút thuốc|thuốc lào|thuốc lá|gói[\s\/-]*năm|pack[\s-]*years?", re.IGNORECASE)
RE_ASTHMA = re.compile(r"tiền sử hen|hen phế quản|cơn hen|co thắt phế quản|khò khè về đêm|rít thì thở ra", re.IGNORECASE)
RE_COPD = re.compile(r"copd|phổi tắc nghẽn|tắc nghẽn mạn tính", re.IGNORECASE)
RE_TB = re.compile(r"tiền sử lao|lao phổi|ho ra máu|sụt cân|sốt nhẹ về chiều|mồ hôi trộm|điều trị lao", re.IGNORECASE)
RE_COVID = re.compile(r"covid|sars[\s-]*cov[\s-]*2|f0|tiếp xúc f0|vùng dịch", re.IGNORECASE)

# High specificity hallmark syndrome signs
RE_EFFUSION = re.compile(r"hội chứng 3 giảm|ba giảm|gõ đục|mờ đáy phổi|dịch màng phổi|rút dịch", re.IGNORECASE)
RE_PNEUMOTHORAX = re.compile(r"gõ vang|tam chứng galliard|khí màng phổi|tràn khí|đau ngực đột ngột|nhói ngực", re.IGNORECASE)
RE_EDEMA = re.compile(r"bọt hồng|ran ẩm dâng|khó thở khi nằm|phù hai chi|phù phổi cấp", re.IGNORECASE)
RE_ATELECTASIS = re.compile(r"xẹp phổi|giảm thể tích phổi|co kéo khí quản|xẹp thùy", re.IGNORECASE)
RE_TUMOR = re.compile(r"khối u|u phổi|nốt mờ đơn độc|ngón tay dùi trống|hội chứng pancoast|hội chứng cushing", re.IGNORECASE)


CLINICAL_FEATURE_NAMES: tuple[str, ...] = (
    "vital_spo2_val",
    "vital_spo2_missing",
    "vital_hypoxemia_severe",    # SpO2 < 90%
    "vital_hypoxemia_moderate",  # 90% <= SpO2 < 95%
    "vital_spo2_normal",        # SpO2 >= 95%
    "vital_fever_high",         # Temp >= 38.5C
    "vital_fever_present",      # Temp >= 37.5C or mentioned
    "temporal_is_acute",        # <= 7 days
    "temporal_is_chronic",      # > 21 days or chronic keywords
    "risk_smoking",
    "risk_asthma_history",
    "risk_copd_history",
    "risk_tb_history",
    "risk_covid_contact",
    "sign_effusion_hallmark",
    "sign_pneumothorax_hallmark",
    "sign_pulmonary_edema_hallmark",
    "sign_atelectasis_hallmark",
    "sign_tumor_hallmark",
)


def extract_clinical_vital_features(text: str, graph: dict[str, Any] | None = None) -> dict[str, float]:
    """Extract continuous and binary clinical quantitative/temporal indicators from free text and graph."""
    text_lower = text.lower() if text else ""

    # Aggregate node labels and properties from graph if available
    graph_tokens: list[str] = []
    if graph and "nodes" in graph:
        for node in graph["nodes"]:
            if not isinstance(node, dict):
                continue
            props = node.get("properties", {}) if isinstance(node.get("properties"), dict) else {}
            assertion = str(props.get("assertion", node.get("assertion", "PRESENT"))).upper()
            if assertion == "NEGATED":
                continue
            etype = str(props.get("entity_type", node.get("label", "")))
            text_val = str(props.get("text", node.get("text", "")))
            canonical = str(props.get("canonical", props.get("canonical_name", node.get("canonical_name", ""))))
            for item in (etype, text_val, canonical):
                if item:
                    graph_tokens.append(item)

    graph_text = " ".join(graph_tokens).lower()
    combined_text = f"{text_lower} {graph_text}"

    # 1. SpO2 extraction
    spo2_val = 98.0
    spo2_missing = 1.0
    hypo_severe = 0.0
    hypo_moderate = 0.0
    spo2_normal = 0.0

    match_spo2 = RE_SPO2.search(combined_text)
    if match_spo2:
        try:
            val = float(match_spo2.group(1))
            if 50.0 <= val <= 100.0:
                spo2_val = val
                spo2_missing = 0.0
                if val < 90.0:
                    hypo_severe = 1.0
                elif val < 95.0:
                    hypo_moderate = 1.0
                else:
                    spo2_normal = 1.0
        except ValueError:
            pass

    # 2. Temperature extraction
    fever_high = 0.0
    fever_present = 0.0
    match_temp = RE_TEMP.search(combined_text)
    if match_temp:
        try:
            temp_str = match_temp.group(1).replace(",", ".")
            t_val = float(temp_str)
            if 35.0 <= t_val <= 42.5:
                if t_val >= 38.5:
                    fever_high = 1.0
                    fever_present = 1.0
                elif t_val >= 37.5:
                    fever_present = 1.0
        except ValueError:
            pass
    elif "sốt" in combined_text and not re.search(r"(?:không|chưa|không\s+thấy|không\s+có)\s+sốt\b", combined_text):
        fever_present = 1.0
        if "sốt cao" in combined_text or "sốt rét run" in combined_text:
            fever_high = 1.0

    # 3. Temporal cues
    is_acute = 0.0
    is_chronic = 0.0
    # Sanitize out smoking durations (e.g. "tiền sử hút thuốc lào 20 năm") so it doesn't trigger chronic symptom duration
    temporal_text = re.sub(
        r"(?:tiền sử\s*)?(?:hút\s*)?thuốc\s*(?:lá|lào)?[^\d,;\.]{0,10}\d+\s*năm",
        " ",
        combined_text,
        flags=re.IGNORECASE,
    )

    match_days = RE_ACUTE_DAYS.search(temporal_text)
    if match_days:
        try:
            d_val = int(match_days.group(1))
            if d_val <= 7:
                is_acute = 1.0
            elif d_val > 21:
                is_chronic = 1.0
        except ValueError:
            pass

    if RE_CHRONIC_SYMPTOM.search(temporal_text):
        is_chronic = 1.0

    # 4. Risks & Hallmarks (all non-negative for Naive Bayes compatibility)
    return {
        "vital_spo2_val": float(max(0.0, spo2_val / 100.0)),  # Scaled to [0, 1]
        "vital_spo2_missing": spo2_missing,
        "vital_hypoxemia_severe": hypo_severe,
        "vital_hypoxemia_moderate": hypo_moderate,
        "vital_spo2_normal": spo2_normal,
        "vital_fever_high": fever_high,
        "vital_fever_present": fever_present,
        "temporal_is_acute": is_acute,
        "temporal_is_chronic": is_chronic,
        "risk_smoking": 1.0 if RE_SMOKING.search(combined_text) else 0.0,
        "risk_asthma_history": 1.0 if RE_ASTHMA.search(combined_text) else 0.0,
        "risk_copd_history": 1.0 if RE_COPD.search(combined_text) else 0.0,
        "risk_tb_history": 1.0 if RE_TB.search(combined_text) else 0.0,
        "risk_covid_contact": 1.0 if RE_COVID.search(combined_text) else 0.0,
        "sign_effusion_hallmark": 1.0 if RE_EFFUSION.search(combined_text) else 0.0,
        "sign_pneumothorax_hallmark": 1.0 if RE_PNEUMOTHORAX.search(combined_text) else 0.0,
        "sign_pulmonary_edema_hallmark": 1.0 if RE_EDEMA.search(combined_text) else 0.0,
        "sign_atelectasis_hallmark": 1.0 if RE_ATELECTASIS.search(combined_text) else 0.0,
        "sign_tumor_hallmark": 1.0 if RE_TUMOR.search(combined_text) else 0.0,
    }
