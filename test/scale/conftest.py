"""Prevent pytest from collecting scale test files.

These are integration tests that require a running Nexent instance
and should not be executed by the regular pytest/CI pipeline.
Run manually via: python test/scale/spec_test.py
"""
collect_ignore_glob = ["*"]
