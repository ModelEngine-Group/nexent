from backend.services.agent_share_token_service import (
    build_agent_share_token,
    parse_agent_share_token,
)


SECRET = "test-agent-share-secret"
PUBLIC_SHARE_ID = "f7e76518-4df2-4e10-9f49-48d785342f4f"


def test_share_token_round_trips_only_for_its_current_generation_and_nonce():
    token = build_agent_share_token(
        public_share_id=PUBLIC_SHARE_ID,
        generation=2,
        nonce="server-side-nonce",
        secret=SECRET,
    )

    payload = parse_agent_share_token(
        token,
        nonce="server-side-nonce",
        secret=SECRET,
    )

    assert payload is not None
    assert payload.public_share_id == PUBLIC_SHARE_ID
    assert payload.generation == 2


def test_share_token_rejects_tampering_wrong_secret_and_northbound_key():
    token = build_agent_share_token(
        public_share_id=PUBLIC_SHARE_ID,
        generation=1,
        nonce="server-side-nonce",
        secret=SECRET,
    )
    public_id, generation, signature = token.split(".")
    replacement = "x" if signature[-1] != "x" else "y"
    tampered_token = f"{public_id}.{generation}.{signature[:-1]}{replacement}"

    assert parse_agent_share_token(tampered_token, nonce="server-side-nonce", secret=SECRET) is None
    assert parse_agent_share_token(token, nonce="server-side-nonce", secret="another-secret") is None
    assert parse_agent_share_token("nexent-0123456789abcdef01234567", nonce="server-side-nonce", secret=SECRET) is None


def test_share_token_rejects_non_positive_generation():
    assert parse_agent_share_token(
        f"{PUBLIC_SHARE_ID}.0.signature",
        nonce="server-side-nonce",
        secret=SECRET,
    ) is None
