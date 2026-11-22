#!/bin/bash
# Show the step-by-step output of the last local run_pipeline.py run (from ~/sparkcheck/logs/pipeline.log)
LOG=~/sparkcheck/logs/pipeline.log
grep -v 'Stage [0-9]' "$LOG" | awk '/Pipeline run .* started/{on=1} on' \
  | grep -v '^\s*\[cell\|^\s*\[%run\|^\s*\[sql\|^+-\|^|\|^\s*$' | head -${1:-60}
