"""agent run 收尾时的两个文字信号，供 writing_graph 对照本请求的实际写入记录使用。

1. 这次 run 是不是停在一段写完的 ``<file>…</file>`` 上（``</file>`` 之后没有给作者的话）。
   流式写文件协议把正文放在回复文字里，而 openai-agents 把「不带工具调用的回复」当作
   最终输出、直接结束 run。所以写完 ``</file>`` 没有接着调用工具时，run 结束不是模型决定
   收尾，而是协议让正文这次回复成了最后一次回复：计划里没写的文件和给作者的总结都还没来得及写。
2. 回复里有没有「已还原 / 已保存 / 已改好 / 已录入」这类说本轮改了东西的话。

这里只看文字；有没有真的写入由调用方用读写台账（RepeatReadGuard）判断。
"""

from __future__ import annotations

import re

from agent.core.stream_processor import normalize_file_markers

_FILE_BLOCK_RE = re.compile(r"<file>.*?(?:</file>|\Z)", re.DOTALL)
_TASK_COMPLETE_RE = re.compile(
    r"(?:\[\s*task_complete\s*\]|[\[【]\s*任务完成\s*[\]】])", re.IGNORECASE
)


def ends_on_file_block(tail_text: str) -> bool:
    """最后一次工具调用之后的文字是不是以一段非空、已闭合的 ``<file>`` 正文结束。

    ``</file>`` 之后只剩空白、完成标记或空的 ``<file></file>`` 时也算（作者看不到任何话）。
    """
    normalized = normalize_file_markers(tail_text or "")
    close = normalized.rfind("</file>")
    if close == -1:
        return False
    after = normalized[close + len("</file>"):]
    after = after.replace("<file>", "").replace("</file>", "")
    if _TASK_COMPLETE_RE.sub("", after).strip():
        return False
    before = normalized[:close]
    start = before.rfind("<file>")
    if start == -1:
        return False
    body = before[start + len("<file>"):]
    if body.strip():
        return True
    # 最后一对是空的 <file></file>（模型闭合后又多发了一对），往前找真正写了正文的那一段。
    blocks = [
        block[len("<file>"):].removesuffix("</file>")
        for block in _FILE_BLOCK_RE.findall(before[:start])
    ]
    return any(block.strip() for block in blocks)


def author_text_outside_files(text: str) -> str:
    """回复里作者能在对话里看到的文字（去掉 ``<file>`` 正文和完成标记）。"""
    normalized = normalize_file_markers(text or "")
    outside = _FILE_BLOCK_RE.sub("", normalized)
    return _TASK_COMPLETE_RE.sub("", outside).strip()


# 说本轮已经改了文件 / 项目信息的话。同一分句里有「你 / 您 / 作者」的不算（「你之前已修改的
# 第二章」说的是作者改的），说以前的事（「上一轮已经写好」）不算，紧挨着否定的也不算（「还没保存」）。
# 简体与繁体写法都收（作者写繁体时回复也是繁体）。
_CHANGE_CLAIM_RE = re.compile(
    r"(?:已经?|已經|都)(?:帮你|幫你)?(?:还原|還原|恢复|恢復|改回|撤销|撤銷|撤回|保存|存好|存入|"
    r"写入|寫入|写进|寫進|写好|寫好|录入|錄入|记录|記錄|记下|記下|更新|修改|改好|改成|改为|改為|"
    r"替换|替換|删除|刪除|删掉|刪掉|补上|補上|补好|補好|补进|補進|加上|添加|新建|创建|創建|同步|调整|調整)"
    r"|(?:改好|存好|删好|刪好|补好|補好|记下|記下|记住|記住|还原|還原|改回)了"
)
_CLAIM_NEGATED_RE = re.compile(r"(?:没有|沒有|没|沒|未|不|尚未|还没|還沒)\s*$")
_CLAIM_OTHER_SUBJECT_RE = re.compile(
    r"(?:你|您|作者|之前|上次|上一轮|上一輪|此前|先前|原来|原來|原本|以前)"
)
_CLAUSE_BREAK_RE = re.compile(r"[，,。！？!?；;：:\n]")


def find_unbacked_change_claim(text: str) -> str | None:
    """回复里第一句说「本轮已经改了」的话（原文片段）；没有时返回 None。"""
    visible = author_text_outside_files(text)
    for match in _CHANGE_CLAIM_RE.finditer(visible):
        before = visible[: match.start()]
        clause = _CLAUSE_BREAK_RE.split(before)[-1]
        if _CLAIM_NEGATED_RE.search(clause) or _CLAIM_OTHER_SUBJECT_RE.search(clause):
            continue
        return match.group(0)
    return None


__all__ = [
    "author_text_outside_files",
    "ends_on_file_block",
    "find_unbacked_change_claim",
]
