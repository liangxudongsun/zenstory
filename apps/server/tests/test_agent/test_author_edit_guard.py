"""作者手动改过的文件，作者本轮没点名时 AI 不改不删（2026-10-09 审计 P1-3）。

审计原样：作者在第 3 章把「老周」手改成「老秦」（19 处），发「继续写下一章」。AI 写完
第 4 章后把第 3 章全改了回去，总结里写「顺手修的两处」。
"""

import json

import pytest
from fastapi import BackgroundTasks
from sqlmodel import Session

from agent.service import routing_from_router_decided
from agent.tools import mcp_tools
from agent.tools.author_edit_guard import (
    AUTHOR_EDIT_PROTECTED_ERROR,
    CONFIRM_FILE_IDS_ROUTING_KEY,
    AuthorEditRefusals,
    AuthorScope,
    confirmed_file_ids_from_history,
    ends_with_conditional_offer,
    latest_text_is_authors,
    mentioned_sequences,
    previous_offer_context_from_history,
    previous_offer_from_history,
    previous_offer_items,
    referenced_file_ids_from_metadata,
    rename_source_terms,
    request_deletes_file,
    request_deletes_folder,
    request_targets_file,
    resolve_offer_context_file,
)
from agent.tools.file_ops import FileCRUD
from api import files as files_api
from models import File, Project, User
from services.features.activation_event_service import activation_event_service
from services.features.file_version_service import FileVersionService

AI_CH3 = "老周在收摊。折叠桌一张张码上三轮车。老周回头看了他一眼。"
AUTHOR_CH3 = "老秦在收摊。折叠桌一张张码上三轮车。老秦回头看了他一眼。"


def _scope(message: str, **kwargs) -> AuthorScope:
    return AuthorScope(messages=(message,), **kwargs)


def _targets(message: str, *, title: str = "第3章 三十年", file_id: str = "ch3", **kwargs) -> bool:
    focus = kwargs.pop("focus", None)
    return request_targets_file(
        _scope(message, focus_file_id=focus), file_id=file_id, title=title, **kwargs
    )


class TestRequestTargetsFile:
    def test_continue_next_chapter_does_not_target_the_open_chapter(self):
        # 审计原样：作者正开着第 3 章，说「继续写下一章」。
        assert _targets("继续写下一章", focus="ch3") is False
        assert _targets("继续写下一章", focus="ch3", edits=[{"op": "append", "text": "续写"}]) is False

    def test_named_chapter_is_targeted(self):
        assert _targets("把第三章结尾改一下") is True
        assert _targets("第3章的错别字帮我改掉") is True
        assert _targets("前三章的错别字改一下") is True
        assert _targets("第2、3章统一称呼") is True
        assert _targets("把《三十年》这章的结尾改得狠一点") is True

    def test_negated_mention_is_not_a_request(self):
        assert _targets("继续写第5章。另外以后别改我已经写好的章节，要改先问我。") is False
        assert _targets("别动第3章，写第4章") is False
        assert _targets("不要统一称呼，按我改的来") is False
        assert mentioned_sequences("不用管第2章，把第3章的结尾改一下") == {(3, "novel")}

    def test_rename_request_allows_only_replacing_the_old_name(self):
        assert rename_source_terms("帮我把老秦全部改成老周") == {"老秦"}
        rename = {"op": "replace", "old": "老秦在收摊。", "new": "老周在收摊。"}
        unrelated = {"op": "replace", "old": "折叠桌一张张码上三轮车。", "new": "桌子收好了。"}
        assert _targets("把老秦改回老周", edits=[rename]) is True
        assert _targets("把老秦改回老周", edits=[rename, unrelated]) is False

    def test_continue_writing_the_open_chapter_may_only_append(self):
        assert _targets("继续写", focus="ch3", edits=[{"op": "append", "text": "后来"}]) is True
        assert _targets(
            "继续写", focus="ch3", edits=[{"op": "replace", "old": "老秦", "new": "老周"}]
        ) is False
        # 不是正开着的文件，追加也不行。
        assert _targets("继续写", focus="ch2", edits=[{"op": "append", "text": "后来"}]) is False

    def test_this_chapter_refers_to_the_open_file(self):
        assert _targets("帮我润色一下这一章", focus="ch3") is True
        assert _targets("帮我润色一下这一章", focus="ch2") is False

    def test_file_category_needs_an_edit_verb(self):
        assert request_targets_file(
            _scope("按大纲写第5章"), file_id="o1", title="核心大纲", file_type="outline"
        ) is False
        assert request_targets_file(
            _scope("把大纲里第5章改一下"), file_id="o1", title="分章大纲", file_type="outline"
        ) is True

    def test_referenced_and_confirmed_files_are_targeted(self):
        assert request_targets_file(
            AuthorScope(messages=("改一下",), referenced_file_ids=frozenset({"ch3"})),
            file_id="ch3",
            title="第3章",
        ) is True
        # 上一轮因为作者手改过没改它，作者这一轮说清了往哪改。
        assert request_targets_file(
            AuthorScope(messages=("统一成老周吧",), confirmed_file_ids=frozenset({"ch3"})),
            file_id="ch3",
            title="第3章",
            edits=[{"op": "replace", "old": "老秦", "new": "老周"}],
        ) is True

    @pytest.mark.parametrize(
        ("reply", "unlocked"),
        [
            # 说清了往哪改（不点名别的章）：放行把这一章往这个写法改。
            ("统一成老周吧", True),
            ("改回老周", True),
            ("可以，统一成老周，然后写下一章", True),
            # 上一轮 AI 问的是「要把第2章也改成老秦吗？」：「好 / 可以」答应的是改第2章，
            # 不放开作者改过的第3章（审计复查：答应改别的章时第3章被改回去）。
            ("可以", False),
            ("好", False),
            ("行", False),
            ("嗯", False),
            ("OK", False),
            ("没问题", False),
            ("改吧", False),
            ("好，改吧，然后写下一章", False),
            ("可以，第2章也改成老秦", False),
            ("第2章改成老秦", False),
            # 往作者的写法统一：用不着动作者改过的这一章。
            ("统一成老秦吧", False),
            # 作者不同意、或只是让 AI 往下写：上一轮问过也不放行。
            ("不用改，继续写下一章", False),
            ("不用改，第3章就叫老秦", False),
            ("先不改，按我的来", False),
            ("好，继续写下一章", False),
            ("继续写第5章", False),
            ("继续写下一章，人名要统一", False),
            ("统一吧", False),
            ("要统一", False),
            ("继续写第5章，写好一点", False),
            ("继续写下一章，开头改得有悬念一点", False),
            ("我已经把老周改成老秦了，继续写下一章", False),
            ("我自己改好了", False),
        ],
    )
    def test_reply_to_the_ais_question_unlocks_only_with_a_direction(self, reply, unlocked):
        scope = AuthorScope(messages=(reply,), confirmed_file_ids=frozenset({"ch3"}))
        revert = [{"op": "replace", "old": "老秦", "new": "老周", "replace_all": True}]
        assert request_targets_file(scope, file_id="ch3", title="第3章 三十年", edits=revert) is unlocked

    def test_direction_reply_still_allows_only_edits_toward_it(self):
        scope = AuthorScope(messages=("统一成老周吧",), confirmed_file_ids=frozenset({"ch3"}))
        unrelated = {"op": "replace", "old": "折叠桌一张张码上三轮车。", "new": "桌子收好了。"}
        assert request_targets_file(scope, file_id="ch3", title="第3章 三十年", edits=[unrelated]) is False
        # 没有逐处修改（删除 / 整份重写）不算答应。
        assert request_targets_file(scope, file_id="ch3", title="第3章 三十年") is False

    def test_edit_request_on_the_open_chapter(self):
        # 作者正开着第 1 章、直接提改动：就是改这一章。
        assert _targets("把开头改得更有悬念一点", title="第1章 夜班", file_id="ch1", focus="ch1") is True
        assert _targets("精简一下对话", title="第1章 夜班", file_id="ch1", focus="ch1") is True
        # 没开着它、点名了别的章、或者要的是下一章：都不算改它。
        assert _targets("把开头改得更有悬念一点", title="第1章 夜班", file_id="ch1") is False
        assert _targets("把第3章开头改一下", title="第1章 夜班", file_id="ch1", focus="ch1") is False
        assert _targets("继续写下一章，开头改得有悬念一点", title="第1章 夜班", file_id="ch1", focus="ch1") is False
        assert _targets("不用改，继续写", title="第1章 夜班", file_id="ch1", focus="ch1") is False

    def test_rename_by_description_allows_only_the_new_name(self):
        rename = {"op": "replace", "old": "张三", "new": "李明", "replace_all": True}
        in_context = {"op": "replace", "old": "张三推开门。", "new": "李明推开门。"}
        unrelated = {"op": "replace", "old": "折叠桌一张张码上三轮车。", "new": "桌子收好了。"}
        message = "帮我把主角的名字改成李明"
        assert _targets(message, edits=[rename]) is True
        assert _targets(message, edits=[rename, in_context]) is True
        assert _targets(message, edits=[rename, unrelated]) is False
        # 开着的那一章：提了改动，整章都算作者要改的。
        assert _targets(message, focus="ch3", edits=[unrelated]) is True

    def test_title_word_or_unify_alone_is_not_a_request_to_edit(self):
        # 提到「夜市」只是在说下一章的内容。
        assert _targets("继续写第四章，夜市那段的氛围延续下去", title="第3章 夜市") is False
        assert _targets("夜市那段改得紧凑一点", title="第3章 夜市") is True
        assert _targets("参考第3章的写法写第4章") is False
        assert _targets("第3章写得太拖了，帮我精简一下") is True
        assert _targets("第2章不用改，第3章改成老周", title="第2章 夜班", file_id="ch2") is False
        # 「统一」不再整轮放开所有已有章节（审计：作者手改的「老秦」会被改回去）。
        assert _targets("统一一下格式再写下一章", focus="ch3") is False
        assert _targets("继续写下一章，人名要统一") is False

    def test_unify_without_a_direction_does_not_unlock_the_open_chapter(self):
        # 作者刚把第 3 章的老周改成老秦、还开着它：「人名要统一」「统一一下格式」不能让 AI
        # 把老秦改回老周；点名「这一章」或说清「统一成老周」才算。
        revert = [{"op": "replace", "old": "老秦", "new": "老周"}]
        assert _targets("人名要统一", focus="ch3", edits=revert) is False
        assert _targets("把格式统一一下", focus="ch3", edits=revert) is False
        assert _targets("这一章的人名统一一下", focus="ch3", edits=revert) is True
        assert _targets("第3章人名统一一下", edits=revert) is True
        assert _targets("老秦统一成老周", focus="ch3", edits=revert) is True

    def test_words_that_only_look_like_an_edit_request(self):
        # 「改变」「继续更新」不是要改已有章节；作者讲自己改过的也不是。
        assert _targets("继续写第四章，夜市里主角命运改变", title="第3章 夜市") is False
        assert _targets("继续更新", focus="ch3", edits=[{"op": "replace", "old": "老秦", "new": "老周"}]) is False
        assert _targets("今天更新两章") is False
        assert _targets("我把第3章的老周改成老秦了，继续写下一章") is False
        assert _targets("第3章夜市那段我改过了，你继续写第4章", title="第3章 夜市") is False
        assert _targets("我在第3章把人名改了，继续写下一章") is False
        assert _targets("第3章已经改好了，继续写第4章") is False
        # 接着往下写时，开着的文件只能往后追加，不能改作者写过的字。
        assert _targets("接着写，节奏改快点", focus="ch3", edits=[{"op": "replace", "old": "老秦", "new": "老周"}]) is False
        assert _targets("接着写，节奏改快点", focus="ch3", edits=[{"op": "append", "text": "后来"}]) is True
        # 真正的要求照常放行。
        assert _targets("帮我把第3章改了") is True
        assert _targets("我想把第3章的开头改一下") is True
        assert _targets("我觉得第3章太拖了，精简一下") is True
        assert _targets("把之前写的第3章改一下") is True

    @pytest.mark.parametrize(
        "message",
        [
            # 拿第3章当标准 / 来源：作者是在让 AI 跟着第3章走，不是要改第3章。
            "写第4章，和第3章的人名保持统一",
            "第4章的人名要和第3章统一",
            "第4章要跟第3章保持一致",
            "第4章沿用第3章的改动",
            "以第3章为准，统一一下人名",
            "人名以第3章为准",
            "第3章为准，其他章统一一下",
            "按第3章统一人名",
            "按照《三十年》统一人名",
            "第2章按第3章改",
            "把第2章改得跟第3章一样",
            "同步第3章的人名到第4章",
            # 讲完第3章改过了，下一分句的要求说的是别的章。
            "第3章是我改过的，以它为准统一一下其他章",
            "第3章我改了名字，把前面的章节也统一一下",
            "第3章改了名字，后面的章节统一一下",
            # 讲第3章已经改过（没有「我 / 已经 / 过」）。
            "第3章老周改成老秦了，继续写下一章",
            "第3章里老周换成老秦了",
            "第3章改好了，继续写下一章",
            "第3章改完了，继续写下一章",
            "第3章刚改完，接着写第4章",
            "第3章有改动，继续写下一章",
            "第3章做了修改，继续写下一章",
            "第3章调整了一下人名，继续写下一章",
            "第3章改好了吗",
        ],
    )
    def test_naming_the_chapter_as_the_standard_or_reporting_an_edit_does_not_unlock_it(self, message):
        # 审计复查：这些话里作者都是在让 AI 跟着第3章走；模型要是反过来统一，就会把
        # 作者手改的「老秦」改回「老周」。
        revert = [{"op": "replace", "old": "老秦", "new": "老周", "replace_all": True}]
        assert _targets(message) is False
        assert _targets(message, edits=revert) is False

    @pytest.mark.parametrize(
        "message",
        [
            "第3章人名统一一下",
            "把第3章统一成老周",
            "把第3章和第4章统一一下",
            "把第2章和第3章统一成老周",
            "第3章跟第2章统一成老周",
            "第3章的人名改回老周",
            "第3章再改一下",
            "请把第3章改短一点",
            "第3章，帮我润色一下",
            "把第3章的结局改变一下",
            "第3章写得太烂了，删了吧",
        ],
    )
    def test_asking_to_change_the_named_chapter_still_unlocks_it(self, message):
        assert _targets(message) is True

    def test_deleting_inside_a_folder_is_not_deleting_the_folder(self):
        for message in ("正文里的第2章删掉", "正文里多余的空行删掉", "正文里的错别字去掉", "把正文里重复的段落删掉"):
            assert request_deletes_folder(_scope(message), file_id="f", title="正文") is False, message
        assert request_deletes_folder(_scope("正文整个删掉"), file_id="f", title="正文") is True
        # 删的说法要落在点名第3章的那一处：「把废稿删了」说的是废稿。
        assert request_deletes_file(_scope("第3章改一下，把废稿删了"), file_id="ch3", title="第3章 三十年") is False
        assert request_deletes_file(_scope("把第3章和废稿都删了"), file_id="ch3", title="第3章 三十年") is True

    def test_deleting_a_folder_needs_the_author_to_say_delete(self):
        assert request_deletes_folder(_scope("把废稿文件夹删了"), file_id="f", title="废稿") is True
        assert request_deletes_folder(_scope("废稿那个文件夹，不要了"), file_id="f", title="废稿") is True
        # 只提到文件夹名的改动要求、或者说的是别的，不算要删它。
        assert request_deletes_folder(_scope("正文改紧凑一点"), file_id="f", title="正文") is False
        assert request_deletes_folder(_scope("别删正文文件夹"), file_id="f", title="正文") is False
        assert request_deletes_folder(
            AuthorScope(messages=("改一下",), referenced_file_ids=frozenset({"f"})), file_id="f", title="正文"
        ) is False
        # 文件夹里作者改过的章节：点名并说删才跟着删，只说「改一下」不算。
        assert request_deletes_file(_scope("第3章删掉"), file_id="ch3", title="第3章 三十年") is True
        assert request_deletes_file(_scope("第3章改一下"), file_id="ch3", title="第3章 三十年") is False

    def test_whole_book_request_targets_every_file(self):
        assert _targets("全书统一一下称呼") is True
        assert _targets("全书写到第3章了，继续写下一章") is False


def test_history_and_metadata_helpers():
    history = [
        {"role": "user", "content": "继续写下一章"},
        {"role": "assistant", "content": "…", "routing": {CONFIRM_FILE_IDS_ROUTING_KEY: ["ch3"]}},
        {"role": "user", "content": "可以"},
    ]
    assert confirmed_file_ids_from_history(history) == ["ch3"]
    # 只看上一条 assistant 消息：更早问过的不算。
    later = [*history, {"role": "assistant", "content": "好的", "routing": {}}]
    assert confirmed_file_ids_from_history(later) == []
    assert referenced_file_ids_from_metadata(
        {"attached_file_ids": ["a"], "text_quotes": [{"fileId": "b", "text": "x"}], "current_file_id": "c"}
    ) == ["a", "b"]
    # 笼统要求问过一次的标记随路由落库（下一轮不再问第二次）。
    persisted = routing_from_router_decided(
        {"initial_agent": "writer", "routing_metadata": {"agent_type": "writer", "clarify_first": True}}
    )
    assert persisted["clarify_first"] is True
    assert "clarify_first" not in routing_from_router_decided({"initial_agent": "writer"})


# ----------------------------------------------------------------- 工具层


@pytest.fixture
def owner_project(db_session, monkeypatch):
    user = User(username="guard-owner", email="guard-owner@example.test", hashed_password="unused", email_verified=True)
    project = Project(name="还剩三分钟", owner_id=user.id)
    db_session.add_all([user, project])
    db_session.commit()
    monkeypatch.setattr(FileCRUD, "_schedule_index_upsert", lambda *_a, **_kw: None)
    monkeypatch.setattr(activation_event_service, "record_ai_write_accepted", lambda *_a, **_kw: None)
    monkeypatch.setattr(activation_event_service, "record_once", lambda *_a, **_kw: None)
    monkeypatch.setattr(FileVersionService, "check_user_version_quota", lambda *_a, **_kw: (True, 0, 10))
    monkeypatch.setattr("services.llama_index.schedule_index_upsert", lambda **_kw: None)
    monkeypatch.setattr("services.infra.dashboard_cache.dashboard_cache.bump_project_version", lambda *_a, **_kw: None)
    return user, project


def _ai_chapter(session, project, title="第3章 三十年", content=AI_CH3):
    """AI 写的章节：正文 + 一个 AI 版本（和 create_file 带正文时一样）。"""
    file = File(project_id=project.id, title=title, content=content, file_type="draft")
    session.add(file)
    session.flush()
    FileVersionService().create_version(
        session, file.id, content, change_type="create", change_source="ai", commit=False
    )
    session.commit()
    session.refresh(file)
    return file


def _author_saves(session, user, file, content):
    """作者在编辑器里手动改正文（走真实的保存接口，留下作者版本）。"""
    files_api.update_file(
        file.id,
        files_api.FileUpdate(content=content),
        BackgroundTasks(),
        current_user=user,
        session=session,
    )


async def _run(tool, session, user, project, args, *, message, refusals=None, **context):
    engine = session.get_bind()
    mcp_tools.ToolContext.set_context(
        None,
        user.id,
        project.id,
        None,
        create_session_func=lambda: Session(engine),
        author_message=message,
        author_steering=[],
        author_edit_refusals=refusals,
        **context,
    )
    try:
        raw = await tool(args)
    finally:
        mcp_tools.ToolContext.clear_context()
    return json.loads(raw["content"][0]["text"])


def _revert_rename_edit(file_id):
    return {"id": file_id, "edits": [
        {"op": "replace", "old": "老秦", "new": "老周", "replace_all": True},
    ]}


async def test_ai_cannot_revert_the_authors_rename_in_an_unrequested_chapter(db_session, owner_project):
    user, project = owner_project
    chapter = _ai_chapter(db_session, project)
    _author_saves(db_session, user, chapter, AUTHOR_CH3)
    refusals = AuthorEditRefusals()

    payload = await _run(
        mcp_tools.edit_file, db_session, user, project, _revert_rename_edit(chapter.id),
        message="继续写下一章", refusals=refusals, focus_file_id=chapter.id,
    )

    assert payload["status"] == "error"
    assert payload["error_type"] == AUTHOR_EDIT_PROTECTED_ERROR
    assert payload["mutation_applied"] is False
    # 给模型的说明：以作者为准、不要重试、去问作者；给作者的话不带内部名字。
    assert "以作者为准" in payload["error"] and "问作者" in payload["error"]
    assert "手动改过" in payload["user_message"] and "edit_file" not in payload["user_message"]
    db_session.expire_all()
    assert db_session.get(File, chapter.id).content == AUTHOR_CH3
    # 记下来随路由落库，作者下一轮回答时放行。
    assert refusals.file_ids() == [chapter.id]


@pytest.mark.parametrize(("change_type", "protected"), [("edit", True), ("ai_edit", False)])
async def test_comparison_save_keeps_the_rename_protected_only_as_an_author_edit(
    db_session, owner_project, change_type, protected
):
    """作者改名还没自动保存时 AI 写了这一章，作者在对比里保留自己的改名后点完成：
    编辑器按作者编辑保存（change_type=edit），下一轮 AI 不能把改名改回去。
    作者接受的 AI 修改（去AI味审阅，change_type=ai_edit）照旧不算作者的文字。"""
    user, project = owner_project
    chapter = _ai_chapter(db_session, project)
    files_api.update_file(
        chapter.id,
        files_api.FileUpdate(content=AUTHOR_CH3, change_type=change_type, change_source="user"),
        BackgroundTasks(),
        current_user=user,
        session=db_session,
    )
    db_session.expire_all()
    assert latest_text_is_authors(db_session, db_session.get(File, chapter.id)) is protected

    payload = await _run(
        mcp_tools.edit_file, db_session, user, project, _revert_rename_edit(chapter.id),
        message="继续写下一章",
    )
    assert (payload.get("error_type") == AUTHOR_EDIT_PROTECTED_ERROR) is protected


async def test_author_can_still_ask_for_the_change(db_session, owner_project):
    user, project = owner_project
    chapter = _ai_chapter(db_session, project)
    _author_saves(db_session, user, chapter, AUTHOR_CH3)

    payload = await _run(
        mcp_tools.edit_file, db_session, user, project, _revert_rename_edit(chapter.id),
        message="第3章的老秦还是改回老周吧",
    )

    assert payload["status"] == "success"
    db_session.expire_all()
    assert db_session.get(File, chapter.id).content == AI_CH3


async def test_reply_to_the_ais_question_unlocks_the_file(db_session, owner_project):
    user, project = owner_project
    chapter = _ai_chapter(db_session, project)
    _author_saves(db_session, user, chapter, AUTHOR_CH3)

    # AI 上一轮问「要把第2章也改成老秦吗？」，作者回「可以」：答应的是改第2章，第3章不动。
    agreed = await _run(
        mcp_tools.edit_file, db_session, user, project, _revert_rename_edit(chapter.id),
        message="可以", author_confirmed_file_ids=[chapter.id],
    )
    assert agreed["error_type"] == AUTHOR_EDIT_PROTECTED_ERROR
    db_session.expire_all()
    assert db_session.get(File, chapter.id).content == AUTHOR_CH3

    # 作者说清了往回统一：放行。
    payload = await _run(
        mcp_tools.edit_file, db_session, user, project, _revert_rename_edit(chapter.id),
        message="统一成老周吧", author_confirmed_file_ids=[chapter.id],
    )

    assert payload["status"] == "success"


async def test_ai_written_chapter_is_still_editable_this_round(db_session, owner_project):
    """审稿返工改本轮刚写的章节（最新版本是 AI 的）不受影响。"""
    user, project = owner_project
    chapter = _ai_chapter(db_session, project, title="第4章 数在我这儿", content="老周在收摊。")

    payload = await _run(
        mcp_tools.edit_file, db_session, user, project,
        {"id": chapter.id, "edits": [{"op": "replace", "old": "老周在收摊。", "new": "老周收摊了。"}]},
        message="继续写下一章",
    )

    assert payload["status"] == "success"


async def test_unversioned_manual_edit_is_protected_too(db_session, owner_project):
    """作者的版本额度用满时正文照存、不留版本：正文和最新 AI 版本不一致也算作者改过。"""
    user, project = owner_project
    chapter = _ai_chapter(db_session, project)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(FileVersionService, "check_user_version_quota", lambda *_a, **_kw: (False, 10, 10))
        _author_saves(db_session, user, chapter, AUTHOR_CH3)
    db_session.expire_all()
    assert latest_text_is_authors(db_session, db_session.get(File, chapter.id)) is True

    payload = await _run(
        mcp_tools.edit_file, db_session, user, project, _revert_rename_edit(chapter.id),
        message="继续写下一章",
    )

    assert payload["error_type"] == AUTHOR_EDIT_PROTECTED_ERROR


async def test_delete_of_an_author_edited_chapter_is_refused(db_session, owner_project):
    user, project = owner_project
    chapter = _ai_chapter(db_session, project)
    _author_saves(db_session, user, chapter, AUTHOR_CH3)

    payload = await _run(
        mcp_tools.delete_file, db_session, user, project, {"id": chapter.id},
        message="继续写下一章",
    )

    assert payload["error_type"] == AUTHOR_EDIT_PROTECTED_ERROR
    db_session.expire_all()
    assert db_session.get(File, chapter.id).is_deleted is False


async def test_deleting_an_author_edited_chapter_needs_delete_where_it_is_named(db_session, owner_project):
    """「第3章改一下，把废稿删了」：删的是废稿，作者改过的第3章不能借这句被删掉。"""
    user, project = owner_project
    chapter = _ai_chapter(db_session, project)
    _author_saves(db_session, user, chapter, AUTHOR_CH3)

    refused = await _run(
        mcp_tools.delete_file, db_session, user, project, {"id": chapter.id},
        message="第3章改一下，把废稿删了",
    )
    assert refused["error_type"] == AUTHOR_EDIT_PROTECTED_ERROR
    db_session.expire_all()
    assert db_session.get(File, chapter.id).is_deleted is False

    allowed = await _run(
        mcp_tools.delete_file, db_session, user, project, {"id": chapter.id},
        message="第3章不要了，删掉吧",
    )
    assert allowed["status"] == "success"
    db_session.expire_all()
    assert db_session.get(File, chapter.id).is_deleted is True


async def test_guard_is_off_without_an_author_message(db_session, owner_project):
    """非应用内对话的调用路径（没有作者原话）不受影响。"""
    user, project = owner_project
    chapter = _ai_chapter(db_session, project)
    _author_saves(db_session, user, chapter, AUTHOR_CH3)
    engine = db_session.get_bind()
    mcp_tools.ToolContext.set_context(None, user.id, project.id, None, create_session_func=lambda: Session(engine))
    try:
        raw = await mcp_tools.edit_file(_revert_rename_edit(chapter.id))
    finally:
        mcp_tools.ToolContext.clear_context()

    assert json.loads(raw["content"][0]["text"])["status"] == "success"


async def test_declined_reply_keeps_the_file_protected(db_session, owner_project):
    """上一轮被拒、AI 问过作者；作者回「不用改，继续写下一章」时第 3 章仍然改不了。"""
    user, project = owner_project
    chapter = _ai_chapter(db_session, project)
    _author_saves(db_session, user, chapter, AUTHOR_CH3)
    first_round = AuthorEditRefusals()
    refused = await _run(
        mcp_tools.edit_file, db_session, user, project, _revert_rename_edit(chapter.id),
        message="继续写下一章", refusals=first_round,
    )
    assert refused["error_type"] == AUTHOR_EDIT_PROTECTED_ERROR
    history = [
        {"role": "user", "content": "继续写下一章"},
        {
            "role": "assistant",
            "content": "第4章写好了。第3章是你手动改过的，我没动它：那里摊主叫老秦，第2章写的是老周，要统一吗？",
            "routing": {CONFIRM_FILE_IDS_ROUTING_KEY: first_round.file_ids()},
        },
    ]

    payload = await _run(
        mcp_tools.edit_file, db_session, user, project, _revert_rename_edit(chapter.id),
        message="不用改，继续写下一章",
        author_confirmed_file_ids=confirmed_file_ids_from_history(history),
    )

    assert payload["error_type"] == AUTHOR_EDIT_PROTECTED_ERROR
    db_session.expire_all()
    assert db_session.get(File, chapter.id).content == AUTHOR_CH3


async def test_author_can_edit_the_chapter_they_have_open(db_session, owner_project):
    """作者自己写的第 1 章开着，说「把开头改得更有悬念一点」：照常改，不先问一句。"""
    user, project = owner_project
    chapter = _ai_chapter(db_session, project, title="第1章 夜班", content="夜里十点，他到了店里。")
    _author_saves(db_session, user, chapter, "夜里十点，他推门进了店。")

    payload = await _run(
        mcp_tools.edit_file, db_session, user, project,
        {"id": chapter.id, "edits": [
            {"op": "replace", "old": "夜里十点，他推门进了店。", "new": "门是从里面锁着的。夜里十点，他推门进了店。"},
        ]},
        message="把开头改得更有悬念一点", focus_file_id=chapter.id,
    )

    assert payload["status"] == "success"


async def test_rewriting_an_author_edited_episode_through_create_file_is_refused(db_session, owner_project):
    """剧本项目：create_file 复用同名剧集后 <file> 会整份覆盖，作者手改过的第 3 集不复用。"""
    user, project = owner_project
    project.project_type = "screenplay"
    folder = File(id=f"{project.id}-script-folder", project_id=project.id, title="剧本", file_type="folder")
    db_session.add_all([project, folder])
    db_session.commit()
    episode = File(
        project_id=project.id, parent_id=folder.id, title="第3集", file_type="script", content=AI_CH3, order=3
    )
    db_session.add(episode)
    db_session.flush()
    FileVersionService().create_version(
        db_session, episode.id, AI_CH3, change_type="create", change_source="ai", commit=False
    )
    db_session.commit()
    _author_saves(db_session, user, episode, AUTHOR_CH3)
    args = {"title": "第3集", "file_type": "script", "content": "", "parent_id": folder.id}

    refused = await _run(mcp_tools.create_file, db_session, user, project, args, message="继续写下一集")

    assert refused["status"] == "error"
    assert refused["error_type"] == AUTHOR_EDIT_PROTECTED_ERROR
    assert "<file>" in refused["error"]
    # 作者点名要重写第 3 集时照常复用。
    allowed = await _run(mcp_tools.create_file, db_session, user, project, args, message="第3集重写一下")
    assert allowed["status"] == "success"
    assert allowed["data"]["reused_existing"] is True


async def test_recursive_folder_delete_keeps_author_edited_chapters(db_session, owner_project):
    user, project = owner_project
    folder = File(project_id=project.id, title="正文", file_type="folder")
    db_session.add(folder)
    db_session.commit()
    chapter = _ai_chapter(db_session, project)
    chapter.parent_id = folder.id
    db_session.add(chapter)
    db_session.commit()
    _author_saves(db_session, user, chapter, AUTHOR_CH3)

    payload = await _run(
        mcp_tools.delete_file, db_session, user, project, {"id": folder.id, "recursive": True},
        message="继续写下一章",
    )

    assert payload["error_type"] == AUTHOR_EDIT_PROTECTED_ERROR
    db_session.expire_all()
    assert db_session.get(File, chapter.id).is_deleted is False
    assert db_session.get(File, folder.id).is_deleted is False

    # 只提到文件夹名的改动要求（「正文改紧凑一点」）不是要删它，里面的章节照样保住。
    edit_request = await _run(
        mcp_tools.delete_file, db_session, user, project, {"id": folder.id, "recursive": True},
        message="正文改紧凑一点",
    )
    assert edit_request["error_type"] == AUTHOR_EDIT_PROTECTED_ERROR
    db_session.expire_all()
    assert db_session.get(File, chapter.id).is_deleted is False

    # 作者明说删这个文件夹时照常删。
    allowed = await _run(
        mcp_tools.delete_file, db_session, user, project, {"id": folder.id, "recursive": True},
        message="把正文文件夹删了，我要重新开始",
    )
    assert allowed["status"] == "success"
    db_session.expire_all()
    assert db_session.get(File, chapter.id).is_deleted is True


# --------------------------------------------- 回答上一轮 AI 对这个文件的提议（I14）
#
# 线上：AI 自己提出「按这个改，我直接写进第四节」，作者回「好的，继续」「两件都做」
# 「按新来历修改」仍被拦，AI 只能让作者照抄一句口令。上一轮 AI 的提议原文在历史里，
# 守卫据此判断作者答应 / 选中的那一项是不是改这个文件。以下文本都是构造的。

_OFFER_CH4 = (
    "《第四节 码头夜谈》写好了，我再通读核对一遍。第四节是你手动改过的，我没有直接动它。\n\n"
    "我准备的改法：把「货早就出不去了」那一句换成两处能对上的硬伤，第六节翻盘时正好用上。\n\n"
    "- 按这个改（冷库停电＋大客户转单），我直接写进第四节。\n"
    "- 换一种：改成海关扣货、合伙人跑路，方向类似。\n"
    "- 第四节先不动，等写到第六节再回头补。"
)
_OFFER_OUTLINE_OR_CH2 = (
    "第一章、第三章的口径都改好了。\n\n"
    "《总纲与前十章细纲》是你手动改过的，我没有动。里面还有三处是旧说法。\n"
    "要改这个文件得你点头，你说一声我就动。\n\n"
    "请挑一个：\n"
    "1. 大纲那三处按新身份改掉（核心冲突、第五卷、第九章细纲）\n"
    "2. 先把第二章和第一章重复的那段压掉\n"
    "3. 两件都做"
)
_OFFER_OUTLINE_LABELS = (
    "大纲是你手动改过的文件，我没有动它。大纲里还有三处旧说法，要不要一起改？\n\n"
    "请挑一个：\n"
    "1. 大纲那三处按新身份改掉，正文那三处也一起理顺\n"
    "2. 只改大纲那三处，正文先留着\n"
    "3. 都先不动，我接着往下写"
)
_OFFER_OTHER_CHAPTER = "第3章是你手动改过的，我没动它：那里摊主叫老秦，第2章写的是老周，要把第2章也改成老秦吗？"
_OFFER_ONE_LINE = "核心大纲第七行和新结局对不上。要不要我把大纲那一行同步改成新落点？你说改我就改，不改就留着。"
_OFFER_DECLINE_FIRST = "第四节是你手动改过的。\n\n- 第四节先不动，以后再说\n- 按这个改第四节，把那句换成冷库停电"
_OFFER_NEXT_STEPS = "第3章写好了。\n\n接下来你可以：\n1. 把第3章开头改紧凑一点\n2. 继续写第4章"
# AI 交代这一轮做了什么（「第四节是你手动改过的，我没动它」）不是提议改第四节。
_REPORT_BULLETS_THEN_QUESTION = (
    "第五节写好了。\n\n"
    "- **第四节**：是你手动改过的，我没动它\n"
    "- **第五节**：按细纲写完了，结尾留了钩子\n\n"
    "要不要继续写第六节？"
)
_REPORT_INLINE_QUESTION = "第五节写好了。第四节是你手动改过的，要我继续吗？"
_REPORT_RUN_WITH_OFFER = (
    "这轮做了：\n- 第四节：你手动改过，我没动\n- 第五节写完了\n需要的话我可以接着写第六节。"
)
# 改第四节和「继续写第五节」并列时，「继续」选的是接着写。
_OFFER_EDIT_OR_CONTINUE = "要不要我把第四节结尾改紧凑一点？还是继续写第五节？"
_OFFER_ONE_QUESTION_CH4 = "要不要我把第四节结尾改紧凑一点？"

_CH4 = {"file_id": "ch4", "title": "第四节 码头夜谈", "file_type": "draft"}
_CH6 = {"file_id": "ch6", "title": "第六节 翻盘", "file_type": "draft"}
_OUTLINE = {"file_id": "o1", "title": "总纲与前十章细纲", "file_type": "outline"}
_CH2 = {"file_id": "c2", "title": "第二章 雪夜", "file_type": "draft"}
_CH9 = {"file_id": "c9", "title": "第九章 勋章", "file_type": "draft"}
_CH3 = {"file_id": "ch3", "title": "第3章 三十年", "file_type": "draft"}
_CH2_NUM = {"file_id": "ch2", "title": "第2章 夜市", "file_type": "draft"}


class TestReplyToThePreviousOffer:
    @pytest.mark.parametrize(
        ("offer", "reply", "file", "unlocked"),
        [
            # AI 提议改第四节、作者答应：第一项（推荐项）就是改第四节。
            (_OFFER_CH4, "好的，继续", _CH4, True),
            (_OFFER_CH4, "可以", _CH4, True),
            (_OFFER_CH4, "按这个改", _CH4, True),
            (_OFFER_CH4, "1", _CH4, True),
            (_OFFER_CH4, "选第一个", _CH4, True),
            # 选了「先不动」、说了不改、或者答应之外又提了别的事：不放开。
            (_OFFER_CH4, "3", _CH4, False),
            (_OFFER_CH4, "第四节先不动", _CH4, False),
            (_OFFER_CH4, "好，继续写第五节", _CH4, False),
            # 提议改的是第四节：第六节（只在提议里被提到）不跟着放开。
            (_OFFER_CH4, "好的，继续", _CH6, False),
            # 选项：1 改大纲，2 改第二章，3 两件都做。
            (_OFFER_OUTLINE_OR_CH2, "两件都做", _OUTLINE, True),
            (_OFFER_OUTLINE_OR_CH2, "两件都做", _CH2, True),
            (_OFFER_OUTLINE_OR_CH2, "3", _OUTLINE, True),
            (_OFFER_OUTLINE_OR_CH2, "1", _OUTLINE, True),
            (_OFFER_OUTLINE_OR_CH2, "1", _CH2, False),
            (_OFFER_OUTLINE_OR_CH2, "2", _OUTLINE, False),
            # 只答「好」：按第一项（改大纲），不放开第二章。
            (_OFFER_OUTLINE_OR_CH2, "好", _OUTLINE, True),
            (_OFFER_OUTLINE_OR_CH2, "好", _CH2, False),
            # 「第九章细纲」是大纲里的一段，不是第九章正文。
            (_OFFER_OUTLINE_OR_CH2, "1", _CH9, False),
            # 作者复述了某一项的说法（「按新身份」只出现在第 1 项里）。
            (_OFFER_OUTLINE_LABELS, "按新身份修改，改完再把1-10章里冲突的地方重写", _OUTLINE, True),
            (_OFFER_OUTLINE_LABELS, "都先不动", _OUTLINE, False),
            # AI 问的是「要把第2章也改成老秦吗？」：「好 / 可以」答应的是第2章，不放开第3章。
            (_OFFER_OTHER_CHAPTER, "好", _CH3, False),
            (_OFFER_OTHER_CHAPTER, "可以", _CH3, False),
            (_OFFER_OTHER_CHAPTER, "可以", _CH2_NUM, True),
            # 一句话的提议，结尾是「你说改我就改」。
            (_OFFER_ONE_LINE, "改", _OUTLINE, True),
            (_OFFER_ONE_LINE, "不改", _OUTLINE, False),
            # 第一项是「先不动」时，「好」答应的是不动。
            (_OFFER_DECLINE_FIRST, "好", _CH4, False),
            # 作者复述了改法、却点名的是别的章：不是在选这一项。
            (_OFFER_NEXT_STEPS, "第5章的开头改紧凑一点", _CH3, False),
            (_OFFER_NEXT_STEPS, "1", _CH3, True),
            # AI 交代的是做了什么、问的是别的事：「好 / 1」不放开它说「没动」的第四节。
            (_REPORT_BULLETS_THEN_QUESTION, "好", _CH4, False),
            (_REPORT_BULLETS_THEN_QUESTION, "1", _CH4, False),
            (_REPORT_INLINE_QUESTION, "好", _CH4, False),
            (_REPORT_RUN_WITH_OFFER, "1", _CH4, False),
            (_REPORT_RUN_WITH_OFFER, "好", _CH4, False),
            # 「继续」选的是并列的「继续写第五节」，不是改第四节。
            (_OFFER_EDIT_OR_CONTINUE, "继续", _CH4, False),
            (_OFFER_EDIT_OR_CONTINUE, "好的，继续", _CH4, False),
            (_OFFER_EDIT_OR_CONTINUE, "好", _CH4, True),
            (_OFFER_EDIT_OR_CONTINUE, "改吧", _CH4, True),
            # 客套话不是答应；「继续」单独说也不算答应改（可能只是让 AI 往下写）。
            (_OFFER_ONE_QUESTION_CH4, "辛苦了", _CH4, False),
            (_OFFER_ONE_QUESTION_CH4, "谢谢", _CH4, False),
            (_OFFER_ONE_QUESTION_CH4, "麻烦了", _CH4, False),
            (_OFFER_ONE_QUESTION_CH4, "吧", _CH4, False),
            (_OFFER_ONE_QUESTION_CH4, "继续", _CH4, False),
            (_OFFER_ONE_QUESTION_CH4, "好的，谢谢", _CH4, True),
            (_OFFER_ONE_QUESTION_CH4, "可以吧", _CH4, True),
        ],
    )
    def test_assent_or_pick_unlocks_only_the_file_the_ai_offered_to_change(self, offer, reply, file, unlocked):
        scope = AuthorScope(messages=(reply,), previous_offer=previous_offer_items(offer))
        assert request_targets_file(scope, **file) is unlocked

    def test_assent_without_a_previous_offer_does_not_unlock(self):
        for reply in ("好的，继续", "好", "两件都做", "1"):
            assert request_targets_file(_scope(reply), **_CH4) is False
        # 上一轮只交代做了什么、没提议改它。
        report = previous_offer_items("《第四节 码头夜谈》写好了，1066 字，没发现需要返工的地方。")
        assert request_targets_file(AuthorScope(messages=("好",), previous_offer=report), **_CH4) is False

    def test_offer_is_read_from_the_last_assistant_reply_only(self):
        history = [
            {"role": "user", "content": "诱饵那颗雷再实一点"},
            {"role": "assistant", "content": _OFFER_CH4 + "\n\n[此前的工具操作]\n- 编辑《第四节 码头夜谈》被拒"},
            {"role": "user", "content": "好的，继续"},
        ]
        offer = previous_offer_from_history(history)
        assert request_targets_file(AuthorScope(messages=("好的，继续",), previous_offer=offer), **_CH4) is True
        later = [*history, {"role": "assistant", "content": "第五节写好了。"}]
        assert previous_offer_from_history(later) == ()

    def test_conditional_offer_counts_as_asking(self):
        assert ends_with_conditional_offer(_OFFER_ONE_LINE) is True
        assert ends_with_conditional_offer("要改的话你说一声，我就动。") is True
        assert ends_with_conditional_offer("第4章写好了。") is False


# ------------------------------- 提议没点名文件：看上一轮在谈的是哪个文件（live run 2 场景 C）
#
# 作者问「第一章开头节奏有点慢，有什么建议？先说建议，别直接改」，AI 给了几条建议，选项是
# 「1. 按上面几条整体调开头，我出改稿给你看」，没点名文件。改动前作者回「1」被拒，回「好的」
# 只因第 2 项碰巧引用了标题词才放行。以下文本按线上的形状另写。

_ASK_CH2 = "第二章中段有点拖，你有什么具体建议？先说建议，别直接动手。"
_SUGGEST_UNNAMED = (
    "拖的地方在渡口那三段：等船、回忆、再等船，读者手里没有要追的问题。\n\n"
    "1. 把等船压成一段，只留雾和铃声\n"
    "2. 回忆挪到上船以后\n\n"
    "另外雾是傍晚起的，后文又写成清早。要不要统一，你说一声。\n\n"
    "你想怎么走：\n"
    "1. 按上面几条整体调中段，我出改稿给你看\n"
    "2. 只做第一条（压缩等船），回忆先不动\n"
    "3. 先告诉我一件事：船夫和第一章的老人是同一个人吗？定了我再给方案"
)
# 收尾是「三个可选的地方」，每一项都没点名文件；文件只在开头点到。
_LEFTOVERS_UNNAMED = (
    "《第二章 夜渡》中段按那几条调过了，等船压成了一段。\n\n"
    "三个可选的地方，你定了我再动：\n"
    "1. 雾起的时辰前后还不一样，要不要统一成一种说法\n"
    "2. 结尾两句都用了「铃声」，可以把后一句改成「水声」\n"
    "3. 段首缩进有的有、有的没有，要不要统一一遍"
)
_CH2_NIGHT = {"file_id": "n2", "title": "第二章 夜渡", "file_type": "draft"}
_CH3_NIGHT = {"file_id": "n3", "title": "第三章 上岸", "file_type": "draft"}


def _unnamed_offer_scope(reply: str, history: list[dict]) -> AuthorScope:
    return AuthorScope(
        messages=(reply,),
        previous_offer=previous_offer_from_history(history),
        previous_offer_context=previous_offer_context_from_history(history),
    )


def _context_target(history: list[dict], files: list[dict], protected: set[str]) -> str | None:
    return resolve_offer_context_file(
        previous_offer_context_from_history(history),
        [(item["file_id"], item["title"], item["file_type"]) for item in files],
        lambda file_id: file_id in protected,
    )


class TestUnnamedOfferResolvesFromContext:
    _HISTORY = [
        {"role": "user", "content": _ASK_CH2},
        {"role": "assistant", "content": _SUGGEST_UNNAMED},
    ]

    @pytest.mark.parametrize(
        ("reply", "unlocked"),
        [
            ("好的，按你说的改", True),
            ("好的", True),
            ("1", True),
            ("选1", True),
            ("第一个", True),
            ("A", True),
            ("2", True),
            # 第 3 项只是问问题，不是改。
            ("3", False),
            ("先不改", False),
        ],
    )
    def test_assent_or_pick_maps_to_the_file_the_previous_turn_discussed(self, reply, unlocked):
        target = _context_target(self._HISTORY, [_CH2_NIGHT, _CH3_NIGHT], {"n2", "n3"})
        assert target == "n2"
        scope = _unnamed_offer_scope(reply, self._HISTORY)
        assert request_targets_file(scope, **_CH2_NIGHT, offer_context_file=lambda: target) is unlocked
        # 别的文件不跟着放开。
        assert request_targets_file(scope, **_CH3_NIGHT, offer_context_file=lambda: target) is False

    def test_without_the_context_an_unnamed_offer_does_not_unlock(self):
        scope = _unnamed_offer_scope("1", self._HISTORY)
        assert request_targets_file(scope, **_CH2_NIGHT) is False

    def test_leftover_options_resolve_from_the_file_named_earlier_in_the_reply(self):
        history = [
            {"role": "user", "content": "好的，按你说的改"},
            {"role": "assistant", "content": _LEFTOVERS_UNNAMED},
        ]
        target = _context_target(history, [_CH2_NIGHT, _CH3_NIGHT], {"n2"})
        assert target == "n2"
        for reply in ("好", "3", "第三个"):
            scope = _unnamed_offer_scope(reply, history)
            assert request_targets_file(scope, **_CH2_NIGHT, offer_context_file=lambda: target) is True

    def test_no_previous_offer_means_no_unlock(self):
        history = [
            {"role": "user", "content": _ASK_CH2},
            {"role": "assistant", "content": "第二章中段拖在渡口那三段，等船和回忆叠在一起了。"},
        ]
        target = _context_target(history, [_CH2_NIGHT], {"n2"})
        for reply in ("好的，按你说的改", "1"):
            scope = _unnamed_offer_scope(reply, history)
            assert request_targets_file(scope, **_CH2_NIGHT, offer_context_file=lambda: target) is False

    def test_an_offer_naming_another_file_does_not_unlock_this_one(self):
        history = [
            {"role": "user", "content": _ASK_CH2},
            {"role": "assistant", "content": "第二章中段拖。\n\n1. 把第三章开头压一压，第二章先不动\n2. 继续写第四章"},
        ]
        target = _context_target(history, [_CH2_NIGHT, _CH3_NIGHT], {"n2"})
        for reply in ("1", "好"):
            scope = _unnamed_offer_scope(reply, history)
            assert request_targets_file(scope, **_CH2_NIGHT, offer_context_file=lambda: target) is False

    def test_two_protected_files_in_the_context_are_ambiguous(self):
        history = [
            {"role": "user", "content": "第二章和第三章都有点拖，有什么建议？"},
            {"role": "assistant", "content": _SUGGEST_UNNAMED},
        ]
        assert _context_target(history, [_CH2_NIGHT, _CH3_NIGHT], {"n2", "n3"}) is None
        # 只有一个是作者手改过的：改的就是它（另一个本来就能改）。
        assert _context_target(history, [_CH2_NIGHT, _CH3_NIGHT], {"n2"}) == "n2"
        # 「其他章」也不猜。
        others = [{"role": "user", "content": _ASK_CH2}, {"role": "assistant", "content": "其他章也有同样的问题。要不要统一一下？"}]
        assert _context_target(others, [_CH2_NIGHT], {"n2"}) is None

    def test_a_file_the_ai_said_it_left_alone_is_not_the_one_being_discussed(self):
        # 守卫拒绝后 AI 用的固定说法：作者手改过的第3章只是被交代「没动」，问的是统一称呼。
        history = [
            {"role": "user", "content": "继续写"},
            {"role": "assistant", "content": "第3章是你手动改过的，我没动它：那里摊主叫老秦，第2章写的是老周。要不要统一一下称呼？"},
        ]
        assert _context_target(history, [_CH3, _CH2_NUM], {"ch3"}) is None
        # 作者拿它当标准的那一章也不算在谈要改它。
        standard = [
            {"role": "user", "content": "以第3章为准，看看人名哪里对不上"},
            {"role": "assistant", "content": "有两处称呼对不上。要不要统一一下？"},
        ]
        assert _context_target(standard, [_CH3], {"ch3"}) is None

    def test_context_skips_streamed_file_bodies_and_synthesized_sections(self):
        history = [
            {"role": "user", "content": "写第三章"},
            {"role": "assistant", "content": (
                "<file>第二章里那场雾……</file>\n第三章写好了。要不要把开头再压一压？"
                "\n\n[此前的工具操作]\n- 编辑《第二章 夜渡》"
            )},
        ]
        context = previous_offer_context_from_history(history)
        assert all("第二章" not in text for text in context)
        assert _context_target(history, [_CH2_NIGHT, _CH3_NIGHT], {"n2", "n3"}) == "n3"


async def test_option_number_for_an_unnamed_offer_edits_the_discussed_file(db_session, owner_project):
    """上一轮选项没点名文件、作者回「1」：改的是上一轮在谈的那个作者手改过的章节。"""
    user, project = owner_project
    chapter = _ai_chapter(db_session, project, title="第二章 夜渡", content="雾是傍晚起的。")
    _author_saves(db_session, user, chapter, "雾是傍晚起的。他等船。")
    other = _ai_chapter(db_session, project, title="第三章 上岸", content="上岸了。")
    history = [
        {"role": "user", "content": _ASK_CH2},
        {"role": "assistant", "content": _SUGGEST_UNNAMED},
    ]
    context = {
        "author_previous_offer": previous_offer_from_history(history),
        "author_previous_offer_context": previous_offer_context_from_history(history),
    }
    edit = {"id": chapter.id, "edits": [{"op": "replace", "old": "他等船。", "new": "雾里有铃声。"}]}

    payload = await _run(mcp_tools.edit_file, db_session, user, project, edit, message="1", **context)
    assert payload["status"] == "success"

    # 第三章也被作者手改过：上一轮在谈的是哪一章说不清（作者问的是第二章，AI 回复又点了
    # 第三章），不猜，照旧拒。
    db_session.expire_all()
    _author_saves(db_session, user, db_session.get(File, chapter.id), "雾里有铃声。他还在等。")
    _author_saves(db_session, user, db_session.get(File, other.id), "上岸了，天还没亮。")
    ambiguous = [
        {"role": "user", "content": _ASK_CH2},
        {"role": "assistant", "content": _SUGGEST_UNNAMED.replace("拖的地方", "第三章开头也拖，拖的地方")},
    ]
    refused = await _run(
        mcp_tools.edit_file, db_session, user, project,
        {"id": chapter.id, "edits": [{"op": "replace", "old": "他还在等。", "new": "他不等了。"}]},
        message="1",
        author_previous_offer=previous_offer_from_history(ambiguous),
        author_previous_offer_context=previous_offer_context_from_history(ambiguous),
    )
    assert refused["error_type"] == AUTHOR_EDIT_PROTECTED_ERROR


async def test_agreeing_to_the_ais_own_proposal_edits_the_author_edited_file(db_session, owner_project):
    """AI 上一轮提议改作者手改过的第四节、作者回「好的，继续」：这一轮改得了。"""
    user, project = owner_project
    chapter = _ai_chapter(db_session, project, title="第四节 码头夜谈", content="货早就出不去了。")
    _author_saves(db_session, user, chapter, "他说，货早就出不去了。")
    history = [
        {"role": "user", "content": "诱饵那颗雷再实一点"},
        {"role": "assistant", "content": _OFFER_CH4, "routing": {CONFIRM_FILE_IDS_ROUTING_KEY: [chapter.id]}},
    ]
    edit = {"id": chapter.id, "edits": [
        {"op": "replace", "old": "货早就出不去了。", "new": "冷库停电三天，最大的客户也转了单。"},
    ]}

    payload = await _run(
        mcp_tools.edit_file, db_session, user, project, edit,
        message="好的，继续",
        author_confirmed_file_ids=confirmed_file_ids_from_history(history),
        author_previous_offer=previous_offer_from_history(history),
    )

    assert payload["status"] == "success"
    db_session.expire_all()
    assert "冷库停电" in db_session.get(File, chapter.id).content

    # 作者又手改了一次；这回 AI 问的是别的章，作者回「好」：第四节照样不动。
    db_session.expire_all()
    _author_saves(db_session, user, db_session.get(File, chapter.id), "冷库停电三天，大客户也走了。")
    other = [
        {"role": "user", "content": "继续"},
        {"role": "assistant", "content": "第四节是你手动改过的，我没动它。要把第三节也改成冷库停电吗？"},
    ]
    refused = await _run(
        mcp_tools.edit_file, db_session, user, project,
        {"id": chapter.id, "edits": [{"op": "replace", "old": "冷库停电三天", "new": "冷库停电五天"}]},
        message="好",
        author_previous_offer=previous_offer_from_history(other),
    )
    assert refused["error_type"] == AUTHOR_EDIT_PROTECTED_ERROR
