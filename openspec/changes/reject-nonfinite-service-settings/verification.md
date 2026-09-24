<!-- markdownlint-disable MD013 MD041 -->

## 計画段階の検証（2026-09-25）

提案のみ。0/8 tasksで、製品修正・正式verify・archive・merge・pushは未実施。SETTINGS-FINITE-001は未解決のまま。

### 確認した事実

- `load_settings('convert', env=...)`の隔離した合成設定で、4種類すべての秒数環境変数が`nan`/`NaN`/`inf`/`+Infinity`/`1e309`を受理することを確認した。`-inf`、0、負数は既存の比較で拒否される。実Serviceへその値を渡す実験はしていない。
- 直接Settingsを作ると4 fieldともNaN/±Infinityを受理する。既存`test_settings.py`は0拒否と正常値を検査しており、この問題の回帰Testは存在しない。
- Pydantic 2.13.5の公開FiniteFloatは非有限を拒否し、PositiveFloatだけでは正のInfinityが通る。FiniteFloatとgt=0のTypeAdapterを組み合わせたメモリ内候補で、非有限・非正数の拒否と0.25/1,800/21,600/最大有限floatの保持を確認した。これは製品修正の証拠ではない。
- 生文字列を直接Pydanticへ渡すと、既存floatで受理される全角数字等の扱いが変わる。標準float変換を維持する設計へ反映した。内部retry=0を使う既存Testも確認し、env制約との区別を設計に記載した。
- 読取専用の実CLI診断で、.env無効・実秘密を渡さない子processへ合成の無効秒数と合成API keyを渡した。`python cli.py runs`は終了コード1、設定名あり、無効設定値markerあり、無関係な合成API key markerなし。出力本文は保存・表示せず存在判定だけを記録した。設定失敗なのでRun作成処理へ到達せず、新規Model要求は行っていない。
- from Noneは通常tracebackから原因表示を抑止するが、`__context__`を消すものではない。Pydanticの`.errors()`やunsafe構築APIを安全化済みと扱わない。

### 実翻訳との区別

既存のsession 58094（Run `01a0d4f7-20bf-7ed0-b580-7ddd2cb6299d`）を複数回pollし、同じlive handleを確認した。SPLIT〜STRUCTURE完了後、TRANSLATEが継続している。このprocessには本Changeの未実装修正は含まれない。停止・再起動や並列のLLM/Embedding呼出はしていない。

### 残課題

- 全実装・回帰・公開境界・実機検証が未完了。別Changeの441 passedを本修正の証拠にしない。
- CLIの不正設定値の原因表示を解消し、実入口でmarkerが出ないことを確認する必要がある。
- common配置、独自Resume状態の統合、表内画像の曖昧時動作、先行Word/PDFの利用者目視という未回答/未解決事項を引き継ぐ。本提案はその方針を決定しない。

### 文書の品質検査

- OpenSpec status: proposal/design/tasksがdone、仕様変更なしのためspecsはskipped。実装完了ではない。
- `openspec validate reject-nonfinite-service-settings --strict`: valid。
- `uv run pytest -q tests/test_documentation.py`: 21 passed（0.25秒）。
- `git diff --check`: 指摘なし。製品Codeは未変更のため全製品Test・型検査・実機Gateは本提案ターンでは再実行していない。

## Applyと自動検証（2026-09-25）

5/8 tasks完了。以下は計画段階の記録を更新する実装証拠であり、正式verify・実機Gateの合格ではない。

### 修正と再現

- 製品変更は`translate/common/settings.py`だけ。4 fieldを既存PydanticのFiniteFloatとし、環境変数は従来のfloat変換後に`TypeAdapter(Annotated[FiniteFloat, Field(gt=0)])`で検証する。独自finite検証器・新Dependency・新module・再開状態は追加していない。
- 修正前に追加した境界Testは32 failed / 29 passed（1.51秒）。非有限のenv受理20件と、直接Model構築での受理12件を再現した。製品修正後は同じ61件が成功（1.75秒）。
- 標準floatが受理する全角/Arabic数字、指数、符号、空白、underscore、分数、1,800/21,600秒、最大有限floatを保持する。内部retry=0も維持し、公開envでは0以下を拒否する。既定request timeout=1,800秒・Task deadline=21,600秒と、正常設定のfingerprint不変を確認した。
- 不正値は設定名と固定理由`must be a finite positive number`のValueErrorとなる。通常tracebackの原因表示は`from None`で抑止する。例外属性や任意のPydantic詳細を安全化するという保証には拡張しない。

### 公開境界

- 実CLI子processは4環境変数それぞれについて、dotenv無効・OS起動に必要な環境だけ継承・合成Credentialでconvertを実行した。終了コード1、設定名/固定理由あり、不正値marker/合成Credentialなし、Run root/成果物未作成を確認した。
- CliRunnerでtranslate/review/register/convertの全操作にNaN/Infinity/overflow/非数値を渡し、実loaderの拒否後にRun準備・外部実行が0回であることを確認した。
- main.pyの実AppTestで4環境変数×3不正値を検査し、画面の例外messageが設定名/固定理由だけで、Repository初期化・外部HTTP要求が0回、Run未作成であることを確認した。現行UIは起動時に例外画面で停止する。設定編集UIや全体的な例外UXの改修はしていない。
- 初回のUI Testはsocket.connect全禁止がWindows asyncioの内部loopbackも遮断し12件失敗した。テスト側の監視をhttpx.Client.sendへ限定し、AppTestの内部通信と製品の外部HTTPを区別した。修正後のUI境界12件は成功（4.27秒）。製品の通信制御を変更して合格させていない。

### 品質と再現範囲

- `uv run ruff check .`: 成功。`uv run ruff format --check .`: 318 files整形済み。`uv run ty check`: 成功。
- `uv run pytest -q`: **556 passed / 1 skipped**（38.22秒）。skipはWindows上のPOSIX PTY契約。関数説明の文書Testもこの全体検査に含まれる。
- OpenSpec strict validation: valid。`git diff --check`: 指摘なし。apply時の既存config警告（Unknown operation ID verify）は別の既存差分であり、無断修正していない。
- 基点commitは`3c138cfcf4b9acd0034c55bfe5c5daa84d3230eb`。製品差分はsettings.py、回帰Test差分はtest_settings/test_fingerprint/test_cli_runs/test_cli_process/test_streamlit_ui。settings.pyのSHA-256は`d0f6f21365a56b3682fbf352a3053f5bf98f3b9854abc35e683711bf47e46837`。
- 全体Testは既存の未コミット差分を含むworktreeで実行した。llm.py/lifecycle.py/terminal_evidence.py/review.pyのhashは先行Checkpoint実行記録と一致し、今回変更していない。HEADだけの検証と混同しない。
- 追加したTest関数には目的のdocstringを付与し、既存関数の説明も更新した。製品側の検証は導入済みPydanticへ委譲し、pyproject.toml/uv.lockに差分はない。

### 実機Gateと引継ぎ

- session 58094を同じhandleで再pollしliveを確認した。新しい終端出力はなく、接続警告のみ継続している。先行processへ設定を注入したり停止・再起動したりしていない。今回のsource編集は今後起動するprocess用であり、この先行Runが新修正を検証したとは扱わない。
- task 3.1〜3.3は未完了。先行実行の終端後に新Codeの実translation→自分で起動する非表示WordによるPDF化→元PDFとのComparison Reviewを逐次実行し、利用者目視を得る必要がある。
- SETTINGS-FINITE-001の実装と自動回帰は是正済みだが、元Changeを含めた最終解決・archive・main merge・pushは実機証拠が揃うまで行わない。

### 実機Gateの更新（2026-09-25）

先行session 58094はTRANSLATEのOpenAIConnectionErrorで終了コード1となった。現在の短い生成要求は成功したが、先行接続断の原因は未確定。失敗Runは保持し、新processでRun `01a0d520-15a4-74a2-9eaf-afafa726a03a`（session 3343）を開始した。基点は後続入力コピー修正を含む848296eと既存の未コミット差分で、今回の有限設定修正も含む。起動設定はcontext 30,208 / timeout 1,800秒 / deadline 21,600秒 / retry 3。SPLIT〜LOAD完了、終端未確認。

診断・入力hash・正確なrevision範囲は[Checkpoint実機記録](../sanitize-workflow-checkpoint-errors/verification.md)の最新節を参照。実translation→Word PDF→Comparison Review・利用者目視は未完了のため、tasks 3.1〜3.3を完了にしない。
