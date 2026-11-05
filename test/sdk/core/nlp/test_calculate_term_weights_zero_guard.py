"""Guards calculate_term_weights against a zero total_weight (#3813)."""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[4]  # nexent repo root
TOKENIZER = ROOT / 'sdk' / 'nexent' / 'core' / 'nlp' / 'tokenizer.py'


def load_tokenizer():
    # Minimal package stubs so relative-free absolute module loads
    for name in (
        'nexent',
        'nexent.core',
        'nexent.core.nlp',
    ):
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.__path__ = []
            sys.modules[name] = mod

    spec = importlib.util.spec_from_file_location('nexent.core.nlp.tokenizer', TOKENIZER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules['nexent.core.nlp.tokenizer'] = mod
    spec.loader.exec_module(mod)
    return mod


class CalculateTermWeightsZeroGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tokenizer = load_tokenizer()

    def test_all_stop_words_returns_empty_without_division_error(self):
        with patch.object(self.tokenizer, 'analyse') as analyse, patch.object(
            self.tokenizer, 'pseg'
        ) as pseg:
            analyse.default_tfidf.stop_words = {'的', '是', '在'}
            pseg.cut.return_value = [('的', 'u'), ('是', 'v'), ('在', 'p')]
            self.assertEqual(self.tokenizer.calculate_term_weights('的 是 在'), {})

    def test_empty_tokens_returns_empty(self):
        with patch.object(self.tokenizer, 'analyse') as analyse, patch.object(
            self.tokenizer, 'pseg'
        ) as pseg:
            analyse.default_tfidf.stop_words = set()
            pseg.cut.return_value = []
            self.assertEqual(self.tokenizer.calculate_term_weights(''), {})

    def test_nonzero_weight_still_normalizes(self):
        with patch.object(self.tokenizer, 'analyse') as analyse, patch.object(
            self.tokenizer, 'pseg'
        ) as pseg, patch.dict(self.tokenizer.POS_WEIGHTS, {'n': 1.0}, clear=False):
            analyse.default_tfidf.stop_words = set()
            pseg.cut.return_value = [('智能', 'n'), ('问答', 'n')]
            result = self.tokenizer.calculate_term_weights('智能问答')
            self.assertTrue(result)
            self.assertTrue(all(0 < w <= 1 for w in result.values()))


if __name__ == '__main__':
    unittest.main()
