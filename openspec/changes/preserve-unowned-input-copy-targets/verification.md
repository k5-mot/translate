<!-- markdownlint-disable MD013 MD041 -->

## 計画段階の調査（2026-09-25）

提案のみで0/8 tasks。INPUT-COPY-001の実装、正式verify、archive、merge、pushは未実施。

### 確認した事実

- 現行runs.pyの_copy_verifiedはsource/target openの失敗もexceptで受け、target.unlink(missing_ok=True)を無条件に実行する。Mock試験でtargetのFileExistsError時に1回、source open失敗でtarget未openの場合にも1回呼ばれることを再確認した。
- 現在の製品呼出元はRunRepository.createだけ。UUIDv7 rootの排他的mkdirはcleanup用tryの前にあり、衝突した既存Runをrmtreeするコードではない。今回の調査は、通常の公開操作で利用者Fileが実際に消失したという証拠ではない。
- 既存manifest Testは入力のread_bytesを禁止するが、すべてのread APIのsizeや最大memoryを検査していない。既存先の保持とsource open失敗時cleanupのTestもない。Applyで実際の合成Fileと障害注入を追加する。
- Python 3.12.9の標準APIを調査した。copyfileはwbで開くため不可、copyfileobjは開いたstreamへ有限bufferでcopyでき、file_digestはcopy済みstreamをhash化できる。BytesIO試験でcopy内容・size・digest一致を確認した。実Fileでのfsync/copystat/cleanupの証拠はまだない。
- cleanupのOSErrorだけをcontextlib.suppressで抑止した合成試験では、元例外のidentityを維持できた。作成成功のlocal値は作成後の敵対的path置換を防がないため、完全な競合対策とは扱わない。

### 範囲と実行中処理

- 基点は`a23f074`。製品Code/Test/依存をこの提案で編集していない。既存の未コミット差分は保持し、新しい共有moduleも作らない。
- session 58094の同じlive handleを再pollして実行中を確認した。停止・再起動・モデル要求の重複起動は行っていない。この先行processは本修正も前Changeの有限設定修正も検証しない。
- common最終配置、旧UUIDv7移行、全操作の新保存形式、表内画像の曖昧時動作、Word/PDFの利用者目視は回答待ち/未解決のまま。

### 判断と次のGate

grill-with-docsに従って環境の事実を分担調査し、作成前/後の失敗・cleanupの失敗・既存API委譲を設計へ対応付けた。新しいDomain用語や不可逆なArchitecture判断がないためADR/Glossaryは追加しない。

実装開始前に提案を提示する。適用後の正式verifyは自動Testだけではなく、実translation→Word PDF→元PDFとのComparison Reviewと利用者目視が必要。提案を未実装指摘の解消と数えない。

### 文書品質検査

- OpenSpec status: mysddのproposal/specs/design/tasksが4/4完了。これは計画Artifactの存在であり、実装Taskの完了ではない。
- `openspec validate preserve-unowned-input-copy-targets --strict`: valid。
- `uv run pytest -q tests/test_documentation.py`: 21 passed（0.24秒）。
- `git diff --check`: 指摘なし。製品Code未変更の提案ターンのため、全製品Testと実機Gateは再実行していない。

## Applyと自動検証（2026-09-25）

5/8 tasks完了。計画段階の未実装状態を以下で更新する。実機Gateと正式verify・archive・merge・pushは未完了。

### 再現と修正

- 修正前の再現Testは4 failed（1.81秒）。隔離した合成targetとsource自身をtargetにした場合に、旧実装がFileExistsErrorの後でそれらを削除した。source open失敗でもtarget.unlinkを呼んだ。利用者の入力・Run・成果物は使用していない。
- 製品変更はruns.pyの既存_copy_verifiedだけ。排他的open成功後にだけlocalの作成済み印を設定し、失敗時はその場合だけ、close後にcleanupする。cleanupのOSErrorは標準contextlib.suppressにより元のcopy例外を置換させない。永続印・Task台帳・Resume判定は追加していない。
- copy/hashの独自loopを除去し、標準shutil.copyfileobjとhashlib.file_digestへ委譲した。1 MiBのcopy buffer、size取得、flush/fsync、targetのseek(0)からのhash、close後copystatを使用する。hash対象は再読したsourceではなく保存byte列である。
- 作成後の敵対的なpath置換への完全防御、新保存形式、common配置整理を解決済みとは扱わない。

### Scenarioと自動証拠

| Scenario / 契約 | Testと観測 |
| --- | --- |
| 既存targetとの衝突 | test_copy_preserves_preexisting_targetの2ケース。別Fileとsource自身の内容不変 |
| source open失敗 | test_source_open_failure_never_cleans_targetの2ケース。target既存/未作成の双方でtarget.open/unlinkなし |
| 作成後の失敗 | test_failed_copy_closes_streams_before_removing_partial_targetのread/write/flush/fsync/hash/copystat計6ケース。stream close後の実unlink、元例外identity、source不変 |
| cleanup拒否 | test_cleanup_refusal_does_not_replace_original_copy_error。残存Fileありでも元のfsync例外を通知 |
| 公開準備とmetadata非公開 | test_prepare_copy_failure_preserves_existing_data_and_publishes_no_metadataの2ケース。cleanup成功/拒否を模擬し、既存入力・Run・export不変、部分コピーのRun一覧非掲載 |
| 保存root衝突 | test_new_run_root_collision_never_cleans_existing_run。UUIDv7を固定し、既存root全Fileのbyte列不変 |
| 正常copyと標準API委譲 | test_copy_uses_bounded_stdlib_io_and_preserves_metadataの空/複数buffer入力。内容、size、SHA-256、mtime一致。実streamのread/readintoへ観測を付け、各readの正数上限、copyfileobj/file_digestへの委譲を確認 |

cleanup拒否の公開準備TestではunlinkへPermissionErrorを注入し、rmtree(ignore_errors=True)の削除不能結果をmockで模擬する。OS ACLや敵対的processを実際に変更した試験ではない。有限readの観測は対象APIの上限確認であり、OS cacheを含むprocess全体のpeak memory測定ではない。

### 品質と実行revision

- 関連manifest/Repository Test: 32 passed（1.97秒）。
- `uv run ruff check .`: 成功。`uv run ruff format --check .`: 324 files整形済み。`uv run ty check`: 成功。
- `uv run pytest -q`: **572 passed / 1 skipped**（39.47秒）。Windows上のPOSIX PTYのみskip。関数説明の文書Testを含む。
- OpenSpec strict validation: valid。`git diff --check`: 指摘なし。
- 基点commit: `bdd387ea6c7c2312c9e6ab63fb012ed0241e9f69`。製品差分はruns.py、Test差分はtest_run_input_manifest.py。SHA-256はそれぞれ`0a38006d6cae6c79cb60117bb04843e8002f455809b4819c4eef11bf6f530223`、`3600636d122602d2fe06d08f00fc1aea88722cc64b80f3a32fc6bdb0700ff2ff`。
- 全体Testは先行の未コミット差分を保持したworktreeで実行しており、HEADだけの結果ではない。今回それらを変更・stageしていない。新module/依存はなく、pyproject.toml/uv.lockの差分は0件。
- 追加Testと入れ子の観測関数には目的のdocstringを付けた。製品関数の説明は新しいcleanup境界に合わせて更新した。

### 実機と未完了事項

- session 58094の同一handleを再pollしliveを確認した。新しいTask完了・終端出力はなく、Qdrant接続警告が追加された。停止・再起動・重複Model要求はしていない。
- この先行processは起動済みの旧moduleを使用しており、今回のcopy修正を含む実機証拠ではない。source編集と既存processの検証revisionを区別する。
- tasks 3.1〜3.3は未完了。先行実行後、新Codeのtranslation→Word PDF→Comparison Reviewと利用者目視が必要。INPUT-COPY-001の実装・自動回帰は是正済みだが、最終解決判定は保留する。

### 新規Runによる実入力保存の確認（2026-09-25）

先行session 58094のTRANSLATE接続Errorによる終了コード1を確認し、現在の短い生成要求の成功後、最新848296eのprocessで新規Run `01a0d520-15a4-74a2-9eaf-afafa726a03a`（session 3343）を開始した。既存RunのResumeではコピーが再実行されないため、このGateでは新規保存経路を通している。失敗Runは保全した。

実sample3.pdfの新しい保存copyは5,284,914 bytes、SHA-256 `5ccb472e2b072a83713814d13ceb303957b1a9b3dcb2740fe1bf55d95d79b34f`で、入力とmetadataのhash/sizeに一致した。SPLIT〜LOADは完了しているが、最終DOCXと終了状態は未取得のためtask 3.1は未完了。[実機記録](../sanitize-workflow-checkpoint-errors/verification.md)に診断・実行設定・dirty Codeの範囲を集約した。Word PDF・Comparison Review・利用者目視もまだ完了していない。
