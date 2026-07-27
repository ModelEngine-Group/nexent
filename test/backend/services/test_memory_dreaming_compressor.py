import json
import re
from types import SimpleNamespace

import pytest

from nexent.memory.dreaming import (
    DreamingCompressionRequest,
    DreamingMemoryUnit,
)
from nexent.monitor import get_agent_monitoring_context
from services.memory_dreaming_compressor import TenantDreamingCompressor


def test_compressor_initializes_tenant_model(mocker):
    config = {
        "model_name": "test-model",
        "base_url": "https://model.invalid/v1",
        "api_key": "secret",
        "max_input_tokens": 8_000,
        "ssl_verify": False,
    }
    mocker.patch(
        "services.memory_dreaming_compressor.tenant_config_manager.get_model_config",
        return_value=config,
    )
    mocker.patch(
        "services.memory_dreaming_compressor.get_model_name_from_config",
        return_value="test-model",
    )
    model_class = mocker.patch(
        "services.memory_dreaming_compressor.OpenAIModel"
    )

    compressor = TenantDreamingCompressor("tenant-1", "user-1")

    assert compressor.max_compression_input_chars == 24_000
    model_class.assert_called_once()


def test_compressor_rejects_missing_tenant_model(mocker):
    mocker.patch(
        "services.memory_dreaming_compressor.tenant_config_manager.get_model_config",
        return_value=None,
    )
    with pytest.raises(RuntimeError, match="No tenant LLM"):
        TenantDreamingCompressor("tenant-1", "user-1")


def test_ac019_compressor_binds_run_metadata_and_parses_grounded_json():
    observed = {}

    class Model:
        def generate(self, messages):
            metadata = get_agent_monitoring_context()
            observed["metadata"] = metadata.metadata()
            observed["messages"] = messages
            # Return span-based extraction format
            return SimpleNamespace(
                content=json.dumps([
                    {"unit_id": "short-term:7", "start": 0, "end": 31}
                ])
            )

    compressor = TenantDreamingCompressor.__new__(TenantDreamingCompressor)
    compressor.tenant_id = "tenant-1"
    compressor.user_id = "user-1"
    compressor.model = Model()
    compressor.max_compression_input_chars = 40_000

    output = compressor(
        DreamingCompressionRequest(
            raw_content="- Remember the stable constraint.",
            units=[
                DreamingMemoryUnit(
                    unit_id="short-term:7",
                    content="Remember the stable constraint.",
                    evidence_ids=["7"],
                )
            ],
            max_chars=10_000,
            attempt=1,
            run_id=42,
            agent_id="9",
        )
    )

    assert "Remember the stable constraint." in output.content
    assert output.evidence_ids == ["7"]
    assert observed["metadata"]["dreaming_run_id"] == 42
    assert observed["metadata"]["dreaming_agent_id"] == "9"
    assert observed["metadata"]["dreaming_attempt"] == 1
    assert observed["metadata"]["agent_id"] == 9
    assert "contiguous substring" in observed["messages"][1]["content"].lower()


def test_ac024_oversized_raw_uses_unit_preserving_map_reduce():
    calls = []

    class Model:
        def generate(self, messages):
            prompt = messages[1]["content"]
            calls.append(prompt)
            unit_ids = re.findall(r'"unit_id": "([^"]+)", "text":', prompt)
            if not unit_ids:
                unit_ids = ["one", "two"]
            spans = []
            for uid in unit_ids[:1]:
                spans.append({"unit_id": uid, "start": 0, "end": 100})
            return SimpleNamespace(content=json.dumps(spans))

    compressor = TenantDreamingCompressor.__new__(TenantDreamingCompressor)
    compressor.tenant_id = "tenant-1"
    compressor.user_id = "user-1"
    compressor.max_compression_input_chars = 800
    compressor.model = Model()

    output = compressor(
        DreamingCompressionRequest(
            raw_content="A" * 6_000 + "\n" + "B" * 6_000,
            units=[
                DreamingMemoryUnit(
                    unit_id="one",
                    content="A" * 6_000,
                    evidence_ids=["1"],
                ),
                DreamingMemoryUnit(
                    unit_id="two",
                    content="B" * 6_000,
                    evidence_ids=["2"],
                ),
            ],
            max_chars=1_000,
            attempt=1,
            run_id=43,
            agent_id="9",
        )
    )

    assert len(calls) >= 2
    assert output.evidence_ids == ["1", "2"]


def test_stage1_batches_large_unit_sets_even_when_raw_fits_context():
    calls = []

    class Model:
        def generate(self, messages):
            unit_ids = re.findall(
                r'"unit_id": "([^"]+)", "text":', messages[1]["content"]
            )
            calls.append(unit_ids)
            return SimpleNamespace(content=json.dumps([
                {"unit_id": unit_id, "start": 0, "end": 6}
                for unit_id in unit_ids
            ]))

    compressor = TenantDreamingCompressor.__new__(TenantDreamingCompressor)
    compressor.tenant_id = "t"
    compressor.user_id = "u"
    compressor.max_compression_input_chars = 40_000
    compressor.model = Model()
    units = [
        DreamingMemoryUnit(
            unit_id=f"u{i}",
            content=f"fact{i:02d}",
            evidence_ids=[str(i)],
        )
        for i in range(13)
    ]

    output = compressor(DreamingCompressionRequest(
        raw_content="\n".join(f"- {unit.content}" for unit in units),
        units=units,
        max_chars=10_000,
        attempt=1,
    ))

    assert [len(batch) for batch in calls] == [12, 1]
    assert output.evidence_ids == sorted(str(i) for i in range(13))


def test_ac033_information_extraction_framing():
    observed = {}

    class Model:
        def generate(self, messages):
            observed["messages"] = messages
            return SimpleNamespace(content=json.dumps([{"unit_id": "u1", "start": 0, "end": 5}]))

    compressor = TenantDreamingCompressor.__new__(TenantDreamingCompressor)
    compressor.tenant_id = "t"
    compressor.user_id = "u"
    compressor.model = Model()
    compressor.max_compression_input_chars = 40_000

    compressor(DreamingCompressionRequest(
        raw_content="Hello world",
        units=[DreamingMemoryUnit(unit_id="u1", content="Hello world", evidence_ids=["1"])],
        max_chars=10_000,
        attempt=1,
    ))

    system_msg = observed["messages"][0]["content"]
    assert "information extraction" in system_msg.lower()
    assert "exist exactly in the selected source unit" in system_msg.lower()


def test_ac034_extraction_prompt_has_exactly_five_rules():
    prompt = TenantDreamingCompressor._compression_prompt(
        "fact one",
        [{"unit_id": "u1", "text": "fact one", "evidence_ids": ["1"]}],
    )
    assert len(re.findall(r"(?m)^[1-5]\. ", prompt)) == 5
    assert "contiguous substring of its selected unit" in prompt
    assert "smallest complete atomic fact" in prompt
    assert "including labels, identifiers, and numbers" in prompt
    assert '"unit_id": "u1", "text": "fact one"' in prompt
    assert "exclude JSON syntax and unit_id" in prompt


def test_ac036_stage0_preassigned_evidence_ids():
    units = [
        DreamingMemoryUnit(unit_id="u1", content="fact A", evidence_ids=["1", "2"]),
        DreamingMemoryUnit(unit_id="u2", content="fact B", evidence_ids=["3"]),
    ]
    prepared = TenantDreamingCompressor._prepare_units_with_ids(units)
    assert len(prepared) == 2
    assert prepared[0]["unit_id"] == "u1"
    assert prepared[0]["evidence_ids"] == ["1", "2"]
    assert prepared[1]["unit_id"] == "u2"
    assert prepared[1]["evidence_ids"] == ["3"]


def test_ac037_stage1_exact_substring_extraction():
    observed = {}

    class Model:
        def generate(self, messages):
            observed["messages"] = messages
            return SimpleNamespace(content=json.dumps([
                {"unit_id": "u1", "start": 0, "end": 8},
                {"unit_id": "u1", "start": 9, "end": 17},
            ]))

    compressor = TenantDreamingCompressor.__new__(TenantDreamingCompressor)
    compressor.tenant_id = "t"
    compressor.user_id = "u"
    compressor.model = Model()
    compressor.max_compression_input_chars = 40_000

    raw = "- fact one\n- fact two"
    output = compressor(DreamingCompressionRequest(
        raw_content=raw,
        units=[DreamingMemoryUnit(unit_id="u1", content="fact one\nfact two", evidence_ids=["1"])],
        max_chars=10_000,
        attempt=1,
    ))

    assert "fact one" in output.content
    assert "fact two" in output.content


def test_ac038_stage1_exact_substring_validation():
    raw = "Hello world"
    units = [{"unit_id": "u1", "text": "Hello world", "evidence_ids": ["1"]}]

    spans = [{"start": 0, "end": 100, "unit_ids": ["u1"]}]
    facts, feedback = TenantDreamingCompressor._validate_spans(spans, raw, units)
    assert len(feedback) > 0
    assert "out_of_bounds" in feedback[0]

    spans = [{"start": "a", "end": 5, "unit_ids": ["u1"]}]
    facts, feedback = TenantDreamingCompressor._validate_spans(spans, raw, units)
    assert "non_integer" in feedback[0]

    spans = [{"start": 0, "end": 5, "unit_ids": ["u1"]}]
    facts, feedback = TenantDreamingCompressor._validate_spans(spans, raw, units)
    assert len(feedback) == 0
    assert len(facts) == 1
    assert facts[0]["text"] == "Hello"


def test_stage1_normalizes_json_object_relative_offsets():
    unit_id = "pattern-1"
    text = "The authoritative fact."
    prefix = json.dumps(
        {"unit_id": unit_id, "text": ""},
        ensure_ascii=False,
    )[:-2]
    spans = [{
        "unit_id": unit_id,
        "start": len(prefix),
        "end": len(prefix) + len(text),
    }]

    facts, feedback = TenantDreamingCompressor._validate_spans(
        spans,
        text,
        [{"unit_id": unit_id, "text": text, "evidence_ids": ["1"]}],
    )

    assert feedback == []
    assert facts[0]["text"] == text


@pytest.mark.parametrize(
    ("span", "expected"),
    [
        ({"unit_ids": ["u1"]}, "missing_offsets"),
        ({"start": 5, "end": 5, "unit_ids": ["u1"]}, "invalid_range"),
        ({"start": 0, "end": 1}, "invalid_unit"),
        ({"unit_id": "unknown", "start": 0, "end": 1}, "invalid_unit"),
        ({"unit_id": "u1", "start": 6, "end": 11}, "out_of_bounds"),
    ],
)
def test_ac038_span_validation_failure_modes(span, expected):
    _, feedback = TenantDreamingCompressor._validate_spans(
        [span],
        "Hello world",
        [{"unit_id": "u1", "text": "Hello", "evidence_ids": ["1"]}],
    )
    assert expected in feedback[0]


def test_validation_critical_literals_are_deterministically_grounded():
    facts = TenantDreamingCompressor._required_literal_facts(
        [{
            "unit_id": "u1",
            "text": "pattern 10 uses 250ms at https://example.test/api",
            "evidence_ids": ["7"],
        }],
        3,
    )

    assert {fact["text"] for fact in facts} >= {
        "pattern 10",
        "10",
        "250ms",
        "https://example.test/api",
    }
    assert all(fact["unit_ids"] == ["u1"] for fact in facts)
    assert all(fact["evidence_ids"] == ["7"] for fact in facts)
    assert facts[0]["fact_id"] == "f003"


def test_ac039_stage2a_deterministic_dedup():
    facts = [
        {"fact_id": "f001", "text": "User uses Python for ML", "unit_ids": ["u1"], "evidence_ids": ["1"]},
        {"fact_id": "f002", "text": "User uses Python for ML", "unit_ids": ["u2"], "evidence_ids": ["2"]},
        {"fact_id": "f003", "text": "User uses Python", "unit_ids": ["u3"], "evidence_ids": ["3"]},
        {"fact_id": "f004", "text": "User uses Go", "unit_ids": ["u4"], "evidence_ids": ["4"]},
    ]
    unique = TenantDreamingCompressor._deterministic_dedup(facts)
    texts = [f["text"] for f in unique]
    assert "User uses Python for ML" in texts
    assert "User uses Python" in texts
    assert "User uses Go" in texts
    assert len(unique) == 3
    assert unique[0]["unit_ids"] == ["u1", "u2"]
    assert unique[0]["evidence_ids"] == ["1", "2"]


def test_ac040_stage2b_conditional_llm_call():
    calls = []

    class Model:
        def generate(self, messages):
            calls.append(messages)
            return SimpleNamespace(content=json.dumps({"content": "shortened", "evidence_ids": ["1"]}))

    compressor = TenantDreamingCompressor.__new__(TenantDreamingCompressor)
    compressor.tenant_id = "t"
    compressor.user_id = "u"
    compressor.model = Model()

    facts = [
        {"fact_id": "f001", "text": "short fact", "unit_ids": ["u1"], "evidence_ids": ["1"]},
    ]

    output = compressor._format_facts(facts, max_chars=10_000, evidence_ids=["1"])
    assert len(calls) == 0
    assert "short fact" in output.content
    assert output.metadata["all_fact_ids"] == ["f001"]


def test_ac041_retry_always_two_stage():
    calls = []

    class Model:
        def generate(self, messages):
            calls.append(messages)
            return SimpleNamespace(content=json.dumps([
                {"start": 0, "end": 10, "unit_ids": ["u1"]},
            ]))

    compressor = TenantDreamingCompressor.__new__(TenantDreamingCompressor)
    compressor.tenant_id = "t"
    compressor.user_id = "u"
    compressor.model = Model()
    compressor.max_compression_input_chars = 40_000

    compressor(DreamingCompressionRequest(
        raw_content="fact one!!",
        units=[DreamingMemoryUnit(unit_id="u1", content="fact one!!", evidence_ids=["1"])],
        max_chars=10_000,
        attempt=1,
    ))

    compressor(DreamingCompressionRequest(
        raw_content="fact one!!",
        units=[DreamingMemoryUnit(unit_id="u1", content="fact one!!", evidence_ids=["1"])],
        max_chars=10_000,
        attempt=2,
        validation_feedback=["missing_evidence:2"],
    ))

    for call in calls:
        assert "information extraction" in call[0]["content"].lower()


def test_ac042_fact_coverage_computation():
    facts = [
        {"fact_id": "f001", "text": "User uses Python"},
        {"fact_id": "f002", "text": "User uses Go"},
        {"fact_id": "f003", "text": "User uses Rust"},
    ]
    output_content = "- User uses Python\n- User uses Rust"
    covered = TenantDreamingCompressor._count_covered_facts(output_content, facts)
    assert "f001" in covered
    assert "f003" in covered
    assert "f002" not in covered


def test_ac042_source_coverage_rejects_missed_units():
    facts = [
        {
            "fact_id": "f001",
            "text": "fact one",
            "unit_ids": ["u1"],
            "evidence_ids": ["1"],
        }
    ]
    units = [
        {"unit_id": "u1", "text": "fact one", "evidence_ids": ["1"]},
        {"unit_id": "u2", "text": "fact two", "evidence_ids": ["2"]},
    ]
    with pytest.raises(ValueError, match="Source unit coverage too low: 1/2=0.50"):
        TenantDreamingCompressor._require_source_coverage(facts, units)


def test_ac049_lossless_formatter_rejects_missing_fact_ids():
    class Model:
        def generate(self, _messages):
            return SimpleNamespace(
                content=json.dumps(
                    {"facts": [{"fact_id": "f001", "text": "short fact"}]}
                )
            )

    compressor = TenantDreamingCompressor.__new__(TenantDreamingCompressor)
    compressor.model = Model()
    facts = [
        {
            "fact_id": "f001",
            "text": "first fact",
            "unit_ids": ["u1"],
            "evidence_ids": ["1"],
        },
        {
            "fact_id": "f002",
            "text": "second fact",
            "unit_ids": ["u2"],
            "evidence_ids": ["2"],
        },
    ]
    with pytest.raises(ValueError, match="fact_ids do not match"):
        compressor._lossless_formatting(facts, 10, ["1", "2"])


def test_ac049_lossless_formatter_preserves_all_fact_ids():
    class Model:
        def generate(self, _messages):
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "facts": [
                            {"fact_id": "f001", "text": "first"},
                            {"fact_id": "f002", "text": "second"},
                        ]
                    }
                )
            )

    compressor = TenantDreamingCompressor.__new__(TenantDreamingCompressor)
    compressor.model = Model()
    facts = [
        {
            "fact_id": "f001",
            "text": "first verbose fact",
            "unit_ids": ["u1"],
            "evidence_ids": ["1"],
        },
        {
            "fact_id": "f002",
            "text": "second verbose fact",
            "unit_ids": ["u2"],
            "evidence_ids": ["2"],
        },
    ]

    output = compressor._lossless_formatting(facts, 20, ["1", "2"])

    assert output.content == "- first\n- second"
    assert output.metadata["covered_fact_ids"] == ["f001", "f002"]


def test_ac048_ac019_regression_fix():
    """AC-048: Verify span-based extraction preserves all numbered patterns with coverage >= 0.95."""
    raw_content = "\n".join([
        f"- pattern {i}: This is fact number {i} with important data"
        for i in range(1, 36)
    ])
    units = [
        DreamingMemoryUnit(
            unit_id=f"u{i:02d}",
            content=f"pattern {i}: This is fact number {i} with important data",
            evidence_ids=[str(i)],
        )
        for i in range(1, 36)
    ]

    class Model:
        def generate(self, messages):
            spans = []
            unit_ids = re.findall(
                r'"unit_id": "([^"]+)", "text":', messages[1]["content"]
            )
            for unit_id in unit_ids:
                i = int(unit_id.removeprefix("u"))
                unit_text = f"pattern {i}: This is fact number {i} with important data"
                spans.append({
                    "unit_id": unit_id,
                    "start": 0,
                    "end": len(unit_text),
                })
            return SimpleNamespace(content=json.dumps(spans))

    compressor = TenantDreamingCompressor.__new__(TenantDreamingCompressor)
    compressor.tenant_id = "t"
    compressor.user_id = "u"
    compressor.model = Model()
    compressor.max_compression_input_chars = 40_000

    output = compressor(DreamingCompressionRequest(
        raw_content=raw_content,
        units=units,
        max_chars=10_000,
        attempt=1,
    ))

    for i in range(1, 36):
        assert f"pattern {i}" in output.content
    assert len(output.metadata["covered_fact_ids"]) / len(output.metadata["all_fact_ids"]) >= 0.95


def test_ac049_fact_preservation_guarantee():
    """AC-049: Verify no facts are lost during compression pipeline and critical literals preserved."""
    raw_content = "\n".join([
        f"- fact {i}: Critical data point {i} with value {i * 100}"
        for i in range(1, 11)
    ])
    units = [
        DreamingMemoryUnit(
            unit_id=f"u{i:02d}",
            content=f"fact {i}: Critical data point {i} with value {i * 100}",
            evidence_ids=[str(i)],
        )
        for i in range(1, 11)
    ]

    class Model:
        def generate(self, messages):
            spans = []
            for i in range(1, 11):
                unit_text = f"fact {i}: Critical data point {i} with value {i * 100}"
                spans.append({
                    "unit_id": f"u{i:02d}",
                    "start": 0,
                    "end": len(unit_text),
                })
            return SimpleNamespace(content=json.dumps(spans))

    compressor = TenantDreamingCompressor.__new__(TenantDreamingCompressor)
    compressor.tenant_id = "t"
    compressor.user_id = "u"
    compressor.model = Model()
    compressor.max_compression_input_chars = 40_000

    output = compressor(DreamingCompressionRequest(
        raw_content=raw_content,
        units=units,
        max_chars=10_000,
        attempt=1,
    ))

    assert output.metadata["covered_fact_ids"] == output.metadata["all_fact_ids"]
    assert len(output.metadata["covered_fact_ids"]) >= 10
    for i in range(1, 11):
        assert f"fact {i}" in output.content
        assert str(i * 100) in output.content

    from nexent.memory.dreaming.version_builder import _critical_literals, _validate_compression
    literals = _critical_literals(raw_content)
    required_evidence = {str(i) for i in range(1, 11)}
    feedback = _validate_compression(
        output,
        required_evidence=required_evidence,
        required_literals=literals,
        max_chars=10_000,
    )
    assert not any("missing_critical_literals" in f for f in feedback)
