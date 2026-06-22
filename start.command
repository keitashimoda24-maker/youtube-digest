#!/bin/bash
# YouTube ダイジェスト ワンクリック起動
# ダブルクリックで: Webアプリ起動 → ブラウザで開く
cd "$(dirname "$0")"

# 既に起動済みなら二重起動しない
if ! lsof -nP -iTCP:8731 -sTCP:LISTEN >/dev/null 2>&1; then
  nohup python3 app.py > /tmp/ytdigest_web.log 2>&1 &
  sleep 2
fi

open "http://127.0.0.1:8731"
echo "📺 YouTube ダイジェストを開きました → http://127.0.0.1:8731"
echo "（このウィンドウは閉じてOKです。停止するには stop.command）"
