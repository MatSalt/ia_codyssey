#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec bash scripts/verify-db.sh backend/tests/integration/test_job_recovery.py backend/tests/integration/test_resume.py
