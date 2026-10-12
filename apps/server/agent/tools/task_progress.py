"""任务计划板的任务与实际产物的对照（按「第 N 章 / 集 / 卷」编号）。

任务板上的任务是模型按计划写的（「撰写第2-5集剧本」「第一卷正文（第1-119章）」），
状态是否属实要看项目里是不是真有对应的文件。这里只做两件事：

- 从任务文本里取出它要交付的编号范围（单位 + 编号集合）；
- 从文件标题里取出已经存在的编号。

writing_graph 收尾时据此判断 in_progress 任务能不能标为 done（只完成一部分时保持
in_progress 并写明已写 / 待写），update_project 在模型自己标 done 时据此提醒缺了哪些。
取不到编号的任务不在这里判断。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from utils.title_sequence import parse_chinese_number

_UNITS = "章集回幕卷节话"
_NUMBER = r"\d+|[零〇一二两三四五六七八九十百千]+"
_RANGE_SEP = r"[-–—~～至到]"
# 「第2-5集」「第二至第五集」「第2集-第5集」
_RANGE_RE = re.compile(
    rf"第\s*({_NUMBER})\s*([{_UNITS}])?\s*{_RANGE_SEP}\s*第?\s*({_NUMBER})\s*([{_UNITS}])"
)
# 「卷二到卷五」「卷2-5」
_PREFIX_RANGE_RE = re.compile(
    rf"(卷)\s*({_NUMBER})\s*{_RANGE_SEP}\s*卷?\s*({_NUMBER})"
)
# 「第3章」「第十二集」
_SINGLE_RE = re.compile(rf"第\s*({_NUMBER})\s*([{_UNITS}])")
# 「卷二」「卷 3」（卷名常写成「卷二：xxx」）
_PREFIX_SINGLE_RE = re.compile(rf"(卷)\s*({_NUMBER})(?![{_UNITS}])")
# 一个任务的范围过大时（模型把整本书写成一个任务）照样按编号核对，只是不再展开超过这个数。
_MAX_RANGE_SPAN = 2000


def _to_int(token: str) -> int | None:
    token = (token or "").strip()
    if not token:
        return None
    if token.isdigit():
        value = int(token)
        return value if value > 0 else None
    return parse_chinese_number(token.replace("两", "二").replace("〇", "零"))


def _expand(start: int | None, end: int | None) -> set[int]:
    if start is None or end is None or end < start or end - start > _MAX_RANGE_SPAN:
        return set()
    return set(range(start, end + 1))


def _ranges(text: str) -> dict[str, set[int]]:
    found: dict[str, set[int]] = {}
    for match in _RANGE_RE.finditer(text):
        first_unit = match.group(2)
        unit = match.group(4)
        if first_unit and first_unit != unit:
            continue
        numbers = _expand(_to_int(match.group(1)), _to_int(match.group(3)))
        if numbers:
            found.setdefault(unit, set()).update(numbers)
    for match in _PREFIX_RANGE_RE.finditer(text):
        numbers = _expand(_to_int(match.group(2)), _to_int(match.group(3)))
        if numbers:
            found.setdefault("卷", set()).update(numbers)
    return found


def _singles(text: str) -> dict[str, set[int]]:
    found: dict[str, set[int]] = {}
    for match in _SINGLE_RE.finditer(text):
        number = _to_int(match.group(1))
        if number:
            found.setdefault(match.group(2), set()).add(number)
    for match in _PREFIX_SINGLE_RE.finditer(text):
        number = _to_int(match.group(2))
        if number:
            found.setdefault("卷", set()).add(number)
    return found


@dataclass(frozen=True)
class UnitSpec:
    """任务要交付的编号：单位（章 / 集 / 卷…）+ 编号集合。"""

    unit: str
    numbers: frozenset[int]


def task_unit_spec(text: str) -> UnitSpec | None:
    """任务文本要交付的编号范围；取不到时返回 None。

    有范围（「第2-5集」）时只看范围，不看同一句里的单个编号（「第一卷正文（第1-119章）」
    要的是第 1–119 章，不是第一卷这个文件）；几种单位都有时取编号最多的那种。
    """
    text = text or ""
    found = _ranges(text) or _singles(text)
    if not found:
        return None
    unit, numbers = max(found.items(), key=lambda item: len(item[1]))
    return UnitSpec(unit=unit, numbers=frozenset(numbers))


def title_units(titles: list[str], unit: str) -> set[int]:
    """这些文件标题里出现的某一单位的编号（含标题里的范围，如「第1-10章大纲」）。"""
    numbers: set[int] = set()
    for title in titles:
        text = title or ""
        numbers.update(_ranges(text).get(unit, set()))
        numbers.update(_singles(text).get(unit, set()))
    return numbers


def format_units(numbers: set[int] | frozenset[int] | list[int], unit: str) -> str:
    """把编号写成「第2集」「第3–5集」「第2、4–6集」。"""
    ordered = sorted(set(numbers))
    if not ordered:
        return ""
    spans: list[str] = []
    start = previous = ordered[0]
    for number in ordered[1:]:
        if number == previous + 1:
            previous = number
            continue
        spans.append(f"{start}–{previous}" if previous > start else str(start))
        start = previous = number
    spans.append(f"{start}–{previous}" if previous > start else str(start))
    return f"第{'、'.join(spans)}{unit}"


def task_text(task: dict) -> str:
    """任务里用来判断交付范围的文字：任务描述 + 产出物。"""
    parts = [str(task.get("task") or ""), str(task.get("artifact") or "")]
    return " ".join(part for part in parts if part.strip())


__all__ = [
    "UnitSpec",
    "format_units",
    "task_text",
    "task_unit_spec",
    "title_units",
]
