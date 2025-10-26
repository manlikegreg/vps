import os
import sys
import signal
import time
import subprocess
from pathlib import Path
import argparse

ROOT = Path(__file__).resolve().parent

PATHS = {
    "agent_backend": ROOT / "backend",
    "agent_frontend": ROOT / "frontend",
    "master_backend": ROOT / "master-control" / "master-backend",
    "master_frontend": ROOT / "master-control" / "master-frontend",
}

DEFAULT_PORTS = {
    "agent_backend": 8000,
    "master_backend": 9000,
    "agent_frontend": 5173,
    "master_frontend": 5174,
}

processes = []


def start_process(name: str, cmd: list[str], cwd: Path) -> subprocess.Popen:
    creation = 0
    if os.name == "nt":
        # Start each service in its own console window on Windows for clearer logs
        creation = subprocess.CREATE_NEW_CONSOLE
    print(f"[dev] Starting {name} in {cwd} -> {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        creationflags=creation,
        env=os.environ.copy(),
    )
    processes.append((name, proc))
    return proc


def shutdown_all():
    print("\n[dev] Shutting down all services...")
    for name, proc in processes:
        if proc.poll() is None:
            print(f"[dev] Terminating {name} (pid={proc.pid})")
            try:
                proc.terminate()
            except Exception:
                pass
    # Give them a moment to exit cleanly
    time.sleep(1.5)
    for name, proc in processes:
        if proc.poll() is None:
            print(f"[dev] Killing {name} (pid={proc.pid})")
            try:
                proc.kill()
            except Exception:
                pass
    print("[dev] All services stopped.")


def main():
    parser = argparse.ArgumentParser(description="Start agent + master frontends and backends for local dev")
    parser.add_argument("--agent-backend-port", type=int, default=DEFAULT_PORTS["agent_backend"], help="Agent backend port")
    parser.add_argument("--master-backend-port", type=int, default=DEFAULT_PORTS["master_backend"], help="Master backend port")
    parser.add_argument("--agent-frontend-port", type=int, default=DEFAULT_PORTS["agent_frontend"], help="Agent frontend dev port")
    parser.add_argument("--master-frontend-port", type=int, default=DEFAULT_PORTS["master_frontend"], help="Master frontend dev port")
    parser.add_argument("--no-agent-backend", action="store_true", help="Skip agent backend")
    parser.add_argument("--no-master-backend", action="store_true", help="Skip master backend")
    parser.add_argument("--no-agent-frontend", action="store_true", help="Skip agent frontend")
    parser.add_argument("--no-master-frontend", action="store_true", help="Skip master frontend")
    args = parser.parse_args()

    print("[dev] Workspace:")
    for k, v in PATHS.items():
        print(f"  - {k}: {v}")

    # Wire up clean shutdown on Ctrl+C / SIGTERM
    def _sig_handler(signum, frame):
        shutdown_all()
        sys.exit(0)

    signal.signal(signal.SIGINT, _sig_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _sig_handler)

    # Backend commands use current Python to run uvicorn module for reliability
    py = sys.executable
    agent_backend_cmd = [py, "-m", "uvicorn", "main:app", "--reload", "--host", "0.0.0.0", "--port", str(args.agent_backend_port)]
    master_backend_cmd = [py, "-m", "uvicorn", "main:app", "--reload", "--host", "0.0.0.0", "--port", str(args.master_backend_port)]

    # Frontend Vite dev servers; force distinct ports to avoid collision
    agent_frontend_cmd = ["npm", "run", "dev", "--", "--port", str(args.agent_frontend_port)]
    master_frontend_cmd = ["npm", "run", "dev", "--", "--port", str(args.master_frontend_port)]

    print("\n[dev] Launch plan:")
    if not args.no_agent_backend:
        print(f"  - Agent backend:    http://localhost:{args.agent_backend_port}")
    if not args.no_master_backend:
        print(f"  - Master backend:   http://localhost:{args.master_backend_port} (WS: ws://localhost:{args.master_backend_port}/ws/dashboard)")
    if not args.no_agent_frontend:
        print(f"  - Agent frontend:   http://localhost:{args.agent_frontend_port} (API: http://localhost:{args.agent_backend_port})")
    if not args.no_master_frontend:
        print(f"  - Master frontend:  http://localhost:{args.master_frontend_port} (API: http://localhost:{args.master_backend_port})")

    # Start services
    if not args.no_agent_backend:
        start_process("agent-backend", agent_backend_cmd, PATHS["agent_backend"])
    if not args.no_master_backend:
        start_process("master-backend", master_backend_cmd, PATHS["master_backend"])
    if not args.no_agent_frontend:
        start_process("agent-frontend", agent_frontend_cmd, PATHS["agent_frontend"])
    if not args.no_master_frontend:
        start_process("master-frontend", master_frontend_cmd, PATHS["master_frontend"])

    print("\n[dev] Services are starting. Press Ctrl+C to stop all.")

    # Keep the parent process alive while children run
    try:
        while True:
            # If any critical process exits, report it (but keep others running)
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
