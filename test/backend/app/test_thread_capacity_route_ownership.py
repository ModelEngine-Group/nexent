from pathlib import Path

_BACKEND_APPS = Path(__file__).resolve().parents[3] / "backend" / "apps"


def test_tc_tlm_021_service_apps_own_process_local_thread_capacity_route():
    config_source = (_BACKEND_APPS / "config_app.py").read_text(encoding="utf-8")
    runtime_source = (_BACKEND_APPS / "runtime_app.py").read_text(encoding="utf-8")
    northbound_source = (_BACKEND_APPS / "northbound_base_app.py").read_text(
        encoding="utf-8"
    )

    route = '@app.get("/internal/thread-capacity", include_in_schema=False)'
    northbound_route = (
        '@northbound_app.get("/internal/thread-capacity", include_in_schema=False)'
    )
    assert route in config_source
    assert route in runtime_source
    assert northbound_route in northbound_source
    assert "return config_thread_manager.snapshot()" in config_source
    assert "return runtime_thread_manager.snapshot()" in runtime_source
    assert "return northbound_thread_manager.snapshot()" in northbound_source
