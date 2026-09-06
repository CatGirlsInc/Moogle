from __future__ import annotations

import subprocess
from pathlib import Path

DEFAULT_COMPOSE_FILE = Path("compose.yaml")
GPU_COMPOSE_FILE = Path("compose.gpu.yaml")


def _compose_command(*, gpu: bool) -> list[str]:
    cmd = ["docker", "compose", "-f", str(DEFAULT_COMPOSE_FILE)]
    if gpu:
        cmd += ["-f", str(GPU_COMPOSE_FILE)]
    return cmd


def run_up(*, gpu: bool = False, wait: bool = True) -> int:
    cmd = _compose_command(gpu=gpu) + ["up", "-d"]
    if wait:
        cmd.append("--wait")
    return subprocess.run(cmd).returncode


def run_down(*, gpu: bool = False, volumes: bool = False) -> int:
    cmd = _compose_command(gpu=gpu) + ["down"]
    if volumes:
        cmd.append("--volumes")
    return subprocess.run(cmd).returncode
