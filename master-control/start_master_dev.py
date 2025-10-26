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
MASTER_BACKEND_DIR = ROOT / "master-backend"
MASTER_FRONTEND_DIR = ROOT / "master-frontend"

DEFAULT_PORTS = {
    "master_backend": 9000,
    "master_frontend": 5174,
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
    print("\n[dev] Shutting down master-control services...")
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
    print("[dev] Master-control services stopped.")


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
    parser = argparse.ArgumentParser(description="Start master-control backend and frontend for local dev")
    parser.add_argument("--backend-port", type=int, default=DEFAULT_PORTS["master_backend"], help="Master backend port")
    parser.add_argument("--frontend-port", type=int, default=DEFAULT_PORTS["master_frontend"], help="Master frontend dev port")
    parser.add_argument("--no-backend", action="store_true", help="Skip master backend")
    parser.add_argument("--no-frontend", action="store_true", help="Skip master frontend")
    args = parser.parse_args()

    print("[dev] Master-control workspace:")
    print(f"  - backend:  {MASTER_BACKEND_DIR}")
    print(f"  - frontend: {MASTER_FRONTEND_DIR}")

    def _sig_handler(signum, frame):
        shutdown_all()
        sys.exit(0)

    signal.signal(signal.SIGINT, _sig_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _sig_handler)

    py = sys.executable
    backend_cmd = [py, "-m", "uvicorn", "main:app", "--reload", "--host", "0.0.0.0", "--port", str(args.backend_port)]
    frontend_cmd = build_frontend_cmd(MASTER_FRONTEND_DIR, args.frontend_port)

    print("\n[dev] Launch plan (master-control):")
    if not args.no_backend:
        print(f"  - Master backend:   http://localhost:{args.backend_port} (WS: ws://localhost:{args.backend_port}/ws/dashboard)")
    if not args.no_frontend:
        print(f"  - Master frontend:  http://localhost:{args.frontend_port} (API: http://localhost:{args.backend_port})")

    if not args.no_backend:
        start_process("master-backend", backend_cmd, MASTER_BACKEND_DIR)
    if not args.no_frontend:
        if not frontend_cmd:
            print("[dev] ERROR: No package manager found (npm/pnpm/yarn/npx). Install Node.js and ensure PATH includes it.")
        else:
            start_process("master-frontend", frontend_cmd, MASTER_FRONTEND_DIR, env={"BROWSER": "none"})

    print("\n[dev] Master-control services are starting. Press Ctrl+C to stop.")
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
