import pytest

from backend.services import datamate_service


class FakeClient:
    def __init__(self, base_url=None):
        self.base_url = base_url

    def list_knowledge_bases(self):
        return [{"id": "kb1", "name": "KB1"}]

    def get_knowledge_base_files(self, knowledge_base_id):
        return [{"name": "file1", "size": 123, "knowledge_base_id": knowledge_base_id}]

    def sync_all_knowledge_bases(self):
        return {"success": True, "knowledge_bases": [{"id": "kb1"}], "total_count": 1}




@pytest.mark.asyncio
async def test_fetch_datamate_knowledge_base_files_success(monkeypatch):
    monkeypatch.setattr(datamate_service, "_get_datamate_client", lambda: FakeClient())
    files = await datamate_service.fetch_datamate_knowledge_base_files("kb1")
    assert isinstance(files, list)
    assert files[0]["knowledge_base_id"] == "kb1"


@pytest.mark.asyncio
async def test_fetch_datamate_knowledge_base_files_failure(monkeypatch):
    class BadClient(FakeClient):
        def get_knowledge_base_files(self, knowledge_base_id):
            raise Exception("boom")

    monkeypatch.setattr(datamate_service, "_get_datamate_client", lambda: BadClient())
    with pytest.raises(RuntimeError) as excinfo:
        await datamate_service.fetch_datamate_knowledge_base_files("kb1")
    assert "Failed to fetch files for knowledge base kb1" in str(excinfo.value)




