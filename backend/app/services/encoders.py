"""Share one E5 model between RAG and classifier when configuration matches."""
import threading

_cache = {}
_lock = threading.Lock()


class SharedEncoder:
    def __init__(self, model):
        self.model = model
        self.lock = threading.Lock()

    def __getattr__(self, name):
        return getattr(self.model, name)

    def encode(self, *args, **kwargs):
        with self.lock:
            return self.model.encode(*args, **kwargs)


def get_encoder(model, revision=None, device='auto'):
    if device == 'auto':
        import torch
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
    key = (model, revision, device)
    with _lock:
        if key not in _cache:
            from sentence_transformers import SentenceTransformer
            _cache[key] = SharedEncoder(SentenceTransformer(model, revision=revision, device=device))
        return _cache[key]
