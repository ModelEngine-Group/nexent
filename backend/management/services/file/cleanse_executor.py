# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Process-local structural cleansing, composed with a scoped object capability."""

from management.services.file.cleanse import cleanse_object


class CleanseExecutor:
    def __init__(self, *, runtime, objects, parser_version):
        if not isinstance(parser_version, str) or not 0 < len(parser_version) <= 128:
            raise ValueError("Expected a pinned parser version")
        self.runtime = runtime
        self.objects = objects
        self.parser_version = parser_version

    def warmup(self, *, context):
        context.remaining()
        self.runtime.ensure_initialized()
        context.remaining()

    def __call__(self, row, request, *, context):
        context.remaining()
        if row["parser_version"] != self.parser_version:
            raise ValueError("Parser version does not match the admitted job")
        self.warmup(context=context)
        return cleanse_object(
            request.source,
            request.filename,
            self.parser_version,
            parser=self.runtime,
            objects=self.objects,
            context=context,
        )
