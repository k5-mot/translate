<!-- markdownlint-disable MD013 MD041 -->

## Context

proposal.mdのWhyを参照。製品利用元はcommon/runs.pyだけで、関連Testはtest_run_repository.pyとtest_terminal_evidence.py。Python 3.12環境にはstdlib uuid7がないが、langchain-core/langsmith経由でuuid-utils 0.17.1が既にlock/環境に存在する。

## Goals / Non-Goals

独自bit生成を廃止し、canonical UUIDv7の公開契約を維持する。新しいID方式、旧UUIDv4対応、Run移動、一般的ID abstractionの追加は行わない。

## Decisions

1. uuid_utils.compat.uuid7を利用元で直接importする。標準uuid.UUIDを返すことをinstalled API実行で確認した。wrapperを残さず、common/identifiers.pyを廃止する。
2. pyprojectにuuid-utils>=0.17.1,<1を明示し、offline lock更新で既存0.17.1とPackage集合を維持する。間接依存任せだと上流の依存変更で直接importが壊れるため、明示依存にする。新しいPackageの追加導入とは区別する。
3. 既存Testのtime/secretsへのmonkeypatchは独自実装のbit配分へ過剰依存しているため、公開型・version・variant・canonical・生成時刻・一意性のTestへ置き換える。Run IDの拒否判定は変更しない。
4. 最新Web資料とinstalled版ではオプション引数の表記差があるため、実環境の無引数APIだけを利用する。将来versionのAPIを仮定して呼ばない。

## Quality Attribute Design

Q-FUNC/Q-PORT: 実際のRun生成とUUID契約を確認。Q-MNT: identifiers importと独自uuid7定義の残存0を検索する。Q-COMP: repository/interoperability/terminal-evidenceを含む回帰Testと型検査。Package集合とversionの前後比較で依存追加導入なしを確認する。

## Lifecycle, Migration and Operations

Run保存内容とUUID表現は同じで、既存Runを移動・変換・削除しない。lockと宣言を同時更新する。削除ModuleはGit履歴から復元可能。正式E2Eは実行中処理と重複させず、新実装で作成するRunを使う。

## Risks / Trade-offs

- [Risk] Package独自UUID型が入り込む → compat APIと標準型のTestを使用。
- [Risk] lock更新で無関係な依存が動く → offline更新と集合/version比較で検出。
- [Risk] dirty Testの既存修正を巻き込む → terminal-evidenceのimport変更だけをstage。

## Migration Plan

明示依存、利用元、Testを同時変更し、identifiers.pyを削除する。失敗時はCodeと宣言を同時にrevertでき、データ移行は不要。

## References

- [uuid-utils公式READMEの標準UUID互換API](https://github.com/aminalaee/uuid-utils#compatibility-with-python-uuid)
- installed uuid_utils/compat/__init__.py（0.17.1）と実行による型確認。
