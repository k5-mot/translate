<!-- markdownlint-disable MD041 -->

## Context

proposal.mdのWhyを参照。全関数の説明範囲とPackage再利用は汎用規約に属する。一方、再開状態の管理と採用するFramework・Module配置は製品固有の仕様・設計であり、CODING_RULESへ混在させない。監査の具体例は[追加監査](../restore-docx-tables-and-indexes/coding-rules-audit.md)にある。

## Goals / Non-Goals

関数説明と依存機能の契約比較を汎用規約へ、再開状態の要求をrun-lifecycleのdeltaへ、実現手段と配置制約を本設計へ分類する。今回の文書編集では既存コードの全是正、未承認directory配置、旧Run移行の決定は行わず、未実装事項をtasks.mdに残す。

## Decisions

1. 関数の説明はPythonではdocstringを基本とするが、利用者要求の「コメント」を勝手に一律docstring必須へ狭めず、定義に対応する説明コメントも認める。特殊method・入れ子・Testを除外しない。lambdaは周囲の説明と可読性で点検し、説明のためだけのwrapperを増やさない。
2. 機能名の一致だけで置換を決めない。導入済みversionのAPIと、入出力・例外・retry単位・永続化・副作用を比較する。同等なら再利用し、契約差があるなら差の根拠を記録する。新しい汎用adapter/frameworkを増やさない。
3. 再開状態の一元化の実現には既存のLangGraphを使用する。Taskの順序・分岐はGraph定義、再開位置・完了履歴はLangGraph checkpointを正本とし、進捗表示はその実行情報から導出する。再開を制御する独立した完了一覧、進捗台帳、Page/Chunk Cacheを追加しない。細粒度の再開もLangGraphの永続化機能を用い、Task内部に別の機構を持たせない。入力・設定の互換性検証、Artifact入出力、外部副作用の冪等性確認は残せるが、独立したTask完了状態を持たせない。移行時には障害後の再開と副作用の重複防止をTestし、既存の再開粒度を維持する。
4. commonにはlogger/settingsだけを残すという製品固有の配置制約を、本OpenSpec設計で管理する。他の既存追加は追認しない。具体的な移管先は責務監査に基づいて確定し、document_processing/4file案やutils/redaction.pyの独立配置を承認済みとして扱わない。
5. spec.mdは再開時の振る舞いと品質要求、本design.mdはLangGraphの採用と配置制約を保持する。CODING_RULES.mdにはそれらを重複記載しない。用語の変更はないため、この分類訂正だけのために新しいGlossaryやADRは作らない。
6. 公開entry pointをcli.pyとmain.pyに限定し、内部ModuleのDebug入口は公開Interfaceに含めない。Python対応版は3.12以上とする。Task経過時間はtime.perf_counter()で計測する。関数入口とBaseTask/各Taskクラスを併用する既承認方針でも、計測のために独立したTask完了台帳を設けない。
7. CODING_RULES内のpyproject参考例から製品名、Version、実行時/開発依存一覧と型検査除外Pathを除去する。実設定の正本は[pyproject.toml](../../../pyproject.toml)、解決済み依存は[uv.lock](../../../uv.lock)とし、本設計に数値一覧を複製しない。LangChain/LangGraph、Streamlit、Typer、Docling接続、Qdrant接続、PDF/DOCX処理などの製品固有の採用構成は各CapabilityのOpenSpecで扱う。例にだけ存在した直接openai依存などを、移管を理由に製品要件へ昇格させない。型検査の既存除外は今回変更も妥当性の追認もしない。

## CODING_RULES全体の分類

| 対象 | 管理先と判断 |
| --- | --- |
| 最小実装、既存API再利用、共通化の説明責任 | 汎用の開発原則としてCODING_RULESに維持 |
| 関数説明、定数根拠、古いComment更新 | 言語・製品に依存しない保守規則として維持 |
| 品質検査、秘密/生成物混入防止、無関係な一括変更禁止 | 汎用の開発完了条件として維持 |
| LangGraphでの再開管理、common配置 | 本設計とrun-lifecycle deltaへ移管 |
| Python 3.12以上、cli.py/main.py、内部Debug非公開 | run-lifecycle deltaへ契約を移管 |
| 各Task経過時間、time.perf_counter | 計測可能性はdelta、実現手段は本設計へ移管 |
| main guard、Debugから既存関数へ委譲、不要な入口の追加禁止 | ファイル名を伴わない汎用Python実装規則として維持 |
| pathlib/subprocess、Ruff/ty/pytest、標準品質Command | 開発手法・品質規則であり製品動作の要求ではないため維持 |
| 推奨Package表 | 導入必須ではない汎用的な選択指針として維持 |
| pyproject例の製品metadata/依存/除外Path | CODING_RULESから除去し、実設定と本設計の管理方針へ集約 |
| Ruffの汎用Lint/Format例、TypeScript/Java節 | 製品固有の振る舞いや構成を定めていないため維持 |

## Quality Attribute Design

Q-MNT: 汎用規約と製品固有要求の管理先を分離する。Q-REL: 再開正本を増やさず、既存違反の修正には障害/Resume Testを必須とする。文書検査は分類とScenarioの存在を確認するものであり、Runtime適合の検証を代替しない。

## Lifecycle, Migration and Operations

製品の起動方法、データ、依存を変更しない。既存監査は未解決として維持する。正式verifyの実行条件はtranslation→Word PDF化→reviewとし、製品codeが変わらない文書変更でも勝手に省略しない。

## Risks / Trade-offs

- [Risk] コメントが存在するだけで適合とする → 目的、制約、副作用の説明を実装と照合する。
- [Risk] Packageへ機械的置換してretry範囲や失敗時の保存契約が変わる → 契約差と回帰Testを要求する。
- [Risk] 規約整備を全違反の解消と取り違える → 本Changeの完了と監査是正の完了を区別する。

## Migration Plan

製品固有の再開状態節とcommon配置制約をCODING_RULESから除去し、OpenSpecの要求・設計へ移す。独立したPage/Chunk記録、独自完了情報、公開状態の正本統合は未実装として追跡する。register/convertを含む移行設計と既存UUIDv7データの扱いを確定する前に、再開データを削除・変換しない。
