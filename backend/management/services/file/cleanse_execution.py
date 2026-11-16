# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Scoped run/KB dispatch without importing the retired task service."""

from contracts.agentos_knowledge import FileCleanseLookup, FileCleanseRequest
from contracts.knowledge_cleanse import KnowledgeCleanseLookup, KnowledgeCleanseRequest
from management.services.file.cleanse_authorization import KnowledgeCleanseAuthorization
from management.services.file.cleanse_executor import CleanseExecutor
from management.services.file.cleanse_jobs import CleanseJobs
from management.services.file.cleanse_lease import CleanseLeaseGuard
from management.services.file.cleanse_worker import (
    HANDLER,
    CleanseHandler,
    HandlerRegistry,
    consume_once,
)
from management.services.file.process_cleanse_executor import ProcessCleanseExecutor
from management.services.file.run_cleanse_authorization import RunCleanseAuthorization
from nexent.storage.errors import InvalidInput, ScopeDenied

from infrastructure.file_processing.objects import bind_cleanse_objects
from infrastructure.file_processing.parser import DocumentParserRuntime
from infrastructure.knowledge_cleanse import knowledge_cleanse_ports


def _authorization(resources, user_id, reference):
    if isinstance(reference, (FileCleanseRequest, FileCleanseLookup)):
        return RunCleanseAuthorization(resources, user_id=user_id)
    if isinstance(reference, (KnowledgeCleanseRequest, KnowledgeCleanseLookup)):
        return KnowledgeCleanseAuthorization(resources, user_id=user_id)
    raise ScopeDenied()


def execute_cleanse(row, request, *, tick, context):
    def factory(*, context):
        from contracts.constants import environment

        run = (
            FileCleanseLookup(run_id=row["run_id"], job_id=row["job_id"])
            if isinstance(request, FileCleanseRequest)
            else None
        )
        runtime = DocumentParserRuntime(
            environment.DP_PARSE_THREADS_PER_PROCESS,
            [
                alias.strip()
                for alias in environment.DP_PRELOAD_MODELS.split(",")
                if alias.strip()
            ],
            {
                "unstructured_default": environment.UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH,
                "table_transformer": environment.TABLE_TRANSFORMER_MODEL_PATH,
            },
        )
        return CleanseExecutor(
            runtime=runtime,
            objects=bind_cleanse_objects(
                row["tenant_id"], row["user_id"], request.source, context=context, run=run
            ),
            parser_version=row["parser_version"],
        )

    def renew(_row, *, context):
        tick(context=context)

    return ProcessCleanseExecutor(factory, tick=renew)(row, request, context=context)


def consume_cleanse_once(
    queue,
    *,
    owner_id,
    parser_version,
    execute=execute_cleanse,
    lease_seconds=300,
    max_wait=1,
    context,
):
    """The process root owns queue and isolated execution; this call owns record handles."""
    scope = queue.scope
    if scope.system or scope.service_role != "management" or not scope.tenant_id:
        raise ScopeDenied()
    if not callable(execute):
        raise InvalidInput()
    context.remaining()
    with knowledge_cleanse_ports(scope.tenant_id, owner_id, context=context) as (
        records,
        resources,
    ):
        def authorize_request(reference, *, context):
            return _authorization(resources, owner_id, reference).authorize(reference, context=context)

        jobs = CleanseJobs(
            records, authorize=authorize_request, parser_version=parser_version
        )

        def authorize(row, request, *, context):
            return _authorization(resources, row["user_id"], request).authorize_execution(row, request, context=context)

        guard = CleanseLeaseGuard(
            jobs, authorize_execution=authorize, lease_seconds=lease_seconds
        )

        def process(row, request, *, context):
            guard(row, context=context)

            def tick(*, context):
                guard(row, context=context)

            return execute(row, request, tick=tick, context=context)

        handler = CleanseHandler(
            jobs,
            owner_id=owner_id,
            lease_seconds=lease_seconds,
            authorize_execution=authorize,
            execute=process,
        )
        return consume_once(
            queue,
            HandlerRegistry({HANDLER: handler}),
            max_wait=max_wait,
            context=context,
        )
