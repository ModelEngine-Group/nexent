from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import orjson

MODULE_PATH = Path(__file__).resolve().parents[3] / "sdk/nexent/data_process/json_chunk_processor.py"
SPEC = spec_from_file_location("json_chunk_processor_under_test", MODULE_PATH)
MODULE = module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)
JSONChunkProcessor = MODULE.JSONChunkProcessor


class TestJSONChunkProcessor:
    def test_split_with_dict_json(self):
        processor = JSONChunkProcessor(max_characters=200)
        data = b'{"name":"alice","age":18}'

        chunks = processor.split(data)

        assert chunks == ['name: "alice"', "age: 18"]

    def test_split_with_list_json(self):
        processor = JSONChunkProcessor(max_characters=200)
        data = b'[{"a":1},{"b":2}]'

        chunks = processor.split(data)

        assert chunks == ['{"a":1}', '{"b":2}']

    def test_split_with_scalar_json(self):
        processor = JSONChunkProcessor(max_characters=200)
        data = b'"hello"'

        chunks = processor.split(data)

        assert chunks == ['"hello"']

    def test_split_fallback_for_json_decode_error(self):
        processor = JSONChunkProcessor(max_characters=4)

        chunks = processor.split(b"abcdefg")

        assert chunks == ["abcd", "efg"]

    def test_split_fallback_for_type_error(self, monkeypatch):
        processor = JSONChunkProcessor(max_characters=10)

        def raise_type_error(_):
            raise TypeError("bad input")

        monkeypatch.setattr(orjson, "loads", raise_type_error)
        chunks = processor.split(123)

        assert chunks == ["123"]

    def test_split_returns_empty_when_type_error_and_to_text_fails(self, monkeypatch):
        processor = JSONChunkProcessor(max_characters=10)

        def raise_type_error(_):
            raise TypeError("bad input")

        monkeypatch.setattr(orjson, "loads", raise_type_error)
        monkeypatch.setattr(
            JSONChunkProcessor,
            "_to_text",
            staticmethod(lambda _: (_ for _ in ()).throw(RuntimeError("decode failed"))),
        )

        chunks = processor.split(object())

        assert chunks == []

    def test_split_fallback_for_unexpected_error(self, monkeypatch):
        processor = JSONChunkProcessor(max_characters=10)

        def raise_unexpected(_):
            raise RuntimeError("unexpected")

        monkeypatch.setattr(orjson, "loads", raise_unexpected)
        chunks = processor.split(b"plain")

        assert chunks == ["plain"]

    def test_split_plain_prefers_safe_break_and_avoids_trailing_escape(self):
        processor = JSONChunkProcessor(max_characters=6)

        chunks = processor._split_plain("abcde\\XYZ")

        assert chunks == ["abcde", "\\XYZ"]

    def test_split_plain_forces_hard_cut_when_no_safe_break(self):
        processor = JSONChunkProcessor(max_characters=3)

        chunks = processor._split_plain("abcdef")

        assert chunks == ["abc", "def"]

    def test_split_plain_extreme_backslash_boundary(self):
        processor = JSONChunkProcessor(max_characters=1)

        chunks = processor._split_plain("\\abc")

        assert chunks == ["\\", "a", "b", "c"]

    def test_split_json_text_uses_top_level_cut(self):
        processor = JSONChunkProcessor(max_characters=8)

        chunks = processor._split_json_text('{"a":1,"b":2}')

        assert chunks == ['{"a":1,', '"b":2}']

    def test_split_json_text_falls_back_to_plain_when_no_safe_cut(self):
        processor = JSONChunkProcessor(max_characters=4)

        chunks = processor._split_json_text("abcdefgh")

        assert chunks == ["abcd", "efgh"]

    def test_find_last_top_kv_and_string_escape_handling(self):
        processor = JSONChunkProcessor(max_characters=20)
        text = '{"a":"x\\\"y","b":2}'

        cut = processor._find_last_top_kv(text, max_len=14)

        assert cut == text.index(",") + 1

    def test_find_last_top_kv_returns_none_without_comma(self):
        processor = JSONChunkProcessor(max_characters=20)

        cut = processor._find_last_top_kv('{"a":1}', max_len=20)

        assert cut is None

    def test_process_structural_char_branches(self):
        processor = JSONChunkProcessor(max_characters=20)

        depth, cut = processor._process_structural_char("{}", 0, "{", 0, None)
        assert (depth, cut) == (1, None)

        depth, cut = processor._process_structural_char("{}", 1, "}", 1, None)
        assert (depth, cut) == (0, None)

        depth, cut = processor._process_structural_char('{"a":1,', 6, ",", 1, None)
        assert (depth, cut) == (1, 7)

    def test_to_text_variants(self):
        assert JSONChunkProcessor._to_text(b"abc") == "abc"
        assert JSONChunkProcessor._to_text("abc") == "abc"
        assert JSONChunkProcessor._to_text(123) == "123"

    def test_ends_with_unescaped_backslash(self):
        assert JSONChunkProcessor._ends_with_unescaped_backslash("abc\\") is True
        assert JSONChunkProcessor._ends_with_unescaped_backslash("abc\\\\") is False
        assert JSONChunkProcessor._ends_with_unescaped_backslash("abc") is False
