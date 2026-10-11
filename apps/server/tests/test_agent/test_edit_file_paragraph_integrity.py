"""edit_file 不破坏正文（I10）：不并段、插入保持本文的分段与缩进、近似边界不截断句子、
报告成功就必须真的改了。

样例文本都是为测试自拟的，不取自任何用户作品。
"""

import pytest
from sqlmodel import Session

from agent.tools.file_ops.edit import (
    EDIT_ERROR_ANCHOR_NOT_FOUND,
    EDIT_ERROR_NO_CHANGE,
    EditBatchError,
    EditFileError,
    FileEditor,
)
from agent.tools.file_ops.text_matching import find_approximate_match, find_fuzzy_spans
from models import File, Project, User
from services.features.activation_event_service import activation_event_service
from services.features.file_version_service import FileVersionService

P1 = "　　档案室里很静，只有顶灯在嗡嗡作响。"
P2 = "　　林舟翻到腰酸，直起身靠着书架站了一会儿。"
P3 = "　　他数了数这几年的卷宗，一共十七册。"
CHAPTER = "\n\n".join([P1, P2, P3])


@pytest.fixture
def editor() -> FileEditor:
    return FileEditor(session=None)


def _insert_after(editor, content, anchor, text, **extra):
    applied: list[dict] = []
    edit = {"op": "insert_after", "anchor": anchor, "text": text, **extra}
    return editor._apply_insert_after(content, edit, 0, applied, []), applied


def _insert_before(editor, content, anchor, text, **extra):
    applied: list[dict] = []
    edit = {"op": "insert_before", "anchor": anchor, "text": text, **extra}
    return editor._apply_insert_before(content, edit, 0, applied, []), applied


# ------------------------------------------------- 模糊/近似匹配不跨段落分隔 --


def test_fuzzy_spans_do_not_cross_a_paragraph_break_the_pattern_lacks():
    """单行 old 在归一化空间里与「段尾 + 下一段段首」相连：不能当成命中。"""
    old = "靠着书架站了一会儿。他数了数这几年的卷宗"
    stats: dict[str, int] = {}
    spans = find_fuzzy_spans(CHAPTER, old, keep_line_breaks=True, stats=stats)
    assert spans == []
    assert stats["paragraph_rejected"] == 1
    # 不要求保留换行的调用方（锚点定位）行为不变。
    assert len(find_fuzzy_spans(CHAPTER, old)) == 1


def test_fuzzy_replace_across_paragraph_break_errors_instead_of_merging(editor):
    old = "直起身靠着书架站了一会儿。他数了数这几年的卷宗"
    new = "直起身靠着铁架站了一会儿。他数了数这几年的卷宗"
    with pytest.raises(EditFileError) as exc:
        editor._apply_replace(CHAPTER, {"op": "replace", "old": old, "new": new}, 0, [], [])
    assert exc.value.error_type == EDIT_ERROR_ANCHOR_NOT_FOUND
    assert "换行" in str(exc.value)


def test_fuzzy_delete_across_paragraph_break_errors_instead_of_merging(editor):
    with pytest.raises(EditFileError) as exc:
        editor._apply_delete(
            CHAPTER, {"op": "delete", "old": "站了一会儿。他数了数这几年的卷宗，"}, 0, [], []
        )
    assert "换行" in str(exc.value)


def test_fuzzy_replace_that_writes_the_paragraph_break_keeps_both_paragraphs(editor):
    """old 写出了原文的分段（只是标点有出入）：照常命中，两段仍是两段。"""
    old = "直起身靠着书架站了一会儿.\n\n　　他数了数这几年的卷宗"
    new = "直起身靠着铁架站了一会儿。\n\n　　他数了数这几年的卷宗"
    result = editor._apply_replace(CHAPTER, {"op": "replace", "old": old, "new": new}, 0, [], [])
    assert result == "\n\n".join([P1, P2.replace("书架", "铁架"), P3])


def test_approximate_match_window_does_not_cross_a_paragraph_break():
    content = (
        "　　风从窗缝里钻进来，吹得纸页沙沙地响个不停。\n"
        "　　她把台灯拧亮了一点，低头继续抄写那份名单。"
    )
    # 近似（有错字）且跨了两行的单行 pattern。
    pattern = "吹得纸张沙沙地响个不停她把台灯拧亮了一些"
    assert find_approximate_match(content, pattern, max_error_rate=0.25, min_pattern_len=8) is not None
    stats: dict[str, int] = {}
    assert (
        find_approximate_match(
            content, pattern, max_error_rate=0.25, min_pattern_len=8, keep_line_breaks=True, stats=stats
        )
        is None
    )
    assert stats["paragraph_rejected"] >= 1


def test_approximate_replace_never_merges_two_lines(editor):
    content = (
        "　　风从窗缝里钻进来，吹得纸页沙沙地响个不停。\n"
        "　　她把台灯拧亮了一点，低头继续抄写那份名单。"
    )
    old = "吹得纸张沙沙地响个不停她把台灯拧亮了一些"
    with pytest.raises(EditFileError):
        editor._apply_replace(content, {"op": "replace", "old": old, "new": "吹得纸页乱响"}, 0, [], [])


# --------------------------------------------- 插入保持本文自己的分段与缩进 --


def test_insert_after_paragraph_without_leading_break_gets_the_files_separator(editor):
    result, applied = _insert_after(editor, CHAPTER, P2, "　　窗外有人走过，脚步声很快远了。")
    assert result == "\n\n".join([P1, P2, "　　窗外有人走过，脚步声很快远了。", P3])
    assert applied[0]["layout_notes"]


def test_insert_after_with_separator_at_the_end_moves_it_to_the_front(editor):
    result, _ = _insert_after(editor, CHAPTER, P2, "　　窗外有人走过。\n\n")
    assert result == "\n\n".join([P1, P2, "　　窗外有人走过。", P3])


def test_insert_after_uses_the_files_own_single_newline_separator(editor):
    content = "\n".join([P1, P2, P3])
    result, _ = _insert_after(editor, content, P2, "\n\n　　窗外有人走过。")
    assert result == "\n".join([P1, P2, "　　窗外有人走过。", P3])


def test_insert_after_new_paragraph_without_indent_follows_the_files_indent(editor):
    result, _ = _insert_after(editor, CHAPTER, "靠着书架站了一会儿。", "\n\n窗外有人走过。")
    assert result == "\n\n".join([P1, P2, "　　窗外有人走过。", P3])


def test_insert_before_paragraph_keeps_the_next_paragraphs_indent_on_its_own_line(editor):
    """U068 的形状：下一段的「　　」不能接到新插入的段落行尾。"""
    result, _ = _insert_before(editor, CHAPTER, P3, "　　窗外有人走过。")
    assert result == "\n\n".join([P1, P2, "　　窗外有人走过。", P3])
    assert "。　　" not in result


def test_insert_before_unindented_anchor_places_the_paragraph_before_the_indent(editor):
    result, _ = _insert_before(editor, CHAPTER, "他数了数这几年的卷宗", "窗外有人走过。\n\n")
    assert result == "\n\n".join([P1, P2, "　　窗外有人走过。", P3])


def test_insert_after_anchor_ending_with_the_break_does_not_glue_onto_next_indent(editor):
    result, _ = _insert_after(editor, CHAPTER, P2 + "\n\n", "　　窗外有人走过。")
    assert result == "\n\n".join([P1, P2, "　　窗外有人走过。", P3])


def test_insert_after_plain_sentence_at_paragraph_end_still_continues_the_paragraph(editor):
    """没有任何分段标记的一句话：接在段尾，是原来的行为。"""
    result, applied = _insert_after(editor, CHAPTER, P2, "他喘了口气。")
    assert result == "\n\n".join([P1, P2 + "他喘了口气。", P3])
    assert "layout_notes" not in applied[0]


def test_insert_after_mid_paragraph_split_is_left_as_written(editor):
    """段中插入以换行开头：模型就是要在这里拆段，原样执行。"""
    content = "　　他推开门，屋里没人。桌上放着一封信。"
    result, _ = _insert_after(editor, content, "屋里没人。", "\n\n　　他愣住了。\n\n　　")
    assert result == "　　他推开门，屋里没人。\n\n　　他愣住了。\n\n　　桌上放着一封信。"


def test_append_paragraph_without_break_is_separated_from_the_last_line(editor):
    notes: list[str] = []
    pos, text = editor._position_insert(
        CHAPTER, len(CHAPTER), "　　夜深了。", direction="after", snap_sentence=False, notes=notes
    )
    assert (pos, text) == (len(CHAPTER), "\n\n　　夜深了。")
    assert notes


# --------------------------------------------- 插入点不落在字和标点之间 --


def test_insert_after_sentence_does_not_land_between_word_and_its_period(editor):
    result, applied = _insert_after(editor, CHAPTER, "靠着书架站了一会儿", "他喘了口气。")
    assert "站了一会儿。他喘了口气。" in result
    assert "。。" not in result
    assert applied[0]["layout_notes"]


def test_insert_after_clause_still_goes_right_after_the_anchor(editor):
    """以逗号开头的分句是要接在锚点后面的，位置不动。"""
    result, _ = _insert_after(editor, CHAPTER, "靠着书架站了一会儿", "，腿有些发麻")
    assert "站了一会儿，腿有些发麻。" in result


def test_insert_before_sentence_does_not_split_an_opening_quote_from_its_line(editor):
    content = "　　他抬起头：“你来了。”她没说话。"
    result, _ = _insert_before(editor, content, "你来了。", "门响了一声。")
    assert result == "　　门响了一声。他抬起头：“你来了。”她没说话。"


def test_approximate_insert_after_snaps_to_the_end_of_the_sentence(editor):
    content = (
        "　　林舟翻到腰酸，直起身靠着书架站了一会儿，才想起水杯还落在楼下。\n\n"
        "　　他数了数这几年的卷宗，一共十七册。"
    )
    # 有错字的锚点，只覆盖到句子中间。
    anchor = "林舟翻得腰酸，直起身倚着书架站了一会儿，才想起水杯"
    result, applied = _insert_after(editor, content, anchor, "他喘了口气。")
    assert applied[0]["match_mode"] == "approximate"
    assert "落在楼下。他喘了口气。\n\n" in result


def test_approximate_replace_ending_mid_sentence_is_refused(editor):
    """old 以句号收尾，近似命中的范围却停在字中间：拒绝，不留半句残尾。"""
    content = (
        "　　风从窗缝里钻进来，吹得纸页沙沙地响个不停，像有人在翻一本很旧很旧的书。\n"
        "　　她把台灯拧亮了一点。"
    )
    # 近似窗口停在「翻」：以前替换成「风停了。一本很旧很旧的书。」，留下半句残尾。
    old = "风从窗缝里吹进来，吹得纸页沙沙作响个不停，像有人在翻书。"
    with pytest.raises(EditFileError) as exc:
        editor._apply_replace(content, {"op": "replace", "old": old, "new": "风停了。"}, 0, [], [])
    assert "句子中间" in str(exc.value)


# ----------------------------------------------------- DB 级：成功就必须改了 --


@pytest.fixture
def owner_project(db_session, monkeypatch):
    import database

    user = User(username="i10-owner", email="i10-owner@example.test", hashed_password="unused", email_verified=True)
    project = Project(name="编辑完整性", owner_id=user.id)
    db_session.add_all([user, project])
    db_session.commit()
    engine = db_session.get_bind()
    monkeypatch.setattr(database, "create_session", lambda: Session(engine))
    monkeypatch.setattr(activation_event_service, "record_ai_write_accepted", lambda *_a, **_kw: None)
    monkeypatch.setattr(activation_event_service, "record_once", lambda *_a, **_kw: None)
    monkeypatch.setattr(FileVersionService, "check_user_version_quota", lambda *_a, **_kw: (True, 0, 10))
    return user, project


def _add_file(session, project, content, file_type="draft"):
    file = File(project_id=project.id, title="第1章", content=content, file_type=file_type)
    session.add(file)
    session.commit()
    session.refresh(file)
    return file


def test_replace_with_identical_text_is_reported_as_no_change(db_session, owner_project):
    user, project = owner_project
    chapter = _add_file(db_session, project, CHAPTER)

    with pytest.raises(EditBatchError) as exc:
        FileEditor(db_session, user.id).edit_file(
            chapter.id, [{"op": "replace", "old": "一共十七册", "new": "一共十七册"}]
        )
    assert exc.value.failed_edits[0]["error_type"] == EDIT_ERROR_NO_CHANGE
    db_session.expire_all()
    assert db_session.get(File, chapter.id).content == CHAPTER


def test_no_change_edit_is_not_counted_as_applied(db_session, owner_project):
    user, project = owner_project
    chapter = _add_file(db_session, project, CHAPTER)

    result = FileEditor(db_session, user.id).edit_file(
        chapter.id,
        [
            {"op": "replace", "old": "一共十七册", "new": "一共十八册"},
            {"op": "replace", "old": "顶灯在嗡嗡作响", "new": "顶灯在嗡嗡作响"},
        ],
        continue_on_error=True,
    )
    assert result["edits_applied"] == 1
    assert [item["index"] for item in result["failed_edits"]] == [1]
    assert result["failed_edits"][0]["error_type"] == EDIT_ERROR_NO_CHANGE


def test_corner_to_curly_conversion_is_applied_not_normalized_back(db_session, owner_project):
    """U079 的形状：「」稿件里把对白改成 “”，规范化器不能再把它改回「」还报成功。"""
    user, project = owner_project
    original = "　　「回来了？」母亲问。\n\n　　「嗯。」他把伞靠在门边。"
    chapter = _add_file(db_session, project, original)

    result = FileEditor(db_session, user.id).edit_file(
        chapter.id,
        [
            {"op": "replace", "old": "「回来了？」母亲问。", "new": '"回来了？"母亲问。'},
            {"op": "replace", "old": "「嗯。」他把伞", "new": '"嗯。"他把伞'},
        ],
        normalize_quotes=True,
    )

    assert result["edits_applied"] == 2
    db_session.expire_all()
    assert db_session.get(File, chapter.id).content == (
        "　　“回来了？”母亲问。\n\n　　“嗯。”他把伞靠在门边。"
    )


def test_halfwidth_rewrite_in_corner_draft_still_follows_the_draft_style(db_session, owner_project):
    """改了字的编辑照旧按稿件体例规范引号（只有「只改引号」才视为体例转换）。"""
    user, project = owner_project
    chapter = _add_file(db_session, project, "　　「回来了？」母亲问。")

    FileEditor(db_session, user.id).edit_file(
        chapter.id,
        [{"op": "replace", "old": "「回来了？」母亲问。", "new": '"吃了吗？"母亲问。'}],
        normalize_quotes=True,
    )

    db_session.expire_all()
    assert db_session.get(File, chapter.id).content == "　　「吃了吗？」母亲问。"


def test_curly_to_ascii_noop_is_reported_honestly(db_session, owner_project):
    user, project = owner_project
    original = "　　“回来了？”母亲问。"
    chapter = _add_file(db_session, project, original)

    with pytest.raises(EditBatchError) as exc:
        FileEditor(db_session, user.id).edit_file(
            chapter.id,
            [{"op": "replace", "old": "“回来了？”母亲问。", "new": '"回来了？"母亲问。'}],
            normalize_quotes=True,
        )
    assert exc.value.failed_edits[0]["error_type"] == EDIT_ERROR_NO_CHANGE
    assert "引号" in exc.value.failed_edits[0]["error"]
    db_session.expire_all()
    assert db_session.get(File, chapter.id).content == original
