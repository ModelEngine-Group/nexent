"""Agent Card factories shared by the SDK server and Nacos registration."""

from __future__ import annotations

from typing import Any

from .auth import AUTH_PROFILES, security_contract


def card_dict(base_url: str, agent_key: str, name: str | None = None) -> dict[str, Any]:
    profile = AUTH_PROFILES[agent_key]
    schemes, requirements = security_contract(profile)
    endpoint = f"{base_url}/{agent_key}"
    card: dict[str, Any] = {
        "name": name or f"Nexent A2A Mock ({agent_key})",
        "description": "Deterministic A2A test agent for Nexent integration tests.",
        "version": "1.0.0",
        "protocolVersion": "1.0.0",
        "supportedInterfaces": [
            {"url": endpoint, "protocolBinding": "HTTP+JSON", "protocolVersion": "1.0.0"},
            {"url": f"{endpoint}/v1", "protocolBinding": "JSONRPC", "protocolVersion": "1.0.0"},
        ],
        "capabilities": {"streaming": True, "pushNotifications": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "skills": [
            {
                "id": "data_query",
                "name": "Data query",
                "description": "Returns deterministic campus alarm and pedestrian-flow data.",
                "tags": ["data", "query", "campus"],
                "examples": ["Query security alarms", "Query pedestrian flow"],
            }
        ],
    }
    if schemes:
        card["securitySchemes"] = schemes
        card["securityRequirements"] = requirements
    return card
