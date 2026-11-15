#!/usr/bin/env bash
set -euo pipefail
# mutmut writes full source copies under mutants/; pytest would collect them as duplicate
# test modules (module-name collisions, 19 phantom collection errors). Always remove them.
trap 'rm -rf mutants' EXIT

MUTATION_MIN="${MUTATION_MIN:-80}"
COVERAGE_MIN="${COVERAGE_MIN:-90}"

# Two callers: ticket 00's Interface (arg = <base-ref>) and the build harness gate.sh
# (args = changed files, base via GATE_BASE or merge-base with develop).
if [ "$#" -ge 1 ] && git rev-parse --verify --quiet "$1" >/dev/null; then
  base="$1"
else
  base="${GATE_BASE:-$(git merge-base HEAD develop)}"
fi

uv run pytest -q --cov=watcher --cov-report=xml:/tmp/watcher-cov.xml
uv run diff-cover /tmp/watcher-cov.xml --compare-branch="$base" --fail-under="$COVERAGE_MIN"
if [ "${GATE_MUTATION:-on}" = "off" ]; then
  echo "GATE-EXTRA: pass (coverage only; mutation runs in CI)"
  exit 0
fi
uv run mutmut run --max-children 4 >/dev/null || true
score=$(uv run mutmut results --all true | python3 -c '
import sys

killed = 0
total = 0
for line in sys.stdin:
    if ": killed" in line:
        killed += 1
        total += 1
    elif ": survived" in line or ": timeout" in line or ": suspicious" in line:
        total += 1
if total == 0:
    sys.exit(3)  # no mutants ran: a silent pass would hide a broken mutmut run
print(int(killed / total * 100))
')
[ "$score" -ge "$MUTATION_MIN" ] || { echo "mutation score $score < $MUTATION_MIN"; exit 1; }
echo "GATE-EXTRA: pass (mutation $score)"
