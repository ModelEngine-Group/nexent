# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Patch a collaborator at every explicit lookup site created by a module split."""

import importlib
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import _patch, patch


SPLIT_MODULES = (
    (
        "management.services.file.service", "management.services.file.access",
        "management.services.file.preview", "management.services.file.image_proxy",
        "management.services.file.upload", "management.services.model.media",
        "data_process.services.conversion",
    ),
    (
        "gateway.authentication.auth", "gateway.authentication.northbound_auth",
        "management.services.permission.identity.provider",
        "infrastructure.security.internal_tokens", "infrastructure.security.signatures",
    ),
    ("management.services.monitor.audit", "management.utils.request_context"),
    ("management.services.notification.service", "management.services.repository.review_notifications"),
    tuple("management.services.evaluation." + name for name in (
        "runs", "execution", "scoring", "case_generation", "analysis", "queries", "common")),
    tuple("management.services.repository.agent." + name for name in (
        "listing", "icons", "publishing", "installation", "common")),
    tuple("management.services.mcp." + name for name in (
        "service", "health", "provisioning", "registration", "tools", "common")),
    tuple("management.services.tool." + name for name in (
        "configuration", "discovery", "validation", "common")) + ("management.services.mcp.openapi",),
    (
        "management.services.knowledge_base.quota",
        "management.services.knowledge_base.quota_common",
        "management.services.knowledge_base.usage",
        "management.services.configuration.platform.capacity",
        "management.services.configuration.tenant.quotas",
        "management.services.configuration.user.quotas",
    ),
)


def _family(module):
    name = getattr(module, "__name__", "")
    filename = getattr(module, "__file__", None)
    for family in SPLIT_MODULES:
        if name in family:
            return family
        if isinstance(filename, str):
            for candidate in family:
                if Path(filename).as_posix().endswith(candidate.replace(".", "/") + ".py"):
                    return family
    return ()


def _lookups(module, name):
    """Include only loaded owners that actually bind the selected collaborator."""
    targets = [module]
    for candidate in _family(module):
        owner = sys.modules.get(candidate)
        if owner is not None and owner is not module and name in vars(owner):
            targets.append(owner)
    return targets


def patch_import_object(mocker, module, name, *args, **kwargs):
    owners = _lookups(module, name)
    replacement = mocker.patch.object(module, name, *args, **kwargs)
    for owner in owners[1:]:
        mocker.patch.object(owner, name, replacement)
    return replacement


def _resolve(target):
    for family in SPLIT_MODULES:
        for name in sorted(family, key=len, reverse=True):
            if target.startswith(name + "."):
                attribute = target[len(name) + 1:]
                if "." not in attribute:
                    return importlib.import_module(name), attribute
    return None


def patch_imports(mocker, target, *args, **kwargs):
    resolved = _resolve(target)
    if resolved:
        return patch_import_object(mocker, *resolved, *args, **kwargs)
    return mocker.patch(target, *args, **kwargs)


def set_import_attribute(monkeypatch, target, name, *args, **kwargs):
    if isinstance(target, str):
        resolved = _resolve(target)
        if resolved:
            module, attribute = resolved
            for owner in _lookups(module, attribute):
                monkeypatch.setattr(owner, attribute, name, **kwargs)
            return
        return monkeypatch.setattr(target, name, *args, **kwargs)
    for owner in _lookups(target, name):
        monkeypatch.setattr(owner, name, *args, **kwargs)


def bind_import_attribute(module, name, value):
    """Install collection-time or fresh-fixture doubles at the actual owners."""
    for owner in _lookups(module, name):
        setattr(owner, name, value)


class _LookupPatch(_patch):
    """Retain unittest's decorator injection and start/stop lifecycle."""

    def __enter__(self):
        owners = _lookups(self.getter(), self.attribute)
        replacement = super().__enter__()
        self.lookup_stack = ExitStack()
        try:
            for owner in owners[1:]:
                self.lookup_stack.enter_context(patch.object(owner, self.attribute, replacement))
        except BaseException:
            self.lookup_stack.close()
            super().__exit__(*sys.exc_info())
            raise
        return replacement

    def __exit__(self, *exc_info):
        self.lookup_stack.close()
        return super().__exit__(*exc_info)


def _with_lookups(patcher):
    relocated = object.__new__(_LookupPatch)
    relocated.__dict__.update(patcher.__dict__)
    return relocated


def patch_import_context(target, *args, **kwargs):
    return _with_lookups(patch(target, *args, **kwargs))


def patch_import_object_context(target, name, *args, **kwargs):
    return _with_lookups(patch.object(target, name, *args, **kwargs))
