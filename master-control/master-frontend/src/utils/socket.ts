type Agent = { agent_id: string; name: string };

type DashboardEvent =
  | { type: 'agents'; agents: Agent[] }
  | { type: 'log'; agent_id: string; line: string }
  | { type: 'exit'; agent_id: string; exit_code: number }
  | { type: 'error'; message: string };

class DashboardSocket {
  private ws: WebSocket | null = null;
  private url = (import.meta as any).env?.VITE_DASHBOARD_WS_URL || 'ws://localhost:9000/ws/dashboard';
  private agents: Agent[] = [];
  private listeners: { [agentId: string]: ((line: string) => void)[] } = {};
  private agentsListeners: ((agents: Agent[]) => void)[] = [];
  private statusListeners: ((status: 'connected' | 'disconnected') => void)[] = [];

  connect() {
    if (this.ws) return;
    this.ws = new WebSocket(this.url);
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

  sendCommand(agentId: string, command: string) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.ws.send(JSON.stringify({ target: agentId, command }));
  }

  sendCommandToMany(agentIds: string[], command: string) {
    agentIds.forEach((id) => this.sendCommand(id, command));
  }
}

export const dashboardSocket = new DashboardSocket();
