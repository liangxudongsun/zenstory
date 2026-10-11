"""
项目备注（AI 记忆里的 notes 字段）的来源分区。

notes 仍是一段纯文本（AI 记忆面板里的一个文本框，不需要改表或迁移数据），
用两行固定标题把它分成三块：

    <没有标题的条目>            未标来源：作者在面板里直接写的，或本规则之前记下的
    【作者确认】
    <条目>                     作者在对话里说过、update_project 核对过作者原话的约定
    【AI 提议·待作者确认】
    <条目>                     AI 提出或推断、作者还没同意的内容

写入（agent 的 update_project）由 :func:`merge_project_notes` 决定每条进哪一块：
已在「作者确认」里的照旧；新条目只有附上作者本轮的原话（逐字出现在作者消息里）
才进「作者确认」，否则记成 AI 提议。注入上下文时 :func:`split_project_notes`
把三块分开渲染，AI 提议不会被当成定论。作者在面板里怎么改都行，解析只认这两行标题。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CONFIRMED_HEADER = "【作者确认】"
PROPOSALS_HEADER = "【AI 提议·待作者确认】"

_CONFIRMED_HEADER_RE = re.compile(r"^\s*【\s*作者(?:已)?确认\s*】\s*$")
_PROPOSALS_HEADER_RE = re.compile(r"^\s*【\s*AI\s*提议[^】]*】\s*$", re.IGNORECASE)

# 一行里用分号隔开的多条约定，按条比较（「A；B」与「A」「B」是同两条）
_ENTRY_SPLIT_RE = re.compile(r"[；;]")
# 行首的列表符号 / 序号
_BULLET_RE = re.compile(r"^\s*(?:[-*•·]+|\d+[.、)）]|[（(]\d+[)）])\s*")
# 模型自己给条目贴的来源标签（来源由分区表达，条目里的自称不算数）
_SELF_LABEL_RE = re.compile(
    r"[【\[（(]\s*(?:作者)?(?:已)?(?:确认|定|拍板)(?:设定|的?事实)?\s*[】\]）)]"
)
# 比较 / 核对原话时忽略的空白与标点
_IGNORABLE_RE = re.compile(r"[\s　，,。.！!？?；;：:、\"'“”‘’「」『』《》〈〉（）()【】\[\]…—\-~～·]+")

_MIN_QUOTE_CHARS = 2


@dataclass
class ProjectNotesSections:
    """notes 按来源拆开后的三块，每块是若干行文本。"""

    unlabeled: list[str] = field(default_factory=list)
    confirmed: list[str] = field(default_factory=list)
    proposals: list[str] = field(default_factory=list)


@dataclass
class ProjectNotesMerge:
    """merge_project_notes 的结果。"""

    text: str
    # 作为「作者确认」传进来、但找不到作者原话依据，改记成 AI 提议的条目
    downgraded: list[str] = field(default_factory=list)
    # 这次新记进「作者确认」的条目
    confirmed_added: list[str] = field(default_factory=list)


def split_project_notes(notes: str | None) -> ProjectNotesSections:
    """按两行固定标题把 notes 拆成 未标来源 / 作者确认 / AI 提议 三块（空行丢掉）。"""
    sections = ProjectNotesSections()
    current = sections.unlabeled
    for raw_line in (notes or "").splitlines():
        if _CONFIRMED_HEADER_RE.match(raw_line):
            current = sections.confirmed
            continue
        if _PROPOSALS_HEADER_RE.match(raw_line):
            current = sections.proposals
            continue
        line = raw_line.rstrip()
        if line.strip():
            current.append(line)
    return sections


def compose_project_notes(sections: ProjectNotesSections) -> str:
    """把三块拼回一段文本；空块不写标题。"""
    blocks: list[str] = []
    if sections.unlabeled:
        blocks.append("\n".join(sections.unlabeled))
    if sections.confirmed:
        blocks.append("\n".join([CONFIRMED_HEADER, *sections.confirmed]))
    if sections.proposals:
        blocks.append("\n".join([PROPOSALS_HEADER, *sections.proposals]))
    return "\n\n".join(blocks)


def _normalize(text: str) -> str:
    return _IGNORABLE_RE.sub("", text or "").lower()


def _entry_key(entry: str) -> str:
    return _normalize(_SELF_LABEL_RE.sub("", _BULLET_RE.sub("", entry)))


def _split_line(line: str) -> tuple[str, list[str]]:
    """一行拆成若干条；返回 (拼回用的分隔符, 条目)。"""
    separator = "；" if "；" in line or ";" not in line else ";"
    parts = [part.strip() for part in _ENTRY_SPLIT_RE.split(line)]
    return separator, [part for part in parts if _entry_key(part)]


def _keys_of(lines: list[str]) -> set[str]:
    keys: set[str] = set()
    for line in lines:
        _, entries = _split_line(line)
        keys.update(_entry_key(entry) for entry in entries)
    return keys


def verified_author_quotes(quotes: list[str] | None, author_messages: list[str]) -> list[str]:
    """留下逐字出现在作者消息里的原话（忽略空白和标点，至少 2 个字）。"""
    normalized_messages = [_normalize(message) for message in author_messages if message]
    verified: list[str] = []
    for quote in quotes or []:
        if not isinstance(quote, str):
            continue
        key = _normalize(quote)
        if len(key) < _MIN_QUOTE_CHARS:
            continue
        if any(key in message for message in normalized_messages):
            verified.append(quote.strip())
    return verified


def _clean_entry(entry: str) -> str:
    """去掉模型自己贴的「已定 / 作者确认」标签，留下条目本身。"""
    cleaned = _SELF_LABEL_RE.sub("", entry).strip()
    return cleaned or entry.strip()


def merge_project_notes(
    existing: str | None,
    *,
    notes: str | None,
    proposals: str | None,
    author_quotes: list[str] | None,
    author_messages: list[str] | None,
) -> ProjectNotesMerge:
    """按来源合并 update_project 传来的 notes / proposals，返回要存的整段文本。

    - ``notes`` 是要保留的全部约定（整体替换，和以前一样：没传回来的旧条目视为删除）。
      其中已在「作者确认」或「未标来源」里的条目原样留在原来那块；
      其余条目（新条目、或把 AI 提议改记成约定）要有作者原话支撑：``author_quotes``
      里至少有一句逐字出现在 ``author_messages`` 里，才进「作者确认」，否则记成 AI 提议。
    - ``proposals`` 是 AI 提议块的全部内容（整体替换）；不传时保留原有提议。
      已经进了「作者确认」的条目从提议里去掉。
    - ``notes`` 传空串且没传 ``proposals``：整个字段清空（和以前一样）。
    - ``author_messages`` 为 None 表示拿不到作者原话（不是应用内对话），不做核对，
      新条目和以前一样记成未标来源的文本（不贴「作者确认」）。
    """
    if notes is not None and not notes.strip() and proposals is None:
        # 清空备注：和以前一样整个字段清空（含 AI 提议）
        return ProjectNotesMerge(text="")

    current = split_project_notes(existing)
    unlabeled_keys = _keys_of(current.unlabeled)
    confirmed_keys = _keys_of(current.confirmed)

    # 拿不到作者原话时不核对，也不贴「作者确认」：新条目和以前一样记成未标来源的文本
    unverifiable = author_messages is None
    can_confirm = not unverifiable and bool(
        verified_author_quotes(author_quotes, author_messages or [])
    )

    result = ProjectNotesSections()
    downgraded: list[str] = []
    confirmed_added: list[str] = []

    if notes is None:
        result.unlabeled = list(current.unlabeled)
        result.confirmed = list(current.confirmed)
    else:
        incoming = split_project_notes(notes)
        # 传进来的 notes 里若带着 AI 提议块（照抄了上下文），那部分按提议处理
        incoming_lines = [*incoming.unlabeled, *incoming.confirmed]
        for line in incoming_lines:
            separator, entries = _split_line(line)
            kept_unlabeled: list[str] = []
            kept_confirmed: list[str] = []
            for raw_entry in entries:
                entry = _clean_entry(raw_entry)
                key = _entry_key(entry)
                if key in confirmed_keys:
                    kept_confirmed.append(entry)
                elif key in unlabeled_keys or unverifiable:
                    kept_unlabeled.append(entry)
                elif can_confirm:
                    kept_confirmed.append(entry)
                    confirmed_added.append(entry)
                else:
                    downgraded.append(entry)
            if kept_unlabeled:
                result.unlabeled.append(separator.join(kept_unlabeled))
            if kept_confirmed:
                result.confirmed.append(separator.join(kept_confirmed))
        if incoming.proposals and proposals is None:
            proposals = "\n".join(incoming.proposals)

    if proposals is None:
        proposal_lines = list(current.proposals)
    else:
        # 传进来的提议不管带没带标题，整段都是提议
        given = split_project_notes(proposals)
        proposal_lines = [*given.unlabeled, *given.confirmed, *given.proposals]
    proposal_lines.extend(downgraded)

    settled_keys = _keys_of(result.unlabeled) | _keys_of(result.confirmed)
    seen: set[str] = set()
    for line in proposal_lines:
        separator, entries = _split_line(line)
        kept: list[str] = []
        for entry in entries:
            key = _entry_key(entry)
            if key in settled_keys or key in seen:
                continue
            seen.add(key)
            kept.append(entry)
        if kept:
            result.proposals.append(separator.join(kept))

    return ProjectNotesMerge(
        text=compose_project_notes(result),
        downgraded=downgraded,
        confirmed_added=confirmed_added,
    )
