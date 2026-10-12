"""Measure the local official VieNeu PCM endpoint after startup warmup."""
from __future__ import annotations

import argparse
import json
import time
import wave
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--voice', default='Mai Anh')
    parser.add_argument('--text', default='Mình sẽ giải thích từng ý cho dễ hiểu. Thông tin này cần được đối chiếu với triệu chứng và kết quả khám của bạn.')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    first = None
    data = bytearray()
    started = time.perf_counter()
    with httpx.Client(timeout=180, trust_env=False) as client:
        with client.stream('POST', 'http://127.0.0.1:8880/v1/audio/speech', json={
            'model': 'vieneu-v3-turbo', 'voice': args.voice, 'input': args.text,
            'response_format': 'pcm', 'stream_format': 'audio', 'sample_rate': 48000,
        }) as response:
            response.raise_for_status()
            if response.headers.get('X-Sample-Rate') != '48000' or 'audio/pcm' not in response.headers.get('Content-Type', ''):
                raise RuntimeError('Expected mono 48 kHz PCM from VieNeu')
            for chunk in response.iter_bytes():
                if chunk:
                    if first is None:
                        first = time.perf_counter() - started
                    data.extend(chunk)
    elapsed = time.perf_counter() - started
    if not data or len(data) % 2:
        raise RuntimeError('Empty or truncated PCM response')
    duration = len(data) / (48000 * 2)
    if args.output:
        with wave.open(str(args.output), 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(48000)
            output.writeframes(data)
    print(json.dumps({'first_audio_ms': round(first * 1000), 'total_ms': round(elapsed * 1000),
                      'audio_seconds': round(duration, 2), 'rtf': round(elapsed / duration, 3),
                      'output': str(args.output) if args.output else None}, ensure_ascii=False))


if __name__ == '__main__':
    main()
