<!-- markdownlint-disable MD013 MD041 -->

## 1. 入力コピーの是正

- [x] 1.1 tests/test_run_input_manifest.pyへ既存の合成targetを使う衝突Testとsource open失敗Testを追加し、修正前の失敗を記録する。既存targetのbyte列不変と未作成先へのunlink未実行を確認する（Q-REL/Q-SEC）
- [x] 1.2 _copy_verifiedで排他的作成成功後だけcleanupを許可し、独自copy/hashループをshutil.copyfileobj/hashlib.file_digestへ委譲する。既存target保全、空File/複数buffer入力の内容・size・SHA-256、有限read、metadata維持のTestを通す。新module/Dependency/独自stream wrapperを追加しない（Q-MNT/Q-PERF）
- [x] 1.3 read/write/flush/fsync/hash/copystatの障害とcleanup拒否を注入し、Fileを閉じてから後始末すること、元例外維持、source不変、不完全コピーを成功扱いしないことを検証する（Q-REL/Q-SEC/Q-PORT）

## 2. 公開経路と品質

- [x] 2.1 prepare_run/RunRepository.createでコピー失敗時のmetadata未公開と既存Run・元入力・外部成果物の不変をTestする。固定UUIDv7によるroot衝突で既存Runを削除しないことも確認する
- [x] 2.2 Ruff/Format、ty、全pytest、OpenSpec strict validation、diff checkを実行し、各Scenarioの証拠、実行commit/差分、関数説明と標準API委譲の確認結果をverification.mdへ記録する

## 3. 実機受入と完了

- [ ] 3.1 先行Model processの終端をlive handleで確認してから、修正後Codeのprocessでsample3.pdfを実translationする。入力/保存copyのSHA-256とsize、所要時間、Run ID、終了状態を記録し、LLM/Embeddingを重複実行しない
- [ ] 3.2 自分で起動した非表示Microsoft Wordで生成DOCXをPDF化し、元sample3.pdfとの実Comparison Reviewを逐次実行する。成果物hash・report・終了状態を記録し、Word/PDFを利用者の目視に提示する
- [ ] 3.3 INPUT-COPY-001と全Scenarioを自動/実機証拠へ対応付けて正式verifyする。残課題がない場合だけarchiveし、PR/CI後にmainへmerge・originへpushする。旧Run移行・過去入力削除は行わず、.agents/サンプル/生成物/無関係な差分をcommitへ含めない
