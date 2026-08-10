#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash .string-research/assemble.sh              # validate and show diff
  bash .string-research/assemble.sh --apply      # replace the two target files
  bash .string-research/assemble.sh --apply --force

The default is a dry run. --apply refuses to overwrite locally modified target
files unless --force is supplied. Git remains the backup and review mechanism.
EOF
}

apply=0
force=0
for arg in "$@"; do
  case "$arg" in
    --apply) apply=1 ;;
    --force) force=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

root="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "assemble.sh must run inside the mus git checkout" >&2
  exit 1
}
cd "$root"

payload=".string-research/payload/chunks"
pluck_dir="$payload/pluck"
test_dir="$payload/tests"
pluck_target="mus-rs/crates/mus-dsp/src/pluck.rs"
test_target="mus-rs/crates/mus-dsp/tests/pluck_invariants.rs"

mapfile -t pluck_parts < <(find "$pluck_dir" -maxdepth 1 -type f -name 'part-*' | sort)
mapfile -t test_parts < <(find "$test_dir" -maxdepth 1 -type f -name 'part-*' | sort)

if [[ ${#pluck_parts[@]} -ne 7 ]]; then
  echo "expected 7 pluck chunks, found ${#pluck_parts[@]}" >&2
  printf '  %s\n' "${pluck_parts[@]}" >&2
  exit 1
fi
if [[ ${#test_parts[@]} -ne 3 ]]; then
  echo "expected 3 test chunks, found ${#test_parts[@]}" >&2
  printf '  %s\n' "${test_parts[@]}" >&2
  exit 1
fi

# Require the exact contiguous naming sequence. Lexicographic sort is safe
# because the staged names are zero-padded.
for i in 0 1 2 3 4 5 6; do
  expected="$pluck_dir/part-0$i"
  [[ "${pluck_parts[$i]}" == "$expected" ]] || {
    echo "pluck chunk sequence mismatch at $i: ${pluck_parts[$i]}" >&2
    exit 1
  }
done
for i in 0 1 2; do
  expected="$test_dir/part-0$i"
  [[ "${test_parts[$i]}" == "$expected" ]] || {
    echo "test chunk sequence mismatch at $i: ${test_parts[$i]}" >&2
    exit 1
  }
done

tmp="$(mktemp -d "${TMPDIR:-/tmp}/ariadne-assemble.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT

cat "${pluck_parts[@]}" > "$tmp/pluck.rs"
cat "${test_parts[@]}" > "$tmp/pluck_invariants.rs"

pluck_lines="$(wc -l < "$tmp/pluck.rs" | tr -d ' ')"
test_lines="$(wc -l < "$tmp/pluck_invariants.rs" | tr -d ' ')"

[[ "$pluck_lines" -eq 1181 ]] || {
  echo "assembled pluck.rs has $pluck_lines lines; expected 1181" >&2
  exit 1
}
[[ "$test_lines" -eq 363 ]] || {
  echo "assembled pluck_invariants.rs has $test_lines lines; expected 363" >&2
  exit 1
}

# Structural sentinels catch missing or duplicated payload boundaries without
# pretending to be a parser.
grep -q '^pub struct StringNetworkVoice' "$tmp/pluck.rs"
grep -q '^pub fn pluck_note' "$tmp/pluck.rs"
grep -q '^pub fn weave_note' "$tmp/pluck.rs"
grep -q '^pub fn weave_holonomy_defect' "$tmp/pluck.rs"
grep -q '^fn weave_is_path_sensitive_but_deterministic' "$tmp/pluck_invariants.rs"
grep -q '^fn streaming_blocks_equal_offline_render' "$tmp/pluck_invariants.rs"

if grep -q '^//! An extended Karplus-Strong plucked string' "$tmp/pluck.rs"; then
  echo "assembled payload unexpectedly contains the old module header" >&2
  exit 1
fi

printf 'Ariadne payload validated:\n'
printf '  %s (%s lines)\n' "$pluck_target" "$pluck_lines"
printf '  %s (%s lines)\n' "$test_target" "$test_lines"

if [[ $apply -eq 0 ]]; then
  echo
  echo "Dry run only. Proposed diffs follow (a nonzero diff status is expected):"
  git diff --no-index -- "$pluck_target" "$tmp/pluck.rs" || true
  git diff --no-index -- "$test_target" "$tmp/pluck_invariants.rs" || true
  echo
  echo "Run with --apply after reviewing the handoff and current working tree."
  exit 0
fi

if [[ $force -eq 0 ]]; then
  dirty=0
  if ! git diff --quiet -- "$pluck_target"; then
    echo "refusing to overwrite locally modified $pluck_target" >&2
    dirty=1
  fi
  if ! git diff --quiet -- "$test_target"; then
    echo "refusing to overwrite locally modified $test_target" >&2
    dirty=1
  fi
  if [[ $dirty -ne 0 ]]; then
    echo "commit/stash the changes or rerun deliberately with --force" >&2
    exit 1
  fi
fi

install -m 0644 "$tmp/pluck.rs" "$pluck_target"
install -m 0644 "$tmp/pluck_invariants.rs" "$test_target"

printf '\nInstalled payload. Next commands:\n'
printf '  cd mus-rs\n'
printf '  cargo fmt --all\n'
printf '  cargo check --workspace\n'
printf '  cargo test -p mus-dsp --test pluck_invariants -- --nocapture\n'
printf '\nReview with:\n'
printf '  git diff -- %q %q\n' "$pluck_target" "$test_target"
