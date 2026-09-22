<!-- markdownlint-disable MD013 MD041 -->

## Context

動機は[proposal.md](proposal.md)のWhyを参照する。現行の設定層はModel上限を16,384 tokensへ固定し、最大出力4,096、画像予約2,048を使用する。実PDFのpage 1はCOVERとしてLLM対象外、page 2はblock 0件のno-opであり、page 3が最初のSTRUCTURE text requestだった。page 3相当の同一requestを逐次2回実行すると、いずれも入力1,328、出力4,096、合計5,424 tokens、`finish_reason=length`、本文0文字となった。したがってpage 1／2の通過はLLM処理の成功を意味せず、再現できた一次原因はcontext全体の超過ではなく最大出力の枯渇である。

現在のAdapterは応答本文を直ちにparseし、終了理由を検査しないため、出力枯渇を`OutputParserException`として同条件で有限retryする。LifecycleはTask、page、target、stageおよび例外型を安全に保持するが、終了理由とtoken usageを表現できない。Run fingerprintには既に`tokens.context`、`tokens.output`および`tokens.image`が含まれている。ModelおよびEmbeddingは同一のlocal Hardwareで動作し、並行requestを許容しない。

## Goals / Non-Goals

**Goals:**

- 実Modelの30,208-token contextと製品設定を一致させ、有限で検証可能な入力・出力予算を定義する。
- 出力上限到達をparse前に識別し、安全な診断を一回の失敗からRunへ伝播する。
- truncated responseを成果物にせず、checkpointとAtomic Artifactの境界を維持する。
- token設定変更を既存fingerprintで検出し、旧Runを不変のまま新しいUUIDv7 Runへ移行する。
- Model probe、Workflow、Embeddingを含む外部AI requestをすべて逐次実行する。

**Non-Goals:**

- Model、Provider、reasoning方式、prompt内容またはstructured-output Libraryの置換。
- 動的なcontext探索、自動的なtoken予算増加、同一requestの並行実行。
- 既存Run metadataの移行、旧Runの削除またはtoken fingerprint不一致の緩和。
- Qdrant、Docling、LibreTranslate、Langfuse、公開CLI optionまたは成果物形式の変更。
- `complete-sample-pdf-acceptance-verification`の受入判定や全page目視確認の代替。

## Decisions

### 1. 30,208 contextへ固定し、既定最大出力を16,384にする

Model上限と既定contextを30,208、既定最大出力を16,384、画像予約を2,048、安全余白を1,024 tokensとする。既定時は30,208 - 16,384 - 2,048 - 1,024 = 10,752 tokensを入力とschema指示へ残す。16,384は再現時に枯渇した4,096の4倍であり、無制限生成を避けながらpage 3の小さいJSONに十分な余裕を与える。実装では安全余白を単一の定数として扱い、chunk予算と設定検証で同じ計算を使用する。

明示contextは正の整数として読み、30,208を上限に制限する。最大出力または画像予約が不正、あるいは両者と安全余白の合計が有効contextを使い切る場合は、値を暗黙補正せず起動前に設定Errorを返す。暗黙補正は利用者の指定とfingerprintの意味をずらすため採用しない。

代替として最大出力8,192も検討したが、local Modelのhidden reasoningが4,096を既に使い切ったEvidenceに対する余裕が小さい。context全量を最大出力へ割り当てる案は入力容量と停止上限を失うため採用しない。

### 2. 応答metadataを本文parseより先に正規化する

Adapterは一回のinvoke成功後、LangChain messageの`response_metadata`および`usage_metadata`から次のallowlist値だけを抽出する。

- 終了理由: 文字列`length`と一致するかどうか。
- token usage: non-negative integerのinput、outputおよびtotalだけ。
- modeとstage: 既存の固定値から導出する。

`finish_reason=length`なら本文が空かどうかにかかわらずparseせず、専用の出力枯渇Errorを生成する。公開分類は`output-truncated`、stageは`text-output`または`vision-output`、終了理由はallowlist済みの`length`とする。raw metadata map、response本文、reasoning contentおよび例外messageはErrorへ保持しない。metadataが欠落している通常応答は既存parseへ進み、schema不適合は従来どおり有限retryする。

終了理由が`length`なら同一token予算での再試行では完全な応答にならないためnon-retryableとする。HTTP 408／429／5xx、transport Errorおよび明示的に対応するProvider互換Errorの有限retry規則は維持する。

STRUCTUREのvisionでのみ、切れた応答を捨てて画像なしのtext-only入力へ切り替える。これは同一requestのretryではなく既存の別mode fallbackであり、完全なschema適合応答を得た場合に限りpageを確定する。text-onlyも失敗した場合と他Taskの出力枯渇は従来どおり停止する。

代替として空本文だけを検出する案は、途中JSONを伴うtruncationを見逃すため採用しない。parse失敗後に終了理由を調べる案も、parserへ文書断片を渡し原因を曖昧にするため採用しない。

### 3. 安全な診断値をoptional fieldでLifecycleへ伝播する

LLM境界ErrorとTask statusへ、`failure_kind`、`finish_reason`および3つのtoken countをoptionalな型付き値として追加する。LifecycleのFailure recordも同じoptional fieldを持ち、固定stage、固定分類、`length`およびnon-negative integerだけを受理する。表示は値が存在するときだけ`kind=output-truncated finish_reason=length input_tokens=... output_tokens=... total_tokens=...`を追加する。

旧Failure JSONには新fieldが存在しないため、optional defaultによって変換なしで読める。新fieldを持つFailureは既存のAtomic writeで保存し、失敗したpageの成果物は従来のTask境界より外へ公開しない。既存のredactionとcredential scanへ、raw prompt、本文、reasoning、endpointおよびmetadata mapを含まないことの回帰Testを追加する。

### 4. Token設定差分には既存fingerprint機構を使用する

fingerprint schemaを増やさず、既存の`tokens.context`、`tokens.output`、`tokens.image`を使用する。既定値変更により旧Run `01a0c138-0e5f-7e62-b0a8-8f9fd1e5bfa5`は少なくともcontextとoutputで不一致となる。明示Resumeはfield単位の理由を返して拒否し、旧Run directoryは読取り確認以外に変更しない。

新設定で同じ入力を処理するときは新しいUUIDv7 Runを作成する。Qdrant状態は既存契約どおりfingerprintへ追加しない。コードversionだけを特別扱いするfingerprintや旧Run checkpointのcopyは、再現性を下げるため採用しない。

### 5. 実Model検証は最小の逐次gateから始める

Unit／Integration Testに合格した後、保存済みDocling documentからpage 3と同等のrequestを新設定で一回だけ実行し、非空かつschema適合、`finish_reason`が`length`ではないこと、およびcontext内の数値usageを記録する。probeは本文、prompt、raw responseおよびendpointをEvidenceへ残さない。probe成功後に旧RunのResume拒否を確認し、その後だけ同じ入力の新規Translation Runを開始する。すべてを同時実行数1で行う。

probeが再びtruncationし完全な別mode応答を得られない場合は最大出力を自動増加せず、Failure Evidenceを保持してChangeを未完了とする。これにより実Model挙動を推測で製品既定へ反映することを防ぐ。

## Quality Attribute Design

| 品質ID | Design approachとtrade-off | 影響箇所 | 検証Evidence |
|---|---|---|---|
| Q-FUNC | 実context、有限出力予算、parse前truncation判定を一つのContractにする | Settings、LLM Adapter | 境界Test、page 3 probe、schema適合結果 |
| Q-PERF | 16,384の有限上限とdeadlineを維持し、同条件truncation retryを省く。単発requestは長くなり得る | Settings、retry loop | invoke回数1、wall time、token usage、同時request最大1 |
| Q-COMP | optional Failure fieldと既存fingerprint keyを使用する | Lifecycle、fingerprint | 旧Failure読取り、旧Run Resume拒否、新Run UUIDv7 |
| Q-USE | 原因を`output-truncated`、stage、終了理由、数値usageで直接表示する | CLI／Streamlit共通Failure表示 | format Test、実Failure Evidence |
| Q-REL | truncated本文をparse・保存せず、checkpointとAtomic writeを維持する | Adapter、Workflow、Lifecycle | non-retry Test、途中Artifact 0件、Resume可能状態 |
| Q-SEC | allowlist済みmetadataだけを伝播し、raw値を捨てる | Adapter、Failure、logging | sentinel scan、credential scan、Evidence review |
| Q-MAIN | token計算、metadata正規化、retry分類をfocused helperへ分離する | Settings、Adapter | Ruff、Format、ty、focused pytest、全pytest |
| Q-PORT | 既存Python／LangChain interfaceだけを使用する | 全変更箇所 | Dependency差分0件、Windows Test |

## Lifecycle, Migration and Operations

- **取得・供給:** 新規Package、ServiceおよびModelを追加しない。既存OpenAI互換Serverが返すLangChain metadataだけを入力にする。
- **移行:** 保存済みRunとFailureは変換しない。token設定差分はResume拒否として明示し、新設定では新しいUUIDv7 Runを作る。
- **運用:** probe、Translation、ReviewおよびEmbeddingを逐次実行する。request timeout、Task deadlineおよび有限retryを維持し、truncationを同条件非retryとし、STRUCTUREの完全な別mode回復がない場合だけ停止する。
- **Support:** Failure表示とrun-local logには安全な分類と数値usageだけを残す。保守者はpage、mode、stageおよびusageからtoken枯渇とtransport障害を区別する。
- **保守:** Model context、既定出力または安全余白を変更するときは、設定境界、chunk計算、fingerprintおよび実probeを同じChangeで更新する。
- **廃止:** 旧Run、新Run、外部exportおよびQdrant Collectionを自動削除しない。利用者の明示削除まで診断Evidenceを保持する。

## Risks / Trade-offs

- [最大出力16,384により一回の失敗requestが長時間化する] → timeoutとTask deadlineを維持し、`length`到達後の同条件retryを廃止して総待機時間を抑える。
- [Providerが終了理由またはusageを別fieldで返す] → 既知の2つのLangChain metadata形だけをallowlist正規化し、未知形はraw値を保存せず既存parse動作へ進める。
- [16,384でもlocal Modelがschema出力前に枯渇する] → page 3 probeを新規Run前のgateとし、自動増加や不完全成果物の採用を行わない。
- [入力容量が従来のchunk計算より小さくなる] → 画像予約と安全余白を含む共通のavailable-input計算へ統一し、分割数が増える性能trade-offをTestで可視化する。
- [旧RunをResumeできずDocling処理から再実行になる] → 旧Runを不変のEvidenceとして保持し、誤った設定混在より再現性を優先する。

## Migration Plan

1. 設定境界、token予算計算、truncation分類、optional Failure fieldおよびfingerprint拒否のTestを先に追加する。
2. Settings、LLM Adapter、Task status、Lifecycle表示およびchunk予算を実装し、focused Testと全品質gateを実行する。
3. 旧Runのdirectory hashまたは更新時刻を記録し、新設定での明示Resumeが`tokens.context`と`tokens.output`の差を示して拒否されることを確認する。
4. 保存済みpage 3 payloadを使用して、外部へ本文を残さない単発の逐次Model probeを実行する。
5. probe成功時だけ同じ実PDFから新しいUUIDv7 Translation Runを開始し、Workflowの逐次性、FailureおよびArtifactを確認する。
6. Rollback時はコードと既定設定を直前versionへ戻す。新旧どちらのRunも削除または書換えず、rollback後のfingerprintと一致しないRunはResumeしない。
