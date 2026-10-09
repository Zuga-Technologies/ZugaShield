"""
The bundled TF-IDF model must load on every Python / scikit-learn this package supports.

Regression test for the model file shipped in 1.2.2. It had been serialized by
scikit-learn 1.8.0, which only exists for Python >= 3.11. On Python 3.10 pip
resolves scikit-learn 1.7.x; the pickle still loaded, but ``predict_proba`` raised
``'LogisticRegression' object has no attribute 'multi_class'`` (1.8 removed that
parameter), the canary check refused the model, and the ML layer ran silently
disabled. Pickles load forward, not backward: the bundled model has to be saved
with the OLDEST scikit-learn the ``ml-light`` extra allows. The CI matrix runs this
on 3.10, 3.11 and 3.12 so a model saved with too new a scikit-learn is a red job,
not a warning in a log nobody reads.
"""

from pathlib import Path

import pytest

sklearn = pytest.importorskip("sklearn")
joblib = pytest.importorskip("joblib")

from zugashield.config import ShieldConfig  # noqa: E402
from zugashield.layers.ml_detector import MLDetectorLayer  # noqa: E402

_BUNDLED = Path(__file__).resolve().parents[2] / "zugashield" / "models" / "tfidf_injection.joblib"


def test_bundled_model_loads_under_this_scikit_learn():
    detector = MLDetectorLayer(ShieldConfig(ml_detector_enabled=True, ml_onnx_enabled=False))
    detector._load_tfidf()
    stats = detector.get_stats()
    assert stats["tfidf_loaded"] is True, (
        f"bundled TF-IDF model did not load under scikit-learn {sklearn.__version__}: {stats}"
    )
    assert stats["hash_verified"] is True, (
        "integrity.json has no (matching) hash for the bundled model"
    )
    assert stats["canary_passed"] is True
    assert stats["model_version"] == "2.0.0"


def test_bundled_model_records_what_saved_it():
    meta = joblib.load(_BUNDLED)["__zugashield_meta__"]
    assert meta.get("sklearn_version"), (
        "retrain with train_tfidf.py so the bundle records its scikit-learn"
    )
    assert meta.get("python_version")
