# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Simplify successful execution wrappers after original subtree metrics are computed."""


def simplify_code_nodes(nodes, *, check=lambda: None):
    children = {identity: [] for identity in nodes}
    protected = set()
    for identity, node in nodes.items():
        check()
        parent = node["parent_id"]
        if parent in children:
            children[parent].append(identity)
        if node["status"] not in {"completed", "success"}:
            # Keep diagnostic ancestors even if their own status was captured as successful.
            current = identity
            while current in nodes and current not in protected:
                protected.add(current)
                current = nodes[current]["parent_id"]

    removed = {
        identity
        for identity, node in nodes.items()
        if node["kind"] == "phase"
        and node["name"] == "code.execute"
        and children[identity]
        and identity not in protected
        and node["parent_id"] in nodes
        and nodes[node["parent_id"]]["kind"] == "tool"
        and nodes[node["parent_id"]]["name"] == "python_interpreter"
    }

    def retained_parent(parent):
        while parent in removed:
            parent = nodes[parent]["parent_id"]
        return parent

    effective_children = {identity: [] for identity in nodes}
    for identity, node in nodes.items():
        check()
        if identity not in removed:
            parent = retained_parent(node["parent_id"])
            if parent in effective_children:
                effective_children[parent].append(identity)

    for identity, node in nodes.items():
        check()
        if node["kind"] != "tool" or node["name"] != "python_interpreter":
            continue
        direct = effective_children[identity]
        if identity in protected or node["parent_id"] not in nodes or not direct:
            continue
        if all(
            nodes[child]["kind"] in {"agent", "model", "tool"}
            or (
                nodes[child]["kind"] == "phase"
                and nodes[child]["name"] == "code.execute"
            )
            for child in direct
        ):
            removed.add(identity)

    result = {
        identity: node for identity, node in nodes.items() if identity not in removed
    }
    for node in result.values():
        check()
        node["parent_id"] = retained_parent(node["parent_id"])
        node["direct_child_count"] = 0
    for node in result.values():
        if node["parent_id"] in result:
            result[node["parent_id"]]["direct_child_count"] += 1
    return result
