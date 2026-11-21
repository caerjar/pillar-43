#!/usr/bin/env bash
# Back up, restore and guard the governance state: levels of consent, withdrawals
# (tombstones), accounts and the ledger. They live in the Docker volume
# `<project>_pillar43_data` with the search index, and `down -v` deletes them.
#
#   scripts/governance.sh backup [dest]      write one verified file outside the volume
#   scripts/governance.sh restore <file> [--force]
#   scripts/governance.sh check              exit 1 unless a backup covers the ledger
#
# dest is a file, or a folder (an existing one, or a path ending in /; default: ./backups, or $PILLAR43_BACKUP_DIR). In a
# folder the file is named governance-<project>-<UTC time>-seq<ledger lines>.sqlite;
# `check` reads the ledger length from that name.
#
# Project: $ARCHIVE_PROJECT (default pillar43). The api container is
# <project>-api-1. Override the way the live state is read with
# GOVERNANCE_STATE_CMD (tests do). CONFIRM_DATA_LOSS=yes lets `check` pass.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${ARCHIVE_PROJECT:-pillar43}"
CONTAINER="${PROJECT}-api-1"
BACKUP_DIR="${PILLAR43_BACKUP_DIR:-$ROOT/backups}"
CLI=(docker exec -i "$CONTAINER" python scripts/archive_cli.py)

die() { echo "$*" >&2; exit 1; }

live_state() {
  if [[ -n "${GOVERNANCE_STATE_CMD:-}" ]]; then
    bash -c "$GOVERNANCE_STATE_CMD"
  else
    "${CLI[@]}" ledger-state
  fi
}

latest_backup() {
  # newest by name: the UTC time in the name sorts
  local f
  f=$(ls -1 "$BACKUP_DIR"/governance-"$PROJECT"-*-seq*.sqlite 2>/dev/null | sort | tail -1 || true)
  echo "$f"
}

cmd_check() {
  local state seq items tomb accts
  if ! state=$(live_state 2>/dev/null) || [[ -z "$state" ]]; then
    state=""
  fi
  if [[ -z "$state" ]]; then
    if [[ "${CONFIRM_DATA_LOSS:-}" == "yes" ]]; then
      echo "Cannot read the records of '$PROJECT' (is it running?); going ahead because CONFIRM_DATA_LOSS=yes." >&2
      return 0
    fi
    cat >&2 <<EOF
Refusing: cannot read the records of '$PROJECT' (is it running?), so there is no
way to tell whether a backup covers them. The data volume holds consent levels,
withdrawals, accounts and the ledger, and this would delete it.
  Start it and run:  ./pillar43 backup
  Or, if you are sure nothing there matters:  CONFIRM_DATA_LOSS=yes
EOF
    return 1
  fi
  seq=$(sed -n 's/^ledger_seq=//p' <<<"$state")
  items=$(sed -n 's/^items=//p' <<<"$state")
  tomb=$(sed -n 's/^tombstones=//p' <<<"$state")
  accts=$(sed -n 's/^accounts=//p' <<<"$state")
  seq=${seq:-0}; items=${items:-0}; tomb=${tomb:-0}; accts=${accts:-0}
  if [[ "$seq" == 0 && "$items" == 0 && "$tomb" == 0 && "$accts" == 0 ]]; then
    return 0   # nothing governance-related to lose
  fi
  local last have=-1
  last=$(latest_backup)
  if [[ -n "$last" ]]; then
    have=$(sed -n 's/.*-seq\([0-9][0-9]*\)\.sqlite$/\1/p' <<<"$last")
    have=${have:--1}
  fi
  if (( have >= seq )); then
    return 0
  fi
  if [[ "${CONFIRM_DATA_LOSS:-}" == "yes" ]]; then
    echo "No backup covers '$PROJECT' ($seq ledger line(s), $items item(s), $tomb withdrawal(s), $accts account(s)); going ahead because CONFIRM_DATA_LOSS=yes." >&2
    return 0
  fi
  cat >&2 <<EOF
Refusing: this deletes the records of '$PROJECT' and no backup covers them.
It would lose: $seq ledger line(s), $items item(s) with their consent levels,
$tomb withdrawal(s), $accts account(s). After a re-intake, withdrawn files
would be registered again.
EOF
  if [[ -n "$last" ]]; then
    echo "Newest backup: $last ($have ledger line(s); the archive has $seq)." >&2
  else
    echo "No backup found in $BACKUP_DIR." >&2
  fi
  cat >&2 <<EOF
  Make one:  ./pillar43 backup
  Or, to delete anyway:  CONFIRM_DATA_LOSS=yes
EOF
  return 1
}

cmd_backup() {
  local dest="${1:-}" seq name
  [[ -n "$dest" ]] || dest="$BACKUP_DIR/"   # default: the backups folder
  TMP_BACKUP=$(mktemp "${TMPDIR:-/tmp}/p43-gov.XXXXXX")
  local tmp="$TMP_BACKUP"
  trap 'rm -f "$TMP_BACKUP"' EXIT
  "${CLI[@]}" backup - >"$tmp" || die "Backup failed; nothing was kept."
  [[ -s "$tmp" ]] || die "Backup failed: the file is empty; nothing was kept."
  # verify the copy that is now on this machine, not the one in the container
  seq=$("${CLI[@]}" backup-check - <"$tmp" | sed -n 's/^ledger_seq=//p') \
    || die "The copy did not verify; nothing was kept."
  [[ -n "$seq" ]] || die "The copy did not verify; nothing was kept."
  if [[ -d "$dest" || "$dest" == */ ]]; then
    mkdir -p "$dest"
    name="governance-$PROJECT-$(date -u +%Y%m%dT%H%M%SZ)-seq$seq.sqlite"
    dest="${dest%/}/$name"
  else
    mkdir -p "$(dirname "$dest")"
  fi
  mv "$tmp" "$dest"
  chmod 600 "$dest"
  echo "Backup written and verified: $dest ($seq ledger line(s))"
}

cmd_restore() {
  local file="${1:-}" force=""
  [[ -n "$file" && -f "$file" ]] || die "Usage: restore <backup file> [--force]"
  [[ "${2:-}" == "--force" ]] && force="--force"
  "${CLI[@]}" backup-check - <"$file" >/dev/null || die "That file is not a good backup; nothing was changed."
  "${CLI[@]}" restore - $force <"$file"
  echo "Restored from $file."
}

case "${1:-}" in
  backup)  shift; cmd_backup "$@" ;;
  restore) shift; cmd_restore "$@" ;;
  check)   cmd_check ;;
  *) die "Usage: scripts/governance.sh backup [dest] | restore <file> [--force] | check" ;;
esac
