"""Heading-line detection in paragraph_layout: indented headings count, prose doesn't, and a long
run of tabs or spaces is rejected in linear time (CodeQL flagged the old leading [ \t　]* pattern)."""

import time

import pytest

from agent.tools.file_ops.paragraph_layout import _is_heading_line


@pytest.mark.parametrize(
    "line",
    ["第31章 雨夜", "　　第五集", "\t第十二回：夜奔", "# 标题", "### 小节", "Chapter 3", "  episode  12 Rain"],
)
def test_heading_lines_with_or_without_indent(line):
    assert _is_heading_line(line)


@pytest.mark.parametrize("line", ["第三部电影很好看", "　　他想起第一章里的那场雨。", "#没有空格", ""])
def test_prose_is_not_a_heading(line):
    assert not _is_heading_line(line)


@pytest.mark.parametrize("pad", ["\t", " ", "　"])
def test_long_whitespace_run_is_rejected_quickly(pad):
    started = time.perf_counter()
    assert not _is_heading_line(pad * 200_000 + "x")
    assert time.perf_counter() - started < 0.5
