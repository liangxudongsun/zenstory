import pytest
from pydantic import ValidationError

from api.files import FileCreate, FileUpdate
from api.agent_api import FileCreate as AgentFileCreate, FileUpdate as AgentFileUpdate


@pytest.mark.parametrize("model", [FileCreate, FileUpdate, AgentFileCreate, AgentFileUpdate])
@pytest.mark.parametrize("title", ["设定" * 1600, "😀" * 256], ids=["body-sized-cjk", "over-limit-emoji"])
def test_requests_reject_body_sized_titles(model, title):
    with pytest.raises(ValidationError):
        model(title=title)


@pytest.mark.parametrize("model", [FileCreate, FileUpdate, AgentFileCreate, AgentFileUpdate])
def test_title_boundary_keeps_long_body(model):
    body = "正文" * 4000
    value = model(title="😀" * 255, content=body)
    assert value.content == body
    assert value.title == "😀" * 255


def test_agent_rejects_invalid_title_before_any_database_use():
    from agent.tools.file_ops.crud import FileCRUD
    class NoDatabase:
        def __getattr__(self, name):
            pytest.fail(f"Invalid title reached database: {name}")
    crud = FileCRUD(NoDatabase(), "user")
    with pytest.raises(ValueError, match="255"):
        crud.create_file("project", "设定" * 1600, content="")
    with pytest.raises(ValueError, match="255"):
        crud.update_file("file", title="😀" * 256)
