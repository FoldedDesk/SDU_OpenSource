#!/bin/zsh
set -e # 启动失败时停止，保留终端中的错误信息。
cd -- "$(dirname -- "$0")" # 双击启动时也切换到项目根目录。
if [[ ! -x .venv/bin/python ]]; then # 首次启动时准备项目依赖。
  uv sync --locked # 使用已经锁定的运行与测试依赖。
fi # 依赖准备结束。
print '正在启动退货协同 Demo；请打开下方 Uvicorn 日志中的 http 地址。' # 提示正确访问入口。
print '请保持此终端窗口运行，按 Ctrl+C 停止服务。' # 避免关闭终端后误以为页面仍可读取接口。
exec .venv/bin/python -m app # 监听地址与端口仍由 config.yaml 统一配置。
