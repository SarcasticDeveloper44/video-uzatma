"""JSON profile save/load + resume state file."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from video_extender.core.job import ExtendMode, JobSpec


def _enum_to_value(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: _enum_to_value(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_enum_to_value(v) for v in obj]
    return obj


def jobspec_to_dict(spec: JobSpec) -> dict[str, Any]:
    d = asdict(spec)
    return _enum_to_value(d)


def jobspec_from_dict(data: dict[str, Any]) -> JobSpec:
    kwargs: dict[str, Any] = {}
    for f in fields(JobSpec):
        if f.name not in data:
            continue
        val = data[f.name]
        if f.name == "extend_mode" and isinstance(val, str):
            val = ExtendMode(val)
        elif f.name == "filters" and isinstance(val, list):
            val = tuple(val)
        kwargs[f.name] = val
    return JobSpec(**kwargs)


def save_profile(path: Path, spec: JobSpec, extra: dict[str, Any] | None = None) -> None:
    payload = {
        "version": 1,
        "spec": jobspec_to_dict(spec),
        "extra": extra or {},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_profile(path: Path) -> tuple[JobSpec, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    spec = jobspec_from_dict(payload["spec"])
    return spec, payload.get("extra", {})


# ---- Resume state ----
def load_state(state_path: Path) -> dict[str, Any]:
    if not state_path.exists():
        return {"completed": [], "failed": {}}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"completed": [], "failed": {}}


def save_state(state_path: Path, state: dict[str, Any]) -> None:
    try:
        state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def mark_completed(
    state_path: Path, source: Path, output: Path, spec: JobSpec | None = None
) -> None:
    state = load_state(state_path)
    entry = {"source": str(source), "output": str(output)}
    if spec is not None:
        entry["spec_hash"] = spec_hash(spec)
    # Replace any existing entry with the same (source, spec_hash) key.
    existing = state.setdefault("completed", [])
    key = (entry["source"], entry.get("spec_hash"))
    state["completed"] = [
        e for e in existing if (e.get("source"), e.get("spec_hash")) != key
    ]
    state["completed"].append(entry)
    state.get("failed", {}).pop(str(source), None)
    save_state(state_path, state)


def mark_failed(state_path: Path, source: Path, error: str) -> None:
    state = load_state(state_path)
    state.setdefault("failed", {})[str(source)] = error
    save_state(state_path, state)


def spec_hash(spec: JobSpec) -> str:
    """Stable hash of a JobSpec — only the fields that affect output content.

    Output_subdir doesn't affect the produced file's content; the rest does.
    """
    payload = {
        "extend_seconds": spec.extend_seconds,
        "extend_mode": spec.extend_mode.value,
        "extender_name": spec.extender_name,
        "preset_name": spec.preset_name,
        "quality": spec.quality,
        "video_codec": spec.video_codec,
        "filters": list(spec.filters),
        "filter_options": spec.filter_options,
        "extender_options": spec.extender_options,
        "filename_template": spec.filename_template,
        "audio_fade_out_seconds": spec.audio_fade_out_seconds,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def is_completed(
    state_path: Path,
    source: Path,
    spec: JobSpec | None = None,
    output: Path | None = None,
) -> bool:
    """Resume decision: skip iff this exact (source + spec) was already completed
    and its output file still exists on disk.

    The `output` parameter is retained for backward compatibility with callers
    that pass only output path; in that mode we fall back to (source, output)
    matching for legacy state files.
    """
    state = load_state(state_path)
    src_str = str(source)
    cur_hash = spec_hash(spec) if spec is not None else None
    out_str = str(output) if output is not None else None

    for e in state.get("completed", []):
        if e.get("source") != src_str:
            continue
        # Prefer hash-based match (new state format)
        if cur_hash is not None and e.get("spec_hash") == cur_hash:
            stored_out = e.get("output")
            if stored_out and not Path(stored_out).exists():
                return False  # file was deleted — re-run
            return True
        # Legacy fallback: state predates spec_hash
        if cur_hash is None and out_str is not None and e.get("output") == out_str:
            return True
        if cur_hash is None and out_str is None:
            return True
    return False
