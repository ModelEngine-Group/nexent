import pytest
from pydantic import ValidationError

from backend.consts import model as model_consts


def test_model_connect_status_enum_defaults_and_get_value():
    assert model_consts.ModelConnectStatusEnum.get_default() == "not_detected"
    assert model_consts.ModelConnectStatusEnum.get_value("") == "not_detected"
    assert model_consts.ModelConnectStatusEnum.get_value(None) == "not_detected"
    assert model_consts.ModelConnectStatusEnum.get_value("available") == "available"


def test_model_request_and_validation():
    # Basic construction
    mr = model_consts.ModelRequest(model_name="mymodel", model_type="llm")
    assert mr.model_name == "mymodel"
    assert mr.model_type == "llm"

    # Chunk create request requires non-empty content
    with pytest.raises(ValidationError):
        model_consts.ChunkCreateRequest(content="")

    # Valid chunk create
    req = model_consts.ChunkCreateRequest(content="a", title="t", filename="f")
    assert req.content == "a"
    assert req.title == "t"
    assert req.filename == "f"


