import json
import os
from typing import Any, Dict
import sys

import storage


def _settings_path() -> str:
    return os.path.join(storage.default_data_dir(), "settings.json")


def load_settings() -> Dict[str, Any]:
    path = _settings_path()
    if not os.path.exists(os.path.dirname(path)):
        os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        # Default settings: increase fonts by 25%
        return {"font_scale": 1.25}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {"font_scale": 1.25}
            if "font_scale" not in data:
                data["font_scale"] = 1.25
            return data
    except Exception:
        return {"font_scale": 1.25}


def save_settings(settings: Dict[str, Any]) -> None:
    path = _settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


# Runtime flags
VERBOSE: bool = any(arg == "--verbose" for arg in sys.argv)


def vprint(*args: Any, **kwargs: Any) -> None:
    if VERBOSE:
        print(*args, **kwargs)
