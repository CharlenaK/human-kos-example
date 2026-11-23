"""Environment and CLI configuration helpers for kos-engine (zero hardcoded user paths)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _default_repo_root() -> Path:
    # kos_engine/src/kos_engine/config.py -> check project root and parent workspace
    here = Path(__file__).resolve()
    project_root = here.parent.parent.parent.parent
    for candidate in (project_root, project_root.parent):
        if (candidate / "kos_build" / "release" / "human_kos_core.sqlite").is_file():
            return candidate
        if (candidate / "data" / "human_kos_core.sqlite").is_file():
            return candidate
    return Path.cwd()


@dataclass
class EngineConfig:
    core_path: Path
    ext_dir: Optional[Path]
    model_dir: Optional[Path]
    bridge_db_path: Path
    static_map_dir: Path
    host: str = "127.0.0.1"
    port: int = 8787
    allow_local_only: bool = False

    @classmethod
    def from_env(
        cls,
        *,
        core_path: Optional[str | Path] = None,
        ext_dir: Optional[str | Path] = None,
        model_dir: Optional[str | Path] = None,
        bridge_db_path: Optional[str | Path] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        allow_local_only: bool = False,
    ) -> "EngineConfig":
        root = _default_repo_root()
        default_core = (
            root / "kos_build" / "release" / "human_kos_core.sqlite"
            if (root / "kos_build" / "release" / "human_kos_core.sqlite").is_file()
            else root / "data" / "human_kos_core.sqlite"
        )
        resolved_core = Path(core_path or os.environ.get("KOS_CORE_DB") or default_core).resolve()

        raw_ext = ext_dir or os.environ.get("KOS_EXT_DIR")
        if raw_ext:
            resolved_ext: Optional[Path] = Path(raw_ext).resolve()
        else:
            sibling = resolved_core.parent / "human_kos_ext"
            resolved_ext = sibling if sibling.is_dir() else None

        raw_model = model_dir or os.environ.get("KOS_E5_MODEL_DIR")
        if raw_model:
            resolved_model: Optional[Path] = Path(raw_model).resolve()
        else:
            local_model = root / "Data Repository" / "_derived" / "models" / "multilingual-e5-small"
            resolved_model = local_model if (local_model / "model.onnx").is_file() else None

        resolved_bridge = Path(
            bridge_db_path
            or os.environ.get("KOS_BRIDGE_DB")
            or (root / ".kos_local" / "personal_bridge.sqlite")
        ).resolve()

        static_dir = Path(__file__).resolve().parent / "static" / "map"
        return cls(
            core_path=resolved_core,
            ext_dir=resolved_ext,
            model_dir=resolved_model,
            bridge_db_path=resolved_bridge,
            static_map_dir=static_dir,
            host=host or os.environ.get("KOS_HOST", "127.0.0.1"),
            port=int(port or os.environ.get("KOS_PORT", "8787")),
            allow_local_only=allow_local_only,
        )
