<!-- markdownlint-disable MD013 MD041 -->

## Context

[proposal.md](proposal.md)のWhyを参照。現行`_require_translations()`は本文とセルを`final or translated`で検査し、Captionは対象外。一方、Markdownの`_current`、`_cell_current`、`_caption_current`は`None`だけを未作成として扱う。空の最終訳を検査と描画で別扱いする不整合がある。利用者は2026-09-27に空文字・空白も停止対象とする方針を承認した。

## Goals / Non-Goals

**Goals:** 実際に描画される訳文層の存在を、既存VALIDATEと既存TextUnitを使って確認する。Graphの既存失敗・Checkpoint境界を維持する。

**Non-Goals:** 言語判定、固有名詞の厳密保護、意味的な完全性判定、自動再翻訳、表内画像の復元、ALIGN修正、保存構成の移行。共通rendererの原文fallbackを一律削除せず、独立Markdown→DOCX変換には翻訳の存在を要求しない。旧形式対応の廃止は承認済みだが、保存構成を扱う是正として別途実施する。

## Decisions

### 1. 既存の非永続TextUnitを再利用する

`translate.document.block_text_units()`は本文・Caption・行列順の結合セル起点を列挙する。これをVALIDATEから呼び、`inline_text(unit.source).strip()`が空なら訳文存在検査を省く。Page 1は従来どおり除外する。セルの診断IDは既存TextUnitの`/cell/<row>/<column>`へ揃え、独立した列挙器や新Moduleは作らない。

Caption用ループを既存の本文/セルループへ追加するだけの案では、列挙と空訳条件が分散するため採用しない。既存APIが対象・順序・結合セルの粒度を満たしている。

### 2. 未作成と空を区別して選択する

`unit.final`が`None`でなければその値、そうでなければ`unit.translated`を選ぶ。選択値が`None`または`inline_text(selected).strip()`が空なら失敗する。`inline_text()`はline_breakを改行として処理するため、空文字・Unicode空白・タブ・改行の検査を別実装しない。

`TextUnit.text("final")`だけで判定する案は、両訳層が未作成のときに原文へfallbackするため不採用。既存CHECK/REVIEWが使うそのAPIを変更せず、訳層の存在確認に必要な差分だけをVALIDATEへ置く。非空訳と原文が同一であることは失敗理由にしない。

### 3. 現在の公開前停止境界を利用する

`ValidateTask.run()`は訳検査・asset検査の後だけ成功reportを保存する。実Graphの`validate_node`も成功後だけ検証済みDocumentを保存し、MARKDOWN→DOCXへ進む。この順序を保つ。欠落時に空の成功reportを保存したり、古い成果物を削除したりしない。

失敗の分類は既存のValueErrorと安全なTask失敗境界を使い、本文・訳文を例外へ含めない。ID・pageなど位置情報は既存の通知/保存契約で表現する。Checkpointの安全化には既存adapterを使い、独自の再開位置、完了集合、再翻訳Queueを追加しない。既存IDが安全に取り扱われることも合成marker試験で確認する。

## Quality Attribute Design

| ID | 実現と検証 |
| --- | --- |
| Q-FUNC | 本文/図Caption/表Caption/セル × 訳層状態の回帰行列で欠落見逃し0件。結合セル起点・表紙・空原文を含む |
| Q-REL | 実GraphでVALIDATE失敗、後続0回、既存report/DOCX hash不変、Checkpointのnextがvalidateであることを確認 |
| Q-SEC/Q-INT | 入力本文・周辺訳文・認証markerを公開診断、失敗保存、SQLite/pending writesへ追加保存しない |
| Q-COMP/Q-MNT | 既存TextUnit、BaseTask、Graph、serializerへ委譲。新Dependency/Module/保存Schema/管理台帳0件。FIX skip警告と独立convertを回帰確認 |
| 性能効率 | 外部要求追加0回。対象Inlineの有限走査のみとし、構造検査をLLMへ委譲しない |

## Lifecycle, Migration and Operations

新規Dependencyの取得やデータ変換は不要。今回の停止判定は不完全な出力を従来成功から失敗へ変えるため、公開FailureでVALIDATEの欠落として追跡する。保持されたArtifactを無断で書き換えたり、検査を通すために原文を訳層へ複製したりしない。

回帰は`tests/test_validate_contract.py`を中心に追加する。`tests/test_text_unit_review.py`の既存層選択/ID検査を再利用し、`tests/test_translation_workflow.py`または`tests/test_workflow_state.py`で実VALIDATEを通る失敗境界を確認する。全関数に目的コメントを付ける。実translation→Microsoft Word PDF→元PDFとのReviewをreasoning OFF・逐次で行い、利用者目視までを受入条件に残す。LLM接続障害中は実E2Eを成功扱いにしない。

## Risks / Trade-offs

- [Risk] 空原文のセルや表紙を欠落として拒否する → 原文の非空白判定とPage除外を先に行い、回帰行列に含める。
- [Risk] 空の最終訳を古い初回訳で補う → truthinessでなく`is not None`で選び、描画結果と同じ層を検査する。
- [Risk] 文字列存在の検査を翻訳品質全体の合格と混同する → 抽出漏れ・部分的訳抜け・意味品質・表内画像は別検証として維持する。
- [Risk] 同じ構造を持つTest doubleだけで合格とする → 実Graph、実VALIDATE、実Checkpointを使い、外部サービスのみ合成境界へ置換する。

## Migration Plan

保存形式のmigrationは実施しない。失敗を通過させる互換フラグは導入しない。差分を戻す場合も利用者データを変換/削除せず、旧判定へ戻した成果物を本要求に適合済みと表示しない。新保存構成への一本化は[承認記録](../clarify-code-documentation-and-reuse-rules/verification.md)に従う別の是正であり、本検査変更だけで完了にしない。
