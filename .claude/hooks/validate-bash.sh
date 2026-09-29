#!/usr/bin/env bash
# Bloqueia comandos destrutivos ou que exporiam segredos. Exit 2 = bloqueia e devolve stderr ao Claude.
set -euo pipefail
cmd=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))')
blocked=('rm -rf /' 'rm -rf ~' 'git push --force' 'git push -f' 'git reset --hard' 'chmod -R 777' 'cat .env' 'git add .env' 'git add -f .env')
for p in "${blocked[@]}"; do
  if [[ "$cmd" == *"$p"* ]]; then
    echo "Comando bloqueado pelo hook: contém '$p'" >&2
    exit 2
  fi
done
exit 0
