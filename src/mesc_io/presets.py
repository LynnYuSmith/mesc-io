"""Registration settings you can name, keep, and hand to someone else.

A preset is a small JSON file holding the settings of one motion correction — rigid or
non-rigid, the block edge, the two shift caps, and any Suite2p option on top — plus a sentence
saying what it is for. Nothing else. In particular a preset never says which units share a
reference: which recordings are the same field is a fact about one file, not a setting, so
units stay one-reference-each unless a run names its groups.

Where they live, first match wins:

* a path — ``--preset ./soma.json`` reads that file, wherever it is. This is how a preset is
  shared, or kept beside the project it belongs to;
* ``$MESC_IO_PRESETS``, a directory, when it is set;
* otherwise ``$XDG_CONFIG_HOME/mesc-io/presets`` (``~/.config/mesc-io/presets``).

``pipeline`` is built in — the calcium-imaging pipeline's settings, which are also the defaults
— and cannot be overwritten or deleted.

The file, as `save_preset` writes it::

    {
      "mesc_io_preset": 1,
      "name": "soma",
      "description": "soma fields: coarser blocks, a looser warp cap",
      "settings": {"nonrigid": true, "block_size": 128, "max_shift": 0.1,
                   "max_shift_nr": 5.0, "ops": {"smooth_sigma": 2.0}}
    }

Only keys in ``settings`` that are stated are applied; anything left out keeps the default.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Union

from .errors import MescIOError

__all__ = ["PresetError", "preset_dir", "save_preset", "load_preset", "list_presets",
           "delete_preset", "SETTINGS", "BUILTIN"]

FORMAT = 1

#: The settings a preset may carry, and the type each must have.
SETTINGS = {"nonrigid": bool, "block_size": int, "max_shift": float, "max_shift_nr": float,
            "ops": dict}

#: Built in, and read-only. Empty settings: the defaults ARE the pipeline's.
BUILTIN = {
    "pipeline": {
        "description": "the calcium-imaging pipeline's correction — non-rigid, 64 px blocks, "
                       "3 px warp cap; the same as the defaults",
        "settings": {},
    },
}

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class PresetError(MescIOError, ValueError):
    """A preset that cannot be found, read, or written as asked."""


def preset_dir() -> Path:
    """The directory saved presets live in (not created here)."""
    env = os.environ.get("MESC_IO_PRESETS")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base).expanduser() / "mesc-io" / "presets"


def _check_settings(settings: Dict) -> Dict:
    unknown = sorted(set(settings) - set(SETTINGS))
    if unknown:
        raise PresetError(
            f"a preset holds registration settings only — not {', '.join(unknown)}. "
            f"It may carry: {', '.join(SETTINGS)}"
            + (". Which units share a reference is named per run (groups), never in a preset"
               if {"groups", "reference_from", "units"} & set(unknown) else ""))
    out = {}
    for key, value in settings.items():
        want = SETTINGS[key]
        if want is float and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        if want is int and isinstance(value, float) and value.is_integer():
            value = int(value)
        if not isinstance(value, want) or (want is not bool and isinstance(value, bool)):
            raise PresetError(f"{key} must be {want.__name__}, got {value!r}")
        out[key] = value
    if "block_size" in out and out["block_size"] < 8:
        raise PresetError(f"block_size is the block EDGE in px; {out['block_size']} is too small")
    return out


def _check_ops(ops: Dict) -> None:
    """Refuse a Suite2p option that does not exist, when Suite2p is here to ask."""
    if not ops:
        return
    try:
        from .registration import _suite2p
        _, default_ops = _suite2p()
    except ImportError:
        return                       # checked again when the preset is used to register
    unknown = sorted(k for k in ops if k not in default_ops())
    if unknown:
        raise PresetError(f"Suite2p has no such option(s): {', '.join(unknown)}")


def _path_for(name: str) -> Path:
    if not _NAME.match(name):
        raise PresetError(f"{name!r} is not a preset name: letters, digits, '_', '-', '.', "
                          "starting with a letter or digit, at most 64 characters")
    return preset_dir() / f"{name}.json"


def _looks_like_path(ref: str) -> bool:
    return ref.endswith(".json") or os.sep in ref or "/" in ref


def save_preset(name: str, settings: Dict, description: str = "", *,
                overwrite: bool = False) -> Path:
    """Write a preset under `name` and return where it went."""
    if name in BUILTIN:
        raise PresetError(f"{name!r} is built in and cannot be overwritten; pick another name")
    path = _path_for(name)
    clean = _check_settings(dict(settings))
    _check_ops(clean.get("ops", {}))
    if path.exists() and not overwrite:
        raise PresetError(f"a preset {name!r} already exists ({path}); overwrite it explicitly")
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"mesc_io_preset": FORMAT, "name": name, "description": description,
           "settings": clean}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    tmp.replace(path)                # a half-written preset is never left under the real name
    return path


def load_preset(ref: Union[str, Path, Dict]) -> Dict:
    """``{"name", "description", "settings", "source"}`` for a name, a path, or a dict.

    A dict is taken as the settings themselves, so code can pass a preset without a file.
    """
    if isinstance(ref, dict):
        return {"name": None, "description": "", "settings": _check_settings(ref),
                "source": "dict"}
    ref = str(ref)
    if ref in BUILTIN:
        b = BUILTIN[ref]
        return {"name": ref, "description": b["description"], "settings": dict(b["settings"]),
                "source": "built in"}
    path = Path(ref).expanduser() if _looks_like_path(ref) else _path_for(ref)
    if not path.exists():
        have = ", ".join(p["name"] for p in list_presets())
        raise PresetError(f"no preset {ref!r} (looked in {path}). Have: {have}")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PresetError(f"{path}: not a readable preset — {exc}") from None
    if not isinstance(doc, dict) or doc.get("mesc_io_preset") != FORMAT \
            or not isinstance(doc.get("settings"), dict):
        raise PresetError(f"{path}: not a mesc-io preset (format {FORMAT} expected)")
    return {"name": doc.get("name") or path.stem, "description": doc.get("description", ""),
            "settings": _check_settings(doc["settings"]), "source": str(path)}


def list_presets() -> List[Dict]:
    """Every preset available by name: the built-in ones, then the saved ones, by name."""
    out = [{"name": n, "description": b["description"], "source": "built in"}
           for n, b in BUILTIN.items()]
    d = preset_dir()
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            try:
                got = load_preset(str(p))
                out.append({"name": p.stem, "description": got["description"],
                            "source": str(p)})
            except PresetError as exc:
                out.append({"name": p.stem, "description": f"UNREADABLE — {exc}",
                            "source": str(p)})
    return out


def delete_preset(name: str) -> Path:
    if name in BUILTIN:
        raise PresetError(f"{name!r} is built in and cannot be deleted")
    path = _path_for(name)
    if not path.exists():
        raise PresetError(f"no saved preset {name!r} in {preset_dir()}")
    path.unlink()
    return path
