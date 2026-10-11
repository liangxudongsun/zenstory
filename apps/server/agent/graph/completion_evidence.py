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


# 说「这一轮我已经改了文件 / 项目信息」的话，不是描述项目里已有的东西（I09）。
#
# 两种写法：
# - 「已 / 已经 + 动词」（已还原、已经删除、已改为）：这种写法也常用来描述现状（「第1-3章都已写好」
#   「这一设定已经记录在人物卡里」「主角名字已改为林舟」），所以只有下面两种情况才算本轮的改动：
#   分句以它开头（「好的，已还原」）或主语是我 / 这一轮（「我已经帮你保存」「这一轮已更新人物卡」）；
#   或者动词后紧跟「了」报告完成（「两处都已经删除了」）。
# - 「改好了 / 存好了 / 还原了」这类完成报告：主语是什么都算。
#
# 都不算的：同一分句里主语是你 / 作者或说的是以前（「你之前已修改的第二章」「上一轮已经写好」）、
# 紧挨着否定（「还没保存」）、作定语（「已写好的章节」）、问句（「伏笔已经补上了吗？」）。
# 「记住了 / 记下了」是应答（「好的，我记住了」），不当作改动。简体与繁体写法都收。
_CLAIM_VERBS = (
    r"还原|還原|恢复|恢復|改回|撤销|撤銷|撤回|保存|存好|存入|写入|寫入|写进|寫進|写好|寫好|录入|錄入|"
    r"记录|記錄|记下|記下|更新|修改|改好|改成|改为|改為|替换|替換|删除|刪除|删掉|刪掉|补上|補上|补好|"
    r"補好|补进|補進|加上|添加|新建|创建|創建|同步|调整|調整"
)
_CHANGE_CLAIM_RE = re.compile(
    rf"(?P<prefixed>(?:已经?|已經)(?:帮你|幫你|为你|為你|给你|給你)?(?:{_CLAIM_VERBS})(?P<le>了)?)"
    r"|(?P<done>(?:改好|存好|删好|刪好|补好|補好|还原|還原|改回)了)"
)
_CLAIM_NEGATED_RE = re.compile(r"(?:没有|沒有|没|沒|未|不|尚未|还没|還沒)\s*$")
_CLAIM_OTHER_SUBJECT_RE = re.compile(
    r"(?:(?<![帮幫为為给給替])(?:你|您)|作者|之前|上次|上一轮|上一輪|此前|先前|原来|原來|原本|以前|"
    r"昨天|上周|上週|前几轮|前幾輪|前面)"
)
_CLAUSE_BREAK_RE = re.compile(r"[，,。！？!?；;：:\n]")
_SENTENCE_END_RE = re.compile(r"[。！？!?\n]")
_LEADING_FILLER_RE = re.compile(
    r"^(?:好的?|嗯+|行|收到|没问题|沒問題|ok|okay|明白|了解)[\s～~]*", re.IGNORECASE
)
# 分句开头到「已」之间只剩主语「我 / 这一轮」和副词时，算本轮自己说的改动。
_FIRST_PERSON_CLAUSE_RE = re.compile(
    r"^(?:我们?|我們|我这边|我這邊|这一轮|這一輪|本轮|本輪|这次|這次)?"
    r"(?:刚刚|剛剛|刚才|剛才|这边|這邊|也|都|全部|全都|已经|已經)*$"
)


def _is_question(visible: str, end: int) -> bool:
    rest = visible[end:]
    stop = _SENTENCE_END_RE.search(rest)
    sentence_tail = rest[: stop.start()] if stop else rest
    if stop and stop.group(0) in "？?":
        return True
    return sentence_tail.rstrip().endswith(("吗", "嗎", "么", "麼", "呢"))


def find_unbacked_change_claim(text: str) -> str | None:
    """回复里第一句说「这一轮已经改了」的话（原文片段）；没有时返回 None。"""
    visible = author_text_outside_files(text)
    for match in _CHANGE_CLAIM_RE.finditer(visible):
        clause = _CLAUSE_BREAK_RE.split(visible[: match.start()])[-1].strip()
        if _CLAIM_NEGATED_RE.search(clause) or _CLAIM_OTHER_SUBJECT_RE.search(clause):
            continue
        if visible[match.end(): match.end() + 1] == "的":
            continue
        if _is_question(visible, match.end()):
            continue
        if match.group("prefixed") and not match.group("le"):
            subject = _LEADING_FILLER_RE.sub("", clause).strip()
            if not _FIRST_PERSON_CLAUSE_RE.match(subject):
                continue
        return match.group(0)
    return None


__all__ = [
    "author_text_outside_files",
    "ends_on_file_block",
    "find_unbacked_change_claim",
]
