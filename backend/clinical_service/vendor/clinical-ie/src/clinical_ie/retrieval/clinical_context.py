"""Retrieval-only normalization and evidence handling.

Do not use these features as input to the frozen disease classifier. Its feature
extractor is deliberately unchanged. Missing evidence is not a negative finding.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Any

from ..classification import clinical_features as cf
from ..rules import PHRASE_RULES

OBSERVED = "observed::"
HALLMARKS = (
    "vital_fever_high", "vital_hypoxemia_severe", "temporal_is_acute",
    "temporal_is_chronic", "risk_smoking", "sign_effusion_hallmark",
    "sign_pneumothorax_hallmark", "sign_pulmonary_edema_hallmark",
)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text).strip().casefold())


def normalize_prose(text: str) -> str:
    # Preserve line boundaries for negation/history scope.
    return re.sub(r"[^\S\n]+", " ", unicodedata.normalize("NFC", text).casefold()).strip()


ALIASES = {
    (normalize(spec.label), normalize(spec.phrase)): normalize(spec.canonical or spec.phrase)
    for spec in PHRASE_RULES
}


def canonical_name(entity_type: str, text: str) -> str:
    value = normalize(text)
    return ALIASES.get((normalize(entity_type), value), value)


def node_concept(node: dict[str, Any]) -> str:
    props = node.get("properties") or {}
    etype = normalize(str(props.get("entity_type", "")))
    value = props.get("canonical") or props.get("canonical_name") or props.get("text", "")
    name = canonical_name(etype, str(value))
    return f"{etype}:{name}" if etype and name else ""


def is_current_positive(item: dict[str, Any]) -> bool:
    props = item.get("properties") or {}
    return (
        normalize(str(props.get("assertion", item.get("assertion", "present")))) == "present"
        and normalize(str(props.get("temporality", item.get("temporality", "current")))) == "current"
    )


def graph_elements(graph: dict[str, Any] | None) -> tuple[set[str], set[str]]:
    """Only confirmed, current Entity findings and Entity-to-Entity SPOs."""
    graph = graph or {}
    nodes = [n for n in graph.get("nodes", []) if n.get("kind") == "Entity" and is_current_positive(n)]
    node_map = {n["uid"]: n for n in nodes if n.get("uid")}
    concepts = {key for n in nodes if (key := node_concept(n))}
    triples: set[str] = set()
    for edge in graph.get("edges", []):
        source, target = node_map.get(edge.get("source")), node_map.get(edge.get("target"))
        if source and target and is_current_positive(edge):
            s_key, t_key = node_concept(source), node_concept(target)
            pred = normalize(str(edge.get("predicate", "")))
            if s_key and t_key and pred:
                triples.add(f"{s_key.split(':', 1)[1]}--{pred}-->{t_key.split(':', 1)[1]}")
    return concepts, triples


@lru_cache(maxsize=8192)
def phrase_pattern(phrase: str) -> re.Pattern[str]:
    return re.compile(r"(?<!\w)" + re.escape(normalize(phrase)).replace(r"\ ", r"\s+") + r"(?!\w)")


def contains_phrase(text: str, phrase: str) -> bool:
    return bool(phrase and phrase_pattern(phrase).search(normalize(text)))


# Scope stops at punctuation/contrast, not at arbitrary fixed word counts.
# Decimal points between digits are not clause boundaries.
CLAUSE_BREAK = re.compile(r"[,;!?\n]|(?<!\d)\.|\.(?!\d)|\b(?:nhưng|tuy nhiên|hiện tại|hiện nay)\b")
NEGATION = re.compile(r"\b(?:không(?!\s+chỉ\b)|chưa|phủ nhận)\b")
POSSIBLE = re.compile(r"\b(?:nghi ngờ|nghi|có thể|theo dõi|chưa loại trừ)\b")
HISTORY = re.compile(r"\b(?:tiền sử|trước đây|từng bị|đã từng)\b")


def mention_context(text: str, start: int, end: int) -> tuple[bool, bool]:
    """Return (affirmed, current) using conservative local Vietnamese cue rules."""
    left = CLAUSE_BREAK.split(text[:start])[-1]
    suffix_negative = bool(re.match(r"\s*\(\s*-\s*\)", text[end:]))
    affirmed = not (NEGATION.search(left) or POSSIBLE.search(left) or suffix_negative)
    return affirmed, not bool(HISTORY.search(left))


def positive_phrase_in_text(text: str, phrase: str) -> bool:
    text = normalize_prose(text)
    return any(all(mention_context(text, m.start(), m.end())) for m in phrase_pattern(phrase).finditer(text))


def text_concepts(text: str, vocabulary: set[str] | dict[str, Any]) -> set[str]:
    """Boundary-aware phrase fallback, including two-letter 'ho' and aliases."""
    text = normalize_prose(text)
    found = {
        key for key in vocabulary
        if ":" in key and positive_phrase_in_text(text, key.split(":", 1)[1])
    }
    for (etype, alias), canonical in ALIASES.items():
        key = f"{etype}:{canonical}"
        if key in vocabulary and positive_phrase_in_text(text, alias):
            found.add(key)
    return found


def normalize_vitals(values: dict[str, float]) -> dict[str, float]:
    """Read old sparse bundles without interpreting omitted zero flags as missing.

    Legacy to_dict dropped missing=0 but retained the measured value. A missing=1
    flag always wins over a default/imputed value, even if that value is 0.98.
    Legacy zero binary values have unknown observation status, never 'negative'.
    """
    result = {str(k): float(v) for k, v in values.items()}
    if "vital_spo2_missing" not in result:
        result["vital_spo2_missing"] = 0.0 if "vital_spo2_val" in result else 1.0
    for key in HALLMARKS:
        result.setdefault(OBSERVED + key, float(result.get(key, 0.0) > 0.0))
    result.setdefault(OBSERVED + "vital_fever_present", float(result.get("vital_fever_present", 0.0) > 0.0))
    return result


NUMBER_WORDS = {"một": 1, "hai": 2, "ba": 3, "bốn": 4, "năm": 5, "sáu": 6, "bảy": 7, "tám": 8, "chín": 9, "mười": 10}
NUMBER_DURATION = re.compile(r"\b(" + "|".join(NUMBER_WORDS) + r")\s+(ngày|tháng|năm)\b")


def _duration_words(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        preceding = re.findall(r"\w+", text[:match.start()])
        # Do not turn 'mười ba ngày' into 'mười 3 ngày' (false acute).
        if preceding and preceding[-1] in {*NUMBER_WORDS, "mươi", "lẻ", "linh"}:
            return match[0]
        return f"{NUMBER_WORDS[match[1]]} {match[2]}"
    return NUMBER_DURATION.sub(replace, text)


def _graph_evidence_text(graph: dict[str, Any] | None) -> str:
    fragments = []
    for node in (graph or {}).get("nodes", []):
        if node.get("kind") != "Entity":
            continue
        props = node.get("properties") or {}
        assertion = normalize(str(props.get("assertion", "present")))
        temporality = normalize(str(props.get("temporality", "current")))
        if temporality not in {"current", "history"}:
            continue
        prefix = "tiền sử " if temporality == "history" else ""
        prefix += "không " if assertion == "negated" else "nghi " if assertion != "present" else ""
        # Keep numeric measurements in the surface text, even when canonical is
        # only the test name (e.g. canonical='SpO2', text='SpO2 92%').
        for value in dict.fromkeys([normalize(str(props.get("text", ""))), node_concept(node).split(":", 1)[-1]]):
            if value:
                fragments.append(prefix + value)
    return "; ".join(fragments)


def extract_retrieval_vitals(text: str, graph: dict[str, Any] | None = None) -> dict[str, float]:
    """Clinical evidence with observation masks; independent of classifier features."""
    text = normalize_prose(text or "")
    text = _duration_words(text)
    combined = text + "; " + _graph_evidence_text(graph)

    # Keep the affirmed prefix of each clause. Explicit negations/uncertainty/
    # history are separately inspected below, not fed back as positive findings.
    clauses = CLAUSE_BREAK.split(combined)
    positive_text = "; ".join(re.split(r"\b(?:không(?!\s+chỉ\b)|chưa|phủ nhận|nghi ngờ|nghi|có thể|theo dõi|tiền sử|trước đây|từng bị|đã từng)\b", c, maxsplit=1)[0] for c in clauses)
    values = cf.extract_clinical_vital_features(positive_text)
    for key in cf.CLINICAL_FEATURE_NAMES:
        values[OBSERVED + key] = 0.0

    # Only a valid, affirmed, current numeric SpO2 is a measurement.
    spo2_matches = [m for m in cf.RE_SPO2.finditer(combined) if all(mention_context(combined, m.start(), m.end())) and 50 <= float(m[1]) <= 100]
    values["vital_spo2_missing"] = float(not spo2_matches)
    if spo2_matches:
        val = float(spo2_matches[0][1])
        values["vital_spo2_val"] = val / 100.0
        for key, flag in (("vital_hypoxemia_severe", val < 90), ("vital_hypoxemia_moderate", 90 <= val < 95), ("vital_spo2_normal", val >= 95)):
            values[key], values[OBSERVED + key] = float(flag), 1.0
        values[OBSERVED + "vital_spo2_val"] = 1.0
    else:
        values["vital_spo2_val"] = 0.0  # no imputed normal reading in retrieval
        for key in ("vital_hypoxemia_severe", "vital_hypoxemia_moderate", "vital_spo2_normal"):
            values[key] = 0.0

    temp_matches = [m for m in cf.RE_TEMP.finditer(combined) if all(mention_context(combined, m.start(), m.end())) and 35 <= float(m[1].replace(",", ".")) <= 42.5]
    fever_matches = list(phrase_pattern("sốt").finditer(combined))
    if temp_matches:
        temp = float(temp_matches[0][1].replace(",", "."))
        values["vital_fever_high"], values["vital_fever_present"] = float(temp >= 38.5), float(temp >= 37.5)
        values[OBSERVED + "vital_fever_high"] = values[OBSERVED + "vital_fever_present"] = 1.0
    elif fever_matches:
        affirmed = [m for m in fever_matches if all(mention_context(combined, m.start(), m.end()))]
        negative = [m for m in fever_matches if NEGATION.search(CLAUSE_BREAK.split(combined[:m.start()])[-1]) and not POSSIBLE.search(CLAUSE_BREAK.split(combined[:m.start()])[-1]) and mention_context(combined, m.start(), m.end())[1]]
        values["vital_fever_present"] = float(bool(affirmed))
        values["vital_fever_high"] = float(positive_phrase_in_text(combined, "sốt cao") or positive_phrase_in_text(combined, "sốt rét run"))
        values[OBSERVED + "vital_fever_present"] = float(bool(affirmed or negative))
        values[OBSERVED + "vital_fever_high"] = float(bool(values["vital_fever_high"] or (negative and not affirmed)))

    # Duration categories are observed together only when a duration is stated.
    if cf.RE_ACUTE_DAYS.search(positive_text) or cf.RE_CHRONIC_SYMPTOM.search(positive_text):
        values[OBSERVED + "temporal_is_acute"] = values[OBSERVED + "temporal_is_chronic"] = 1.0

    patterns = {
        "risk_smoking": cf.RE_SMOKING, "risk_asthma_history": cf.RE_ASTHMA,
        "risk_copd_history": cf.RE_COPD, "risk_tb_history": cf.RE_TB,
        "risk_covid_contact": cf.RE_COVID, "sign_effusion_hallmark": cf.RE_EFFUSION,
        "sign_pneumothorax_hallmark": cf.RE_PNEUMOTHORAX,
        "sign_pulmonary_edema_hallmark": cf.RE_EDEMA,
        "sign_atelectasis_hallmark": cf.RE_ATELECTASIS, "sign_tumor_hallmark": cf.RE_TUMOR,
    }
    for key, pattern in patterns.items():
        matches = list(pattern.finditer(combined))
        eligible = [m for m in matches if key.startswith("risk_") or mention_context(combined, m.start(), m.end())[1]]
        values[key] = float(any(mention_context(combined, m.start(), m.end())[0] for m in eligible))
        # Uncertain mentions are unknown, not explicit negative evidence.
        values[OBSERVED + key] = float(any(not POSSIBLE.search(CLAUSE_BREAK.split(combined[:m.start()])[-1]) for m in eligible))
    return values


def vitals_similarity(query: dict[str, float], reference: dict[str, float]) -> float:
    """Same 0.5/0.5 components, without missing/default agreement bonuses."""
    q, r = normalize_vitals(query), normalize_vitals(reference)
    spo2_sim = 0.0
    if q["vital_spo2_missing"] == r["vital_spo2_missing"] == 0.0:
        spo2_sim = max(0.0, 1.0 - abs(q.get("vital_spo2_val", 0.0) - r.get("vital_spo2_val", 0.0)) * 100.0 / 20.0)
    known = [key for key in HALLMARKS if q.get(OBSERVED + key, 0.0) and r.get(OBSERVED + key, 0.0)]
    match_sim = sum(q.get(k, 0.0) == r.get(k, 0.0) for k in known) / len(known) if known else 0.0
    return 0.5 * spo2_sim + 0.5 * match_sim
