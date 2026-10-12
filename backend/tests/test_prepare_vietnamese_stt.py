import json
import sys
import types
from pathlib import Path

import pytest
from dotenv import dotenv_values
from scripts.prepare_vietnamese_stt import activate_model, prepare


def test_activation_preserves_existing_settings_and_backup(tmp_path):
    env = tmp_path / '.env'
    old = 'VOICE_STT_MODEL=small\nCONTEXT_NEO4J_PASSWORD=example-only\n# keep me\n'
    env.write_text(old)
    model = tmp_path / 'models' / 'phowhisper-small-ct2'
    activate_model(env, model)
    settings = dotenv_values(env)
    assert settings['VOICE_STT_MODEL'] == str(model.resolve())
    assert settings['CONTEXT_NEO4J_PASSWORD'] == 'example-only' and '# keep me' in env.read_text()
    backups = list(tmp_path.glob('.env.before-phowhisper-*'))
    assert len(backups) == 1 and backups[0].read_text() == old


def test_conversion_pins_one_revision_and_reuses_complete_output(tmp_path, monkeypatch):
    calls = []
    class Converter:
        def __init__(self, source, **kwargs):
            calls.append((source, kwargs))
        def convert(self, directory, **kwargs):
            path = Path(directory); path.mkdir()
            (path / 'model.bin').write_bytes(b'test-weight')
            (path / 'config.json').write_text('{}')
    class Tokenizer:
        @classmethod
        def from_pretrained(cls, source, **kwargs):
            calls.append((source, kwargs)); return cls()
        def save_pretrained(self, directory):
            (Path(directory) / 'tokenizer.json').write_text('{}')
    preprocessor = tmp_path / 'preprocessor.json'; preprocessor.write_text('{}')
    monkeypatch.setitem(sys.modules, 'ctranslate2.converters', types.SimpleNamespace(TransformersConverter=Converter))
    monkeypatch.setitem(sys.modules, 'transformers', types.SimpleNamespace(AutoTokenizer=Tokenizer))
    monkeypatch.setitem(sys.modules, 'huggingface_hub', types.SimpleNamespace(
        HfApi=lambda: types.SimpleNamespace(model_info=lambda source: types.SimpleNamespace(sha='fixed-revision')),
        hf_hub_download=lambda *args, **kwargs: str(preprocessor)))
    output = tmp_path / 'model'
    prepare('small', output); prepare('small', output)
    assert len(calls) == 2 and all(kw['revision'] == 'fixed-revision' and not kw['trust_remote_code'] for _, kw in calls)
    assert json.loads((output / 'source.json').read_text())['source'] == 'vinai/PhoWhisper-small'
    with pytest.raises(FileExistsError): prepare('medium', output)


def test_refuses_incomplete_directory_and_does_not_delete_it(tmp_path):
    output = tmp_path / 'model'; output.mkdir(); marker = output / 'important.txt'; marker.write_text('keep')
    with pytest.raises(FileExistsError): prepare('small', output)
    assert marker.read_text() == 'keep'
