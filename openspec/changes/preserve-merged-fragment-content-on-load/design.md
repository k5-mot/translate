<!-- markdownlint-disable MD013 MD041 -->

## Context

[proposal.md](proposal.md)のWhyと[調査記録](verification.md)を参照。POSITIONはbody.childrenから結合元参照だけを削除し、LOADはbody展開後にcollectionsを補完する。表ではPOSITIONがcellsだけを変える一方、LOADはgridを優先する。既存reportの結合記録はNORMALIZE/LOADへ渡されない。

## Goals / Non-Goals

**Goals:** POSITIONが自ら変更するDocling文書の参照整合を完結させ、既存LOADの正常な補完処理を維持する。曖昧な結合を入力変更前に回避する。

**Non-Goals:** Doclingの汎用編集Libraryや新たな文書Schema、再開管理、内容ベース除重、読み順アルゴリズム全体の刷新。保存構成の新旧互換やmigrationは導入しない。

## Decisions

### 1. 結合後の文書自体を整合させ、別の除外台帳を持たない

POSITION内で安全な結合を行い、消費した元要素をcollectionsから除いてindexを整理する。残存要素とセルのID、構造上の参照を一括で対応付け直してから既存の原子的保存を行う。処理中の対応表はメモリ内だけとし、LOAD用のskip一覧やWorkflowの完了履歴として保存しない。既存reportは診断だけに使い、結合from/intoと読込み後のIDを追跡できるよう入力IDと出力IDの区別を明示する。

LOADのcollection補完を廃止する案は未参照の正当な要素を失うため不採用。元要素を残して新しい除外metadataを各工程に理解させる案は、同じ内容を二系統で保持しconsumerへの契約を増やすため不採用。空要素への置換も不正なDocling要素を残すため採用しない。

### 2. 所有関係を先に調べ、候補全体を検査してから変更する

文書内の構造上の参照を一度収集し、参照元の要素・fieldを区別する。childrenによる所有、caption参照、cellのparent逆参照を同じ参照数として扱わない。結合元だけでなく結合先も共有されていないことを確認する。同じ親の重複参照、同一要素への結合、外部からの参照を安全に対応付けできない候補は固定理由で警告し保持する。

本文は既存`_continuous`を位置条件として使い、formatting、hyperlink等の表現差や、所有するchildren/Caption等の保全が確定しない場合は結合しない。本文は空白、コードは改行という既存区切りを維持する。位置とprov以外の情報を無条件に先頭要素へ捨ててはならない。

参照treeの再訪問はソート/結合の各呼出内で抑止する。ただしvisitedだけで共有要素の不正な結合を正当化しない。循環など正常な後続読込みを保証できない文書を、本Changeの成功fixtureに読み替えない。一般的な不正Schemaの回復処理は追加しない。

### 3. 表の対応が証明できる範囲だけ結合する

既存の近接・列数条件に加え、セルの始終端・span・ID・所有関係を検査する。初期実装では、両表が同じ単一の`table_cells`または`cells`表現であり、セルを移しても参照対応を一意に保てる場合を結合対象とする。後半の行位置だけを先頭表の行数分移し、列位置・span・本文・その他のセル情報を保つ。セルIDの再割当ては識別子対応表で扱い、両表の`cell/0`を衝突させない。

`grid`のみ、空gridを含む複数表現の併存、未対応セルID、外部cell参照、Caption/childrenの帰属が不確かな候補は両表をそのまま残して警告する。これは表を削除・平文化するfallbackではなく、未変更の各表を既存LOADへ渡す処理である。gridを黙って捨てたり、一方だけを更新して結合成功としない。対応範囲を広げる際も内容・span・所有関係の統合回帰を必須とする。

### 4. 参照fieldだけを対応付けし、文字列replaceを廃止する

既存MERGEの`_remap`に倣い、`self_ref`と`$ref`の値だけを更新する。collectionの完全なindex segmentと、既知のセルID対応を区別し、`#/tables/1`が`#/tables/10`へ前方一致する置換を行わない。本文、URL、asset URI等には触れない。削除によるindex変更も同じ対応表で一度だけ適用し、旧IDと更新済みIDの連鎖置換を避ける。

MERGEのoffset専用APIを任意mappingに使えるとはみなさず、その処理全体を改変して共有基盤を増やさない。導入済み環境にはDocling編集APIがない。今回必要なのは汎用JSON Pointerの再実装ではなく、既存Docling構造の所有・結合・再採番規則であり、既存resolverと標準dict/listを使う。セルself_refは必ずしも実JSON pathではないため、全IDをresolverで解決できるという誤った検査を導入しない。

## Quality Attribute Design

| ID | 手段と証拠 |
| --- | --- |
| Q-FUNC | POSITION→NORMALIZE→LOADで本文/コード/表の一度だけの出力、独立要素、Caption/children、後続参照、cell spanを検査する |
| Q-REL | 共有候補は変更前に拒否し、連鎖結合・再適用で内容件数と参照の不変条件を確認する |
| Q-COMP/Q-MNT | BaseTask、既存関数入口、原子的保存とLOAD補完を維持。共有前処理を使うReview/registerの回帰、新Dependency/永続台帳0件を差分で確認する |
| Q-SEC/Q-INT | 既存reportに参照と固定理由だけを記録し、本文/URL/認証markerの追加転記0件を検査する |
| 性能効率 | 外部呼出0件。所有関係を一度収集し、候補ごとの文書全探索と無制限再帰を避ける |

## Lifecycle, Migration and Operations

全関数の目的説明と既存APIの適用範囲を確認する。回帰Testは既存POSITION Testを拡張し、LOAD単体doubleでなく実POSITION/NORMALIZE/LOADを接続する。新規実sample3 Translation→Microsoft Word PDF→原本とのReviewと利用者目視を別の受入条件として維持する。外部サービス障害中は合成Testで実受入を代替しない。

## Risks / Trade-offs

- [Risk] collection整理で後続indexやcell IDが壊れる → 全参照の同時対応付け、後続index 1/10・連鎖結合・再適用の回帰を行う。
- [Risk] 元表除外でCaptionやgrid後半行が消える → 所有関係/表現を変更前に検査し、不確かな候補は未変更で保持する。
- [Risk] 保守的判定で従来結合した候補を分離する → 内容保持を優先する承認済み方針に従い、固定理由を記録して実成果物で確認する。
- [Risk] 新しい出力IDと過去report IDを混同する → 入出力IDの対応を診断で明確化し、古いRunを修正後の成功証拠として利用しない。

## Migration Plan

既存Artifactの変換・互換読込み・旧実装の併存は行わない。新規処理の前処理に適用して検証する。利用者の既存入力/成果物を削除しない。コードを戻した場合も、旧成果物を本要求に適合した検証済み出力として扱わない。
