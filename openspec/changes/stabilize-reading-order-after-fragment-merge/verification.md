<!-- markdownlint-disable MD013 MD041 -->

# 検証記録

## 2026-09-27 原因調査と計画

計画時点の状態: 実装Task 0/7。POSITION-ORDER-001は未解決。Code起点は`61868de`で、この時点では製品Code/Testを変更していない。実装後の結果は後節に記載する。既存の無関係な作業差分は保持した。

grill-with-docsによる調査として、main agentは現在の実装・Testと保存済みsample3の座標統計を確認し、限定したsub-agentは最小合成fixtureと成立条件を読取り/メモリ実行で独立に確認した。main agentも両最小fixtureを再現した。外部モデル/Docling/Wordは呼び出していない。

### 原因と再現

`_reading_order`は各要素の先頭provだけから幅中央値と左端候補を得る。結合後は元要素が消えるが、元のprovは結合先に残る。再適用時にそれを統計へ含めないため、段の判定が変わる。

全要素を同一page、label=text、TOPLEFT、height=10とする3要素の合成fixture:

| 条件 | A (left, top, width) | B | C | 初回の段組統計 | 再適用時の統計 |
| --- | --- | --- | --- | --- | --- |
| 幅中央値変化 | (0, 0, 100) | (0, 12, 100) | (80, -40, 300) | median=100、許容幅60、段左端[0,80] | median=200、許容幅120、段左端[0] |
| 左端標本消失 | (20, 0, 100) | (0, 12, 100) | (70, -40, 100) | median=100、許容幅60、段左端[0,70] | median=100、許容幅60、段左端[20] |

両方で初回`[A B,C]`、二回目`[C,A B]`となった。結合件数は1→0、texts配列は不変。したがって内容の再結合ではなく段組統計の変化である。幅だけを補正する案では第二fixtureを解決できない。

### 実sample3の照合

保存済みRun `01a0d8b6-c2ab-7c92-bed9-58403a8410b3` のMERGE Artifactをメモリ上でPOSITION相当の既存処理へ渡した。元SHA-256は`989b39b390a42e5a99a94c349ab02cf18fa6f12fa7817d284b44090b4d5c70d6`で読取前後不変。

- Page 3: 代表座標の標本数11→9、許容幅281.91826492494033→137.8227311999999、段左端[53.94,419.1003288179]→[53.94,199.86,419.1003288179]。
- Page 8: 標本数10→9、許容幅113.91436634019013→107.99962991999993、段左端[53.93994,168.48,342.12]→[53.94,168.48,342.12,454.679753394]（表記の末尾桁は丸めた）。
- bodyの全prov座標を使って同じ統計を計算すると、入力と結合後でページ別の標本数・許容幅・段左端が一致した。これは母集団保全の根拠であり、まだ製品修正後の成功証拠ではない。

### 成立条件と計画境界

代表ページでprovを限定するには、結合前後で代表ページが同じことが必要。現在の末尾prov比較だけでは、先頭page1/末尾page2のAと先頭page2のBを結合できることをsub-agentが合成確認した。本文・表で代表ページの一致も検査し、不確かな候補は承認済みの保持＋警告にする。

元から複数provを持つ入力では初回の段推定も変わり得る。元からのprovと結合で増えたprovを区別する新しい保存状態は作らず、同一規則で既存出典を用いる。先頭provが不正な要素の後続bboxを代表位置へ昇格させる変更はしない。推定の安定性だけで原本の読取り順が正しいとは判断せず、実PDF Reviewと利用者目視を残す。

既存の文書構造/決定的読み順要求と、承認済みの曖昧候補保持方針の是正であり、新しい公開設定や障害時方針は選択しない。Domain用語・独立Architectureを導入しないためglossary/ADRは追加しない。旧構成の移行や旧版並存も追加しない。

### 計画の検査

- OpenSpec status: proposal/specs/design/tasks 4/4作成済み、実装準備完了。
- OpenSpec strict validation: valid。
- `uv run pytest tests/test_documentation.py -q`: 21 passed、0.32秒。
- `git diff --check`: 指摘なし。新たな製品Code/Test差分なし。既存の無関係な差分、`.agents`、入力・成果物をコミット対象から除外する。

## 2026-09-27 実装と回帰検証

起点Commit `5717405`。POSITIONと既存の二つのPOSITION Testを変更した。段組推定は代表ページの全有効provから幅と左端の両方を集計し、同一座標も別標本として保持する。要素の代表位置は先頭provのままとし、別ページのprovを統計へ混ぜない。本文・表の結合前に代表ページ一致も検査する。

### 自動Testと規約確認

- 修正前: 幅中央値/左端消失 × TOPLEFT/BOTTOMLEFTの4ケースが失敗、18 deselected、1.40秒。結合件数1→0かつtexts不変でも再適用時の順序が反転した。
- 修正後: 対象46 passed、2.34秒。実POSITION→NORMALIZE→LOADを3回繰り返し、文書・読み順の一致を検査した。同一prov重複、別ページprov、不正な追加/先頭prov、欄外、同位置、座標欠損、本文/表の代表ページ不一致を含む。
- 全体: **935 passed, 1 skipped、54.48秒**（session 43254、exit 0）。Review/登録を含む既存回帰も成功した。
- Ruff check、Ruff format（386 files）、ty、OpenSpec strict、git diff --check: 成功。
- 変更関数とTest helperに目的説明あり。既存座標変換、`statistics.median`、安定sort、BaseTaskと保存処理を再利用した。新しいDependency/Module/永続制御状態/公開設定/互換分岐は0件。reportへ本文・秘密を新たに転記せず、合成marker検査も成功した。
- この回帰検証ではLLM/Embedding/Docling/Wordへの外部要求を行っていない。

検査対象SHA-256:

- `translate/tasks/position.py`: `ced37c7eae1674a549ad9c051596443e15fffedd91aaa1fa2b2a82e3c26cb91b`
- `tests/test_position_layout.py`: `db1137cabac84499a5e01de8e3b1224c18b3b9a4953ef5b4bdda261aa6de7802`
- `tests/test_position_tables.py`: `f77bf245f6abce0d65f005af3aa66ab341ee772ffef0b7bbf7a4f34466e367ea`

### 保存済みsample3の補助検証

Run `01a0d8b6-c2ab-7c92-bed9-58403a8410b3` のMERGE JSONを読取り、所有する一時領域で実POSITION→NORMALIZE→LOADを3回実行した。元SHA-256は前後とも`989b39b390a42e5a99a94c349ab02cf18fa6f12fa7817d284b44090b4d5c70d6`。元Runを変更せず、一時領域は終了後に解放した。

- POSITIONの全JSONとLOADのDocumentは3回とも完全一致。
- 結合件数 `[23, 0, 0]`、並べ替え件数 `[3, 0, 0]`、警告件数 `[0, 0, 0]`、Block件数 `[135, 135, 135]`。
- 3回共通POSITION SHA-256: `8079f7cf1d2228f9e23846e9c1ebbb98dbd7fdbfaabf57cf06325cfa2b0312be`。
- 初回LOAD保存SHA-256: `f8394246ed3869c9540fced14e1d588448d5f47d7b109f7cdb1c89812269a57d`。

POSITION-ORDER-001の再現ケースと保存済み実データで順序反転は解消した。ただし中間Artifactの補助検証であり、新規Translation→Word PDF→Reviewの成功や原本に対する読み順の正しさを意味しない。Taskは**5/7**、実E2Eと利用者目視・正式verify/archive/供給は未完了に維持する。
