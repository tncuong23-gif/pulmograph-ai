"""Embedding-based boundaries within a section, with exact source offsets.

Semantic chunks do not overlap across topic boundaries. A token ceiling is a
safety constraint, including for an individual sentence longer than E5 accepts.
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
import math

CHUNKER_VERSION = 'section-semantic-offset-v2'


@dataclass(frozen=True)
class ChunkConfig:
    target: int = 450
    overlap: int = 80
    method: str = 'semantic'
    semantic_percentile: float = 90.0
    semantic_min_distance: float = 0.05
    semantic_min_tokens: int = 80
    semantic_window: int = 2

    def __post_init__(self):
        if not isinstance(self.target, int) or self.target < 1:
            raise ValueError('RAG_CHUNK_TOKENS phải là số nguyên dương.')
        if not isinstance(self.overlap, int) or not 0 <= self.overlap < self.target:
            raise ValueError('Overlap phải nhỏ hơn chunk size.')
        if self.method not in {'semantic', 'token'}:
            raise ValueError('RAG_CHUNK_METHOD phải là semantic hoặc token.')
        if not math.isfinite(self.semantic_percentile) or not 0 <= self.semantic_percentile <= 100:
            raise ValueError('RAG_SEMANTIC_PERCENTILE phải nằm trong [0, 100].')
        if not math.isfinite(self.semantic_min_distance) or not 0 <= self.semantic_min_distance <= 2:
            raise ValueError('RAG_SEMANTIC_MIN_DISTANCE phải nằm trong [0, 2].')
        if not isinstance(self.semantic_min_tokens, int) or self.semantic_min_tokens < 1:
            raise ValueError('RAG_SEMANTIC_MIN_TOKENS phải là số nguyên dương.')
        if not isinstance(self.semantic_window, int) or not 1 <= self.semantic_window <= 8:
            raise ValueError('RAG_SEMANTIC_WINDOW phải nằm trong [1, 8].')


def profile(encoder, config):
    effective = config.method
    if effective == 'semantic' and not getattr(encoder, 'supports_semantic', False):
        effective = 'token'
    return {'version': CHUNKER_VERSION, 'requested_method': config.method,
            'method': effective, 'config': vars(config), 'embedding_max_tokens': encoder.max_length,
            'fallback_reason': 'encoder_not_semantic' if effective != config.method else None}


def _fits(text, header, encoder, config):
    return (len(encoder.offsets(text)) <= config.target
            and encoder.count('passage: ' + header + text) <= encoder.max_length)


def _split_sentence(full, begin, end, header, encoder, config):
    """Return contiguous ranges; retain spaces, newlines and source characters."""
    if _fits(full[begin:end], header, encoder, config):
        return [(begin, end)]
    offsets = encoder.offsets(full[begin:end])
    if not offsets:
        raise ValueError('Không thể chia câu nguồn vừa giới hạn embedding.')
    ranges = []
    cursor, token = begin, 0
    while token < len(offsets):
        lo, hi, best = token + 1, min(token + config.target, len(offsets)), None
        while lo <= hi:
            mid = (lo + hi) // 2
            stop = end if mid == len(offsets) else begin + offsets[mid][0]
            if _fits(full[cursor:stop], header, encoder, config):
                best, lo = mid, mid + 1
            else:
                hi = mid - 1
        if best is None:
            raise ValueError('Một token không vừa cửa sổ embedding; kiểm tra tiêu đề và nguồn.')
        # Only this fallback may split a source sentence. Prefer punctuation,
        # but never mistake a decimal such as 92.5 for a sentence boundary.
        if best < len(offsets):
            punctuation = False
            for candidate in range(best, max(token + 1, best - 40), -1):
                a, b = offsets[candidate - 1]
                last = full[begin+a:begin+b]
                next_char = full[begin+b:begin+b+1]
                stop = begin + offsets[candidate][0]
                if last.endswith(('.', '!', '?', ';')) and (not next_char or next_char.isspace()) and _fits(full[cursor:stop], header, encoder, config):
                    best = candidate
                    punctuation = True
                    break
            if not punctuation:
                for candidate in range(best, max(token + 1, best - 40), -1):
                    stop = begin + offsets[candidate][0]
                    if full[stop-1:stop].isspace() and _fits(full[cursor:stop], header, encoder, config):
                        best = candidate
                        break
        stop = end if best == len(offsets) else begin + offsets[best][0]
        if stop <= cursor:
            raise ValueError('Tokenizer offsets không tiến triển.')
        ranges.append((cursor, stop))
        cursor, token = stop, best
    return ranges


def _unit(vector):
    if not vector or any(not math.isfinite(x) for x in vector):
        raise ValueError('Embedding ngữ nghĩa rỗng hoặc không hữu hạn.')
    length = math.sqrt(math.fsum(x*x for x in vector))
    if length <= 1e-12:
        raise ValueError('Embedding ngữ nghĩa có độ dài bằng không.')
    return [x / length for x in vector]


def _mean(vectors):
    return _unit([math.fsum(values) / len(vectors) for values in zip(*vectors)])


def _percentile(values, percentile):
    values = sorted(values)
    position = (len(values)-1) * percentile / 100
    left = int(position)
    right = min(left + 1, len(values)-1)
    return values[left] + (values[right]-values[left]) * (position-left)


def semantic_ranges(full, spans, header, encoder, config):
    """Ranges carry a reason and score; no section-wide fixed-size slicing."""
    atoms = []
    begin = 0
    for _sa, end, sid, _pid in spans:
        for a, b in _split_sentence(full, begin, end, header, encoder, config):
            atoms.append((a, b, sid))
        begin = end
    if not atoms:
        return []
    distances, threshold = {}, None
    if len({atom[2] for atom in atoms}) > 1:
        texts = [full[a:b] for a, b, _sid in atoms]
        # Explicit bounded batches avoid materializing all model tensors at once.
        vectors = []
        for start in range(0, len(texts), 32):
            # E5 uses query: for symmetric semantic similarity; final RAG
            # chunks still use passage: in the ordinary indexing step.
            batch = encoder.encode(texts[start:start+32], query=True)
            if len(batch) != len(texts[start:start+32]):
                raise ValueError('Số vector ngữ nghĩa không khớp câu nguồn.')
            vectors.extend(_unit(v) for v in batch)
        if len({len(v) for v in vectors}) != 1:
            raise ValueError('Chiều embedding ngữ nghĩa không thống nhất.')
        window = config.semantic_window
        for i in range(len(atoms)-1):
            if atoms[i][2] == atoms[i+1][2]:
                continue  # fragments of one original sentence use only the ceiling
            left = _mean(vectors[max(0, i-window+1):i+1])
            right = _mean(vectors[i+1:i+1+window])
            cosine = max(-1.0, min(1.0, math.fsum(a*b for a, b in zip(left, right))))
            distances[i] = 1.0 - cosine
        if distances:
            threshold = max(config.semantic_min_distance, _percentile(list(distances.values()), config.semantic_percentile))
    offsets = encoder.offsets(full)
    token_starts = [a for a, _b in offsets]
    minimum = min(config.semantic_min_tokens, config.target)
    ranges, start, end = [], 0, 0
    for i, (a, b, _sid) in enumerate(atoms):
        if end > start and not _fits(full[start:b], header, encoder, config):
            ranges.append({'start': start, 'end': end, 'reason': 'token_limit', 'distance': None, 'threshold': threshold})
            start = a
        end = b
        distance = distances.get(i)
        remaining = len(token_starts) - bisect_left(token_starts, b)
        if (threshold is not None and distance is not None and distance > 1e-10
                and distance + 1e-12 >= threshold
                and len(encoder.offsets(full[start:end])) >= minimum and remaining >= minimum):
            ranges.append({'start': start, 'end': end, 'reason': 'semantic', 'distance': distance, 'threshold': threshold})
            start = end
    if end > start:
        ranges.append({'start': start, 'end': end, 'reason': 'section_end', 'distance': None, 'threshold': threshold})
    return ranges


def token_ranges(full, header, encoder, config):
    """Legacy token windows, with bounded overlap and exact source spans."""
    offsets = encoder.offsets(full)
    if not offsets:
        if not _fits(full, header, encoder, config):
            raise ValueError('Nguồn không thể chia vừa giới hạn embedding.')
        return [{'start': 0, 'end': len(full), 'reason': 'section_end', 'distance': None, 'threshold': None}]
    ranges, start = [], 0
    while start < len(offsets):
        lo, hi, best = start+1, min(start+config.target, len(offsets)), None
        a = 0 if start == 0 else offsets[start][0]
        while lo <= hi:
            mid = (lo+hi)//2
            b = len(full) if mid == len(offsets) else offsets[mid][0]
            if _fits(full[a:b], header, encoder, config):
                best, lo = mid, mid+1
            else:
                hi = mid-1
        if best is None:
            raise ValueError('Một token không vừa cửa sổ embedding.')
        if best < len(offsets):
            for j in range(best, max(start+1, best-40), -1):
                if full[offsets[j-1][0]:offsets[j-1][1]].endswith(('.', '!', '?', ';')) and _fits(full[a:offsets[j][0]], header, encoder, config):
                    best = j
                    break
        b = len(full) if best == len(offsets) else offsets[best][0]
        ranges.append({'start': a, 'end': b, 'reason': 'section_end' if best == len(offsets) else 'token_limit', 'distance': None, 'threshold': None})
        if best == len(offsets):
            break
        start = max(start+1, best-min(config.overlap, (best-start)//2))
    return ranges
