# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Kubernetes generation checks around the existing shared Jupyter protocol."""

from nexent.core.agents.sandbox.execution import _JupyterKernelLease


class KubernetesKernelLease(_JupyterKernelLease):
    def __init__(self, *args, run_lifecycle=None, **kwargs):
        self._runtime_lifecycle = run_lifecycle
        self._execution_pending = False
        self._lifetime_holder = run_lifecycle.begin('kernel') if run_lifecycle is not None else None
        try:
            super().__init__(*args, **kwargs)
        except BaseException:
            # Kernel allocation has not returned to any business executor.
            if self._lifetime_holder is not None:
                run_lifecycle.finish(self._lifetime_holder)
            raise
    def _create_kernel(self):
        self._container_executor.assert_generation()
        return super()._create_kernel()

    def run_code_raise_errors(self, code):
        self._container_executor.assert_generation()
        result = super().run_code_raise_errors(code)
        self._container_executor.assert_generation()
        return result

    def cleanup(self):
        if self._closed:
            return
        stopped = not self._execution_pending
        try:
            self._container_executor.assert_generation()
            response = self._requests.delete(f'{self.base_url}/api/kernels/{self.kernel_id}', timeout=5)
            if response.status_code == 204:
                stopped = True
            elif response.status_code != 404:
                self._logger.warning('Kubernetes kernel cleanup was not confirmed kernel_id=%s status=%s',
                                     self.kernel_id, response.status_code)
        finally:
            self._closed = True
            if self._lifetime_holder is not None:
                if stopped:
                    self._runtime_lifecycle.finish(self._lifetime_holder)
                else:
                    self._runtime_lifecycle.unknown(self._lifetime_holder)
