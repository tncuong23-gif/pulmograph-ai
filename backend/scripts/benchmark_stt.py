"""Compare recorded Vietnamese speech with a verified reference via the running backend."""
from __future__ import annotations

import argparse
import json
import time
import unicodedata
from pathlib import Path

import httpx


def normalize(text: str) -> str:
    return ' '.join(unicodedata.normalize('NFC', text).casefold().split())


def edit_distance(reference, hypothesis):
    row = list(range(len(hypothesis)+1))
    for i, token in enumerate(reference, 1):
        new = [i]
        for j, other in enumerate(hypothesis, 1):
            new.append(min(new[-1]+1, row[j]+1, row[j-1]+(token != other)))
        row = new
    return row[-1]


def error_rates(reference: str, hypothesis: str) -> dict:
    reference, hypothesis = normalize(reference), normalize(hypothesis)
    if not reference:
        raise ValueError('Reference cannot be empty')
    tokens = reference.split()
    # Vietnamese whitespace units are usually syllables, not linguistic words.
    return {'character_error_rate': edit_distance(reference, hypothesis)/len(reference),
            'whitespace_token_error_rate': edit_distance(tokens, hypothesis.split())/len(tokens)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--reference', help='Verified original words; punctuation is counted.')
    parser.add_argument('--base-url', default='http://127.0.0.1:8100')
    parser.add_argument('--runs', type=int, choices=range(1, 6), default=2)
    parser.add_argument('--mode', choices=('fast', 'careful'), default='fast')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    audio = args.audio.read_bytes()
    if not audio or len(audio) > 12*1024*1024:
        parser.error('Audio must be nonempty and at most 12 MiB')
    results = []
    with httpx.Client(timeout=600, trust_env=False) as client:
        for _ in range(args.runs):
            started = time.perf_counter()
            response = client.post(args.base_url.rstrip('/')+'/api/v1/voice/transcribe',
                                   data={'mode': args.mode},
                                   files={'file': (args.audio.name, audio, 'application/octet-stream')})
            response.raise_for_status()
            result = response.json()
            result['request_ms'] = round((time.perf_counter()-started)*1000)
            if args.reference is not None:
                result.update(error_rates(args.reference, result['transcript']))
            results.append(result)
    report = json.dumps({'audio': str(args.audio), 'runs': results}, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(report+'\n', encoding='utf-8')
    print(report)


if __name__ == '__main__':
    main()
