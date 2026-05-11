"""Markdown 论文 → docx 转换器。一次性工具，用于学校提交格式转换。

用法: uv run python scripts/md2docx.py [-i input.md] [-o output.docx]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from docx.shared import Cm, Pt

# ── 格式化常量（顶部集中可调） ─────────────────────────────────

# 字体
FONT_BODY = "宋体"
FONT_HEADING = "黑体"
FONT_CODE = "Courier New"

# 字号（磅）
SIZE_H1 = Pt(18)    # 二号
SIZE_H2 = Pt(16)    # 三号
SIZE_H3 = Pt(15)    # 小三
SIZE_H4 = Pt(14)    # 四号
SIZE_BODY = Pt(12)  # 小四
SIZE_CODE = Pt(10)  # 五号
SIZE_REF = Pt(9)    # 小五（参考文献）
SIZE_TOC = Pt(12)   # 目录正文

# 段落
LINE_SPACING = 1.5
FIRST_LINE_INDENT = Cm(0.85)  # 12pt 宋体约 2 字符

# 页面边距
MARGIN_TOP = Cm(2.54)
MARGIN_BOTTOM = Cm(2.54)
MARGIN_LEFT = Cm(3.17)
MARGIN_RIGHT = Cm(3.17)

# mermaid
MERMAID_API = "https://mermaid.ink/img/"
MERMAID_TIMEOUT = 10  # 秒
MERMAID_CACHE_DIR = Path("archive/mermaid")

# 默认路径
DEFAULT_INPUT = Path("archive/定稿-20260511.md")
DEFAULT_OUTPUT = Path("archive/定稿-20260511.docx")


def parse(filepath: Path) -> list[dict]:
    """解析 markdown 文件为 token 字典列表。"""
    from markdown_it import MarkdownIt

    md = MarkdownIt()
    try:
        tokens = md.parse(filepath.read_text(encoding="utf-8"))
    except Exception as e:
        sys.exit(f"markdown 解析失败: {e}")

    result: list[dict] = []
    for t in tokens:
        d: dict = {"type": t.type, "tag": t.tag, "content": t.content}
        if t.attrs:
            d["attrs"] = dict(t.attrs)
        if t.children:
            d["children"] = [
                {"type": c.type, "content": c.content} for c in t.children
            ]
        result.append(d)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Markdown 论文 → docx 转换器")
    parser.add_argument("-i", "--input", type=Path, default=DEFAULT_INPUT,
                        help="输入 markdown 文件路径")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT,
                        help="输出 docx 文件路径")
    args = parser.parse_args()

    if not args.input.exists():
        sys.exit(f"输入文件不存在: {args.input}")

    print(f"解析: {args.input}")
    tokens = parse(args.input)
    print(f"  获得 {len(tokens)} 个 token")


if __name__ == "__main__":
    main()
