import { useEffect, useRef, useState } from 'react'
import { dashboardSocket } from '../utils/socket'

type Agent = { agent_id: string; name: string }

type Props = { agent: Agent; onClose: () => void }

export default function AgentTerminal({ agent, onClose }: Props) {
  const [lines, setLines] = useState<string[]>([])
  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const lastLineRef = useRef<string>('')
  const historyRef = useRef<string[]>([])
  const historyIndexRef = useRef<number>(0)
  const [files, setFiles] = useState<Array<{ name: string; is_dir: boolean; size?: number; modified?: number }>>([])
  const [currentDir, setCurrentDir] = useState<string>('')
  const [uploading, setUploading] = useState(false)
  const uploadRef = useRef<HTMLInputElement | null>(null)
  const lastCmdRef = useRef<string>('')
  const apiBase = (import.meta as any).env?.VITE_MASTER_API_URL || 'http://localhost:9000'
  const token = (typeof localStorage !== 'undefined' ? localStorage.getItem('master_token') : null) || ''

  useEffect(() => {
    const handler = (line: string) => {
      setLines((prev) => {
        if ((prev.length ? prev[prev.length - 1] : lastLineRef.current) === line) return prev
        lastLineRef.current = line
        return [...prev, line]
      })
    }
    dashboardSocket.subscribe(agent.agent_id, handler)
    return () => dashboardSocket.unsubscribe(agent.agent_id, handler)
  }, [agent.agent_id])

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [lines])

  const send = () => {
    const cmd = input.trim()
    if (!cmd) return
    historyRef.current.push(cmd)
    historyIndexRef.current = historyRef.current.length
    lastCmdRef.current = cmd
    dashboardSocket.sendCommand(agent.agent_id, cmd)
    setInput('')
  }

  const refreshStats = async () => {
    try {
      const res = await fetch(`${apiBase}/agent/${agent.agent_id}/stats`, { headers: { Authorization: `Bearer ${token}` } })
      const data = await res.json()
      setFiles(Array.isArray(data?.files) ? data.files : [])
      setCurrentDir(typeof data?.current_dir === 'string' ? data.current_dir : '')
    } catch {}
  }

  const triggerUpload = () => uploadRef.current?.click()

  const onUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch(`${apiBase}/agent/${agent.agent_id}/upload`, { method: 'POST', body: fd, headers: { Authorization: `Bearer ${token}` } })
      await res.json()
      await refreshStats()
    } catch {}
    setUploading(false)
    if (uploadRef.current) uploadRef.current.value = ''
  }

  useEffect(() => {
    // initial fetch when opening
    refreshStats()
  }, [agent.agent_id])

  useEffect(() => {
    const onExit = (code: number) => {
      const lc = (lastCmdRef.current || '').trim().toLowerCase()
      if (code === 0 && (lc === 'cd' || lc.startsWith('cd ') || lc.startsWith('chdir '))) {
        refreshStats()
      }
    }
    dashboardSocket.onExit(agent.agent_id, onExit)
    return () => dashboardSocket.offExit(agent.agent_id, onExit)
  }, [agent.agent_id])

  const cdUp = () => {
    lastCmdRef.current = 'cd ..'
    dashboardSocket.sendCommand(agent.agent_id, 'cd ..')
  }
  const cdTo = (name: string) => {
    const cmd = `cd "${name.replace(/\"/g, '\\\"').replace(/"/g, '\\"')}"`
    lastCmdRef.current = cmd
    dashboardSocket.sendCommand(agent.agent_id, cmd)
  }

  const download = async (name: string) => {
    try {
      const res = await fetch(`${apiBase}/agent/${agent.agent_id}/download?name=${encodeURIComponent(name)}`, { headers: { Authorization: `Bearer ${token}` } })
      if (!res.ok) return
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = name
      document.body.appendChild(a)
      a.click()
      URL.revokeObjectURL(url)
      a.remove()
    } catch {}
  }

  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <div style={{ color: '#9efc9e' }}>Terminal: {agent.name}</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ color: '#9efc9e', fontSize: 12 }}>Path: <span style={{ color: '#ddd' }}>{currentDir || '(loading...)'}</span></span>
          <button className="btn secondary" onClick={cdUp}>Up</button>
          <button className="btn secondary" onClick={refreshStats}>Refresh</button>
          <button className="btn" onClick={triggerUpload} disabled={uploading}>{uploading ? 'Uploading...' : 'Upload'}</button>
          <input ref={uploadRef} type="file" style={{ display: 'none' }} onChange={onUpload} />
          <button className="btn secondary" onClick={onClose}>Close</button>
        </div>
      </div>
      <div className="terminal" ref={scrollRef}>
        {lines.map((l, i) => (
          <p key={i} className="line">{l}</p>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <input
          className="input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a command and press Enter"
          onKeyDown={(e) => {
            const k = e.key
            if (k === 'Enter') { e.preventDefault(); send(); return }
            if (e.ctrlKey && k.toLowerCase() === 'c') {
              e.preventDefault()
              setLines((prev) => [...prev, '^C'])
              setInput('')
              return
            }
            if (k === 'ArrowUp') {
              e.preventDefault()
              if (historyRef.current.length) {
                historyIndexRef.current = Math.max(0, historyIndexRef.current - 1)
                const cmd = historyRef.current[historyIndexRef.current] ?? ''
                setInput(cmd)
              }
              return
            }
            if (k === 'ArrowDown') {
              e.preventDefault()
              if (historyRef.current.length) {
                historyIndexRef.current = Math.min(historyRef.current.length, historyIndexRef.current + 1)
                const idx = historyIndexRef.current
                const cmd = idx < historyRef.current.length ? historyRef.current[idx] : ''
                setInput(cmd)
              }
              return
            }
          }}
        />
        <button className="btn" onClick={send}>Send</button>
      </div>
      <div style={{ marginTop: 8 }}>
        <h4 style={{ margin: '0 0 6px', color: '#9efc9e', fontSize: 14 }}>Current Directory Files</h4>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr auto auto auto', gap: 6 }}>
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <button className="btn secondary" title="Up one folder" onClick={cdUp}>↑</button>
              <span onClick={cdUp} style={{ color: '#9efc9e', cursor: 'pointer' }}>.. Parent folder</span>
            </div>
            <div style={{ color: '#888', fontSize: 12 }}>dir</div>
            <div style={{ color: '#666', fontSize: 12 }}></div>
            <div>
              <button className="btn secondary" onClick={cdUp}>Open</button>
            </div>
          </>
          {files.map((f, i) => (
            <>
              <div style={{ color: f.is_dir ? '#9efc9e' : '#ddd', cursor: f.is_dir ? 'pointer' : 'default' }} onClick={() => f.is_dir && cdTo(f.name)}>{f.name}</div>
              <div style={{ color: '#888', fontSize: 12 }}>{f.is_dir ? 'dir' : (f.size ?? 0) + ' B'}</div>
              <div style={{ color: '#666', fontSize: 12 }}>{f.modified ? new Date(f.modified * 1000).toLocaleString() : ''}</div>
              <div>
                {!f.is_dir ? (
                  <button className="btn secondary" onClick={() => download(f.name)}>Download</button>
                ) : (
                  <button className="btn secondary" onClick={() => cdTo(f.name)}>Open</button>
                )}
              </div>
            </>
          ))}
        </div>
        {files.length === 0 && (
          <div style={{ color: '#888', fontSize: 12, marginTop: 6 }}>(No items)</div>
        )}
      </div>
    </div>
  )
}