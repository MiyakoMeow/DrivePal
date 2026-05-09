"""消融实验命令行接口."""

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    """构建消融实验命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="DrivePal-2 消融实验")
    parser.add_argument(
        "--group",
        choices=["safety", "architecture", "personalization", "all"],
        default="all",
        help="实验组",
    )
    parser.add_argument("--synthesize-only", action="store_true", help="仅合成场景")
    parser.add_argument("--judge-only", action="store_true", help="仅重新评分")
    parser.add_argument("--data-dir", default="data/experiments")
    parser.add_argument("--seed", type=int, default=42, help="ABLATION_SEED")
    return parser


async def main(argv: list[str] | None = None) -> None:
    """消融实验主入口。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir)
    # TODO(author): 转发到各实验组，后续任务连接  # noqa: TD003, FIX002
    print(f"实验组: {args.group}, 数据目录: {data_dir}")  # noqa: T201
