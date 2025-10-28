import React, { useEffect, useRef, useState } from 'react';
import { Terminal as XTerm } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { WebLinksAddon } from '@xterm/addon-web-links';
import '@xterm/xterm/css/xterm.css';

const Terminal: React.FC = () => {
  const terminalRef = useRef<HTMLDivElement>(null);
  const xtermRef = useRef<XTerm | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isBusy, setIsBusy] = useState(false);
  const isBusyRef = useRef(false);
  const inputBufferRef = useRef<string>('');
  const caretRef = useRef<number>(0);
  const historyRef = useRef<string[]>([]);
  const historyIndexRef = useRef<number>(0);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  const [files, setFiles] = useState<Array<{ name: string; is_dir: boolean; size?: number; modified?: number }>>([]);
  const [uploading, setUploading] = useState(false);
  const uploadInputRef = useRef<HTMLInputElement | null>(null);
  const apiUrl = (import.meta as any).env?.VITE_API_URL || 'http://localhost:8000';
  const token = typeof window !== 'undefined' ? (localStorage.getItem('terminal_token') || '') : '';

  useEffect(() => {
    if (!terminalRef.current) return;

    const term = new XTerm({
      cursorBlink: true,
      fontSize: 16,
      lineHeight: 1.2,
      scrollback: 5000,
      convertEol: true,
      fontFamily: 'Consolas, "Courier New", monospace',
      theme: {
        background: '#1e1e1e',
        foreground: '#ffffff',
        cursor: '#ffffff',
      },
    });

    const fitAddon = new FitAddon();
    const webLinksAddon = new WebLinksAddon();
    term.loadAddon(fitAddon);
    term.loadAddon(webLinksAddon);

    term.open(terminalRef.current);
    // Fit after render to avoid dimensions undefined
    requestAnimationFrame(() => {
      try { fitAddon.fit(); } catch { /* ignore */ }
    });

    xtermRef.current = term;
    fitAddonRef.current = fitAddon;

    const prompt = () => {
      term.write('$ ');
      inputBufferRef.current = '';
      caretRef.current = 0;
      historyIndexRef.current = historyRef.current.length;
    };

    const renderLine = () => {
      // Clear line and redraw prompt + buffer, then place cursor
      const buf = inputBufferRef.current;
      const caret = caretRef.current;
      term.write('\r\x1b[2K');
      term.write('$ ' + buf);
      const moveLeft = buf.length - caret;
      if (moveLeft > 0) {
        term.write(`\x1b[${moveLeft}D`);
      }
    };

    const setBusy = (val: boolean) => { setIsBusy(val); isBusyRef.current = val; };

    // Observe size changes and refit
    if ('ResizeObserver' in window) {
      const ro = new ResizeObserver(() => {
        try { fitAddon.fit(); } catch { /* ignore */ }
      });
      ro.observe(terminalRef.current);
      resizeObserverRef.current = ro;
    }

    // Connect to WebSocket
     const wsUrl = apiUrl.replace('http', 'ws') + '/ws/terminal' + (token ? `?token=${encodeURIComponent(token)}` : '');
     const ws = new WebSocket(wsUrl);
     wsRef.current = ws;

    ws.onopen = () => {
      setIsConnected(true);
      term.writeln('Connected to terminal server');
      prompt();
     // Auto refresh file list on connect
     (async () => {
       try {
         const res = await fetch(`${apiUrl}/stats?token=${encodeURIComponent(token)}`);
         const data = await res.json();
         setFiles(Array.isArray(data?.files) ? data.files : []);
       } catch {}
     })();
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.message) {
          term.writeln(data.message);
        }
        if (data.output) {
          term.write(data.output);
        }
        if (data.error) {
          term.write(`\r\n\x1b[31m${data.error}\x1b[0m`);
        }
        if (data.exit_code !== undefined) {
          setBusy(false);
          term.write(`\r\n[Process exited with code ${data.exit_code}]\r\n`);
          prompt();
          renderLine();
        }
      } catch (e) {
        term.writeln(`\r\nParse error: ${String(e)}`);
      }
    };

    ws.onclose = (event) => {
      setIsConnected(false);
      if (event.code === 1008) {
        term.writeln('\r\nUnauthorized. Please login.');
      } else {
        term.writeln('\r\nConnection closed');
      }
    };

    ws.onerror = () => {
      term.writeln('\r\nWebSocket error');
    };

    // Handle terminal input with buffer, caret, history
    term.onData((data) => {
      if (isBusyRef.current) {
        return; // ignore input while command is running
      }
      const charCode = data.charCodeAt(0);
      if (charCode === 13) { // Enter
        const input = inputBufferRef.current.trim();
        term.write('\r\n');
        if (input.length > 0) {
          historyRef.current.push(input);
          historyIndexRef.current = historyRef.current.length;
          if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            setBusy(true);
            wsRef.current.send(input);
          } else {
            term.writeln('Not connected to server');
          }
        }
        inputBufferRef.current = '';
        caretRef.current = 0;
      } else if (charCode === 127 || charCode === 8) { // Backspace
        if (caretRef.current > 0) {
          const buf = inputBufferRef.current;
          const idx = caretRef.current - 1;
          inputBufferRef.current = buf.slice(0, idx) + buf.slice(idx + 1);
          caretRef.current = Math.max(0, idx);
          renderLine();
        }
      } else if (charCode >= 32) {
        // Insert printable characters at caret position
        const buf = inputBufferRef.current;
        const caret = caretRef.current;
        inputBufferRef.current = buf.slice(0, caret) + data + buf.slice(caret);
        caretRef.current = caret + data.length;
        renderLine();
      }
    });

    // Key handling for arrows and Ctrl combos
    term.onKey(({ domEvent }) => {
      const k = domEvent.key;
      // Ctrl+V paste
      if (!isBusyRef.current && domEvent.ctrlKey && k.toLowerCase() === 'v') {
        domEvent.preventDefault();
        if (navigator.clipboard && navigator.clipboard.readText) {
          navigator.clipboard.readText().then((text) => {
            if (!text) return;
            const buf = inputBufferRef.current;
            const caret = caretRef.current;
            inputBufferRef.current = buf.slice(0, caret) + text + buf.slice(caret);
            caretRef.current = caret + text.length;
            renderLine();
          }).catch(() => {});
        }
        return;
      }
      // Ctrl+C to clear current line (or send cancel in future)
      if (domEvent.ctrlKey && k.toLowerCase() === 'c') {
        domEvent.preventDefault();
        if (isBusyRef.current) {
          // Show ^C, rely on backend cancellation support when available
          term.write('^C\r\n');
        } else {
          term.write('^C\r\n');
          inputBufferRef.current = '';
          caretRef.current = 0;
        }
        prompt();
        renderLine();
        return;
      }
      if (isBusyRef.current) return;
      // Arrow keys and history navigation
      if (k === 'ArrowLeft') {
        domEvent.preventDefault();
        caretRef.current = Math.max(0, caretRef.current - 1);
        renderLine();
        return;
      }
      if (k === 'ArrowRight') {
        domEvent.preventDefault();
        const len = inputBufferRef.current.length;
        caretRef.current = Math.min(len, caretRef.current + 1);
        renderLine();
        return;
      }
      if (k === 'ArrowUp') {
        domEvent.preventDefault();
        if (historyRef.current.length > 0) {
          historyIndexRef.current = Math.max(0, historyIndexRef.current - 1);
          const cmd = historyRef.current[historyIndexRef.current] ?? '';
          inputBufferRef.current = cmd;
          caretRef.current = cmd.length;
          renderLine();
        }
        return;
      }
      if (k === 'ArrowDown') {
        domEvent.preventDefault();
        if (historyRef.current.length > 0) {
          historyIndexRef.current = Math.min(historyRef.current.length, historyIndexRef.current + 1);
          const idx = historyIndexRef.current;
          const cmd = idx < historyRef.current.length ? historyRef.current[idx] : '';
          inputBufferRef.current = cmd;
          caretRef.current = cmd.length;
          renderLine();
        }
        return;
      }
    });

    const onWindowResize = () => {
      try { fitAddon.fit(); } catch { /* ignore */ }
    };
    window.addEventListener('resize', onWindowResize);

    return () => {
      window.removeEventListener('resize', onWindowResize);
      resizeObserverRef.current?.disconnect();
      ws.close();
      term.dispose();
    };
  }, []);

  const refreshStats = async () => {
    try {
      const res = await fetch(`${apiUrl}/stats?token=${encodeURIComponent(token)}`);
      const data = await res.json();
      setFiles(Array.isArray(data?.files) ? data.files : []);
    } catch {}
  };

  const handleUploadClick = () => {
    uploadInputRef.current?.click();
  };

  const onFileSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await fetch(`${apiUrl}/upload?token=${encodeURIComponent(token)}`, { method: 'POST', body: fd });
      await res.json();
      await refreshStats();
    } catch {}
    setUploading(false);
    if (uploadInputRef.current) uploadInputRef.current.value = '';
  };

    return (
      <div style={{ padding: '0', height: '100%' }}>
        <div style={{ marginBottom: '8px', padding: '0 2px', display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ color: isConnected ? 'green' : 'red', fontSize: '12px', fontWeight: 'bold' }}>
            {isConnected ? '● Connected' : '● Disconnected'}
          </span>
          {isBusy && <span style={{ marginLeft: 8, color: '#bbb', fontSize: '12px' }}>Running...</span>}
          <button onClick={handleUploadClick} style={{ background: 'transparent', border: '1px solid #444', color: '#fff', padding: '4px 8px', borderRadius: 4, cursor: 'pointer' }} disabled={!isConnected || uploading}>
            {uploading ? 'Uploading...' : 'Upload File'}
          </button>
          <input ref={uploadInputRef} type="file" style={{ display: 'none' }} onChange={onFileSelected} />
          <button onClick={refreshStats} style={{ background: 'transparent', border: '1px solid #444', color: '#fff', padding: '4px 8px', borderRadius: 4, cursor: 'pointer' }} disabled={!isConnected}>
            Refresh Files
          </button>
          <span style={{ color: '#bbb', fontSize: 12 }}>Files: {files.length}</span>
        </div>
        <div ref={terminalRef} style={{ width: '100%', height: 'calc(100% - 24px)', border: '1px solid #333', borderRadius: '4px' }} />
        {files.length > 0 && (
          <div style={{ marginTop: 8, padding: 6, border: '1px solid #333', borderRadius: 4 }}>
            <div style={{ color: '#9efc9e', marginBottom: 6, fontSize: 12 }}>Current Directory Files</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr auto auto', gap: 6 }}>
              {files.map((f, i) => (
                <React.Fragment key={i}>
                  <div style={{ color: '#ddd' }}>{f.name}</div>
                  <div style={{ color: '#888', fontSize: 12 }}>{f.is_dir ? 'dir' : (f.size ?? 0) + ' B'}</div>
                  <div style={{ color: '#666', fontSize: 12 }}>{f.modified ? new Date(f.modified * 1000).toLocaleString() : ''}</div>
                </React.Fragment>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  };

export default Terminal;