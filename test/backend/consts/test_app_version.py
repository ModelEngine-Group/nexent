"""
Unit tests for ``backend.consts.const``'s version-resolution helpers.

The app version is read at import time by looking for the project
``VERSION`` file at one of several candidate paths:

    1. ``$APP_VERSION_FILE`` (env override)
    2. ``/opt/nexent/VERSION`` (container image)
    3. ``<repo-root>/VERSION`` (local development)

These tests cover each branch without depending on real filesystem state
outside the pytest tmp area. We exercise:

  - ``_collect_version_candidates`` — verifies the candidate enumeration
    order and the override / repo-root derivation logic.
  - ``_read_version_from`` — covers trim, blank-line skip, missing file,
    and ``OSError`` behaviour at the parse layer.
  - ``_resolve_app_version`` — covers end-to-end resolution by stubbing
    out ``_collect_version_candidates`` so the only path that varies is
    which candidates return content.
"""
import os
from pathlib import Path

import pytest

from backend.consts.const import (
    _collect_version_candidates,
    _read_version_from,
    _resolve_app_version,
)


def _str_path(p):
    """Render a path in a way the per-OS candidate-value tests can compare.

    On Windows ``pathlib.Path("/opt/nexent/VERSION")`` resolves to the
    current drive's absolute form (``C:\\opt\\nexent\\VERSION``) so the
    raw ``str()`` does not equal the literal POSIX string. We compare
    via ``os.path.normpath`` so the POSIX and Windows forms are
    considered equal (``/opt/nexent/VERSION`` and ``\\opt\\nexent\\VERSION``
    both normalise to ``"\\opt\\nexent\\VERSION"`` on Windows).
    """
    return os.path.normpath(str(p))


# --- Tests for _read_version_from ----------------------------------------


class TestReadVersionFrom:
    """Parsing behaviour for a single VERSION file candidate."""

    def test_reads_and_strips_first_line(self, tmp_path):
        path = tmp_path / "VERSION"
        path.write_text("  v1.2.3-trimmed  \nignored second line\n", encoding="utf-8")

        assert _read_version_from(path) == "v1.2.3-trimmed"

    def test_missing_file_returns_none(self, tmp_path):
        assert _read_version_from(tmp_path / "absent") is None

    def test_blank_first_line_returns_none(self, tmp_path):
        path = tmp_path / "VERSION"
        path.write_text("\n", encoding="utf-8")
        assert _read_version_from(path) is None

    def test_whitespace_only_first_line_returns_none(self, tmp_path):
        path = tmp_path / "VERSION"
        path.write_text("   \nreal on line two\n", encoding="utf-8")
        # ``read_text`` parses both lines; the helper only considers
        # line 0, which is whitespace-only — it should return ``None``.
        assert _read_version_from(path) is None

    def test_oserror_is_swallowed(self, tmp_path):
        # Build a tiny class that pretends the file exists but blows up
        # when read. This exercises the ``except OSError`` branch.
        class _BoomPath:
            def is_file(self):
                return True

            def read_text(self, *args, **kwargs):
                raise OSError("simulated failure")

        assert _read_version_from(_BoomPath()) is None


# --- Tests for _collect_version_candidates ------------------------------


class TestCollectVersionCandidates:
    """Enumeration of the candidate paths the resolver probes."""

    def test_no_override_yields_container_and_local(self, monkeypatch, tmp_path):
        monkeypatch.delenv("APP_VERSION_FILE", raising=False)
        candidates = [_str_path(p) for p in _collect_version_candidates()]

        # Container path is always present, normalised so the assertion
        # works on both POSIX and Windows hosts.
        assert os.path.normpath("/opt/nexent/VERSION") in candidates

        # Local layout is derived from this module's parents[2] + "VERSION".
        from backend.consts import const as const_module

        expected_local = (
            Path(const_module.__file__).resolve().parents[2] / "VERSION"
        )
        assert _str_path(expected_local) in candidates

    def test_override_is_first_when_set(self, monkeypatch):
        monkeypatch.setenv("APP_VERSION_FILE", "/some/explicit/path")
        candidates = [_str_path(p) for p in _collect_version_candidates()]

        assert candidates[0] == os.path.normpath("/some/explicit/path")

    def test_override_must_be_non_empty(self, monkeypatch):
        # ``os.getenv`` with no default returns ``""`` when the var is set
        # but empty; the helper should *not* treat that as a candidate.
        monkeypatch.setenv("APP_VERSION_FILE", "")
        candidates = [_str_path(p) for p in _collect_version_candidates()]
        assert "/some/explicit/path" not in candidates


# --- Tests for _resolve_app_version (end-to-end) ------------------------


class _FakePath:
    """Minimal stand-in for a ``Path``-like candidate.

    Lets each test declare which candidate strings exist and what content
    they contain, without touching the real filesystem.
    """

    def __init__(self, contents):
        self._contents = contents

    def is_file(self):
        return True

    def read_text(self, *args, **kwargs):
        return self._contents


class TestResolveAppVersion:
    """End-to-end resolution by stubbing out the candidate list."""

    @pytest.fixture
    def patch_candidates(self, monkeypatch):
        """Replace ``_collect_version_candidates`` so the resolver sees only
        the fake candidates the test declares.

        Returns a function ``set_(string_contents_pairs)`` that registers
        ``<path-string> -> contents`` mappings and produces a list of fake
        ``Path``-like objects for those entries in the order supplied.
        """
        installed = {"paths": []}

        def _install(string_contents_pairs):
            paths = [_FakePath(contents) for _path, contents in string_contents_pairs]
            installed["paths"] = paths
            monkeypatch.setattr(
                "backend.consts.const._collect_version_candidates",
                lambda: paths,
            )
            return paths

        return _install

    def test_first_candidate_with_content_wins(self, patch_candidates):
        patch_candidates(
            [
                ("/override", "v0.0.1-override\n"),
                ("/container", "v9.9.9-container\n"),
                ("/local", "v9.9.9-local\n"),
            ]
        )

        assert _resolve_app_version() == "v0.0.1-override"

    def test_skips_candidates_returning_none(self, patch_candidates):
        patch_candidates(
            [
                ("/override", ""),
                ("/container", "v3.0.0-container\n"),
                ("/local", "v9.9.9-local\n"),
            ]
        )

        assert _resolve_app_version() == "v3.0.0-container"

    def test_falls_back_to_local_when_earlier_candidates_blanks(
        self, patch_candidates
    ):
        patch_candidates(
            [
                ("/override", "   \n"),
                ("/container", "\n"),
                ("/local", "v4.5.6-local\n"),
            ]
        )

        assert _resolve_app_version() == "v4.5.6-local"

    def test_returns_default_when_no_candidate_resolves(
        self, patch_candidates
    ):
        patch_candidates(
            [
                ("/override", ""),
                ("/container", "   \n"),
                ("/local", "\n"),
            ]
        )

        assert _resolve_app_version() == "v2.2.1"

    def test_returns_custom_default(self, patch_candidates):
        patch_candidates([("/override", "")])

        assert _resolve_app_version(default="v9.9.9-custom") == "v9.9.9-custom"

    def test_real_repo_root_version_is_used_when_no_env_override(
        self, monkeypatch, tmp_path
    ):
        # Drive ``_collect_version_candidates`` to return only the real
        # local repo-root VERSION file, and assert that the helper picks
        # up the real on-disk version. This guards the integration between
        # the candidate enumeration and the parsing layer.
        from backend.consts import const as const_module

        local_path = Path(const_module.__file__).resolve().parents[2] / "VERSION"

        def _candidate():
            return [local_path]

        monkeypatch.setattr(
            "backend.consts.const._collect_version_candidates", _candidate
        )
        monkeypatch.delenv("APP_VERSION_FILE", raising=False)

        # The real file should resolve to the literal contents of the
        # repository's ``VERSION`` file (whatever it currently is).
        expected = local_path.read_text(encoding="utf-8").splitlines()[0].strip()
        assert _resolve_app_version() == expected
