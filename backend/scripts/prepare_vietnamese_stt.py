"""Prepare the official VinAI PhoWhisper model for the existing faster-whisper runtime."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
import shutil
import tempfile


def activate_model(env_file: Path, model_path: Path):
    from dotenv import set_key
    if not env_file.is_file():
        raise FileNotFoundError('Create backend/.env from your existing configuration first.')
    backup = env_file.with_name(env_file.name + '.before-phowhisper-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    shutil.copyfile(env_file, backup)
    # python-dotenv preserves other settings and uses atomic writeback.
    set_key(str(env_file), 'VOICE_STT_MODEL', str(model_path.resolve()).replace('\\', '/'))
    print('Saved previous configuration:', backup)


def prepare(size: str, output: Path):
    required = ('model.bin', 'config.json', 'tokenizer.json', 'preprocessor_config.json')
    if output.exists():
        manifest = output / 'source.json'
        source_info = json.loads(manifest.read_text(encoding='utf-8')) if manifest.is_file() else {}
        if all((output / name).is_file() for name in required) and source_info.get('source') == f'vinai/PhoWhisper-{size}':
            print('Using existing converted model:', output)
            return
        raise FileExistsError('Output exists but is incomplete. Choose another --output directory.')
    from ctranslate2.converters import TransformersConverter
    from transformers import AutoTokenizer
    from huggingface_hub import HfApi, hf_hub_download
    source = f'vinai/PhoWhisper-{size}'
    # Resolve once and use the same immutable revision for weights and tokenizer.
    revision = HfApi().model_info(source).sha
    if not revision:
        raise RuntimeError('Cannot resolve official model revision')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='phowhisper-', dir=output.parent) as staging:
        converted = Path(staging) / 'converted'
        print('Downloading/converting', source, revision, 'to int8; this first step can take several minutes.', flush=True)
        converter = TransformersConverter(source, revision=revision, trust_remote_code=False)
        converter.convert(str(converted), quantization='int8')
        AutoTokenizer.from_pretrained(source, revision=revision, use_fast=True, trust_remote_code=False).save_pretrained(converted)
        preprocessor = hf_hub_download(source, 'preprocessor_config.json', revision=revision)
        shutil.copyfile(preprocessor, converted / 'preprocessor_config.json')
        if not all((converted / name).is_file() for name in required):
            raise RuntimeError('Conversion did not produce all runtime files; configuration has not changed.')
        (converted / 'source.json').write_text(json.dumps({'source': source, 'revision': revision, 'quantization': 'int8'}, indent=2), encoding='utf-8')
        converted.rename(output)
    print('Model ready:', output)


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--size', choices=('small', 'medium'), default='small')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--activate', action='store_true', help='Back up backend/.env and set VOICE_STT_MODEL after successful conversion.')
    args = parser.parse_args()
    output = (args.output or root / 'models' / f'phowhisper-{args.size}-ct2').resolve()
    prepare(args.size, output)
    if args.activate:
        activate_model(root / '.env', output)
    print('Restart backend. VOICE_STT_MODEL=' + str(output).replace('\\', '/'))
    print('Measure accuracy with your own recordings; regional accents are not guaranteed to transcribe perfectly.')


if __name__ == '__main__':
    main()
