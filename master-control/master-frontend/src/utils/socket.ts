type Agent = { agent_id: string; name: string };

type DashboardEvent =
  | { type: 'agents'; agents: Agent[] }
  | { type: 'log'; agent_id: string; line: string }
  | { type: 'exit'; agent_id: string; exit_code: number }
  | { type: 'error'; message: string };

class DashboardSocket {
  private ws: WebSocket | null = null;
  private baseUrl = (import.meta as any).env?.VITE_DASHBOARD_WS_URL || 'ws://localhost:9000/ws/dashboard';
  private token: string | null = null;
  private agents: Agent[] = [];
  private listeners: { [agentId: string]: ((line: string) => void)[] } = {};
  private exitListeners: { [agentId: string]: ((code: number) => void)[] } = {};
  private agentsListeners: ((agents: Agent[]) => void)[] = [];
  private statusListeners: ((status: 'connected' | 'disconnected') => void)[] = [];

  setToken(token: string | null) {
    this.token = token;
    // Reset socket to apply new auth
    if (this.ws) {
      try { this.ws.close(); } catch {}
      this.ws = null;
    }
  }

  private buildUrl() {
    const t = this.token || (typeof localStorage !== 'undefined' ? localStorage.getItem('master_token') : null);
    if (!t) return this.baseUrl;
    const sep = this.baseUrl.includes('?') ? '&' : '?';
    return `${this.baseUrl}${sep}token=${encodeURIComponent(t)}`;
  }

  connect() {
    if (this.ws) return;
    this.ws = new WebSocket(this.buildUrl());
    this.ws.onopen = () => {
      this.statusListeners.forEach((cb) => cb('connected'));
    };
    this.ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data) as DashboardEvent;
        if (data.type === 'agents') {
          this.agents = data.agents;
          this.agentsListeners.forEach((cb) => cb([...this.agents]));
        } else if (data.type === 'log') {
          const cbs = this.listeners[data.agent_id] || [];
          cbs.forEach((cb) => cb(data.line));
        } else if ((data as any).type === 'exit') {
          const d = data as { type: 'exit'; agent_id: string; exit_code: number };
          const cbs = this.exitListeners[d.agent_id] || [];
          cbs.forEach((cb) => cb(d.exit_code));
        }
      } catch (e) {
        // ignore parse error
      }
    };
    this.ws.onclose = () => {
      this.ws = null;
      this.statusListeners.forEach((cb) => cb('disconnected'));
      setTimeout(() => this.connect(), 1000);
    };
  }

  onAgents(cb: (agents: Agent[]) => void) {
    this.agentsListeners.push(cb);
    if (this.agents.length) cb([...this.agents]);
  }

  onStatus(cb: (status: 'connected' | 'disconnected') => void) {
    this.statusListeners.push(cb);
    cb(this.ws && this.ws.readyState === WebSocket.OPEN ? 'connected' : 'disconnected');
  }

  getAgents() {
    return [...this.agents];
  }

  subscribe(agentId: string, cb: (line: string) => void) {
    if (!this.listeners[agentId]) this.listeners[agentId] = [];
    this.listeners[agentId].push(cb);
  }

  unsubscribe(agentId: string, cb: (line: string) => void) {
    this.listeners[agentId] = (this.listeners[agentId] || []).filter((f) => f !== cb);
  }

  onExit(agentId: string, cb: (code: number) => void) {
    if (!this.exitListeners[agentId]) this.exitListeners[agentId] = [];
    this.exitListeners[agentId].push(cb);
  }

  offExit(agentId: string, cb: (code: number) => void) {
    this.exitListeners[agentId] = (this.exitListeners[agentId] || []).filter((f) => f !== cb);
  }

  sendCommand(agentId: string, command: string) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.ws.send(JSON.stringify({ target: agentId, command }));
  }

  sendCommandToMany(agentIds: string[], command: string) {
    agentIds.forEach((id) => this.sendCommand(id, command));
  }
}

export const dashboardSocket = new DashboardSocket();