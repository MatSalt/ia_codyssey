"""Verification commands must preserve failed prerequisites and image overrides."""
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]


def test_codec_check_failure_cannot_be_masked_by_pytest_success(tmp_path):
    # Simulate the documented CLI boundary: codec probe fails; later tests pass.
    docker = tmp_path / 'docker'
    docker.write_text(
        '#!/usr/bin/env python3\n'
        'import os, sys\n'
        'args = sys.argv[1:]\n'
        'start = args.index("sh")\n'
        'os.execv("/bin/sh", args[start:])\n'
    )
    python = tmp_path / 'python'
    python.write_text('#!/bin/sh\nif [ "$1" = "-c" ]; then exit 7; fi\nexit 0\n')
    docker.chmod(0o755)
    python.chmod(0o755)
    env = dict(os.environ, PATH=f'{tmp_path}:{os.environ["PATH"]}')
    result = subprocess.run(
        ['sh', str(ROOT / 'scripts/verify-codecs.sh')],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 7, result.stdout + result.stderr


def test_codec_command_honors_explicit_test_image(tmp_path):
    record = tmp_path / 'args.txt'
    docker = tmp_path / 'docker'
    docker.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$DOCKER_ARG_RECORD"\n')
    docker.chmod(0o755)
    env = dict(
        os.environ, PATH=f'{tmp_path}:{os.environ["PATH"]}',
        DOCKER_ARG_RECORD=str(record), MORI_VERIFY_IMAGE='custom-runtime',
        MORI_VERIFY_TEST_IMAGE='custom-tests',
    )
    subprocess.run(['sh', str(ROOT / 'scripts/verify-codecs.sh')], env=env, check=True)
    arguments = record.read_text().splitlines()
    assert 'custom-tests' in arguments
    assert 'custom-runtime' not in arguments
