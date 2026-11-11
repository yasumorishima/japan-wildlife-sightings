# CLAUDE.md

自治体が公開しているクマ・イノシシ・シカ等の出没情報を取得し、共通スキーマの
データセット（`data/`）と地図ページ（`docs/`、GitHub Pages）を作るリポジトリ。
詳しい経緯・判断は README.md にある。応答・コメント・commit メッセージは日本語で書く。

## 作業の進め方

- **変更は PR を作って main へのマージまで自分でやる**（オーナーの指示）。確認は求めなくてよい。
  マージ前に `python3 validate.py` など関係する確認を通しておく。
- **途中で止まって確認を取らずに最後まで進める**（オーナーの指示）。区切りごとに PR・マージし、次の作業へ進む。
- ただし `data/` の手動 commit、収録出典（`redistribute`）の追加・変更、ワークフローの変更のように
  公開データや自動収集に影響するものは、マージ前に内容を一言伝える。

## 構成

- `sources.json` — 出典の定義（id / adapter / params / license / 列の対応 `map`）
- `collectors/adapters.py` — 公開形式ごとの取得処理（`csv` `xlsx` `arcgis` `kml` `pdf` `pdf_bbox` `bodik`/`ckan` `ckan_shp`）
- `collectors/normalize.py` — 日付・獣種・区分・座標の正規化（日本の緯度経度範囲 `JP_LAT`/`JP_LON` もここ）
- `collectors/shapefile.py` — 点の Shapefile の読み手と、平面直角座標→緯度経度の変換（依存を増やさないため自前）
- `collectors/pdf_table.py` / `pdf_bbox.py` — PDF の表読み（`pdftotext` が要る）
- `collect.py` — 全出典を取得して `data/sightings.csv` / `summary.json` を作る（GeoJSON は履歴が膨らむので置かない）
- `validate.py` — 生成物の検算（CI でも実行）
- `build_map.py` — `docs/data/sightings.min.geojson` を作る（1 地点 1 行。日次の差分を小さく保つため）
- `build_kaggle.py` — Kaggle に上げる一式を `_kaggle/`（git 管理外）に作る。列の説明 `COLUMNS` と CSV の見出しが違うと失敗する
- `kaggle_published.py` / `kaggle/` — Kaggle の版との突き合わせと、データセットのメタデータ・説明文（`description.md`）
- `docs/` — MapLibre の地図ページ（`docs/vendor/` に同梱、外部 CDN は使わない）

## コマンド

```bash
python3 collect.py --only <source_id> --no-write  # 1 出典だけ取得して品質を見る（書き込まない）
python3 collect.py --no-write                     # 全出典を取得・確認だけ
python3 validate.py                               # 生成物の検算。変更後は必ず通す
python3 build_map.py                              # 地図用データを作り直す
python3 build_kaggle.py                           # Kaggle 用の一式を _kaggle/ に作る（上げはしない）
python3 -m http.server -d docs                    # 地図を手元で見る
```

リンタは無い。`python3 -m unittest discover -s tests`（通信なし。個人情報を伏せる規則など）と、
`validate.py`・`collect.py --only ... --no-write` が確認手段。テストの氏名は架空のものだけ使う。
依存は `requests` / `openpyxl` と `pdftotext`（poppler-utils）。クラウドセッションでは
`.claude/hooks/session-start.sh` が入れる。

## 守ること

- **`data/` と `docs/data/` は commit しない。** GitHub Actions（`.github/workflows/collect.yml`）の
  日次実行だけが書く。手元で `collect.py` を書き込みありで回した場合は、差分を戻してから commit する。
- **再配布の可否は `license.redistribute` で決まる。** true の出典だけが `data/` に入る。
  新しい出典を true にするのは、規約ページを実際に読んで `docs/licenses.md` に引用つきで根拠を書いてから。
- **取れなかった収録済み出典は前回のデータを据え置く**設計（`summary.json` の `reused_previous`）。
  前回の半分未満しか取れない回も据え置く（`collect.SHRINK_RATIO`）。`last_success_at` / `failing_since` で何日続いているかが分かる。
  1 つの公開元の失敗で収録済みデータを消さないこと。
- **個人情報に特に気をつける**（オーナーの指示）。公開元が出していても、再配布で広げない。
  - 通報者・入力者・捕獲者などの氏名や連絡先の列は `map` に入れない。
  - 個人情報について、公開の場所（README・コメント・commit メッセージ・PR・issue）に自治体名・番地・件数などの
    具体例を書かない。公開元への連絡や届出（IPA 等）の取扱いが終わる前に第三者へ開示しないため。
  - 原文を残す列（`normalize.MASKED_FIELDS`）の氏名・電話番号・メールアドレスは `normalize.mask_person` で伏せる。
    規則を足したら `tests/test_normalize.py` に架空の例を足す。新しい出典を足したら、
    `place` と `note` を実際に読んで、規則で拾えない氏名の書き方が無いか確かめ、あれば規則を足す。
  - `validate.py` は伏せ残しがあると失敗する。通すために検査を緩めない。
  - 写真・添付ファイルの列は取り込まない。
- **推測で埋めない。** 判定できない値は原文（`category_raw` など）に残す。置いた仮定は README の
  「正規化で置いた仮定」に書き出す。
- 証明書の検証は緩めない（山口県は暗号の要求だけを緩めている）。
- **スキーマ（列）を変えたら `build_kaggle.py` の `COLUMNS` も直す。** Kaggle へは日次実行だけが上げる
  （変数 `KAGGLE_PUBLISH` が true の時）。手元やクラウドセッションから Kaggle に直接上げない。
- 範囲などの定数は 1 か所に置いて読む（例: `validate.py` は `normalize.JP_LAT` を使う）。

## 実行環境による違い

石川県のカタログは海外 IP（GitHub ランナー等）から 403（凍結済み）、山梨県はタイムアウトすることがある。
一度も収録していない出典が取れないときは validate は警告に留める（`never_published`）。
**配布元が GitHub のランナーを拒否している出典は、別の経路で取りに行かない**（中継・別環境からの取得で回避しない）。
倉敷市・埼玉県の DataEye はこの理由で収録していない（2026-11-02）。
石川県のカタログ経由の 4 出典は凍結（`sources.json` の `frozen`）。取りに行かず、2026-08-29 取得分を据え置く（2026-11-11）。
クラウド環境で取れなくてもコードの不具合とは限らない。届かない出典は警告として出る。

## 現在の状態と残っている作業（2026-11-11 時点）

- **main の履歴は 2026-11-02 に書き換えた**（過去の data/ を含めて個人情報を伏せるため、force push 済み）。
  それより前の clone は `git fetch && git reset --hard origin/main` で合わせる。古い履歴を push し戻さないこと。
- **Kaggle は保留（オーナーの判断、2026-11-11）。** 公開に向けた作業・提案・設定はしない。仕組み（`build_kaggle.py`、
  ワークフローの Kaggle の手順）は残すが、変数 `KAGGLE_PUBLISH` が無い限り動かない。再開するかはオーナーが決める。
- 書き換え前の commit メッセージが、Actions の過去の実行の表示に残っている。消すのはオーナーが Actions 画面から行う。
- 規約で収録できない県（新潟・山形・静岡・宮城の令和7年度以前・福島など）は、担当課から許諾を得れば収録できる。
  問い合わせ先は docs/licenses.md。

## 出典の追加手順

1. `sources.json` にエントリを足す
2. `python3 collect.py --only <id> --no-write` で列の当たりを確認
3. 規約を読み `docs/licenses.md` に判定を書く
4. `python3 validate.py` を通す。README の表と件数も更新する
