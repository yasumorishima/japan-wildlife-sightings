#!/usr/bin/env python3
"""Kaggle の最新版が、このリポジトリで commit 済みのデータと同じかを調べる。

アップロードのたびに版のメモの末尾へ「(commit <sha>)」を書いておき、ここで突き合わせる。
食い違えば behind=true。アップロードが失敗した日も、翌日の実行で取り返せる。
データセットがまだ無ければ exists=false（ワークフローが新規作成する）。

  python3 kaggle_published.py <owner>/<dataset> <commit>

$GITHUB_OUTPUT があれば exists= と behind= を書く。
（earth-vital-signs の scripts/kaggle_published.py と同じ方式）
"""
from __future__ import annotations

import os
import re
import sys

NOTES_COMMIT = re.compile(r"\(commit ([0-9a-f]{7,40})\)")


def notes_commit(notes: str | None) -> str | None:
    m = NOTES_COMMIT.search(notes or "")
    return m.group(1) if m else None


def is_behind(published: str | None, commit: str) -> bool:
    # 短い hash と長い hash は前方一致で比べる。印の無い版は古いものとみなす
    return not published or not (commit.startswith(published) or published.startswith(commit))


def latest_notes(dataset: str) -> tuple[int, str] | None:
    """最新版の番号とメモ。データセットが無ければ None。"""
    import requests
    from kaggle.api.kaggle_api_extended import KaggleApi
    from kagglesdk.datasets.types.dataset_api_service import ApiGetDatasetRequest

    api = KaggleApi()
    api.authenticate()
    owner, slug = dataset.split("/")
    req = ApiGetDatasetRequest()
    req.owner_slug = owner
    req.dataset_slug = slug
    try:
        with api.build_kaggle_client() as kaggle:
            ds = kaggle.datasets.dataset_api_client.get_dataset(req)
    except requests.HTTPError as e:
        # 存在しないデータセットは 404 ではなく 403 が返ることがある
        if e.response is not None and e.response.status_code in (403, 404):
            return None
        raise
    versions = [v for v in (ds.versions or []) if v]
    if not versions:
        raise SystemExit(f"{dataset}: 版が返ってこない")
    v = max(versions, key=lambda v: v.version_number)
    return v.version_number, v.version_notes or ""


def main() -> None:
    dataset, commit = sys.argv[1], sys.argv[2]
    got = latest_notes(dataset)
    if got is None:
        exists, behind = False, True
        print(f"{dataset} は Kaggle にまだ無い（または見えない）")
    else:
        number, notes = got
        exists, behind = True, is_behind(notes_commit(notes), commit)
        print(f"Kaggle の版 {number}: {notes!r} / リポジトリのデータ commit {commit}")
    print(f"exists={'true' if exists else 'false'} behind={'true' if behind else 'false'}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"exists={'true' if exists else 'false'}\nbehind={'true' if behind else 'false'}\n")


if __name__ == "__main__":
    main()
