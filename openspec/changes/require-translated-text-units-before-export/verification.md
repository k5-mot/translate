<!-- markdownlint-disable MD013 MD041 -->

## 計画段階の診断（2026-09-25）

CONTENT-VALIDATE-001は未解決。提案は作成途中で、製品コード・Testは未変更。正式verify、archive、main merge、pushの条件を満たしていない。

### 現実装の再現

`validate._require_translations`、`markdown`の層選択、`document.block_text_units`、WorkflowのVALIDATE→MARKDOWN→DOCX接続を確認した。外部Serviceを呼ばず、メモリ内の合成Documentで以下を再現した。

| 条件 | 現在の結果 | 問題 |
| --- | --- | --- |
| figure/table × page 1/2 × Captionの初回訳/最終訳が各None/空配列/非空配列 | 全36組が通過 | Caption検査が存在しない。page 1除外は意図どおりだが、page 2の欠落も見逃す |
| page 2、原文Captionあり、初回訳と最終訳がNone | 通過しMarkdownに合成原文Captionを出力 | 原文fallbackが訳欠落を隠す |
| page 2、初回訳非空、最終訳が空配列 | 本文・Captionとも通過し、描画は空の最終訳を選ぶ | `final or translated`と`final is not None`の不一致 |
| page 2、原文あり、初回訳が空文字Inline一件 | 本文・Captionとも通過 | 配列の要素数だけでは空訳を検出できない |
| page 2、原文あり、初回訳が空白/タブ/改行だけのInline一件 | 本文・Captionとも通過 | 空白のみを出力しても現在は成功扱い |

本文条件をCaptionへコピーするだけでは、空の最終訳と非空の初回訳の組合せを見逃す。既存`TextUnit.text("final")`も、両訳層がNoneなら原文へfallbackするため、その戻り値だけで訳文の存在を判断できない。

`block_text_units`は本文・Caption・結合セルの起点を列挙できる。セルIDは行列座標形式であり、既存VALIDATE例外の配列index形式と異なる。診断IDを統一する場合はこの変更を回帰Testで明示する。既存Testで見つかった例外文字列依存は本文の`missing translation`部分一致で、セルの完全一致依存は見つからなかった。

### 先行実文書の観測範囲

先行成功Run `01a0d44f-1efa-7597-9d1b-0be4c5748b85`の`.workspace/verify/document.json`を読取り専用で確認した。16ページ、表紙以外で原文のあるCaptionは15件。両訳層None、既存本文条件相当の欠落、出力に選ばれる空配列はいずれも0件だった。文書本文を診断ログへ出力していない。

これは先行Artifactにおける層の存在確認であり、15件の翻訳品質、実PDFからの抽出漏れなし、最新製品のE2E合格を意味しない。合成入力で再現した製品不具合は未解決のままとする。

### 判断の分岐と確認中の事項

1. 本文・Caption・セルで、出力に使用する訳文層を検査する。最終訳が存在する場合は空配列でもその層を選び、古い初回訳で合格にしない。
2. 原文があるのに訳文層がNone/空配列なら公開前に失敗する。原文を自動補充して欠落を隠さない。
3. **回答待ち**: 原文に文字があるのに、選ばれた訳が空文字・空白だけの場合も停止するか。推奨は停止対象へ含めること。原文自体が空のセル・表紙は除外し、保護対象など原文と同一でよい内容を「日本語ではない」という理由では拒否しない。

3の判断を無断で確定せず、specs/design/tasksは回答後に完成させる。新しいDomain用語はなく、小さい検査条件の修正に独立Glossary/ADRは追加しない。未知の意味品質や部分的な訳抜けを、この有限の空訳検査だけで検証済みとはしない。

### 実装時に必要な検証

- None/空配列/非空訳/空文字/空白、初回訳と最終訳の優先順位を本文・図表Caption・結合セルで検査する。表紙と原文が空の対象を含める。
- 正常訳、FIX skip警告、保護対象、asset検査、独立Markdown→DOCX変換を回帰確認する。共通rendererの原文fallbackを一律削除しない。
- 実製品GraphをVALIDATE直前から実行し、欠落時に後続Taskが呼ばれず、新しいvalid reportを公開せず、既存成果物を上書きしないことを確認する。
- Checkpointの未完了位置がVALIDATEで、本文や秘密値が診断・SQLiteに混入しないことを確認する。独自の再開台帳・巻戻し・自動再翻訳は追加しない。
- 修正後の実translation→Microsoft WordでPDF化→入力PDFと生成PDFのreview→利用者目視を完了してから正式verify/archiveを判断する。

### 今回の検査と稼働中の処理

- メモリ合成で上表の36組と、本文/Captionの空配列・空文字・空白の不一致を再現した。ファイル・Runの変更、LLM/Embeddingの呼出は行っていない。
- `uv run pytest -q tests/test_validate_contract.py tests/test_text_unit_review.py tests/test_documentation.py`: **54 passed（2.01秒）**。既存Testが通っても上記の不具合が残るため、修正前の失敗Test追加が必要。
- 先行Comparison Reviewのsession `12758`を同じhandleでpollし、実行継続を確認した。追加のモデル処理は並列起動していない。先行Reviewは本Changeの未実装修正を検証するものではない。
- OpenSpecの必要Artifactはproposal以外が未作成。Deltaなしを隠す`skip_specs`は設定せず、strict検証合格やapply準備完了を宣言しない。
