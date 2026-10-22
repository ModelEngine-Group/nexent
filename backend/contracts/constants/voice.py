# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import os

# TODO: Analyze every variable if this is used
# Test voice file path (WAV format for volcengine STT)
TEST_VOICE_PATH = os.path.join(os.path.dirname(
    os.path.dirname(os.path.dirname(__file__))), 'assets', 'test.wav')
# Test PCM file path (raw PCM format for Ali STT)
TEST_PCM_PATH = os.path.join(os.path.dirname(
    os.path.dirname(os.path.dirname(__file__))), 'assets', 'test_voice.pcm')
