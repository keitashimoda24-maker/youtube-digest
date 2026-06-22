#!/bin/bash
# YouTube ダイジェスト 停止
pkill -f "youtube_digest/app.py" && echo "📺 停止しました" || echo "起動していませんでした"
