"""Resume互換性を判定する出力影響設定のfingerprint。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from translate.common.runs import RunRecord
    from translate.common.settings import Backend, Command, Settings


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """項目別snapshotとそのcanonical SHA-256。"""

    snapshot: dict[str, Any]
    value: str


@dataclass(frozen=True, slots=True)
class SnapshotDifference:
    """保存済みと現在のsnapshotにある一つの差。"""

    path: str
    saved: object
    current: object


@dataclass(frozen=True, slots=True)
class ResumeCompatibility:
    """RunをResumeできるかと拒否理由。"""

    compatible: bool
    differences: tuple[SnapshotDifference, ...]

    @property
    def reasons(self) -> tuple[str, ...]:
        """CLI/UIで表示できる項目別理由を返す。"""

        return tuple(
            f"{item.path}: saved={item.saved!r}, current={item.current!r}"
            for item in self.differences
        )


def build_fingerprint(
    *,
    operation: Command,
    backend: Backend,
    input_hashes: Mapping[str, str],
    settings: Settings,
    rule_paths: Mapping[str, Path],
    glossary_path: Path | None = None,
    template_path: Path | None = None,
    input_manifest: list[dict[str, str | int | None]] | None = None,
) -> Fingerprint:
    """出力へ影響する入力と設定だけをcanonical化する。"""

    snapshot: dict[str, Any] = {
        "inputs": dict(sorted(input_hashes.items())),
        "operation": operation,
        "backend": backend,
        "split_pages": settings.split_pages,
        "docling": {
            "ocr_preset": settings.docling_ocr_preset,
            "ocr_lang": settings.docling_ocr_lang,
            "force_ocr": settings.docling_force_ocr,
        },
        "models": {
            "structure": settings.structure_model,
            "translation": settings.translation_model,
            "review": settings.review_model,
            "fix": settings.fix_model,
            "embedding": settings.embedding_model,
        },
        "tokens": {
            "context": settings.context_tokens,
            "output": settings.output_tokens,
            "image": settings.image_tokens,
        },
        "rules": {
            name: _optional_file_hash(path) for name, path in sorted(rule_paths.items())
        },
        "glossary": _optional_file_hash(glossary_path),
        "template": _optional_file_hash(template_path),
        "libretranslate": {
            "url": settings.libretranslate_url if backend == "libretranslate" else None
        },
    }
    if input_manifest is not None:
        snapshot["input_manifest"] = sorted(
            input_manifest,
            key=lambda item: (str(item.get("logical_path")), str(item.get("role"))),
        )
    canonical = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return Fingerprint(snapshot, hashlib.sha256(canonical).hexdigest())


def diff_snapshots(
    saved: Mapping[str, Any], current: Mapping[str, Any]
) -> tuple[SnapshotDifference, ...]:
    """Nested snapshotを比較し、利用者向けの項目pathを返す。"""

    differences: list[SnapshotDifference] = []
    _compare("", saved, current, differences)
    return tuple(differences)


def check_resume_compatibility(
    saved: RunRecord, current: Fingerprint
) -> ResumeCompatibility:
    """保存済みfingerprintと現在値が完全一致するときだけ許可する。"""

    differences = diff_snapshots(saved.settings_snapshot, current.snapshot)
    if saved.fingerprint != current.value and not differences:
        differences = (
            SnapshotDifference("fingerprint", saved.fingerprint, current.value),
        )
    return ResumeCompatibility(not differences, differences)


def _compare(
    prefix: str,
    saved: object,
    current: object,
    differences: list[SnapshotDifference],
) -> None:
    if isinstance(saved, Mapping) and isinstance(current, Mapping):
        for key in sorted(set(saved) | set(current)):
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in saved:
                differences.append(SnapshotDifference(path, None, current[key]))
            elif key not in current:
                differences.append(SnapshotDifference(path, saved[key], None))
            else:
                _compare(path, saved[key], current[key], differences)
        return
    if saved != current:
        differences.append(SnapshotDifference(prefix, saved, current))


def _optional_file_hash(path: Path | None) -> str | None:
    if path is None:
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
