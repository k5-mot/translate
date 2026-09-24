<!-- markdownlint-disable MD041 -->

## Context

`proposal.md`のWhyを参照。現行REVIEWはページ内の全pairsを一つの高推論要求へ渡し、atomic directoryはTask全体の最後にだけcommitする。実Runではpage単位の応答が出力上限へ達した。

## Goals / Non-Goals

**Goals:**

- Review pairsを決定的なchunkへ分割し、出力枯渇を検出してbounded split fallbackする。
- chunk結果を順序保持でFindingへ統合し、全chunk完了後だけatomic publishする。
- Resume時に完了済みchunkを再利用し、失敗chunkから再開できるArtifact境界を提供する。
- 旧checkpointの`structured/assets/...`はVALIDATE前に`assets/...`へ正規化し、出力Markdown/DOCXの参照先を一貫させる。

**Non-Goals:**

- Review Findingの意味やseverityを変更すること。
- 並列LLM/Embedding、外部依存、モデル設定の変更。
- 未完了Reviewを部分reportとして公開すること。

## Decisions

1. **Deterministic chunking**: pairsを入力順に、最大item数とavailable input budgetの小さい方で分割する。各chunkは安定した`page-XXXX-review-YYYY` IDを持つ。
2. **Output recovery**: 高推論要求の`output-truncated`を既存retryで一度再試行し、再度枯渇した場合はchunkを二分する。最小chunk・最大深度ではFailureを伝播し、無限分割しない。
3. **Finding merge**: chunk応答のFinding IDを正規化し、入力target IDとchunk順をキーに重複を除去する。順序とページ番号を維持し、既存Check findingとの二重計上を防ぐ。
4. **Atomic and Resume boundary**: 各chunkのReview JSONをprivate Artifactへatomic保存し、全chunk完了後にTask Artifactをpublishする。Workflow checkpointはchunk IDを保持し、Resumeは未完了chunkだけを実行する。
5. **Safe diagnostics**: Failure Evidenceにはtask/page/group/target/stage/cause/token usageだけを保存し、prompt、Finding本文、原文および生応答を保存しない。すべて逐次実行する。

## Quality Attribute Design

- **Q-FUNC/Q-COMP**: chunk順、Finding IDおよび全入力pairの一回処理をunit/integration testとsample3実Runで検証する。
- **Q-REL/Q-REC**: output-truncated、最小chunk失敗、atomic cleanup、same-Run ResumeをFailure/Lifecycle testで検証する。
- **Q-SEC**: Failure/Run log/Change Evidenceのsentinel scanで本文・prompt・raw response漏えい0件を確認する。
- **Q-PERF**: chunk数、retry、wall time、token usageを安全な数値証跡へ記録し、並列呼出し0件を確認する。

## Lifecycle, Migration and Operations

- 既存translate checkpointは再利用し、failed REVIEW Runを明示Resumeする。fingerprintとRun形式は変更しない。
- 成功後にcomparison-review report、Markdown/DOCX/PDF成果物を検査し、外部export境界を確認する。
- ロールバックはREVIEW code/Artifact変更を戻すだけで、入力Run・Qdrant・明示exportを削除しない。

## Risks / Trade-offs

- **[Risk]** chunk分割でReviewの文脈が狭くなる → 前後contextを既存promptへ限定的に渡し、chunk順を保持する。
- **[Risk]** chunk数増加で実行時間が増える → sequential bounded splitとResume再利用で再実行を限定する。
- **[Risk]** Finding ID衝突 → chunk prefixと入力target IDで正規化し、重複は決定的に除去する。

## Migration Plan

1. Review unit/recovery/Lifecycle testを通過させる。
2. 失敗したRun `01a0d080-2c51-7da5-a91b-700b9a21e7a9`を明示Resumeし、REVIEWから完了させる。
3. 比較Reviewと成果物・Security・Lifecycleを検証し、verification.mdへ記録する。
4. 問題時はChange commitをrollbackし、Runを保持する。
