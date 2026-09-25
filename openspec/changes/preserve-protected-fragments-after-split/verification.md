<!-- markdownlint-disable MD013 MD041 -->

## 2026-09-25: 本文保護記号の廃止と後継

利用者承認済みの後継 [simplify-translation-literal-checks](../simplify-translation-literal-checks/proposal.md) により、本文markerの生成・復元・正規化・一対一保持・未知marker拒否、および固有名詞/略語/識別子の完全一致を成功条件にする要求は廃止する。URL/既知拡張子ファイル名は事後warningとし、構造化CodeとLink先は保持する。

本Changeの履歴・旧Run・過去の検証結果は削除しない。marker専用の未完了受入を成功扱いにせず「後継要求へ置換」として扱う。対象ID・空応答拒否、有限retry、切断時の逐次分割、本文を含まない失敗診断、既存成果物保持、Rule hashによる旧Run拒否は後継Testに残す。新規sample3、Word PDF、比較Review、利用者目視は後継のtasks 3.1〜3.3で追跡し、旧成果物で代用しない。

同期/archive時は本Changeの旧marker Deltaを再適用しない。Deltaを持つChangeは後継仕様との統合後に仕様同期を省略してarchiveする。skip_specsのChangeはその設定を維持する。これはarchive済み・受入完了の宣言ではなく、旧要求を再導入しないための廃止記録である。
