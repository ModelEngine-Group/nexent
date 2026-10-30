# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Map Jiuwen native and controlled-text proposals to the common delegation policy."""

import json

from nexent.core.agents.cores.jiuwen.protocol import EXECUTION_TOOL, JiuwenProtocolError
from nexent.core.agents.orchestration.delegation import DelegationError
from nexent.core.agents.orchestration.delegation import DelegationPolicy as SharedDelegationPolicy
from nexent.core.agents.output.python_actions import is_delegation_action


class DelegationPolicy(SharedDelegationPolicy):
    """Translate protocol envelopes and errors without redefining business policy."""

    def constrain(self, view):
        if not self.pending:
            return view
        definitions = [tool for tool in view.tool_definitions if tool.name in self.names]
        if not definitions:
            raise JiuwenProtocolError("JIUWEN_DELEGATION_UNAVAILABLE")
        return view.model_copy(update={"tool_definitions": definitions})

    def validate_calls(self, calls):
        if not self.pending:
            return
        names = []
        for call in calls:
            if call.name == EXECUTION_TOOL:
                try:
                    code = json.loads(call.arguments)["code"]
                except (ValueError, KeyError, TypeError):
                    code = None
                names.append(next(iter(self.names), "") if is_delegation_action(code, self.names) else "")
            else:
                names.append(call.name)
        try:
            self.validate_targets(names)
        except DelegationError as error:
            raise JiuwenProtocolError("JIUWEN_DELEGATION_REQUIRED") from error
