<!-- markdownlint-disable MD013 MD041 -->

## 1. 失敗保存境界の実装

- [ ] 1.1 既存TranslationとComparison Reviewの実Graphへ本文・Credential・binary markerを含むTask例外を注入し、既定serializerのDB/pending writes/snapshotにmarkerが残るfailing-first Testを作成する。Workflow全体をdoubleへ置き換えず、失敗Taskだけを置換した再現を記録する
- [ ] 1.2 `adapters/checkpoint.py`に公開serde注入による直接例外の固定分類と接続寿命管理だけを実装し、通常例外/custom repr/dataclass例外/chain/notes/未知型名のmarker非保存、通常値の既定serializerとの往復互換性、closeをUnit Testで確認する（Q-SEC/Q-MNT）
- [ ] 1.3 両WorkflowのCheckpoint生成を新adapterへ接続し、1.1のTest成功、元例外型/既存retry回数の維持、Graph制御例外と取消の意味が変わらないことを回帰Testで確認する。共通台帳・新Dependency・common追加がないことを差分で確認する

## 2. 統合・互換性・品質Gate

- [ ] 2.1 両Workflowについて接続を閉じ再接続した障害後Resumeを試験し、失敗Taskだけが追加1回、成功済みTaskは再実行0回、通常Artifactと既存の安全な合成DBが復元可能であることを確認する（Q-REL/Q-COMP）
- [ ] 2.2 実Graphを通る公開Failure TestでTask/Page/入力role/LLM stage/原因分類/token数が維持され、画面・log・failure.json・DB/WAL・再読込snapshotに合成markerが残らないことを確認する。state/configへ例外や本文を入れず、task/debug payloadを丸ごと公開しない現行境界も検査する
- [ ] 2.3 `uv run ruff check .`、`uv run ruff format --check .`、`uv run ty check`、`uv run pytest`、OpenSpec strict validation、`git diff --check`を実行し、結果と実行時commit/差分をverification.mdへ記録する。関数説明と既存APIへの委譲を確認する

## 3. 実成果物による受入れ

- [ ] 3.1 既存session 40709の終端をlive handleで確認し、修正後のコードを読み込んだprocessから`inputs/sample3.pdf`の実translationを逐次実行する。run ID・コード版・終了状態・成果物hashを記録し、旧process結果を修正後の証拠に流用しない
- [ ] 3.2 DOCXの表・表紙順序・日本語目次/図一覧/表一覧・改ページ・見出し番号を検査し、自分で起動した非表示Microsoft WordでPDFを作成する。対象DOCX/PDFをユーザへ提示し、目視結果と残課題をverification.mdへ記録する。PDF変換を製品機能へ追加しない
- [ ] 3.3 3.2の生成PDFと元の`inputs/sample3.pdf`をComparison Reviewで逐次比較し、入力hash、run ID、終了状態、reportを記録する。修正後Checkpointに本文がないことを秘密非表示の方法で検査する

## 4. 指摘解消と完了判定

- [ ] 4.1 既存失敗Checkpointの過去行に対する影響確認を読取り専用で行い、本文を出力せず対象ID・確認件数・残る疑義を記録する。新規書込み防止と過去情報の浄化を区別し、無断削除・改変を行わない。SECURITY-CHECKPOINT-001の元記録へ実装・Test・実機証拠を対応付ける
- [ ] 4.2 全Task・既存要求・実機/ユーザ目視の証拠に基づいて正式verifyし、未解決事項がない場合だけarchiveする。CONTRIBUTINGに従ってPR/CIを確認しmainへマージ・originへpushする。対象差分に`.agents/`、入力サンプル、PDF/DOCX、実行生成物を含めない
