<!-- markdownlint-disable MD013 MD041 -->

## Context

[proposal.md](proposal.md)のWhyを参照。BaseTask.measure、cli.py/main.pyの__main__境界はfinally内でprintする。既存Testは出力可能な環境の例外identityを検査するが、出力障害は含まない。読取り専用再現ではTaskのValueErrorがBrokenPipeErrorに置換された。

## Goals / Non-Goals

Goalは3か所の出力呼出だけを保護し、通常時の文字列・stdout・計測範囲を維持すること。Non-Goalは一般のstdout故障への復旧Framework、logger移行、出力retry、計測の永続化、終了時flushの全面的な制御。既存のcommon整理や独立した再開管理の是正も別件である。

## Decisions

1. 計測printだけを既存の標準contextlib.suppress(OSError, ValueError)で囲む。BrokenPipeErrorはOSError、閉じたstreamはValueErrorに含まれる。処理本体、時計読取り、成果物公開は囲まない。Exception全体の抑制はプログラミング不具合まで隠すため採用せず、BaseException・KeyboardInterrupt・SystemExitも抑制しない。
2. CLI/UIにも同じ局所的な境界を設ける。3か所のために新しい共通Moduleや汎用出力helperは作らない。BaseTaskへcommon依存を追加しない。loggerはstderr・設定・形式の変更を伴うため代替に使わない。
3. 表示失敗時は追加のprint/logger fallbackを行わない。故障した出力先への再通知を避け、元例外本文・Credentialを新しい経路へ送らない。時計自体の失敗やprocess終了時の遅延flushは別の問題であり、全processのstdout故障を解決したと報告しない。
4. 既存tests/test_timing_contract.pyへ障害注入を追加する。BaseTaskと既存具体Taskの戻り値・例外identity、CLI/UIの実際の__main__境界を動的に検査する。公開入口は本体とstreamをstub化した隔離実行を用い、実LLM/Embeddingは呼ばない。単なるソース文字列の存在検査で代用しない。
5. 保存障害を注入するケースは抑制範囲外であることを検査する。SystemExitのcodeとKeyboardInterruptの伝播も確認し、成功へ変える広いexceptを防ぐ。既存の通常表示・Task公開後計測のTestを維持する。

## Quality Attribute Design

Q-REL/Q-FUNCは3境界×成功/失敗×対象stream障害、元例外identityおよび本体実行1回の検証へ対応する。Q-COMP/Q-MNTは正常時の表示と関数/class入口、依存増加なしを検査する。Q-SECは計測行への例外本文追加とfallback出力がないことを確認する。実行中Runは変更前の証拠として扱い、適用後のE2Eを実行する際は順番に1件ずつ行う。

## Lifecycle, Migration and Operations

データ移行・設定変更・既存Run削除は不要。適用は稼働中実検証が終端に達してから行い、実行コードと証拠を混在させない。運用上、計測行がないことだけで本体の失敗と判定しない。診断JSON、成果物、Checkpointの保存障害を省略対象にしない。

## Risks / Trade-offs

- [Risk] 広い抑制範囲で本体障害を隠す → printだけを囲み、同じ例外型の保存失敗を負のTestで確認する。
- [Risk] Taskだけの修正でTOTALが再度上書きする → CLI/UI境界も動的に検証する。
- [Risk] 表示省略で時間情報が失われる → 承認された本体結果の維持を優先し、新しい保存や通知は追加しない。
- [Risk] 終了時flushまで成功保証したと誤認する → Specと検証記録で同期的出力障害に限定し、OS全体のpipe復旧と区別する。

## Migration Plan

適用前に回帰Testを追加して再現、3境界を修正して成功を確認する。関連Test・全体品質Gate後に実translation→Microsoft Word PDF→入力PDFとのreviewを逐次検証し、利用者目視結果と自動判定を分ける。Rollbackは本ChangeのCode差分のみで可能であり、成果物・既存入力は削除しない。TASK-TIMING-001の解消記録は証拠確認後に更新する。
