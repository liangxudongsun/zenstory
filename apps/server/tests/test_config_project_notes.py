"""项目备注来源分区的解析与合并（config/project_notes）。"""

import pytest

from config.project_notes import (
    CONFIRMED_HEADER,
    PROPOSALS_HEADER,
    merge_project_notes,
    split_project_notes,
    verified_author_quotes,
)


@pytest.mark.unit
def test_split_legacy_notes_are_unlabeled():
    sections = split_project_notes("反派身份第20章前不得揭露\n女主第5章才出场")
    assert sections.unlabeled == ["反派身份第20章前不得揭露", "女主第5章才出场"]
    assert sections.confirmed == [] and sections.proposals == []


@pytest.mark.unit
def test_split_recognizes_both_headers():
    text = f"旧条目\n\n{CONFIRMED_HEADER}\n主角不会游泳\n\n{PROPOSALS_HEADER}\n- 北境封印牵动整个王朝"
    sections = split_project_notes(text)
    assert sections.unlabeled == ["旧条目"]
    assert sections.confirmed == ["主角不会游泳"]
    assert sections.proposals == ["- 北境封印牵动整个王朝"]


@pytest.mark.unit
def test_quotes_must_appear_in_author_messages_ignoring_punctuation():
    messages = ["记住：女主，第五章才出场！"]
    assert verified_author_quotes(["女主第五章才出场"], messages) == ["女主第五章才出场"]
    assert verified_author_quotes(["女主第三章出场"], messages) == []
    # 一个字的「原话」（如「好」）太短，不能当依据
    assert verified_author_quotes(["女"], messages) == []


@pytest.mark.unit
def test_merge_without_author_context_keeps_old_behavior():
    merged = merge_project_notes(
        None, notes="主角冷静", proposals=None, author_quotes=None, author_messages=None
    )
    # 和以前一样原样存成纯文本：不核对，也不冒称作者确认
    assert merged.text == "主角冷静"
    assert merged.downgraded == []


@pytest.mark.unit
def test_merge_mixed_line_splits_entries_by_source():
    merged = merge_project_notes(
        f"{CONFIRMED_HEADER}\n主角冷静",
        notes="主角冷静；白石镇是主角老家",
        proposals=None,
        author_quotes=None,
        author_messages=["接着写第三章"],
    )
    sections = split_project_notes(merged.text)
    assert sections.confirmed == ["主角冷静"]
    assert sections.proposals == ["白石镇是主角老家"]
    assert merged.downgraded == ["白石镇是主角老家"]


@pytest.mark.unit
def test_merge_empty_notes_clears_everything():
    merged = merge_project_notes(
        f"{CONFIRMED_HEADER}\nA约定\n{PROPOSALS_HEADER}\nB提议",
        notes="",
        proposals=None,
        author_quotes=None,
        author_messages=["把备注清空"],
    )
    assert merged.text == ""


@pytest.mark.unit
def test_merge_proposals_only_keeps_confirmed_and_replaces_proposals():
    merged = merge_project_notes(
        f"{CONFIRMED_HEADER}\nA约定\n{PROPOSALS_HEADER}\n旧提议",
        notes=None,
        proposals="新提议一\n新提议二",
        author_quotes=None,
        author_messages=["你有什么想法"],
    )
    sections = split_project_notes(merged.text)
    assert sections.confirmed == ["A约定"]
    assert sections.proposals == ["新提议一", "新提议二"]
