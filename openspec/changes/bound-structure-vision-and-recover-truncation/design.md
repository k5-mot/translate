<!-- markdownlint-disable MD013 MD041 -->

## Context

動機は[proposal.md](proposal.md)のWhyを参照する。STRUCTUREは現在、page画像を120 DPIで描画し、画像付き`structured()`を試した後、有限失敗ならtext-onlyへfallbackする。ただしvisionの`output-truncated`だけは早期にTaskを停止する。Task directoryは全page処理後に一括atomic publishされ、page間の中断位置は保存されない。対象PDFは358ページで、COVERを除く357ページのうち351ページにblockがある。`task_deadline_seconds`はAdapterの各呼出しのretry期限であり、STRUCTURE全体の期限ではない。

元のpage 3画像は1,346,400 pixelsでlocal推論processがassertion終了し、1,090,584 pixelsへ下げた同条件probeはprocessを通過して`vision-output`のtruncationとなった。`reasoning_effort=none`を指定した追加probeも約425.9秒で同じtruncationとなり、思考抑制による短縮は確認できなかった。text-onlyの同page probeはschema適合で成功した。高解像度障害と上流の[llama.cpp issue](https://github.com/ggml-org/llama.cpp/issues/28954)との対応は推論であり、Model全般の画素限界と断定しない。

## Goals / Non-Goals

**Goals:** STRUCTUREがlocal runtimeへ安全な大きさの画像だけを送り、vision出力枯渇後も切れた応答を使わず既存text-only能力で回復できるようにする。長い逐次処理の中断から検証済みpageだけを再利用し、公開Artifactのatomic性を維持する。

**Non-Goals:** 翻訳／Review全般のtruncationを回復可能にすること、ModelやProviderを変更すること、複数Model requestを同時に動かすこと、出力token予算を自動増額すること、raw本文やModel応答を診断logへ追加すること、Word-to-PDF変換を製品へ追加すること。

## Decisions

### 1. STRUCTUREだけに固定の1,000,000-pixel上限を設ける

既存PDF rendererの120 DPIを維持し、画像をModelへ渡す直前に既存Pillowで縦横比を保って縮小する。元画像が上限内なら変更しない。整数丸め後のwidth×heightが上限以下になることを検証し、cropやpageの一部分だけの入力を許さない。描画後の画像はTaskのprivate temporary directoryに置き、成功・失敗のいずれでも公開成果物に混ぜない。COVER画像や他TaskのPDF描画は変更しない。

固定値にする理由はModelごとの新規設定を増やさず、現在のRun fingerprintを変えないためである。1.09 megapixelsでruntime処理を通過した実測と、上流報告の1.15 megapixels未満という条件より余裕を持たせる。大きなpageをそのまま送る案は現在のruntimeを停止させ、LM Studioの公開load APIでphysical micro-batchを変更する案も実効値を変更できなかったため採用しない。

### 2. `vision-output` truncationは別modeの回復のみ許す

Adapterの`finish_reason=length`判定と非retryは変えない。STRUCTUREのvision呼出しが`LLMError(failure_kind="output-truncated")`を返した場合は、他の有限vision失敗と同様に一度だけtext-only経路へ進む。visionの途中応答はparserにもpage補正にも渡さない。text-only応答が完全なschemaへparseされた場合だけpageを確定する。text-onlyも失敗した場合は最終Errorをpage番号と安定IDで包み、Taskを止める。

この回復は同じrequestのretryではなく、画像なしという異なる入力への既存fallbackである。ただし未完了の`align-llm-token-budget-and-truncation-diagnostics` deltaには「出力枯渇時は停止」とあるため、同ChangeのSpec記述をSTRUCTUREで完全な代替応答が得られた例外と整合させ、両Changeをstrict validateしてからarchiveする。翻訳やReviewのtruncation停止契約は維持する。単にtruncated JSONをparseする案は欠落を採用するため禁止する。

### 3. page checkpointは非公開の別directoryへ保存する

Runの`.workspace/`内でSTRUCTUREの公開directoryとは別のprivate progress directoryを使用する。各pageを完全に補正した後、そのpage JSON、audit、および入力page・rules・Model・token設定・画像上限を結び付けるdigestを、既存のatomic directory／manifest機構でpage単位に確定する。再開時はRun fingerprint検証に加えてpage checkpointのschema、manifest、digestおよびpage番号を検証し、失敗したpageから再推論する。入力のない旧Runでは全pageを通常処理する。

Task全体が完了した場合にだけ、検証済みpage結果から従来の`structure/document.json`、page JSON、auditを一括atomic publishする。途中のprivate progressはRun内に保持してよいが、CLI／Streamlitの公開outputsと外部exportに含めない。中断で残る不完全なtemporary directoryはcheckpointとして認識しない。Task全体を毎回最初から再処理する案は351対象pageのlocal逐次推論コストと途中停止リスクが高いため採用しない。

### 4. 実Runは段階的に確認する

まずMock Testと同pageの単発probeで上限とfallbackを確認する。品質Gate後、Model context 30,208、parallel 1、他request 0件、Run fingerprint一致を確認して既存RunをCLIから一度だけ明示Resumeする。長時間処理が中断した場合はpage checkpoint数と完了済みTask Artifactのhash／mtimeを確認し、同Runからのみ再開する。新Runの作成や既存Runの削除はしない。

## Quality Attribute Design

| ID | Approachとtrade-off | Evidence |
|---|---|---|
| Q-FUNC | 有界画像と完全schemaだけを採用する。画像縮小は細部識別能力を下げ得る | 画素数・縦横比Test、page 3 probe、実Runの構造検査 |
| Q-PERF | 逐次requestを維持し、完了pageの再推論を避ける。checkpoint I/Oが増える | invoke count、page checkpoint再利用Test、wall time |
| Q-COMP | 固定画像上限はtoken設定とfingerprintを変えず、旧Runにpage checkpointがなくても動く | 旧Run形式Test、fingerprint Test、hash／mtime |
| Q-USE | 最終失敗の安全なstageとcauseを維持し、成功fallbackはactive failureにしない | CLI／Streamlit Failure Test |
| Q-REL | page checkpointを検証後にだけ再利用し、Task全体はatomic publishする | kill／Resume、破損注入、途中公開0件 |
| Q-SEC | private checkpointはRun root内のみ、公開logはallowlist値のみ | secret sentinel scan、export検査 |
| Q-MAIN／Q-PORT | 既存Pillow、PDF adapter、atomic helperを使い新Dependencyを増やさない | Ruff、Format、ty、全pytest、strict validation |

## Lifecycle, Migration and Operations

既存RunのmetadataやTask checkpointを変換しない。新page checkpoint formatは存在しなければ空とみなし、互換性がないものは再推論する。運用者は単一Modelをcontext 30,208／parallel 1で維持し、900秒timeoutで明示Resumeする。SupportはRun Failureとpage checkpointの件数・整合性だけを報告し、本文や画像を表示しない。Rollback後に新checkpointが残っても旧実装はそれを参照せず、Runと外部exportは削除しない。取得・供給の変更はない。

## Risks / Trade-offs

- [Risk] 1,000,000 pixelsでも他pageでruntimeが停止する → 同Runのprivate checkpointを保持し、原因が再現したpageで停止する。さらに解像度を暗黙低下させない。
- [Risk] text-only構造補正で視覚的手掛かりを失う → 完全schemaと既存構造検証を必須にし、実DOCXの構造・図表検査を後続受入Changeで実施する。
- [Risk] page checkpointと元のDocumentが不一致になる → page入力digest、manifest、schema、Run fingerprintで検証し、不一致pageだけ再処理する。
- [Risk] 長い逐次Runが何度も中断する → pageごとの確定位置を観測し、旧Task Artifactを壊さず同じRunでResumeする。
- [Risk] 先行Changeとのtruncation Specが矛盾する → archive前に限定例外を明文化し、両方のstrict validationとSpec diffを確認する。

## Migration Plan

1. 画像上限、vision truncation fallback、page checkpointの失敗Testを追加する。
2. STRUCTUREだけを最小変更し、旧Run・旧Failure・atomic publishの回帰を確認する。
3. 先行Changeの保留中Spec deltaと設計を整合させ、品質Gateと秘密scanを通す。
4. page 3単発probe後に同じRunを明示Resumeし、完了済みpageとTask Artifactの再利用を検証する。
5. 成功結果を先行Translationと受入Changeへ渡す。Rollback時はコードをGitで戻し、Runと非公開progressを削除しない。
