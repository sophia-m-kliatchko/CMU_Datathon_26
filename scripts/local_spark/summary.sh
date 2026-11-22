#!/bin/bash
# Print the validation results, counts and errors from the last local run of each notebook.
for f in ~/sparkcheck/logs/*.log; do
  echo "===== $(basename "$f" .log)"
  grep -v 'Stage [0-9]' "$f" | grep -E '^(PASS|FAIL) |NOTEBOOK (OK|FAILED)|Error:|Exception:|AssertionError|^Done\.|->|rows; columns' | grep -v '^\s*$' | head -${LINES_PER:-40}
done
