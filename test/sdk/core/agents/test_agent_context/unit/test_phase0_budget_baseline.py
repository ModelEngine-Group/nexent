"""Phase 0 snapshots for current context budget and compression triggers."""

from factories import make_cm, make_memory_mixed, make_model, make_original_messages


def test_default_budget_snapshot():
    manager = make_cm(enabled=True, threshold=10_000)

    assert manager.config.token_threshold == 10_000
    assert manager.config.soft_input_budget_tokens == 0
    assert manager.config.hard_input_budget_tokens == 0
    assert manager._soft_input_budget_tokens() == 10_000
    assert manager._hard_input_budget_tokens() == 11_000
    assert manager.config.keep_recent_steps == 2
    assert manager.config.keep_recent_pairs == 1


def test_disabled_context_manager_never_compresses_baseline():
    manager = make_cm(enabled=False, threshold=1)
    memory = make_memory_mixed(n_prev_pairs=2, n_curr_actions=2)
    original = make_original_messages(memory)

    result = manager.compress_if_needed(None, memory, original, current_run_start_idx=4)

    assert result is original
    assert manager.compression_calls_log == []


def test_soft_budget_is_the_compression_trigger_baseline():
    manager = make_cm(enabled=True, threshold=999_999, keep_recent_steps=2, keep_recent_pairs=1)
    manager.config.soft_input_budget_tokens = 10
    manager.config.hard_input_budget_tokens = 999_999
    memory = make_memory_mixed(n_prev_pairs=3, n_curr_actions=2)
    original = make_original_messages(memory)
    model = make_model('{"task_overview": "phase0 baseline"}')

    result = manager.compress_if_needed(model, memory, original, current_run_start_idx=6)

    assert result is not original
    model.assert_called_once()
    assert manager.get_token_counts()["last_uncompressed"] is not None
    assert manager.get_token_counts()["last_compressed"] is not None
