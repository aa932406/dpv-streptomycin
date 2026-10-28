#!/usr/bin/env python3
"""One-click launcher for the DPV web app (Windows / Linux / macOS).

Called by run_web.bat on Windows. Does everything a human would do by hand:

  1. create .venv if it is missing
  2. install Python dependencies when requirements.txt changed
  3. npm install / npm run build when web/ is missing a build (or changed)
  4. start the FastAPI backend and the Next.js frontend in separate windows
  5. wait until both answer, then open the browser

Usage:
    python scripts/launch_web.py                # normal start (port 3000)
    python scripts/launch_web.py --port 3100    # different frontend port
    python scripts/launch_web.py --check        # only verify prerequisites
    python scripts/launch_web.py --no-new-console  # keep logs in this window
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
WEB = ROOT / "web"
REQ = ROOT / "requirements.txt"
STAMP = VENV / ".deps.json"
LOGS = ROOT / "logs"

IS_WIN = os.name == "nt"


def say(msg: str = "") -> None:
    print(msg, flush=True)


def fail(msg: str) -> "NoReturn":  # type: ignore[valid-type]
    say()
    say("[ERROR] " + msg)
    sys.exit(1)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")


def npm_cmd() -> str:
    return "npm.cmd" if IS_WIN else "npm"


def run(cmd: list[str], cwd: Path | None = None, quiet: bool = False) -> None:
    if not quiet:
        say("    $ " + " ".join(cmd))
    res = subprocess.run(cmd, cwd=str(cwd or ROOT))
    if res.returncode != 0:
        fail("command failed (%d): %s" % (res.returncode, " ".join(cmd)))


def http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 400
    except Exception:
        return False


def tail_log(name: str, lines: int = 25) -> str:
    p = LOGS / (name + ".log")
    if not p.exists():
        return "(no log yet)"
    text = p.read_text("utf-8", "replace").splitlines()[-lines:]
    return "\n".join("    " + ln for ln in text)


def wait_http(url: str, seconds: float, label: str, proc=None) -> bool:
    t0 = time.time()
    while time.time() - t0 < seconds:
        if http_ok(url):
            return True
        if proc is not None and proc.poll() is not None:
            say("    ! %s exited with code %s" % (label, proc.returncode))
            return False
        time.sleep(0.6)
    say("    ! %s did not answer within %d s: %s" % (label, seconds, url))
    return False


# ---------------------------------------------------------------- step 1: venv
def ensure_venv() -> Path:
    py = venv_python()
    if py.exists():
        say("[1/5] Python environment ready")
        return py
    say("[1/5] Creating .venv (first run only, about 20 s)")
    run([sys.executable, "-m", "venv", str(VENV)])
    if not py.exists():
        fail("venv creation finished but %s is missing" % py)
    return py


# ---------------------------------------------------------------- step 2: deps
def deps_stamp() -> str:
    mtimes = [REQ.stat().st_mtime if REQ.exists() else 0.0]
    return json.dumps({"req": max(mtimes), "py": sys.version_info[:2]})


def ensure_deps(py: Path) -> None:
    want = deps_stamp()
    if STAMP.exists():
        try:
            have = json.loads(STAMP.read_text("utf-8"))
        except Exception:
            have = {}
        if have.get("req") == json.loads(want)["req"]:
            say("[2/5] Python dependencies up to date")
            return
    say("[2/5] Installing Python dependencies (first run about 1-2 min)")
    run([str(py), "-m", "pip", "install", "-q", "--upgrade", "pip"], quiet=True)
    run([str(py), "-m", "pip", "install", "-q", "-r", str(REQ)])
    STAMP.write_text(want, "utf-8")


# ------------------------------------------------------------- step 3: web build
def newest_mtime(paths: list[Path]) -> float:
    best = 0.0
    for p in paths:
        if p.is_file():
            best = max(best, p.stat().st_mtime)
        elif p.is_dir():
            for f in p.rglob("*"):
                if f.is_file() and "node_modules" not in f.parts and ".next" not in f.parts:
                    best = max(best, f.stat().st_mtime)
    return best


def missing_packages() -> list[str]:
    """Dependencies listed in package.json that are not actually in node_modules.

    Checking only "does node_modules exist" is how a project breaks after someone
    adds a dependency: the folder is there, the new package is not, and the build
    dies on "Module not found: Can't resolve '@radix-ui/react-slot'".
    """
    pkg = json.loads((WEB / "package.json").read_text("utf-8"))
    want = list(pkg.get("dependencies", {})) + list(pkg.get("devDependencies", {}))
    nm = WEB / "node_modules"
    return [d for d in want if not (nm / d / "package.json").exists()]


DEPS_STAMP = WEB / "node_modules" / ".dpv-deps.json"


def deps_hash() -> str:
    """Fingerprint of the dependency lists, so a changed package.json is detected
    without trusting file mtimes (they change on every copy, unzip or git checkout)."""
    pkg = json.loads((WEB / "package.json").read_text("utf-8"))
    blob = json.dumps(
        {"d": pkg.get("dependencies", {}), "dev": pkg.get("devDependencies", {})},
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def node_modules_stale() -> bool:
    if not (WEB / "node_modules").exists():
        return True
    if missing_packages():
        return True
    try:
        return json.loads(DEPS_STAMP.read_text("utf-8")).get("hash") != deps_hash()
    except Exception:
        return True


def ensure_web(check_only: bool = False) -> None:
    if not (WEB / "package.json").exists():
        fail("web/package.json not found -- is the folder complete?")
    if shutil.which(npm_cmd()) is None:
        fail(
            "npm not found. Install Node.js 20 or newer from https://nodejs.org/ "
            "and reopen the terminal."
        )
    if node_modules_stale():
        miss = missing_packages()
        note = ""
        if miss:
            head = ", ".join(miss[:4]) + (" ..." if len(miss) > 4 else "")
            note = " -- %d package(s) from package.json are not installed: %s" % (len(miss), head)
        if check_only:
            say("[3/5] frontend dependencies need installing" + note)
            return
        say("[3/5] Installing frontend dependencies (about 1 min)" + note)
        run(npm_run("install"), cwd=WEB)
        DEPS_STAMP.write_text(json.dumps({"hash": deps_hash(), "at": time.strftime("%Y-%m-%d %H:%M:%S")}), "utf-8")

    build_id = WEB / ".next" / "BUILD_ID"
    srcs = [WEB / "app", WEB / "components", WEB / "lib", WEB / "next.config.ts",
            WEB / "package.json", WEB / "tsconfig.json", WEB / "postcss.config.mjs"]
    stale = (not build_id.exists()) or (newest_mtime(srcs) > build_id.stat().st_mtime)
    if stale:
        if check_only:
            say("[3/5] frontend needs a build -- would run npm run build")
            return
        say("[3/5] Building frontend (first run about 1 min)")
        run(npm_run("run", "build"), cwd=WEB)
    else:
        say("[3/5] Frontend build up to date")


# ------------------------------------------------------------- step 4: services
HANDLES: list = []


def npm_run(*args: str) -> list[str]:
    """npm on Windows is a .cmd shim; route through cmd.exe so Popen never guesses."""
    if IS_WIN:
        return ["cmd", "/c", "npm", *args]
    return ["npm", *args]


def spawn(cmd: list[str], cwd: Path, env: dict, title: str, mode: str) -> subprocess.Popen:
    """mode='log' -> output to logs/<title>.log (default); mode='console' -> own window."""
    if mode == "console" and IS_WIN:
        return subprocess.Popen(cmd, cwd=str(cwd), env=env,
                                creationflags=subprocess.CREATE_NEW_CONSOLE)
    LOGS.mkdir(exist_ok=True)
    log = LOGS / (title.lower().replace(" ", "_") + ".log")
    fh = open(log, "ab", buffering=0)
    HANDLES.append(fh)
    fh.write(("\n===== %s =====\n" % time.strftime("%Y-%m-%d %H:%M:%S")).encode())
    return subprocess.Popen(cmd, cwd=str(cwd), env=env,
                            stdout=fh, stderr=subprocess.STDOUT)


def start_api(py: Path, api_port: int, mode: str) -> subprocess.Popen | None:
    url = "http://127.0.0.1:%d/api/health" % api_port
    if http_ok(url):
        say("    backend already running on %d -- reusing it" % api_port)
        return None
    say("[4/5] Starting backend API on port %d" % api_port)
    env = os.environ.copy()
    cmd = [str(py), "-m", "uvicorn", "server.app:app",
           "--host", "127.0.0.1", "--port", str(api_port)]
    proc = spawn(cmd, ROOT, env, "api", mode)
    if not wait_http(url, 90, "backend", proc):
        fail("backend did not start. Last lines of logs/api.log:\n" + tail_log("api"))
    say("    backend ready")
    return proc


def start_web(port: int, api_port: int, mode: str) -> subprocess.Popen | None:
    url = "http://127.0.0.1:%d/verdict" % port
    if http_ok(url):
        say("    frontend already running on %d -- reusing it" % port)
        return None
    say("[5/5] Starting frontend on port %d" % port)
    env = os.environ.copy()
    env["PORT"] = str(port)
    env["API_BASE"] = "http://127.0.0.1:%d" % api_port
    cmd = npm_run("run", "start")
    proc = spawn(cmd, WEB, env, "web", mode)
    if not wait_http(url, 120, "frontend", proc):
        fail("frontend did not start. Last lines of logs/web.log:\n" + tail_log("web"))
    say("    frontend ready")
    return proc


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=3000, help="frontend port (default 3000)")
    ap.add_argument("--api-port", type=int, default=8000, help="backend port (default 8000)")
    ap.add_argument("--check", action="store_true", help="verify prerequisites only")
    ap.add_argument("--new-console", action="store_true",
                    help="give each service its own window (debugging)")
    ap.add_argument("--no-browser", action="store_true", help="do not open a browser")
    ap.add_argument("--no-wait", action="store_true",
                    help="start the services and exit (they keep running)")
    args = ap.parse_args()

    say("DPV web app launcher")
    say("project: %s" % ROOT)
    say()

    py = venv_python()
    if args.check:
        if py.exists():
            say("[1/5] Python environment ready")
        else:
            say("[1/5] .venv missing -- would create it")
        if shutil.which(npm_cmd()) is None:
            say("[3/5] npm NOT found -- install Node.js 20+")
        else:
            say("[3/5] npm found: %s" % shutil.which(npm_cmd()))
        ensure_web(check_only=True)
        say()
        say("check finished")
        return

    py = ensure_venv()
    ensure_deps(py)
    ensure_web()

    mode = "console" if args.new_console else "log"
    procs = []
    p1 = start_api(py, args.api_port, mode)
    if p1:
        procs.append(p1)
    p2 = start_web(args.port, args.api_port, mode)
    if p2:
        procs.append(p2)

    url = "http://127.0.0.1:%d/verdict" % args.port
    say()
    say("Ready:  " + url)
    if mode == "log":
        say("Logs:   logs/api.log , logs/web.log")
    say("Keep this window open while you work; close it to stop the service.")
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            say("open the URL above in your browser manually")
    if args.no_wait:
        say("launcher exiting, services keep running in the background")
        return

    say()
    say("Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
            dead = [p for p in procs if p.poll() is not None]
            if dead:
                fail("a service exited. Last lines:\n"
                     + tail_log("api") + "\n" + tail_log("web"))
    except KeyboardInterrupt:
        say()
        say("stopping...")
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        for fh in HANDLES:
            try:
                fh.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
