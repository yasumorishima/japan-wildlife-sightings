#!/bin/bash
# Claude Code のクラウドセッション開始時に、collect.py / validate.py / build_map.py を
# 動かすのに要るものを入れる。手元の実行では何もしない。
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

# PDF の表を読む pdf / pdf_bbox アダプタが pdftotext を使う（CI と同じ poppler-utils）
if ! command -v pdftotext >/dev/null 2>&1; then
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq poppler-utils
fi

# システムの Python に入れるので毎回実行する（入っていれば数秒で終わる）
python3 -m pip install -q --root-user-action=ignore -r requirements.txt
