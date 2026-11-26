# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Reuse the owned file-assistant fixture for persisted retry history."""

import importlib.util
import sys

mode, filename, helper_path = sys.argv[1:4]
spec = importlib.util.spec_from_file_location("owned_file_fixture", helper_path)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
sys.argv = [sys.argv[0], mode, filename, *sys.argv[4:]]
helper.main()
