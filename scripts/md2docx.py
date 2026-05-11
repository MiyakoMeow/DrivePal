"""Markdown 论文 → docx 转换器。一次性工具，用于学校提交格式转换。

用法: uv run python scripts/md2docx.py [-i input.md] [-o output.docx]
"""

from __future__ import annotations

import argparse
import hashlib
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
        # fence token 的 info 在 t.info 而非 attrs
        if hasattr(t, "info") and t.info:
            d["info"] = t.info
        if t.children:
            d["children"] = [
                {"type": c.type, "content": c.content} for c in t.children
            ]
        result.append(d)
    return result


def _mermaid_hash(code: str) -> str:
    """用 mermaid 代码内容的 SHA256 前 16 位作缓存文件名。"""
    return hashlib.sha256(code.encode()).hexdigest()[:16]


def render_mermaid(code: str, cache_dir: Path) -> Path | None:
    """将 mermaid 代码渲染为 PNG，缓存至 cache_dir。"""
    import json
    import zlib
    from base64 import urlsafe_b64encode

    import httpx

    payload = json.dumps({"code": code, "mermaid": '{"theme":"default"}'})
    data = zlib.compress(payload.encode(), level=9)
    encoded = urlsafe_b64encode(data).decode().rstrip("=")

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{_mermaid_hash(code)}.png"
    if cache_path.exists():
        return cache_path

    url = f"{MERMAID_API}pako:{encoded}?type=png"
    try:
        response = httpx.get(url, timeout=MERMAID_TIMEOUT)
        response.raise_for_status()
        cache_path.write_bytes(response.content)
        print(f"  [mermaid] 渲染成功 → {cache_path.name}")
        return cache_path
    except httpx.HTTPError as e:
        print(f"  [mermaid] 渲染失败: {e}", file=sys.stderr)
        return None


def preprocess_tokens(tokens: list[dict], cache_dir: Path) -> list[dict]:
    """扫描 token 流，将 mermaid fence 替换为 image token。"""
    result: list[dict] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t["type"] == "fence" and t.get("info", "").strip() == "mermaid":
            png_path = render_mermaid(t["content"], cache_dir)
            if png_path:
                # 提取紧跟图注段落的文本作 alt
                alt = ""
                peek = i + 1
                if peek < len(tokens) and tokens[peek]["type"] == "paragraph_open":
                    peek += 1
                if peek < len(tokens) and tokens[peek]["type"] == "inline":
                    next_content = tokens[peek].get("content", "")
                    if next_content.strip().startswith("**图"):
                        alt = next_content.strip().strip("*")
                result.append({"type": "image", "path": str(png_path), "alt": alt})
            else:
                result.append({
                    "type": "paragraph",
                    "content": f'[图表渲染失败，请手动处理]\n```mermaid\n{t["content"]}\n```',
                })
            i += 1
            # 跳过紧跟的图注段落
            # token 序列: paragraph_open → inline(含 **图X-X ...**) → paragraph_close
            skipped = 0
            if i < len(tokens) and tokens[i]["type"] == "paragraph_open":
                skipped += 1
                i += 1
            if i < len(tokens) and tokens[i]["type"] == "inline":
                next_content = tokens[i].get("content", "")
                if next_content.strip().startswith("**图"):
                    skipped += 1
                    i += 1
            # 跳过 paragraph_close
            if i < len(tokens) and tokens[i]["type"] == "paragraph_close":
                i += 1
            continue
        result.append(t)
        i += 1
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

    print("渲染 Mermaid 图表...")
    tokens = preprocess_tokens(tokens, MERMAID_CACHE_DIR)
    print(f"  预处理后 {len(tokens)} 个 token")


if __name__ == "__main__":
    main()
