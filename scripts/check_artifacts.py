"""Build, inspect and test wheel/sdist without importing from the checkout."""

from __future__ import annotations

import hashlib
import json
import os
import runpy
import shutil
import subprocess
import sys
import tarfile
import tempfile
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*arguments: str, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    subprocess.run(arguments, cwd=cwd, env=env, check=True)


def main() -> None:
    dist = ROOT / "dist"
    if dist.exists() and list(dist.iterdir()):
        raise RuntimeError("Use a clean dist directory; never mix tested and stale artifacts")
    run(sys.executable, "-m", "build", "--outdir", str(dist))
    wheels, sdists = list(dist.glob("*.whl")), list(dist.glob("*.tar.gz"))
    assert len(wheels) == len(sdists) == 1
    run(sys.executable, "-m", "twine", "check", "--strict", str(wheels[0]), str(sdists[0]))
    version = runpy.run_path(str(ROOT / "mcp_sequential_thinking/_version.py"))["__version__"]
    if os.environ.get("GITHUB_EVENT_NAME") == "release":
        assert os.environ["GITHUB_REF_NAME"] == "v" + version
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        environment = temporary / "environment"
        venv.EnvBuilder(with_pip=True).create(environment)
        executable = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run(str(executable), "-m", "pip", "install", str(wheels[0]), cwd=temporary)
        runner = temporary / "stdio_smoke.py"
        shutil.copyfile(ROOT / "scripts/stdio_smoke.py", runner)
        smoke_env = {**os.environ, "SMOKE_SOURCE_CHECKOUT": str(ROOT)}
        smoke_env.pop("PYTHONPATH", None)
        run(str(executable), str(runner), cwd=temporary, env=smoke_env)
        run(str(executable), "-m", "mcp_sequential_thinking.server", "--version", cwd=temporary)
        with tarfile.open(sdists[0]) as archive:
            archive.extractall(temporary / "source", filter="data")
        source = next((temporary / "source").iterdir())
        rebuilt = temporary / "rebuilt"
        run(sys.executable, "-m", "build", "--wheel", "--outdir", str(rebuilt), cwd=source)
        with (
            zipfile.ZipFile(wheels[0]) as original,
            zipfile.ZipFile(next(rebuilt.glob("*.whl"))) as rebuilt_wheel,
        ):
            for name in original.namelist():
                if name.endswith(".py") or name.endswith("/METADATA"):
                    assert original.read(name) == rebuilt_wheel.read(name), name
        run(str(executable), "-m", "pip", "freeze", cwd=temporary)
    print(
        json.dumps(
            {
                "version": version,
                "python": sys.version,
                "artifacts": {
                    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in (*wheels, *sdists)
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
