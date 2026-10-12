"""Download/test the pinned medical model; optionally activate KG-only configuration."""
from __future__ import annotations
import argparse
import shutil
from dataclasses import replace
from datetime import datetime
from dotenv import load_dotenv, set_key
from app.modules.kg_import.config import BACKEND_ROOT, MEDICAL_COLLECTION, MEDICAL_MODEL, MEDICAL_REVISION, Settings
from app.modules.kg_import.entity_vector import QdrantEntityIndex
from scripts.kg._common import utf8_stdout


def main():
    utf8_stdout()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--activate', action='store_true')
    parser.add_argument('--device', default=None, help='auto, cpu, cuda or cuda:0')
    args = parser.parse_args()
    env_file = BACKEND_ROOT / '.env'
    load_dotenv(env_file)
    current = Settings.from_env().entity_embedding
    settings = replace(current, model=MEDICAL_MODEL, revision=MEDICAL_REVISION, trust_remote_code=True,
                       collection=MEDICAL_COLLECTION, device=args.device or current.device)
    index = QdrantEntityIndex(settings, client=object())
    print(f'Model: {settings.model}\nRevision: {settings.revision}\nCache: {settings.cache_dir}', flush=True)
    print('Lần đầu tải khoảng 1,24 GB; chờ kiểm tra embedding hoàn tất.', flush=True)
    vectors = index._encode(['Bệnh phổi tắc nghẽn mạn tính', 'Bệnh phổi tắc nghẽn mãn tính', 'Đau đầu'])
    if any(vector.shape != (768,) for vector in vectors): raise ValueError('Model did not produce 768-dimensional vectors')
    print(f'Embedding OK: 3 x 768; device={index.encoder.device}', flush=True)
    if args.activate:
        if env_file.exists():
            backup = env_file.with_name('.env.before-kg-medical-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
            shutil.copy2(env_file, backup)
            print(f'Đã sao lưu cấu hình: {backup.name}')
        else: env_file.touch()
        values = {'KG_ENTITY_EMBEDDING_ENABLED': '1', 'KG_ENTITY_MODEL': MEDICAL_MODEL,
            'KG_ENTITY_MODEL_REVISION': MEDICAL_REVISION, 'KG_ENTITY_TRUST_REMOTE_CODE': '1',
            'KG_ENTITY_COLLECTION': MEDICAL_COLLECTION, 'KG_ENTITY_DEVICE': settings.device,
            'KG_ENTITY_BATCH_SIZE': str(settings.batch_size), 'KG_ENTITY_QUERY_BATCH_SIZE': str(settings.query_batch_size),
            'KG_ENTITY_MAX_SEQ_LENGTH': str(settings.max_seq_length), 'KG_ENTITY_CACHE_SIZE': str(settings.cache_size),
            'KG_ENTITY_CACHE_DIR': settings.cache_dir.replace('\\', '/')}
        for name, value in values.items(): set_key(str(env_file), name, value, quote_mode='always', encoding='utf-8')
        print('Đã cập nhật cấu hình KG. Chạy: python -m scripts.kg.index_entities')
        print('Sau khi đồng bộ xong, khởi động lại backend.')


if __name__ == '__main__': main()
