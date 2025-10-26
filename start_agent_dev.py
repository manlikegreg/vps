import os
import sys
import signal
import time
import subprocess
from pathlib import Path
import argparse
import shutil
from typing import Optional, List

ROOT = Path(__file__).resolve().parent
AGENT_BACKEND_DIR = ROOT / "backend"
AGENT_FRONTEND_DIR = ROOT / "frontend"

DEFAULT_PORTS = {
    "agent_backend": 8000,
    "agent_frontend": 5173,
}

processes: List[tuple[str, subprocess.Popen]] = []


def start_process(name: str, cmd: list[str], cwd: Path, env: Optional[dict] = None) -> subprocess.Popen:
    env_final = os.environ.copy()
    if env:
        env_final.update(env)
    print(f"[dev] Starting {name} in {cwd} -> {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, cwd=str(cwd), env=env_final)
    processes.append((name, proc))
    return proc


def shutdown_all():
    print("\n[dev] Shutting down agent services...")
    for name, proc in processes:
        if proc.poll() is None:
            print(f"[dev] Terminating {name} (pid={proc.pid})")
            try:
                proc.terminate()
            except Exception:
                pass
    time.sleep(1.0)
    for name, proc in processes:
        if proc.poll() is None:
            print(f"[dev] Killing {name} (pid={proc.pid})")
            try:
                proc.kill()
            except Exception:
                pass
    print("[dev] Agent services stopped.")


def resolve_pm_exe(cwd: Path) -> Optional[str]:
    # Prefer pnpm if lockfile exists, then yarn, then npm; fallback to npx
    candidates: list[str] = []
    if (cwd / "pnpm-lock.yaml").exists():
        candidates.append("pnpm")
    if (cwd / "yarn.lock").exists():
        candidates.append("yarn")
    candidates.append("npm")
    for name in candidates:
        exe = shutil.which(name) or shutil.which(f"{name}.cmd")
        if exe:
            return exe
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    return npx


def build_frontend_cmd(cwd: Path, port: int) -> Optional[list[str]]:
    exe = resolve_pm_exe(cwd)
    if not exe:
        return None
    base = Path(exe).name.split(".")[0].lower()
    if base in ("pnpm", "yarn", "npm"):
        return [exe, "run", "dev", "--", "--port", str(port)]
    # fallback: npx vite
    return [exe, "vite", "--port", str(port)]


def main():
    parser = argparse.ArgumentParser(description="Start agent backend and frontend for local dev")
    parser.add_argument("--backend-port", type=int, default=DEFAULT_PORTS["agent_backend"], help="Agent backend port")
    parser.add_argument("--frontend-port", type=int, default=DEFAULT_PORTS["agent_frontend"], help="Agent frontend dev port")
    parser.add_argument("--no-backend", action="store_true", help="Skip agent backend")
    parser.add_argument("--no-frontend", action="store_true", help="Skip agent frontend")
    args = parser.parse_args()

    print("[dev] Agent workspace:")
    print(f"  - backend:  {AGENT_BACKEND_DIR}")
    print(f"  - frontend: {AGENT_FRONTEND_DIR}")

    def _sig_handler(signum, frame):
        shutdown_all()
        sys.exit(0)

    signal.signal(signal.SIGINT, _sig_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _sig_handler)

    py = sys.executable
    backend_cmd = [py, "-m", "uvicorn", "main:app", "--reload", "--host", "0.0.0.0", "--port", str(args.backend_port)]
    frontend_cmd = build_frontend_cmd(AGENT_FRONTEND_DIR, args.frontend_port)

    print("\n[dev] Launch plan (agent):")
    if not args.no_backend:
        print(f"  - Agent backend:   http://localhost:{args.backend_port}")
    if not args.no_frontend:
        print(f"  - Agent frontend:  http://localhost:{args.frontend_port} (API: http://localhost:{args.backend_port})")

    if not args.no_backend:
        start_process("agent-backend", backend_cmd, AGENT_BACKEND_DIR)
    if not args.no_frontend:
        if not frontend_cmd:
            print("[dev] ERROR: No package manager found (npm/pnpm/yarn/npx). Install Node.js and ensure PATH includes it.")
        else:
            # Avoid auto-opening browser tabs from Vite on Windows
            start_process("agent-frontend", frontend_cmd, AGENT_FRONTEND_DIR, env={"BROWSER": "none"})

    print("\n[dev] Agent services are starting. Press Ctrl+C to stop.")
    try:
        while True:
            for name, proc in processes:
                code = proc.poll()
                if code is not None:
                    print(f"[dev] Process '{name}' exited with code {code}")
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        shutdown_all()


if __name__ == "__main__":
    main()
