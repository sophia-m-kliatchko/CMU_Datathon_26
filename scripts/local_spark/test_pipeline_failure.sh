#!/bin/bash
# Check that run_pipeline.py logs a broken step and skips the steps that depend on it:
# step 00 gets an input file that doesn't exist.
EXTRA_WIDGETS="--widget pincode_source=/nonexistent/india_post_pincode_directory.csv" \
  bash "$(dirname "$0")/run_all.sh" pipeline
