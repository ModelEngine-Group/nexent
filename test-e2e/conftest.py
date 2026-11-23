"""Load the formal suite fixtures for case-local pytest modules."""

from pathlib import Path
import sys


_AUTOMATION = Path(__file__).resolve().parent / "infra" / "automation"
_REPO = Path(__file__).resolve().parent.parent
for _source in (_AUTOMATION, _REPO, _REPO / "backend", _REPO / "sdk"):
    if str(_source) not in sys.path:
        sys.path.insert(0, str(_source))

pytest_plugins = ["nexent_formal_pytest"]
