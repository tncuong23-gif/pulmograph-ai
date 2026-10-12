import os

# Prevent OpenMP and BLAS runtime clashes and segfaults on Apple Silicon / CPU
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

__version__ = "0.2.0"

from .schema import get_default_schema_path, load_schema

__all__ = [
    "__version__",
    "load_schema",
    "get_default_schema_path",
]

