# Verification: serialize-detached-evidence-io

## 中間判定（2026-09-25）

**検証失敗・未完了。archive不可。** 利用者の設計確認への回答を優先するため、製品修正は途中状態で保持する。

- 修正前の追加Testで無排他read、不正JSON処理漏れ、既存library非利用の3件を再現（3 failed/2 passed）。
- 修正後の対象Testは25 passed。Ruff/format/全体tyとOpenSpec strictは成功。
- 高頻度I/O・終端回収・公開convertの3 Testを10回反復し、command exit 0を確認。
- ただし全体pytestは**286 passed / 1 failed / 1 skipped**。高頻度I/O Testの親watchdogがEvidenceStore.write → atomic_write_json → Path.replaceでWinError 5を再現した。読書きを同じlockへ寄せただけでは十分と証明できない。
- この実行では全体suiteと反復Testは別temp pathで同時に動いていた。外部LLM/Embeddingはどちらも呼ばない。異なるtemp pathなので同一ファイルの競合とは断定できず、負荷条件の影響も含め追加切分けが必要。
- parent/child以外のhandle、lock前のpath存在確認/解決などは原因候補であり、未確定。任意のPermissionErrorを無視して通す修正は行っていない。
- 反復commandのhandleは終了（exit 0）。対象python processが残っていないことも確認。中断を理由にRunを再起動していない。
- Tasks 1.1/1.2の機能Testは成功したが、統合・全体品質の2.1/2.2は未完了のまま。型修復済みChangeと他の既存未commit差分は保持する。

## 再検証（2026-09-25 10:21 JST）

Using change: `serialize-detached-evidence-io`。OpenSpec rootは当Repository、schemaはmysdd、skip_specs=true。proposal/design/tasksと現在の実装を照合した。製品Code、Test、既存Run、設定は変更していない。

### 対象と実装対応

- `terminal_evidence.py:28`は既存portalockerへ10秒の取得期限を委譲する。`EvidenceStore.write/read`は同じFile別lockを使用し、取得済みwriteからは`_read_locked`を呼んで再入取得を避ける。
- `_read_locked`はJSON/schema不正をNoneへ変換する一方、PermissionErrorを成功・欠落へ変換しない。古いrunning更新からterminalを保護する判定も同じlock内にある。
- `_read_heartbeat`とchildのheartbeat保存はEvidenceStoreへ委譲する。旧OS別lockと未使用helperは除去済みだが、これらの実装差分は未commitのままである。
- 既存の決定的Testは読書き時のlock深さ・取得回数、有限取得設定、不正JSON/schema、例外時解放、旧版保持、終端保護、権限障害の伝播を検査している。実親子Testと組み合わせて確認した。

### 実行結果

- 実行前にCIMで対象CLI/診断child/pytestの既存processがないことを確認した。
- `uv run pytest tests/test_terminal_evidence.py -q`: **25 passed、6.56秒**。
- 高頻度Evidence/heartbeat I/O、stdoutなし終端回収、公開convertへの委譲の3 Testを、別々のpytest起動で**20回逐次反復、60/60成功**。session 38204はexit 0。各高頻度Testはchildが100回両JSONを更新し、親は1ms間隔で監視する。exit 0、completed、100/100、保存終端の再読取りを確認した。LLM/Embeddingは呼ばない。
- 反復終了後に全体Testを実行し、負荷条件を混在させなかった。`uv run pytest -q`: **656 passed / 1 skipped、42.21秒**、session 40722はexit 0。PYTHONUTF8などの追加環境指定は行っていない。
- 対象2 filesのRuff check/format、全体ty、OpenSpec strictは成功。既存configの未知operation `verify`警告は今回の対象外で、変更していない。
- 検証対象はHEAD `5946b6e`に既存未commit差分を含むworktreeであり、commit単独の検証ではない。terminal_evidence.pyのSHA-256は`881339c47e68857e782f21b4d7c2e2609c65ab4e6458584c3a5e6c1cd565b6f8`、同Testは`a9f297005d194123513e13b8ced47792a64f5849728b91300346ae3d516e1e2f`。無関係なFailureKind拡張を含む既存差分を今回のcommitへ取り込まない。

### Verification Report

| Dimension | 判定 |
| --- | --- |
| Completeness | tasksは2/4。2.1の反復・2.2の品質commandについて新しい成功証拠を取得したが、既知競合の最終受入は未完了 |
| Correctness | 排他境界・安全な失敗・終端保持のTestは成功。過去の修正後WinError 5は今回非再現であり、原因除去は未証明 |
| Coherence | 既存library利用、有限待機、二重lock回避、新依存なし。公開仕様のDeltaはないためScenario照合はproposal/designと既存Testを対象とした |

**CRITICAL:** 過去に同じ排他修正後の全体Testで起きたPath.replaceのWinError 5について、原因とそれを防ぐ回帰証拠が未確定。今回の反復成功で過去失敗を取り消さない。Tasks 2.1/2.2の最終判定とarchiveは保留する。次は失敗時の操作・対象File・handle所有を観測して切り分ける。`EvidenceStore.__init__`のpath.resolveとreadの存在確認はlock外だが、それらが原因だとはまだ断定しない。任意のPermissionErrorを無視する修正は認めない。

**WARNING:** 実translation→Microsoft Word PDF→Comparison Reviewは未実施。最新OFF翻訳が保護記号欠落で停止している別問題を本Testで代替しない。今回の変更は検証記録だけで、common配置・再開の二重管理・利用者判断待ちも解決済みにしない。

**最終判定: 自動検査は成功、Changeの正式verifyは未合格。archive/main merge/push不可。** 元の監査指摘には本節を参照し、既存の未完了Checkboxは維持する。

## 追加診断: lock外のパス解決を含む置換競合（2026-09-25）

`diagnosing-bugs`に従って既存Testの反復から、モデル・Workflow・watchdogを除いた合成JSONの実親子I/Oへ縮小した。PowerShell here-stringを`uv run python -X utf8 -`へ渡し、所有するTemporaryDirectory内で既存EvidenceStoreを呼んだ。子processは期限付きで終了を回収し、既存Runは使わない。製品Code、Test File、設定は変更していない。

### 再現と比較

1. Repository直下の一時領域で、parentはEvidenceStore.write、childはEvidenceStore(path).readを繰り返した。各12秒上限の3試行中**2試行でwriterのPermissionError / WinError 5**。失敗前のwrite件数は847、223、非再現試行は1253。childは全試行exit 0で、JSON読取りエラーは0。session 66199は終端exit 0で、試験scriptの終了値ではなく各試行のerror欄を判定した。
2. 仮説を利用者へ「constructorのresolve」「exists/read」「reader以外の置換障害」の順に提示し、childの処理だけを替えた。Repository内ではresolve-onlyは2/2失敗（各22 write後）、exists-onlyは1/2失敗、reader使い回しは1/2失敗、writer単独も2/2失敗した。従って、この場所の全障害をresolve一つに帰属させることはできない。session 57248は全childを回収してexit 0。
3. writer単独へ縮小し、例外の型・WinError・直前phase・関数名/行だけを観測した。Repository内は3試行中1失敗（881 write後）、OS一時領域は3試行とも非再現（1060/1092/1170 write）。失敗位置は`EvidenceStore.write → atomic_write_json → atomic_write_text → atomic_write_bytes:71 → Path.replace`、phase=replace。session 97252はexit 0。保存先以外にも時刻・OS負荷が変わる少数試行なので、特定の監視ソフトや保存先そのものを原因と断定しない。
4. OS一時領域でchildのresolveを既存lockで囲む差分だけを比較した。各5秒上限の結果は次のとおり。session 56291はexit 0、全childもexit 0。

| childの操作 | 試行1 / parent write件数 | 試行2 / parent write件数 |
| --- | --- | --- |
| path.resolveのみ、lock外 | WinError 5 / 22 | WinError 5 / 28 |
| 同じpath.resolveを既存_evidence_lock内で実行 | エラーなし / 661 | エラーなし / 653 |
| path.existsのみ、lock外 | エラーなし / 666 | エラーなし / 745 |

実際のheartbeat読取りは毎回`EvidenceStore(heartbeat_path)`を作り、そのconstructorは`path.resolve()`をlock外で実行する。上記はこの標準APIに起因する競合条件を実機で再現しており、「JSON本文のread/writeだけを排他すれば十分」という前提を否定する証拠である。存在確認だけの非再現は、そのAPIの任意条件での安全性を証明しない。

### 標準APIの根拠と結論

実行Pythonは3.12.9。対応するCPython公式Sourceの`os__getfinalpathname_impl`はCreateFileWのshare modeに0を渡し、最終path取得後にhandleを閉じる。パス解決は単なる文字列処理ではなく、その間の共有を制限するFile操作を含む。この実装と差分試験は、lock外のresolveが置換と競合する説明に整合する。一方、Repository内のwriter単独失敗にはreaderのresolveがないので、追加原因の切分けが必要である。

**次の修正・検証範囲:** Tasks 2.1/2.2は未完了を維持する。constructor/heartbeatのパス解決を含むhandle取得と存在確認を排他設計へ含め、同じ競合を検出する回帰Testを追加する。パス正規化・リンク・temp root外という既存安全境界を暗黙に変えず、readerを使い回すだけで全経路が直るとは扱わない。writer単独の失敗は別に追跡し、根拠のないPermissionError無視・無制限retryは追加しない。

今回は診断のみであり、修正済み・正式verify成功・archive可能とは判定しない。所有する試験用TemporaryDirectoryは各試行終了後に自動削除され、再現用の合成JSONだけが対象である。利用者の入力・成果物・Checkpointを削除していない。

### 参考資料

- [CPython 3.12.9 posixmodule.c: os__getfinalpathname_impl](https://github.com/python/cpython/blob/v3.12.9/Modules/posixmodule.c#L4518-L4579): 使用中VersionのWindowsパス解決実装。先に参照した3.12.12ではなく3.12.9を根拠とした。

## Apply: パス操作の排他拡張（2026-09-25）

既存Changeの「全Evidence/heartbeat I/Oを直列化する」設計を補足し、Task 1.3を追加して実装した。constructorは指定Fileの既存lock内でPath.resolveを呼び、readの存在確認もlock内へ移した。既存portalocker、Path.resolve、atomic writeを再利用し、retry・依存・Module・公開仕様は追加していない。最終File symlinkの異名を使う場合のlock identityを今回統一したとは扱わない。

### Test先行と回帰結果

- 実`_read_heartbeat`を呼ぶ追加Testは旧実装で`heartbeat resolve outside lock`により失敗した（1 failed / 1 passed）。constructorだけ修正した段階でも`heartbeat exists outside lock`で失敗し、両箇所を直した後に成功した。Testは既存lockと標準Path APIへ委譲しつつ取得範囲を観測するもので、別の保存実装へ置換していない。
- 解決失敗のPermissionError伝播と次のreaderの成功、相対pathの正規化、`..`経由のtemp内部Evidence拒否を追加確認した。未作成EvidenceのTestをtmp_path配下へ移し、constructorで作成するlock/親directoryをRepository直下へ残さないようにした。
- 対象Testは最終**28 passed、6.82秒**。Test doubleのbool位置引数について初回Ruffが4件指摘したためkeyword-onlyへ修正し、Ruff check/formatを再実行して成功した。
- 全体Ruff check、format（340 files）、ty、OpenSpec strict、git diff --checkは成功。`uv run pytest -q`は**659 passed / 1 skipped、41.05秒**、session 37579はexit 0。
- OS一時領域でconstructor/readとwriteを競合させる実親子試験を6秒上限で3回行い、全child/parent exit 0。writer件数804/739/797、reader件数740/902/691でエラーなし（session 58547）。
- 続いて元と同じRepository内・各12秒の再現試験を3回実行すると、**全試行でwriterのWinError 5が残った**。writer件数1927/812/251、childは全てexit 0。session 54188は失敗assertによりexit 1。全体Test成功やOS一時領域の非再現で、この結果を取り消さない。

### 引継ぎと判定

**3/5 Tasks完了。** 1.1/1.2の既存未commit修正と今回の1.3を、同じ診断I/Oの論理変更としてcommitする。別ChangeのFailureKindへのcontext-exceeded追加はindexから除外し、worktreeに保持する。LLM/REVIEW/Lifecycle、設定、`.agents`、サンプル、outputs/runsの差分は含めない。検査は既存の未commit差分を含むworktreeで行ったため、commit単独の検証とは区別する。

検査時SHA-256: terminal_evidence.pyは`565b29f970313de1653e1601b6c1851f43fb59553cf715de12ca4ce89be9de18`、Testは`b1cd44ea4ebebf9b94444accba14b81a6876aaef021858fb18c30689f0902621`。製品Fileの値は上記の除外対象FailureKindも含むworktreeのhashである。

Tasks 2.1/2.2は統合受入未完了を維持する。既知の排他漏れは回帰Test付きで修正したが、writer単独でも起きる置換失敗について原因・handle所有の追加確認が必要。任意のPermissionErrorを握り潰して合格にする修正は行わず、applyをここで中断する。translation→Word PDF→Reviewも未実施であり、正式verify・archive・main merge/pushは行わない。今回の試験用一時領域だけを自動cleanupし、利用者Runは変更・削除していない。

## 標準APIだけの再現とWindows照会（2026-09-25）

修正commit `4a06c0a`後の残件について、`diagnosing-bugs`でwriter単独まで縮小した再現を継続した。仮説は「他processの一時handle」「置換先の属性」「一時File側の障害」として利用者へ提示し、合成File以外の内容を表示せず調べた。

### 失敗直後の観測

既存EvidenceStoreのPath.replaceを観測用にprocess内だけで包み、実PermissionError発生後、cleanup前のsource/targetをWindows Restart Managerへ登録してRmGetListで照会した。RmStartSession/RegisterResources/GetList/EndSessionだけを使用し、Shutdown/Restartは呼んでいない。追加PackageやToolの導入はない。

- writer単独3試行中、1回でWinError 5（946 write後）。後続2回は各12秒で非再現（2116/2212 write）。session 5194はexit 0。
- エラーのsourceは所有一時領域内、destinationは合成targetと一致。両者のFile attributesは32で、読取り専用bitは立っていなかった。
- Restart Managerの各APIは0（成功）、必要process数0・PID一覧空。これは照会時点で捕捉できなかったという意味であり、瞬間的handleやkernel側の関与がない証拠ではない。
- `handle`/`handle64`/`procmon`/`procmon64`はPATHから見つからなかった。Repository root自身はDirectoryで、LinkType/Target表示なし。配下全体やfilesystem filterの安全性を保証する検査ではない。

### 製品Codeを使わない対照試験

次に、プロジェクトModule・第三者Package・reader・lockをすべて除去した。標準Libraryだけで、所有TemporaryDirectory内にmkstemp → 17 bytesの固定JSONを書込み → flush/fsync → close → os.replaceを繰り返した。PowerShell here-stringから`uv run python -X utf8 -`で実行した。

| 保存場所 | 試行 / 判定 | 置換成功件数 |
| --- | --- | --- |
| Repository直下の新規一時領域 | 3/3でWinError 5、失敗assertでexit 1 | 66 / 16 / 114 |
| OS一時領域の新規一時領域 | 各8秒、3/3非再現、session 70810 exit 0 | 7239 / 7373 / 7338 |
| runs/配下の新規一時領域 | 2/2でWinError 5 | 1472 / 1715 |
| outputs/配下の新規一時領域 | 2/2でWinError 5 | 119 / 349 |

git check-ignoreでruns側は除外対象、outputs側は非除外と確認したが、両方で再現した。従ってGitのignoreだけでは説明できない。場所と試行時刻が同時に変わる対照であり、特定の常駐ソフト・OS機能を原因と断定しない。

### 判断と次の調査条件

残る失敗は製品のEvidenceStore・portalocker・JSON parserを使わなくても再現する。これらを再実装する修正で解消できるという根拠はない。既知のパス操作の排他修正は保持し、原子的置換を非原子的保存へ弱めたり、任意のPermissionErrorを成功扱いにしたりしない。

原因processの特定には、失敗瞬間のFile操作を観測する追加手段が必要。Microsoft Process Monitorによる合成File対象の採取を利用者へ確認する。未承認のダウンロード・起動・監視・常駐ソフト停止・セキュリティ設定変更は行っていない。ログ採取時にも他Fileのpath/command line等を不用意に共有しない。製品依存への追加は提案していない。

今回変更したのは検証記録のみで、LLM/Embedding・Word・利用者Runは使っていない。生成した合成一時領域はcleanup済みで、元の入力・成果物を削除していない。Tasks 2.1/2.2および実translation→Word PDF→Reviewの受入は未完了、archive不可を維持する。

### 参考資料（今回使用）

- [Microsoft: RmGetList](https://learn.microsoft.com/en-us/windows/win32/api/restartmanager/nf-restartmanager-rmgetlist)、[RM_PROCESS_INFO](https://learn.microsoft.com/en-us/windows/win32/api/restartmanager/ns-restartmanager-rm_process_info)、[RmRegisterResources](https://learn.microsoft.com/en-us/windows/win32/api/restartmanager/nf-restartmanager-rmregisterresources)、[RmStartSession](https://learn.microsoft.com/en-us/windows/win32/api/restartmanager/nf-restartmanager-rmstartsession): 使用した照会APIの型・引数・戻り値。
- [Microsoft: Process Monitor](https://learn.microsoft.com/en-us/sysinternals/downloads/procmon): File操作とprocess情報を観測する追加手段。未導入・未実行。
