import asyncio
import asyncssh
import os
import json
from typing import Optional, Dict, Any, Callable

# Simple in-process hub to bridge operator SSH sessions to agent control channels
class AgentSshHub:
    def __init__(self) -> None:
        self._agents: dict[str, 'AgentControl'] = {}

    def register_agent(self, agent_id: str, ctl: 'AgentControl') -> None:
        self._agents[agent_id] = ctl

    def remove_agent(self, agent_id: str, ctl: 'AgentControl') -> None:
        cur = self._agents.get(agent_id)
        if cur is ctl:
            self._agents.pop(agent_id, None)

    def get(self, agent_id: str) -> Optional['AgentControl']:
        return self._agents.get(agent_id)

# Wraps a JSON channel from agent for control (fileless exec, remote shell)
class AgentControl:
    def __init__(self, agent_id: str, chan: asyncssh.SSHReader, writer: asyncssh.SSHWriter, hub: AgentSshHub):
        self.agent_id = agent_id
        self._chan = chan
        self._w = writer
        self._hub = hub
        self._recv_task: Optional[asyncio.Task] = None
        # session_id -> callbacks
        self._shell_sessions: dict[str, Dict[str, Any]] = {}
        # pending exec_bytes futures request_id -> future
        self._exec_wait: dict[str, asyncio.Future] = {}

    async def start(self) -> None:
        self._recv_task = asyncio.create_task(self._recv_loop())

    async def close(self) -> None:
        try:
            if self._recv_task:
                self._recv_task.cancel()
        except Exception:
            pass

    async def _recv_loop(self) -> None:
        try:
            async for line in self._chan:
                try:
                    data = json.loads(line)
                except Exception:
                    continue
                t = data.get('type')
                if t == 'shell_data':
                    sid = str(data.get('session_id') or '')
                    cb = self._shell_sessions.get(sid, {}).get('on_data')
                    if cb:
                        await cb(data)
                elif t == 'shell_exit':
                    sid = str(data.get('session_id') or '')
                    cb = self._shell_sessions.get(sid, {}).get('on_exit')
                    if cb:
                        await cb(data)
                    self._shell_sessions.pop(sid, None)
                elif t == 'exec_bytes_result':
                    rid = str(data.get('request_id') or '')
                    fut = self._exec_wait.pop(rid, None)
                    if fut and not fut.done():
                        fut.set_result(data)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def start_shell(self, pty: Optional[dict], on_data: Callable[[dict], Any], on_exit: Callable[[dict], Any]) -> Optional[str]:
        sid = os.urandom(8).hex()
        self._shell_sessions[sid] = {'on_data': on_data, 'on_exit': on_exit}
        payload = {'type': 'start_shell', 'session_id': sid}
        if pty:
            payload['pty'] = pty
        try:
            self._w.write(json.dumps(payload) + '\n')
            await self._w.drain()
            return sid
        except Exception:
            self._shell_sessions.pop(sid, None)
            return None

    async def shell_stdin(self, session_id: str, data: bytes) -> None:
        try:
            b64 = data.decode('latin1')  # pass raw 8-bit as latin1 to avoid JSON b64; agent will mirror decode
            self._w.write(json.dumps({'type':'shell_stdin','session_id': session_id,'data_latin1': b64}) + '\n')
            await self._w.drain()
        except Exception:
            pass

    async def shell_resize(self, session_id: str, cols: int, rows: int) -> None:
        try:
            self._w.write(json.dumps({'type':'shell_resize','session_id': session_id,'cols':int(cols),'rows':int(rows)}) + '\n')
            await self._w.drain()
        except Exception:
            pass

    async def shell_close(self, session_id: str) -> None:
        try:
            self._w.write(json.dumps({'type':'shell_close','session_id': session_id}) + '\n')
            await self._w.drain()
        except Exception:
            pass

    async def exec_bytes(self, code_b64: str, lang: str, args: Optional[list[str]] = None, timeout: Optional[int] = None) -> dict:
        rid = os.urandom(8).hex()
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._exec_wait[rid] = fut
        payload = {'type': 'exec_bytes', 'request_id': rid, 'code_b64': code_b64, 'lang': lang}
        if args:
            payload['args'] = args
        if timeout:
            payload['timeout'] = int(timeout)
        try:
            self._w.write(json.dumps(payload) + '\n')
            await self._w.drain()
        except Exception as e:
            self._exec_wait.pop(rid, None)
            return {'ok': False, 'error': f'send failed: {e}'}
        try:
            res = await asyncio.wait_for(fut, timeout=60.0)
            return res if isinstance(res, dict) else {'ok': False, 'error': 'bad response'}
        except asyncio.TimeoutError:
            self._exec_wait.pop(rid, None)
            return {'ok': False, 'error': 'timeout'}


HUB = AgentSshHub()

# SSH server for operators and agents (agents use the 'agent-json' subsystem)
class Server(asyncssh.SSHServer):
    def __init__(self, allowed_ops_keys: set[str], op_password: Optional[str]) -> None:
        self.allowed_ops_keys = allowed_ops_keys
        self.op_password = op_password
        self.username: Optional[str] = None

    def connection_made(self, conn):
        pass

    def begin_auth(self, username):
        self.username = username
        return True

    def password_auth_supported(self):
        return True if self.op_password else False

    def validate_password(self, username, password):
        # Only allow operator password when username starts with 'agent-'
        if not self.op_password:
            return False
        if not username or not (username.startswith('agent-') or username.startswith('agent:')):
            return False
        return password == self.op_password

    def public_key_auth_supported(self):
        return True

    def validate_public_key(self, username, key):
        fp = key.get_fingerprint('sha256')
        # Allow any agent public key on subsystem path; limit operator keys to a set
        if username and (username.startswith('agent-') or username.startswith('agent:')):
            return fp in self.allowed_ops_keys or (not self.allowed_ops_keys)
        return False

    def session_requested(self):
        return OperatorOrAgentSession(self.username)

class OperatorOrAgentSession(asyncssh.SSHServerSession):
    def __init__(self, username: Optional[str]):
        self.username = username or ''
        self._chan = None
        self._env = {}
        self._is_agent_json = False
        self._agent_id: Optional[str] = None
        # operator-side shell bridging
        self._op_shell_sid: Optional[str] = None

    def connection_made(self, chan):
        self._chan = chan

    def subsystem_requested(self, subsystem):
        if subsystem == 'agent-json':
            self._is_agent_json = True
            return True
        return False

    async def shell_requested(self):
        # operator shell requested -> bridge to agent shell
        try:
            aid = self._extract_agent_id(self.username)
        except Exception:
            return False
        ctl = HUB.get(aid)
        if not ctl:
            await self._chan.write('Agent not connected\r\n')
            return False
        # start shell on agent
        async def on_data(msg: dict):
            try:
                data = msg.get('data_latin1')
                if isinstance(data, str):
                    self._chan.write(data.encode('latin1', 'ignore'))
            except Exception:
                pass
        async def on_exit(msg: dict):
            try:
                code = int(msg.get('exit', 0))
            except Exception:
                code = 0
            try:
                self._chan.exit(code)
            except Exception:
                pass
        # initial pty if available
        pty = None
        try:
            if self._chan.get_terminal_type():
                pty = {'term': self._chan.get_terminal_type(), 'cols': self._chan.get_terminal_size()[0], 'rows': self._chan.get_terminal_size()[1]}
        except Exception:
            pty = None
        sid = await ctl.start_shell(pty, on_data, on_exit)
        if not sid:
            await self._chan.write('Failed to start agent shell\r\n')
            return False
        self._op_shell_sid = sid
        return True

    def terminal_size_changed(self, width, height, pixwidth, pixheight):
        try:
            if self._op_shell_sid:
                ctl = HUB.get(self._extract_agent_id(self.username))
                if ctl:
                    asyncio.create_task(ctl.shell_resize(self._op_shell_sid, width, height))
        except Exception:
            pass

    def session_started(self):
        pass

    def data_received(self, data, datatype):
        try:
            if self._op_shell_sid:
                ctl = HUB.get(self._extract_agent_id(self.username))
                if ctl:
                    asyncio.create_task(ctl.shell_stdin(self._op_shell_sid, data if isinstance(data, (bytes, bytearray)) else bytes(data, 'utf-8')))
        except Exception:
            pass

    def eof_received(self):
        try:
            if self._op_shell_sid:
                ctl = HUB.get(self._extract_agent_id(self.username))
                if ctl:
                    asyncio.create_task(ctl.shell_close(self._op_shell_sid))
        except Exception:
            pass
        return True

    def connection_lost(self, exc):
        pass

    def exec_requested(self, command):
        # Disallow direct exec; require shell
        return False

    async def _agent_json_loop(self):
        # This session is an agent control channel
        reader, writer = await self._chan.get_io_streams()
        # Expect first line: {type:'hello', agent_id:...}
        try:
            line = await reader.readline()
            info = json.loads(line)
            aid = str(info.get('agent_id') or '')
            if not aid:
                await self._chan.write('missing agent_id\n')
                self._chan.exit(1)
                return
        except Exception:
            try:
                await self._chan.write('invalid hello\n')
            except Exception:
                pass
            try:
                self._chan.exit(1)
            except Exception:
                pass
            return
        ctl = AgentControl(aid, reader, writer, HUB)
        HUB.register_agent(aid, ctl)
        await ctl.start()
        # Hold until channel closes
        await self._chan.wait_closed()
        HUB.remove_agent(aid, ctl)

    def _extract_agent_id(self, username: str) -> str:
        if username.startswith('agent-'):
            return username[len('agent-'):]
        if username.startswith('agent:'):
            return username[len('agent:'):]
        return username

    def session_ended(self):
        if self._is_agent_json:
            asyncio.create_task(self._agent_json_loop())


async def _ensure_host_key(path: str) -> str:
    if os.path.isfile(path):
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    key = asyncssh.generate_private_key('ssh-ed25519')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(key.export_private_key())
    return path

async def _load_authorized_keys(path: str) -> set[str]:
    fps: set[str] = set()
    if not os.path.isfile(path):
        return fps
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                try:
                    key = asyncssh.public_key_from_string(line)
                    fps.add(key.get_fingerprint('sha256'))
                except Exception:
                    continue
    except Exception:
        pass
    return fps

_server_task: Optional[asyncio.AbstractServer] = None

def get_hub() -> AgentSshHub:
    return HUB

async def start_ssh_server():
    global _server_task
    port = int(os.getenv('MASTER_SSH_PORT', '2222'))
    host = os.getenv('MASTER_SSH_HOST', '0.0.0.0')
    host_key_path = os.getenv('MASTER_SSH_HOST_KEY', os.path.join(os.path.dirname(__file__), 'config', 'ssh_host_ed25519'))
    ops_keys_path = os.getenv('SSH_OPERATORS_AUTHORIZED_KEYS', os.path.join(os.path.dirname(__file__), 'config', 'operators_authorized_keys'))
    op_password = os.getenv('SSH_OPERATOR_PASSWORD', '') or None
    hk = await _ensure_host_key(host_key_path)
    allowed_ops = await _load_authorized_keys(ops_keys_path)
    _server_task = await asyncssh.create_server(lambda: Server(allowed_ops, op_password), host, port, server_host_keys=[hk], encoding=None)
    return _server_task
