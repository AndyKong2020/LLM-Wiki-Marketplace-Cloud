#!/usr/bin/env bash
set -euo pipefail

repo="https://github.com/AndyKong2020/LLM-Wiki-Marketplace.git"
ref="main"
workdir="${TMPDIR:-/tmp}/llm-wiki-opencode-bootstrap.$$"

cleanup() {
  rm -rf "${workdir}"
}
trap cleanup EXIT

git clone --depth 1 --branch "${ref}" "${repo}" "${workdir}"
bash "${workdir}/plugins/llm-wiki-client-opencode/install-opencode.sh" "$@"
