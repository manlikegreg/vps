import asyncio
import asyncssh
import os
import subprocess
import sys
from typing import Optional

_server: Optional[asyncio.AbstractServer] = None

class LocalSSHServer(asyncssh.SSHServer):
    def __init__(self, username: str, password: Optional[str]) -> None:
        self.username = username
        self.password = password

    def begin_auth(self, username):
        return True

    def password_auth_supported(self):
        return True if self.password else False

    def validate_password(self, username, password):
        return username == self.username and self.password and password == self.password

    def public_key_auth_supported(self):
        # Add pubkey auth later if needed
        return False

    def session_requested(self):
        return LocalSession()

class LocalSession(asyncssh.SSHServerSession):
    def __init__(self) -> None:
        self._chan = None
        self._pty = None
        self._proc = None

    def connection_made(self, chan):
        self._chan = chan

    async def shell_requested(self):
        # Start system shell
        if os.name == 'nt':
            cmd = ['powershell.exe', '-NoLogo', '-NoProfile']
        else:
            cmd = ['/bin/bash'] if os.path.exists('/bin/bash') else ['/bin/sh']
        try:
            if os.name == 'nt':
                # no PTY on Windows by default; use pipe
                def start_proc():
                    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=False, bufsize=0)
                self._proc = await asyncio.to_thread(start_proc)
                asyncio.create_task(self._pump_windows())
            else:
                self._proc = await asyncio.create_subprocess_exec(*cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                asyncio.create_task(self._pump_posix())
            return True
        except Exception:
            return False

    async def _pump_posix(self):
        try:
            while True:
                if self._proc.stdout is None:
                    break
                data = await self._proc.stdout.read(1024)
                if not data:
                    break
                try:
                    self._chan.write(data)
                except Exception:
                    break
        finally:
            try:
                code = await self._proc.wait()
            except Exception:
                code = 0
            try:
                self._chan.exit(code)
            except Exception:
                pass

    async def _pump_windows(self):
        try:
            loop = asyncio.get_running_loop()
            q: asyncio.Queue[bytes] = asyncio.Queue()
            def reader():
                try:
                    for chunk in self._proc.stdout:  # type: ignore
                        loop.call_soon_threadsafe(q.put_nowait, chunk.encode() if isinstance(chunk, str) else chunk)
                except Exception:
                    pass
                finally:
                    loop.call_soon_threadsafe(q.put_nowait, b'')
            asyncio.create_task(asyncio.to_thread(reader))
            while True:
                chunk = await q.get()
                if not chunk:
                    break
                try:
                    self._chan.write(chunk)
                except Exception:
                    break
        finally:
            try:
                code = await asyncio.to_thread(self._proc.wait)
            except Exception:
                code = 0
            try:
                self._chan.exit(code)
            except Exception:
                pass

    def data_received(self, data, datatype):
        try:
            if self._proc and self._proc.stdin:
                if isinstance(data, (bytes, bytearray)):
                    self._proc.stdin.write(data)  # type: ignore
                else:
                    self._proc.stdin.write(data.encode())  # type: ignore
        except Exception:
            pass

async def start_local_ssh_server():
    global _server
    if _server:
        return True
    host = '0.0.0.0'
    port = int(os.getenv('AGENT_SSH_LOCAL_PORT', '22022'))
    user = os.getenv('AGENT_SSH_LOCAL_USER', 'agent')
    password = os.getenv('AGENT_SSH_PASSWORD', '') or None
    host_key_path = os.getenv('AGENT_SSH_LOCAL_HOST_KEY', os.path.join(os.getcwd(), 'agent_ssh_host_ed25519'))
    if not os.path.isfile(host_key_path):
        key = asyncssh.generate_private_key('ssh-ed25519')
        with open(host_key_path, 'w', encoding='utf-8') as f:
            f.write(key.export_private_key())
    try:
        _server = await asyncssh.create_server(lambda: LocalSSHServer(user, password), host, port, server_host_keys=[host_key_path], encoding=None, sftp_factory=asyncssh.SFTPServer)
        # Best-effort firewall open on Windows
        if os.name == 'nt':
            try:
                subprocess.run(['netsh','advfirewall','firewall','add','rule','name=AgentLocalSSH','dir=in','action=allow','protocol=TCP',f'localport={port}'])
            except Exception:
                pass
        return True
    except Exception:
        return False

async def stop_local_ssh_server():
    global _server
    try:
        if _server:
            _server.close()
            await _server.wait_closed()
            _server = None
            return True
    except Exception:
        pass
    return False