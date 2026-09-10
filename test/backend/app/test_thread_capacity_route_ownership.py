from pathlib import Path

_BACKEND_APPS = Path(__file__).resolve().parents[3] / "backend" / "apps"


def test_tc_tlm_021_config_owns_thread_capacity_route():
    config_source = (_BACKEND_APPS / "config_app.py").read_text(encoding="utf-8")
    runtime_source = (_BACKEND_APPS / "runtime_app.py").read_text(encoding="utf-8")

    route = '@app.get("/internal/thread-capacity", include_in_schema=False)'
    assert route in config_source
    assert route not in runtime_source
