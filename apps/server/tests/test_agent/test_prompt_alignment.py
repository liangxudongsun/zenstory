"""Prompt/tool alignment regression tests.

These tests ensure that the system prompt does not instruct the model to call
tools that are not available in the Tool registry.
"""

import pytest

from agent.prompts.base import get_base_prompt


@pytest.mark.unit
def test_base_prompt_does_not_suggest_removed_tools():
    prompt = get_base_prompt(
        project_id="proj-1",
        folder_ids={
            "draft": "draft-folder",
            "outline": "outline-folder",
            "character": "character-folder",
            "lore": "lore-folder",
            "material": "material-folder",
        },
        config={"role_definition": "Test role", "capabilities": "Test capabilities",
                "directory_structure": "Draft folder: {draft}", "content_structure": "Test structure",
                "file_types": "draft", "writing_guidelines": "Test guidelines"},
    )

    # We allow a plain-language note that tools don't exist, but the prompt
    # must not present them as callables (e.g. backticks, examples, tool list).
    assert "`update_file`" not in prompt
    assert "`read_file`" not in prompt
    assert "\n- update_file" not in prompt
    assert "update_file(" not in prompt
    assert "read_file(" not in prompt



@pytest.mark.unit
def test_product_identity_does_not_depend_on_database_role_definition():
    """数据库里的角色定义没写身份时，系统提示照样带上 ZenStory 写作助手的身份说明。"""
    from agent.prompts.base import OUTPUT_PROTOCOL, PRODUCT_IDENTITY_PROTOCOL

    prompt = get_base_prompt(
        project_id="proj-1",
        folder_ids={"draft": "draft-folder"},
        config={"role_definition": "你是一位资深网文编辑", "capabilities": "",
                "directory_structure": "{draft}", "content_structure": "",
                "file_types": "draft", "writing_guidelines": ""},
    )

    role_at = prompt.index("你是一位资深网文编辑")
    identity_at = prompt.index(PRODUCT_IDENTITY_PROTOCOL)
    assert role_at < identity_at < prompt.index(OUTPUT_PROTOCOL)
