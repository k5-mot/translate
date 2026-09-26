<!-- markdownlint-disable MD013 MD041 -->

## Context

動機は[proposal.md](proposal.md)を参照。`run_public_run_detached()`は`python -m translate.common.terminal_evidence --child ...`で起動する。現状の`__main__`側で定義された`_child_entry()`は同じ名前空間の`bind_call_counts()`を呼ぶ。一方、LLM/Qdrant Adapterは通常のpackage名でimportした`count_external_call()`を呼ぶため、別々の`_CALL_COUNTS`を参照する。

既存の入れ子context Testは通常import内だけ、実childのconvert Testは外部呼出し0件であり、この欠陥を検出できない。通常importと別名の`runpy.run_module()`を用いた先行の読み取り診断でもContextVarのidentity不一致と計数0を確認したが、実child全経路の回帰Testとは区別する。

## Goals / Non-Goals

**Goals:** module入口から、Adapterと同じ通常importの既存child実装へ一度だけ委譲する。Testで実際にcounterが増える経路を通し、終端JSONまで確認する。

**Non-Goals:** counterを別moduleへ移す、独自singleton/共有memory/永続台帳を導入する、`sys.modules`を書き換える、公開entry pointを増やす、hookの計数粒度を変更する、heartbeatの計数保証を追加すること。LangGraphの再開管理や未解決のALIGN方針には触れない。

## Decisions

### 1. Debug入口だけを通常import先へ委譲する

`if __name__ == "__main__":`から通常package名でimportした既存`main()`へ委譲する方式を第一候補とする。これによりparser、child実行、counter束縛、終端保存を同じmodule上で処理できる。通常import後の`main()`直接呼出しも維持する。

新しい計数moduleへの抽出はcommon再整理を先取りし、変更範囲を増やすため採用しない。`sys.modules`の別名登録はmodule loader状態を変更するため不要。起動commandを文字列の`-c`実装へ置き換えることも避け、現行`-m`入口を検査可能なまま残す。

### 2. 数値の意味を変えず、検証結果の解釈を限定する

現行LLM hookは`client.invoke()`の直前にあるため、成功回数ではなく送信試行回数であり、有限retryも数える。Langfuseの`llm.request` spanはretryを内包し得るので、件数の無条件一致は求めない。

現行Embedding hookはClient生成時、Qdrant hookは登録Client生成時および検索のretry外にある。これらは物理通信回数ではない。まず既知hook回数が欠落せず到達することを検証し、通信の正確な回数・同時数を証明するものとして使用しない。残る計測粒度の問題はverification.mdへ引き継ぐ。

進捗callbackは途中のcounterを保存していないため、強制終了・watchdog timeout時の数値も未呼出しの証明にはならない。今回の最終計数保証は、既存の正常終了と`PublicRunError`による保存経路に限定する。

### 3. 実入口とAdapter境界をTestする

- `run_public_run_detached()`の実`-m`起動を通す。Test専用一時領域の`sitecustomize.py`を子processの`PYTHONPATH`へ追加して既存実行境界と設定を安全なfixtureへ差し替える。製品へのテスト用設定や環境変数契約は追加しない。通常moduleへの直接 `_child_entry()`呼出しだけでは合格にしない。
- 既存公開処理境界を一度通し、canonical hookをLLM/Embedding/Qdrantで既知回数呼ぶ成功ケースと`PublicRunError`ケースを確認する。保存されたJSONの値、status、exit、実行回数を検査する。
- LLM Adapterを応答stubで通し、有限retry後に成功/失敗する各ケースで送信試行数を確認する。socket等で外部通信を禁止し、Langfuse送信もstubとする。
- 入れ子・例外後のcontext復元、未束縛時の非計数、既存convert実child、watchdog・lock・cleanup回帰を維持する。

Testの起動方式と差し替え範囲を記録し、fixture付き実child Test、差し替えのない実`-m` convert Test、後続の実Model E2Eを混同しない。補助的に標準`runpy`の`__main__`起動を使う場合も、それだけで実`-m`回帰を通したとはしない。

## Quality Attribute Design

Q-FUNC/Q-RELは既知hook回数・retry回数・成功/失敗終端の一致で判定する。Q-PERFは外部request追加0、逐次維持で確認する。Q-COMPは既存JSON/Resume/convert Test、Q-SECは秘密sentinel不在と外部通信禁止で検査する。Q-MAIN/Q-PORTは最小委譲・既存依存のみ・Windows subprocess Testと全品質Gateで確認する。Q-USEは上記の計数粒度を実測記録に併記する。

## Lifecycle, Migration and Operations

移行処理は不要。診断processが停止していることを確認して修正する。既存Runと診断JSONを保持し、過去値は修正後の実測に置き換えない。次のsample3新規検証でreasoning OFF・逐次のTranslation→Microsoft Word PDF化→Comparison Reviewを実行し、LLM試行数と観測spanの関係を確認する。Word変換は引き続き検証操作であり製品機能にはしない。

## Risks / Trade-offs

- [Risk] Testが通常importだけを通って欠陥を再現しない → 修正前に`__main__`経由の計数Testが失敗することを確認する。
- [Risk] Mockがcounterだけを直接呼んでAdapter retryの誤差を隠す → 実Adapter＋応答stubのTestを別途通す。
- [Risk] 計数修正だけで実E2E全体を合格扱いする → ALIGN不一致・表内画像・目視未確認など既存指摘を残し、計数の検証結果と分ける。
- [Risk] 別Changeの未コミット差分を混入させる → `terminal_evidence.py`の既存FailureKind差分等を保存し、今回の変更だけをstageする。

## Migration Plan

1. 通信なしで起動経路の回帰Testを追加し、現行コードで計数不一致を再現する。
2. 入口委譲を修正し、関連Test・全品質Gateを実行する。
3. 既存検証記録へ原因と制約を追記し、次の実E2Eで検証する。自動Test成功だけで実検証タスクを完了にしない。
4. Rollbackは入口と対応Testだけを戻す。旧Run・入力・成果物・診断JSONは削除しない。
