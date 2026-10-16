# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Public legacy long-context model using the shared text preparation policy."""

from ..model_service.compatibility.long_text import LongTextPreparation
from ..utils.observer import MessageObserver
from .openai_llm import OpenAIModel


class OpenAILongContextModel(LongTextPreparation, OpenAIModel):
    """Keep the existing public constructor while separating text preparation."""

    def __init__(self, observer: MessageObserver, temperature=0.5, top_p=0.95,
                 max_context_tokens=128000, truncation_strategy="start", ssl_verify=True, *args, **kwargs):
        super().__init__(observer=observer, temperature=temperature, top_p=top_p, ssl_verify=ssl_verify, *args, **kwargs)
        self.initialize_long_text(max_context_tokens, truncation_strategy)
