from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from threading import RLock

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / 'vendor' / 'clinical-ie'


class ClinicalRuntime:
    def __init__(self):
        self.ie = Path(os.getenv('CLINICAL_IE_BUNDLE', str(VENDOR/'models/clinical-ie-models-v1.3')))
        self.fusion = Path(os.getenv('CLINICAL_FUSION_BUNDLE', str(VENDOR/'models/classifier-fusion-v1')))
        self.index = Path(os.getenv('CLINICAL_REFERENCE_BUNDLE', str(VENDOR/'data/reference-index-v1.1')))
        self.device = os.getenv('CLINICAL_DEVICE', 'auto')
        self.lock = RLock()
        self.assistant = None
        self.classifier = None

    def inventory(self):
        missing = []
        for label, root, manifest in [('ie', self.ie, 'bundle.json'), ('fusion', self.fusion, 'bundle.json'), ('index', self.index, 'manifest.json')]:
            try:
                data = json.loads((root/manifest).read_text(encoding='utf-8'))
                files = data.get('files', {})
                if not files: missing.append(f'{label}/{manifest}: empty inventory')
                for name in files:
                    if not (root/name).is_file(): missing.append(f'{label}/{name}')
            except (OSError, ValueError): missing.append(f'{label}/{manifest}')
        return missing

    def _imports(self):
        src = str(VENDOR/'src')
        if src not in sys.path: sys.path.insert(0, src)
        # The original package enforces offline flags. It runs in this process only.
        from clinical_ie.models import resolve_device
        dev = resolve_device(self.device)
        if self.device.startswith('cuda') and not dev.startswith('cuda'):
            raise RuntimeError('CLINICAL_DEVICE=cuda nhưng PyTorch của .venv-clinical không nhận CUDA.')
        return dev

    def _classifier(self):
        if self.classifier is None:
            dev = self._imports()
            from clinical_ie.classification.late_fusion import LateFusionClassifier
            self.classifier = LateFusionClassifier.from_bundle(self.fusion, device=dev)
        return self.classifier

    def _assistant(self):
        if self.assistant is None:
            missing = self.inventory()
            if missing:
                raise RuntimeError('Thiếu thành phần Clinical IE: '+', '.join(missing))
            dev = self._imports()
            from clinical_ie.api import ResearchAssistant, ClinicalPipeline
            from clinical_ie.retrieval.reference_index import ReferenceIndex
            # Reuse the same verified fusion model for all modalities.
            self.assistant = ResearchAssistant(ClinicalPipeline.from_bundle(self.ie, device=dev),
                self._classifier(), ReferenceIndex.load(self.index), device=dev,
                model_versions={'ie_bundle':'v1.3','classifier_bundle':'classifier-fusion-v1','index_bundle':'v1.1'})
        return self.assistant

    def analyze(self, *, text=None, image_path=None, document_id=None, symptom_query=False):
        with self.lock:
            if text is not None:
                assistant = self._assistant()
                result = (assistant.ask_symptoms(text) if symptom_query else
                          assistant.analyze_text(text, document_id=document_id, namespace='clinical_case', image_path=image_path))
                data = result.to_dict()
            else:
                prediction = self._classifier().predict(image_path=image_path)
                from clinical_ie.api import RESEARCH_DISCLAIMER
                data = {'schema_version':'1.0','input_type':'xray_image','document_id':document_id,
                    'engine':'convnext_tiny','status':prediction.status,
                    'top5':[row.to_dict() for row in prediction.top5],
                    'all_scores':prediction.all_scores,'all_probabilities':prediction.all_probabilities,
                    'extracted_facts':{'num_entities':0,'num_triples':0,'entities':[],'triples':[]},
                    'graph':None,'similar_cases':[],'missing_information_questions':[],
                    'model_versions':{'classifier_bundle':'classifier-fusion-v1'},
                    'warnings':[RESEARCH_DISCLAIMER, *prediction.warnings]}
            data['modality'] = 'text_xray' if text is not None and image_path else 'text' if text is not None else 'xray'
            data['score_semantics'] = 'uncalibrated_decision_scores'
            return {'ok':True,'data':data}
