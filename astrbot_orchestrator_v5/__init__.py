"""Compatibility package for the historical ``astrbot_orchestrator_v5`` name."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_PACKAGE_DIR = Path(__file__).resolve().parent
_PLUGIN_ROOT = _PACKAGE_DIR.parent

# The AstrBot plugin keeps its modules at the plugin root.  Expose that root as
# this package path so legacy imports such as ``astrbot_orchestrator_v5.tools``
# resolve without changing the plugin directory AstrBot loads.
__path__ = [str(_PLUGIN_ROOT), str(_PACKAGE_DIR)]

__version__ = "4.0.0"
__author__ = "lijiarui"

try:
    from .main import OrchestratorPlugin
except ModuleNotFoundError as exc:
    if exc.name and exc.name.startswith("astrbot"):
        OrchestratorPlugin: Any = None
    else:
        raise

__all__ = ["OrchestratorPlugin"]
