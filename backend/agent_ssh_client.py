import asyncio
import asyncssh
import os
import base64
import json
import sys
import shlex
import subprocess
from typing import Optional

# Agent-side SSH client that connects to the master SSH server and exposes a JSON control channel
# Channel protocol: newline-delimited JSON messages
# - hello: {type:'hello', agent_id, agent_name}
# - start_shell: {type:'start_shell', session_id, pty?:{term,cols,rows}}
#   -> agent spawns OS shell and streams {type:'shell_data',session_id,data_latin1:'...'}; on exit {type:'shell_exit',session_id,exit:int}
# - shell_stdin: {type:'shell_stdin', session_id, data_latin1}
# - shell_resize: {type:'shell_resize', session_id, cols, rows}
# - shell_close: {type:'shell_close', session_id}
# - exec_bytes: {type:'exec_bytes', request_id, code_b64, lang, args?, timeout?}
#   -> respond once done: {type:'exec_bytes_result',request_id,ok,true|false,exit,int,stdout_b64,stderr_b64,error?}


class AgentSshClient:
    def __init__(self, agent_id: str, agent_name: str, host: str, port: int, key_path: str, host_fp: Optional[str] = None) -> None:
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.host = host
        self.port = port
        self.key_path = key_path
        self.host_fp = (host_fp or '').strip().lower().replace(':','') or None
        self._conn: Optional[asyncssh.SSHClientConnection] = None
        self._writer: Optional[asyncssh.SSHWriter] = None
        self._reader: Optional[asyncssh.SSHReader] = None
        self._tasks = []
        self._shells: dict[str, dict] = {}

    async def run(self):
        while True:
            try:
                await self._connect_once()
                await self._hold()
            except asyncio.CancelledError:
                break
            except Exception:
                pass
            await asyncio.sleep(3.0)

    async def _connect_once(self):
        os.makedirs(os.path.dirname(self.key_path), exist_ok=True)
        if not os.path.isfile(self.key_path):
            key = asyncssh.generate_private_key('ssh-ed25519')
            with open(self.key_path, 'w', encoding='utf-8') as f:
                f.write(key.export_private_key())
        client_keys = [self.key_path]
        async def _verify_host_key(host, port, key):
            if not self.host_fp:
                return True
            return (key.get_fingerprint('sha256') or '').lower().replace(':','') == self.host_fp
        self._conn = await asyncssh.connect(self.host, port=self.port, username='agentctl', client_keys=client_keys, known_hosts=None, server_host_key_algs=['ssh-ed25519'],
                                            keepalive_interval=20, keepalive_count_max=3, client_host_keysign=None, passphrase=None, host_key_info=_verify_host_key)
        chan, session = await self._conn.create_session(asyncssh.SSHClientSession, subsystem='agent-json', encoding=None)
        self._reader, self._writer = await chan.get_io_streams()
        # send hello
        hello = {'type': 'hello', 'agent_id': self.agent_id, 'agent_name': self.agent_name}
        self._writer.write(json.dumps(hello) + '\n')
        await self._writer.drain()
        # start reader task
        self._tasks.append(asyncio.create_task(self._recv_loop()))

    async def _hold(self):
        # stay until channel or connection closes
        try:
            await self._conn.wait_closed()  # type: ignore
        except Exception:
            pass

    async def _recv_loop(self):
        try:
            async for line in self._reader:  # type: ignore
                try:
                    msg = json.loads(line)
                except Exception:
                    continue
                t = msg.get('type')
                if t == 'start_shell':
                    await self._handle_start_shell(msg)
                elif t == 'shell_stdin':
                    await self._handle_shell_stdin(msg)
                elif t == 'shell_resize':
                    await self._handle_shell_resize(msg)
                elif t == 'shell_close':
                    await self._handle_shell_close(msg)
                elif t == 'exec_bytes':
                    await self._handle_exec_bytes(msg)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _handle_start_shell(self, msg: dict):
        sid = str(msg.get('session_id') or '')
        pty = msg.get('pty') or {}
        term = pty.get('term') or 'xterm'
        cols = int(pty.get('cols') or 120)
        rows = int(pty.get('rows') or 32)
        # choose shell
        if os.name == 'nt':
            # Use powershell by default for a nicer experience
            cmd = ['powershell.exe', '-NoLogo', '-NoProfile']
        else:
            # Prefer bash if available
            cmd = ['/bin/bash'] if os.path.exists('/bin/bash') else ['/bin/sh']
        # try PTY if available (pywinpty on Windows)
        proc = None
        use_pty = False
        if os.name == 'nt':
            try:
                import pywinpty  # type: ignore
                from pywinpty import PtyProcess  # type: ignore
                proc = await asyncio.to_thread(PtyProcess.spawn, ' '.join(cmd))
                use_pty = True
            except Exception:
                use_pty = False
        if not use_pty:
            # fallback: normal subprocess with pipes
            if os.name == 'nt':
                proc = await asyncio.to_thread(lambda: subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=False, bufsize=0))
            else:
                proc = await asyncio.create_subprocess_exec(*cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        shell = {'proc': proc, 'use_pty': use_pty, 'sid': sid}
        self._shells[sid] = shell
        # start reader task
        async def _pump():
            try:
                if use_pty:
                    # pywinpty: read small chunks
                    while True:
                        try:
                            data = await asyncio.to_thread(proc.read, 1024)  # type: ignore
                        except Exception:
                            break
                        if not data:
                            break
                        await self._send({'type': 'shell_data', 'session_id': sid, 'data_latin1': data})
                else:
                    while True:
                        if proc.stdout is None:
                            break
                        data = await proc.stdout.read(1024)  # type: ignore
                        if not data:
                            break
                        await self._send({'type': 'shell_data', 'session_id': sid, 'data_latin1': data.decode('latin1', 'ignore')})
            finally:
                # exit code
                code = 0
                try:
                    if use_pty:
                        code = await asyncio.to_thread(lambda: getattr(proc, 'exitstatus', 0))  # type: ignore
                    else:
                        code = await proc.wait()  # type: ignore
                except Exception:
                    pass
                await self._send({'type': 'shell_exit', 'session_id': sid, 'exit': int(code)})
                self._shells.pop(sid, None)
        asyncio.create_task(_pump())

    async def _handle_shell_stdin(self, msg: dict):
        sid = str(msg.get('session_id') or '')
        data_s = msg.get('data_latin1') or ''
        sh = self._shells.get(sid)
        if not sh:
            return
        proc = sh['proc']
        try:
            if sh['use_pty']:
                await asyncio.to_thread(proc.write, data_s)  # type: ignore
            else:
                if proc.stdin is not None:
                    proc.stdin.write(data_s.encode('latin1', 'ignore'))  # type: ignore
        except Exception:
            pass

    async def _handle_shell_resize(self, msg: dict):
        sid = str(msg.get('session_id') or '')
        cols = int(msg.get('cols') or 120)
        rows = int(msg.get('rows') or 32)
        sh = self._shells.get(sid)
        if not sh:
            return
        try:
            if sh['use_pty']:
                proc = sh['proc']
                await asyncio.to_thread(proc.setwinsize, rows, cols)  # type: ignore
        except Exception:
            pass

    async def _handle_shell_close(self, msg: dict):
        sid = str(msg.get('session_id') or '')
        sh = self._shells.get(sid)
        if not sh:
            return
        try:
            proc = sh['proc']
            if sh['use_pty']:
                await asyncio.to_thread(proc.terminate, True)  # type: ignore
            else:
                proc.terminate()  # type: ignore
        except Exception:
            pass

    async def _handle_exec_bytes(self, msg: dict):
        rid = str(msg.get('request_id') or '')
        lang = (msg.get('lang') or '').lower()
        code_b64 = msg.get('code_b64') or ''
        args = msg.get('args') or []
        timeout = int(msg.get('timeout') or 0) or None
        try:
            code = base64.b64decode(code_b64, validate=False)
        except Exception as e:
            await self._send({'type': 'exec_bytes_result', 'request_id': rid, 'ok': False, 'error': f'decode failed: {e}'})
            return
        # Build command to exec from stdin
        if os.name == 'nt':
            if lang in ('ps1','powershell','ps'):
                cmd = ['powershell.exe', '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-']
            elif lang in ('py','python'):
                cmd = ['python', '-']
            elif lang in ('cmd','bat','cmdexe'):
                # Not truly fileless; save to temp then run
                tmp = os.path.join(os.environ.get('TEMP','.'), f'script-{rid}.cmd')
                try:
                    with open(tmp, 'wb') as f:
                        f.write(code)
                    cmd = ['cmd.exe', '/c', tmp]
                except Exception as e:
                    await self._send({'type': 'exec_bytes_result', 'request_id': rid, 'ok': False, 'error': f'write temp failed: {e}'})
                    return
            else:
                cmd = ['powershell.exe', '-NoLogo', '-NoProfile', '-']
        else:
            if lang in ('sh','bash'):
                cmd = ['bash', '-s']
            elif lang in ('py','python'):
                cmd = ['python3', '-'] if self._which('python3') else ['python', '-']
            elif lang in ('node','js'):
                cmd = ['node', '-']
            else:
                cmd = ['sh', '-s']
        try:
            proc = await asyncio.create_subprocess_exec(*cmd, *list(map(str,args)), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            if proc.stdin is not None:
                proc.stdin.write(code)
                await proc.stdin.drain()
                proc.stdin.close()
            try:
                if timeout:
                    rc = await asyncio.wait_for(proc.wait(), timeout=timeout)
                else:
                    rc = await proc.wait()
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except Exception:
                    pass
                await self._send({'type':'exec_bytes_result','request_id':rid,'ok':False,'error':'timeout'})
                return
            out = await proc.stdout.read() if proc.stdout else b''
            err = await proc.stderr.read() if proc.stderr else b''
            await self._send({'type':'exec_bytes_result','request_id':rid,'ok':True,'exit':int(rc),'stdout_b64': base64.b64encode(out).decode(), 'stderr_b64': base64.b64encode(err).decode()})
        except Exception as e:
            await self._send({'type': 'exec_bytes_result', 'request_id': rid, 'ok': False, 'error': str(e)})

    def _which(self, exe: str) -> bool:
        for p in os.environ.get('PATH','').split(os.pathsep):
            full = os.path.join(p, exe)
            if os.path.isfile(full) and os.access(full, os.X_OK):
                return True
        return False

    async def _send(self, obj: dict):
        try:
            self._writer.write(json.dumps(obj) + '\n')  # type: ignore
            await self._writer.drain()  # type: ignore
        except Exception:
            pass


async def start_agent_ssh(agent_id: str, agent_name: str):
    host = os.getenv('MASTER_SSH_HOST', os.getenv('MASTER_BACKEND_HOST', '127.0.0.1'))
    port = int(os.getenv('MASTER_SSH_PORT', '2222'))
    key_path = os.getenv('AGENT_SSH_KEY', os.path.join(os.getcwd(), 'agent_ssh_key'))
    host_fp = os.getenv('MASTER_SSH_HOST_FP', '')
    client = AgentSshClient(agent_id, agent_name, host, port, key_path, host_fp)
    await client.run()
