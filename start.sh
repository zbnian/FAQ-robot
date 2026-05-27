#!/bin/bash
set -e

echo "FAQ 机器人启动中..."

# 启动时重建索引（如需要）
python -m src.indexer --rebuild

# 启动API服务
python main.py