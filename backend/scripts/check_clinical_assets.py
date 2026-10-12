"""Check supplied bundle inventory/checksums without importing ML dependencies."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]/'clinical_service/vendor/clinical-ie'
BUNDLES=['models/clinical-ie-models-v1.3','models/classifier-fusion-v1','data/reference-index-v1.1']


def check(root=ROOT):
    report={'verified_files':0,'missing_files':[],'invalid_files':[]}
    for name in BUNDLES:
        folder=root/name
        manifest=folder/('manifest.json' if name.startswith('data/') else 'bundle.json')
        try:data=json.loads(manifest.read_text(encoding='utf-8'))
        except (OSError,ValueError):
            report['missing_files'].append(str(manifest.relative_to(root)));continue
        for relative, expected in data['files'].items():
            path=folder/relative;label=str(path.relative_to(root))
            if not path.resolve().is_relative_to(folder.resolve()):
                report['invalid_files'].append(label);continue
            if not path.is_file():
                report['missing_files'].append(label);continue
            with path.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
            if actual!=expected:report['invalid_files'].append(label)
            else:report['verified_files']+=1
    return report


if __name__=='__main__':
    result=check();print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(1 if result['missing_files'] or result['invalid_files'] else 0)
