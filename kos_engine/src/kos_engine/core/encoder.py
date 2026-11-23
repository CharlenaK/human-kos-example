"""Lightweight ONNX Runtime + HuggingFace tokenizers encoder for multilingual-e5-small.

Avoids PyTorch and transformers at runtime while producing identical mean-pooled
L2-normalized 384d vectors with `"query: "` prefix matching Phase 1 `kos_embeddings`.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import List, Optional, Sequence

import numpy as np


class OnnxE5Encoder:
    """Lazy-loading CPU ONNX encoder for `intfloat/multilingual-e5-small`."""

    MODEL_ID = "intfloat/multilingual-e5-small"
    EMBEDDING_VERSION = "e5-small-int8-v1"
    DIM = 384

    def __init__(self, model_dir: Optional[Path] = None, max_length: int = 256) -> None:
        self.model_dir = Path(model_dir) if model_dir is not None else None
        self.max_length = max_length
        self._lock = threading.Lock()
        self._session = None
        self._tokenizer = None
        self._input_names: List[str] = []
        self._load_error: Optional[str] = None
        self._loaded = False

    @property
    def available(self) -> bool:
        if self.model_dir is None:
            return False
        return (self.model_dir / "model.onnx").is_file() and (self.model_dir / "tokenizer.json").is_file()

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    def _ensure_loaded(self) -> bool:
        if self._loaded:
            return self._session is not None and self._tokenizer is not None
        with self._lock:
            if self._loaded:
                return self._session is not None and self._tokenizer is not None
            self._loaded = True
            if not self.available:
                self._load_error = "ONNX model.onnx or tokenizer.json not found"
                return False
            try:
                import onnxruntime as ort
                from tokenizers import Tokenizer

                tok = Tokenizer.from_file(str(self.model_dir / "tokenizer.json"))
                tok.enable_truncation(max_length=self.max_length)
                tok.enable_padding(pad_id=1, pad_token="<pad>")

                sess_opts = ort.SessionOptions()
                sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                sess = ort.InferenceSession(
                    str(self.model_dir / "model.onnx"),
                    sess_options=sess_opts,
                    providers=["CPUExecutionProvider"],
                )
                self._tokenizer = tok
                self._session = sess
                self._input_names = [inp.name for inp in sess.get_inputs()]
                return True
            except Exception as exc:  # pragma: no cover - defensive runtime fallback
                self._load_error = str(exc)
                self._session = None
                self._tokenizer = None
                return False

    def encode_batch(self, texts: Sequence[str], prefix: str = "query: ") -> Optional[np.ndarray]:
        if not texts:
            return np.zeros((0, self.DIM), dtype=np.float32)
        if not self._ensure_loaded():
            return None

        prefixed = [t if t.startswith(prefix) else f"{prefix}{t}" for t in texts]
        encodings = self._tokenizer.encode_batch(prefixed)
        input_ids = np.asarray([enc.ids for enc in encodings], dtype=np.int64)
        attention_mask = np.asarray([enc.attention_mask for enc in encodings], dtype=np.int64)

        feeds = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
        }
        if "token_type_ids" in self._input_names:
            feeds["token_type_ids"] = np.zeros_like(input_ids, dtype=np.int64)

        outputs = self._session.run(None, feeds)
        last_hidden = outputs[0].astype(np.float32)

        mask = attention_mask[:, :, None].astype(np.float32)
        summed = (last_hidden * mask).sum(axis=1)
        counts = np.clip(mask.sum(axis=1), 1e-9, None)
        pooled = summed / counts
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        return (pooled / np.clip(norms, 1e-12, None)).astype(np.float32)

    def encode_query(self, query_text: str) -> Optional[np.ndarray]:
        vecs = self.encode_batch([query_text], prefix="query: ")
        if vecs is None or len(vecs) == 0:
            return None
        return vecs[0]
