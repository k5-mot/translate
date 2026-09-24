<!-- markdownlint-disable MD013 MD041 -->

## Context

[proposal.md](proposal.md)のWhyを参照。現行のコピー処理はsource/targetのopenからcopystatまでを一つのtryで囲み、どの失敗でもtarget.unlinkを呼ぶ。RunRepository.createは新Run rootの作成後だけ失敗時にそのrootを除去する。後者の所有境界は維持し、前者に同じ区別を設ける。

## Goals / Non-Goals

**Goals:** コピー先作成の成否に基づく後始末、コピー内容のhash/size、元の失敗の伝播を既存の小さな関数で満たす。標準APIとの契約比較を記録し、独自copy/hashループを除去する。

**Non-Goals:** commonの配置承認、新layout移行、登録manifestの設計変更、入力元の並行更新禁止、全filesystem処理の再設計、敵対的な外部processによるpath置換への新しいsandbox。これらの未解決事項を本Changeの修正で解消したとは扱わない。

## Decisions

### 1. 排他的作成成功を後始末の境界とする

sourceを開き、targetを排他的に新規作成できた場合だけ、関数内のlocal値で作成成功を保持する。例外処理はその場合だけtargetの削除を試みる。事前exists判定では作成までの競合を防げないため、作成操作そのものの成否を使用する。このlocal値は永続化せず、Task完了やResume判定には使用しない。

streamのclose後にcleanupへ入る配置を維持する。cleanupのOS Errorは既存contextlib.suppressへ委譲し、元のcopy例外をbare raiseで再送出する。削除失敗を成功に変えず、呼出元の新Run root cleanupとmetadata未公開を維持する。cleanup不能な残存Fileを利用可能な入力と解釈しない。

### 2. 既存APIへcopy/hashを委譲する

Python 3.12.9の標準APIを比較した。

| API | 採否と理由 |
| --- | --- |
| Path.openのx mode | 採用。新規作成に限定し既存先を上書きしない |
| shutil.copyfile | 不採用。宛先をwbで開くため排他的作成と契約が異なる |
| shutil.copyfileobj | 採用。開いたstream間を固定上限bufferでコピーできる |
| hashlib.file_digest | 採用。コピー先の保存内容を有限bufferでhash化できる |
| shutil.copystat、flush、os.fsync | 既存使用を維持。内容copyとは別のmetadata・同期契約 |
| contextlib.suppress(OSError) | 作成済みtargetの例外時cleanupだけに使用。保存失敗そのものを握り潰さない |

targetを`x+b`で作成し、copyfileobjのbuffer上限は従来と同じ1 MiBとする。copy後にsizeを取得し、flush/fsyncとseek(0)後にfile_digestで宛先を読む。file_digest後のstream位置は契約に依存させず、sizeは先に取得する。copystatはclose後の既存位置に残す。

hashは再読したsourceではなく、実際に保存されたtargetのbyte列から求める。新しいtee/hash writer、copy framework、独自hash loopは作らない。2段階処理には宛先の読戻しが増えるが、単一passは既存OpenSpecの要件ではない。有限memoryと内容一致を維持し、③-2のLibrary再利用を優先する。

### 3. 検証境界

- helperだけのmockではなく、一時領域に既存の合成targetを用意し、FileExistsError後もbyte列が不変であることを確認する。source open失敗時はtarget.open/unlink未実行も確認する。
- 作成後のread/write/flush/fsync/hash/copystatへ障害を注入し、close後cleanup、元例外伝播、source不変を確認する。cleanupのPermissionErrorが元の失敗を置換しないことも検査する。
- 正常な空Fileと複数buffer分のFileでcopy/size/SHA-256一致、正数上限付きread、標準API委譲、metadata保存を検査する。read_bytes禁止だけをmemory検証の代わりにしない。
- 公開準備経路では新Runのコピー失敗でmetadataを公開しないことと、固定UUIDv7でのroot衝突が既存Runを変更しないことを確認する。Modelを起動する必要はない。
- 先行する実Model processの終端後に、新Codeのtranslation→Word PDF→Comparison Reviewを逐次実行し、自動検査と別に記録する。

### 4. grill-with-docsと用語の整理

判断の根は「今回作成していない既存データを削除しない」と「標準機能を再実装しない」という既決定の原則。作成前の失敗/作成後の失敗/cleanupの失敗を上の境界へ対応付けた。配置・旧形式移行・表内画像の曖昧時動作という回答待ちの枝とは独立している。

「作成成功」は関数呼出内の資源取得結果であり、CONTEXT.mdのRun状態やArtifact完了を指さない。Domain用語を変更せず、不可逆な構成判断もないため新しいGlossaryやADRは作らない。提案を提示した後のapply依頼で実装着手を確認する。

## Quality Attribute Design

Q-REL/Q-SECは作成境界・close後cleanup・元失敗維持を障害注入で検証する。Q-MNTは標準APIへ委譲し、新moduleと独自stream層を0件にする。Q-PERFは1 MiBのcopy bufferと標準file_digestの有限bufferを用い、入力全体のmemory保持を避ける。Q-COMP/Q-PORTは戻り値・既存layoutを変更せず、Windowsと既存CIのTestで確認する。

## Lifecycle, Migration and Operations

過去Run・入力・成果物を移動または削除しない。修正は今後起動するprocessへ適用し、現在の実翻訳は再起動しない。所有していない入力へのcleanupを防ぐ変更であり、過去の実データ喪失があったことを前提にした復元処理は追加しない。

## Risks / Trade-offs

- [Risk] 宛先の読戻しでI/Oが増える → bufferを有限に保ち、実PDFで所要時間と内容整合を記録する。速度改善や単一passは主張しない。
- [Risk] open成功後に外部processがpathを置換すればlocal値だけでは現在のFile所有を保証できない → 完全な敵対的競合対策と混同せず、既存の新Run専用directory境界を維持する。新たなpath置換防御が必要と判明した場合は別途範囲を提示する。
- [Risk] cleanupのOS Errorを抑止すると残骸が残る → 元の保存失敗は維持し、metadataと成功を公開しない。残骸を有効Runへ自動復旧しない。

## Migration Plan

先に既存target保全の失敗Testを追加し、最小修正と標準API委譲後に障害注入・正常copy・公開準備・全体品質を検証する。実機Gateと利用者目視が揃うまでINPUT-COPY-001を最終解決にしない。DB migrationは不要。code rollbackは可能だが、旧cleanup不具合を復活させるため安全性回復とは扱わない。

## 調査資料

導入済みPython 3.12.9の`pathlib.py`、`_pyio.py`、`shutil.py`、`hashlib.py`、`contextlib.py`、既存runs.py/workspace.py/lifecycle.pyと入力manifest Testを確認した。APIのread-only調査とBytesIO/Mock試験は実File・実Serviceを使用しない。外部Web資料へは依存していない。
