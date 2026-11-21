# Shared by test-api, mypy-api and codegen-types: the backend test container
# for THIS tree. Source it, then call `ensure_test_container`; run commands
# with "${DC[@]}" exec -T api ...
#
# One compose project per tree. A fixed name (`src-test`) let a worktree exec
# into a container that mounts ANOTHER tree's api/ and test, type-check or
# codegen that tree's code without a word (2026-11-19: the merged gate ran an
# agent worktree, 1923 vs 1945 tests). The name is the tree's basename plus a
# hash of its full path, so two trees never share a container even when they
# share a basename. Images are per project too: after changing
# api/requirements*.txt or api/Dockerfile, run `./scripts/test-api --rebuild`.
# Source from bash only: under zsh BASH_SOURCE is empty and TREE is wrong.

TREE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
COMPOSE_FILE="$TREE/docker-compose.test.yml"
TREE_SLUG="$(basename "$TREE" \
    | tr '[:upper:]' '[:lower:]' \
    | tr -c '[:alnum:]-\n' '-' \
    | sed 's/--*/-/g; s/^-//; s/-$//')"
TREE_HASH="$(printf '%s' "$TREE" | shasum | cut -c1-8)"
COMPOSE_PROJECT="src-test-${TREE_SLUG:-tree}-${TREE_HASH}"
DC=(docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE")

# The source the running api container mounts at /app, or empty if none runs.
test_container_app_mount() {
  local cid
  cid="$("${DC[@]}" ps -q --status running api 2>/dev/null || true)"
  [[ -n "$cid" ]] || return 0
  docker inspect "$cid" \
    --format '{{range .Mounts}}{{if eq .Destination "/app"}}{{.Source}}{{end}}{{end}}'
}

# Reuse the warm container only if it mounts this tree's api/; otherwise
# (re)create it. Refuses (exit 2) rather than run against another tree.
ensure_test_container() {
  local mounted
  mounted="$(test_container_app_mount)"
  [[ "$mounted" == "$TREE/api" ]] && return 0
  if [[ -n "$mounted" ]]; then
    echo "[test-container] container mounts $mounted, not $TREE/api; recreating" >&2
  fi
  "${DC[@]}" up -d --force-recreate api >/dev/null
  for _ in $(seq 1 20); do
    if "${DC[@]}" exec -T api python -c "import pytest" 2>/dev/null; then
      break
    fi
    sleep 0.5
  done
  mounted="$(test_container_app_mount)"
  if [[ "$mounted" != "$TREE/api" ]]; then
    echo "[test-container] refusing to run: /app is '$mounted', expected $TREE/api" >&2
    exit 2
  fi
}
