# 🧭 CLIとStreamlitでRun Repositoryを共有する

CLIとStreamlitが同じRunを相互に列挙・Resumeできるよう、`TRANSLATE_RUNS_DIR`配下のRun Repositoryを実行状態の唯一の正本とする。呼出元ごとの一時directoryは単純だがStreamlit終了時にcheckpointを失い、任意のCLI出力先を中央DBへ登録する方式は二重正本になるため採用しない。各Runは`inputs/`、`outputs/`および`.workspace/`を持ち、外部の`--output-dir`は成果物のexport先としてだけ扱う。

