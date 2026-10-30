#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON="$ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    echo "未找到 .venv。请先按 README「安装」一节创建虚拟环境并安装依赖。"
    exit 1
fi
cd "$ROOT"
exec "$PYTHON" "$ROOT/scripts/run.py" "$@"
