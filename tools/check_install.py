"""Install TAB into an empty virtualenv and run the demo out of it.

    python tools/check_install.py

Run this before deploying. `pytest` cannot find what this finds, because pytest
runs in an environment that already has everything.

This project has shipped the same bug twice. `pymupdf` was imported by three
modules and undeclared for a week. `onnxruntime` was needed by the OCR route and
undeclared, because rapidocr 3.x supports four inference engines and deliberately
declares none of them. Both worked here. Both would have died on a fresh box —
the second one did, on the first run of this script, with
`ImportError: onnxruntime is not installed` at startup.

tests/test_packaging.py catches the first kind by reading imports. Only a real
install catches the second, because the missing package is one nobody in this
repo imports by name.

The demo is started from a directory that is NOT the repo, on purpose: anything
resolving a path relative to the working directory passes in development and
fails once a host runs it from somewhere else.

Takes a few minutes, mostly downloading.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = 8099


def main() -> int:
    venv = Path(tempfile.gettempdir()) / "tab-install-check"
    if venv.exists():
        shutil.rmtree(venv, ignore_errors=True)

    print(f"building an empty virtualenv at {venv}")
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, timeout=600)
    python = venv / "Scripts" / "python.exe"
    if not python.exists():
        python = venv / "bin" / "python"

    # Exactly what render.yaml runs.
    print('installing:  pip install ".[ocr]"   (this is what the host does)')
    done = subprocess.run([str(python), "-m", "pip", "install", "--quiet", f"{ROOT}[ocr]"],
                          capture_output=True, text=True, timeout=3600)
    if done.returncode != 0:
        print("INSTALL FAILED\n" + done.stdout[-2000:] + done.stderr[-2000:])
        return 1

    elsewhere = Path(tempfile.gettempdir()) / "tab-not-the-repo"
    elsewhere.mkdir(exist_ok=True)
    script = venv / "Scripts" / "tab-demo.exe"
    command = [str(script)] if script.exists() else [str(python), "-m", "tab.demo"]

    print(f"starting the installed copy from {elsewhere}")
    server = subprocess.Popen(command + ["--port", str(PORT)], cwd=str(elsewhere),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True)
    base = f"http://127.0.0.1:{PORT}"
    try:
        for _ in range(150):
            if server.poll() is not None:
                print("THE SERVER DIED ON STARTUP:")
                print(server.stdout.read()[-2500:])
                return 1
            try:
                urllib.request.urlopen(base + "/api/health", timeout=3).read()
                break
            except OSError:
                time.sleep(1)
        else:
            print("the server never answered")
            return 1

        with urllib.request.urlopen(base + "/", timeout=15) as response:
            page = response.read()
        if b'id="drop"' not in page:
            print("the page came back without its drop zone — package-data is wrong")
            return 1
        print(f"  page      {len(page)} bytes")

        with urllib.request.urlopen(base + "/api/samples", timeout=15) as response:
            found = json.loads(response.read())["samples"]
        if not found:
            print("  no samples in the installed copy — package-data is wrong")
            return 1

        for sample in found:
            request = urllib.request.Request(
                base + "/api/check",
                data=json.dumps({"sample": sample["name"]}).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(request, timeout=300) as response:
                out = json.loads(response.read())
            print(f"  {sample['name']:22} {out['verdict']:<13} via {out['route']:<11} "
                  f"{out['seconds']}s  stored={out['stored']}")
            if out["stored"]:
                print("  a response claimed something was stored")
                return 1
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()

    print("\nthe installed copy works. safe to deploy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
