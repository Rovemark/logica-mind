"""ONNX embedder (optional: `pip install logica-mind[onnx]`).

True semantic embeddings WITHOUT torch: onnxruntime + tokenizers are ~50MB of
wheels (vs ~2GB for the torch stack), so a lean client gets real semantic recall
out of the box. Default model: all-MiniLM-L6-v2 exported to ONNX (384 dims,
mean-pooled + L2-normalised — the exact same vectors as LocalEmbedder).

The model files (~90MB) auto-download once from Hugging Face into
~/.cache/logica-mind/onnx/<model>/ — no network use after that.
"""
from __future__ import annotations

import os
import urllib.request
from typing import List, Optional

from .base import Embedder

_HF = "https://huggingface.co/{repo}/resolve/main/{path}"
_DEFAULT_REPO = "Xenova/all-MiniLM-L6-v2"
_FILES = {"model.onnx": "onnx/model.onnx", "tokenizer.json": "tokenizer.json"}


class OnnxEmbedder(Embedder):
    name = "onnx"

    def __init__(self, repo: str = _DEFAULT_REPO, dim: Optional[int] = None,
                 cache_dir: Optional[str] = None, max_length: int = 256):
        self.repo = repo
        self._dim = dim or 384
        self.max_length = max_length
        self.cache_dir = cache_dir or os.path.join(
            os.path.expanduser("~"), ".cache", "logica-mind", "onnx", repo.replace("/", "__"))
        self._sess = None
        self._tok = None

    # ---- lazy setup ----------------------------------------------------------
    def _fetch(self, fname: str, remote: str) -> str:
        path = os.path.join(self.cache_dir, fname)
        if not os.path.exists(path):
            os.makedirs(self.cache_dir, exist_ok=True)
            url = _HF.format(repo=self.repo, path=remote)
            tmp = path + ".part"
            urllib.request.urlretrieve(url, tmp)        # nosec - fixed HF host
            os.replace(tmp, path)
        return path

    def _ensure(self):
        if self._sess is not None:
            return
        try:
            import onnxruntime as ort                   # type: ignore
            from tokenizers import Tokenizer            # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "onnx extras not installed. Run: pip install logica-mind[onnx] "
                "(onnxruntime + tokenizers — no torch needed)") from e
        model_path = self._fetch("model.onnx", _FILES["model.onnx"])
        tok_path = self._fetch("tokenizer.json", _FILES["tokenizer.json"])
        self._tok = Tokenizer.from_file(tok_path)
        self._tok.enable_truncation(max_length=self.max_length)
        self._tok.enable_padding()
        self._sess = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])

    @property
    def dim(self) -> int:
        return self._dim

    # ---- embedding -----------------------------------------------------------
    def embed(self, texts: List[str]) -> List[List[float]]:
        self._ensure()
        import numpy as np                              # onnxruntime depends on numpy
        encs = self._tok.encode_batch([t or "" for t in texts])
        ids = np.array([e.ids for e in encs], dtype="int64")
        mask = np.array([e.attention_mask for e in encs], dtype="int64")
        feeds = {"input_ids": ids, "attention_mask": mask}
        # some exports also want token_type_ids — feed zeros when the graph asks
        names = {i.name for i in self._sess.get_inputs()}
        if "token_type_ids" in names:
            feeds["token_type_ids"] = np.zeros_like(ids)
        (hidden,) = self._sess.run(["last_hidden_state"], feeds)[:1]
        m = mask[..., None].astype(hidden.dtype)        # mean pooling over real tokens
        pooled = (hidden * m).sum(axis=1) / np.clip(m.sum(axis=1), 1e-9, None)
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        pooled = pooled / np.clip(norms, 1e-9, None)
        self._dim = int(pooled.shape[1])
        return [list(map(float, v)) for v in pooled]
