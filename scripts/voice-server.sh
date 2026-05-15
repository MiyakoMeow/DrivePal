#!/usr/bin/env bash
# 独立语音服务启动脚本
cd "$(dirname "$0")/.." || exit 1
exec uv run python -m app.voice.server "$@"
