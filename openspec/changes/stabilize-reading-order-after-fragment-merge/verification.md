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

## 2026-09-27 verify: 実装と仕様の照合

実装Commit `65ef610`、schema `mysdd`。全4 Artifactを読取り、OpenSpec status/apply instructionsとCode/Testを照合した。statusの`isComplete`は計画Artifactの完備を示すだけで、実装Taskの完了数は5/7である。

| 観点 | 結果 |
| --- | --- |
| Completeness | 5/7 Task。1 Requirementの実装あり。実受入・供給の2 Task未完了 |
| Correctness | 4/4 Scenarioに自動Testあり。保存済み実データの補助検証あり。新規実成果物での受入は未実施 |
| Coherence | 既存Module内の変更、同一ページprovの多重集合、代表位置の維持、既存sort/中央値の再利用を確認。新しい状態台帳や依存なし |

### RequirementとScenarioの対応

要求「断片結合後も読取り順を安定して保持する」は`translate/tasks/position.py:439`の`_reading_order`と同File`:168`の`_merge_metadata_safe`に対応する。

| Scenario | 検査対象 |
| --- | --- |
| 結合により要素幅の分布が変わる | `tests/test_position_layout.py:352` のwidth条件、両座標原点、実LOADと3回一致 |
| 結合元が段の左端位置を持つ | 同Testのleft条件。幅だけの対処では防げないケースを区別 |
| 複数ページの出典を持つ候補 | `tests/test_position_layout.py:394`/`:460`、`tests/test_position_tables.py:327`。別ページ標本の除外、本文/表の未結合と警告 |
| 欄外や同位置・欠損座標を含む文書を再処理する | `tests/test_position_layout.py:426`。Header/Footnote/Footer、同位置と欠損座標の安定順 |

### 未完了指摘と判定

- **CRITICAL V-1**: Task 3.1未完了。LLM接続を確認した後、新規推論OFF・逐次Translation→Word PDF→原本とのReviewを実行し、原本に対する内容と読み順を確認すること。保存済みArtifactの一致で代替しない。
- **CRITICAL V-2**: Task 3.2未完了。最新Word/PDFを利用者へ提示し目視確認を得た後、残件と全証拠を確認して同期/archive・PR/CI・main merge/pushを行うこと。
- 本変更のCode/設計照合で追加のWARNING/SUGGESTIONは検出していない。他ChangeのALIGN、表内画像、保存構成等の指摘を解決済みとする判定ではない。

**判定: CRITICAL 2件、archive不可。** `openspec-verify-change`の完備性基準に従い、未実施の実受入を完了扱いにせずarchive手順を停止する。verify節更新後の`tests/test_documentation.py`は21 passed（0.30秒）、OpenSpec strictとgit diff --checkは成功した。

### LLM接続の再確認（進行中）

2026-09-27 02:51:49.929696 UTC（11:51:49 JST）、既存`_model`経由で短い合成要求を1件だけ開始した。reasoning=none、thinking=disabled、output_tokens=32、設定timeout=1800秒、SDK/外側retry=0。Settingsの接続を使用し、原文・画像・Embedding要求は送っていない。並行するPython/uv processがないことを開始直前に確認した。

exec session **36205** は02:54:39 UTC時点で進行中、終了出力なし。失敗/成功はまだ判定できない。次回はこの同じsessionの終了を回収し、同じ要求を新規に重ねない。前日のHTTP 500を今回の結果とは扱わない。本文やCredentialを診断へ表示していない。
