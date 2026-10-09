"""Auto-discovered endpoints must use credentials from the same deployment."""
import ast
from contextlib import contextmanager
from pathlib import Path
import os
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit


SOURCE = Path(__file__).resolve().parents[3] / 'cases/API-AUTO-357B84F01BA6D321/test.py'


class EndpointPairingTests(unittest.TestCase):
    def exercise(self, environment):
        calls = []
        constants = SimpleNamespace(ES_HOST='original', ES_API_KEY='original')
        common = SimpleNamespace(ES_HOST='original', ES_API_KEY='original')

        class Elasticsearch:
            def __init__(self, host, *, api_key, request_timeout):
                calls.append((host, api_key))

            def ping(self):
                return True

        def inspect(container):
            if container == 'nexent-elasticsearch':
                return {'NetworkSettings': {'Ports': {'9200/tcp': [{'HostPort': '19200'}]}}}
            return {'Config': {'Env': ['ELASTICSEARCH_API_KEY=fixture-deployment-key']}}

        tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
        node = next(item for item in tree.body if isinstance(item, ast.FunctionDef)
                    and item.name == 'configured_product_elasticsearch')
        namespace = {'contextmanager': contextmanager, 'os': os, 'urlsplit': urlsplit,
                     'patch': patch, '_inspect_deployment': inspect}
        modules = {'elasticsearch': SimpleNamespace(Elasticsearch=Elasticsearch),
                   'consts': SimpleNamespace(const=constants),
                   'management.services.knowledge_base': SimpleNamespace(common=common)}
        with patch.dict(sys.modules, modules), patch.dict(os.environ, environment, clear=True):
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'), namespace)
            with namespace['configured_product_elasticsearch']():
                self.assertEqual((constants.ES_HOST, constants.ES_API_KEY), calls[-1])
                self.assertEqual((common.ES_HOST, common.ES_API_KEY), calls[-1])
            self.assertEqual(constants.ES_API_KEY, 'original')
            self.assertEqual(common.ES_API_KEY, 'original')
        return calls[-1]

    def test_discovered_endpoint_ignores_unrelated_host_key(self):
        self.assertEqual(self.exercise({'ELASTICSEARCH_API_KEY': 'fixture-host-key'}),
                         ('http://127.0.0.1:19200', 'fixture-deployment-key'))

    def test_explicit_endpoint_preserves_explicit_key(self):
        self.assertEqual(self.exercise({'NEXENT_TEST_ELASTICSEARCH_URL': 'http://fixture:9200',
                                       'ELASTICSEARCH_API_KEY': 'fixture-explicit-key'}),
                         ('http://fixture:9200', 'fixture-explicit-key'))

    def test_discovered_endpoint_without_host_key(self):
        self.assertEqual(self.exercise({}),
                         ('http://127.0.0.1:19200', 'fixture-deployment-key'))
