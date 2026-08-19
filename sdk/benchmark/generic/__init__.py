# -*- coding: utf-8 -*-
"""Generic benchmark framework powered by Langfuse Datasets.

Provides a reusable experiment runner that bridges Langfuse's Dataset/Experiment
API with NexentAgent via the shared agent_runner.py execution engine.

Public commands are provided by the root-level ``run_*.py`` modules.
Supporting implementation lives in the responsibility-based subpackages.
"""
