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
