import { useEffect, useRef, useState } from 'react'
import { dashboardSocket } from '../utils/socket'

type Agent = { agent_id: string; name: string }

type Props = { agent: Agent; onClose: () => void }

export default function AgentTerminal({ agent, onClose }: Props) {
  const [lines, setLines] = useState<string[]>([])
  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const [files, setFiles] = useState<Array<{ name: string; is_dir: boolean; size?: number; modified?: number }>>([])
  const [uploading, setUploading] = useState(false)
  const uploadRef = useRef<HTMLInputElement | null>(null)
  const apiBase = (import.meta as any).env?.VITE_MASTER_API_URL || 'http://localhost:9000'
  const token = (typeof localStorage !== 'undefined' ? localStorage.getItem('master_token') : null) || ''

  useEffect(() => {
    const handler = (line: string) => setLines((prev) => [...prev, line])
    dashboardSocket.subscribe(agent.agent_id, handler)
    return () => dashboardSocket.unsubscribe(agent.agent_id, handler)
  }, [agent.agent_id])

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [lines])

  const send = () => {
    if (!input.trim()) return
    dashboardSocket.sendCommand(agent.agent_id, input)
    setInput('')
  }

  const refreshStats = async () => {
    try {
      const res = await fetch(`${apiBase}/agent/${agent.agent_id}/stats`, { headers: { Authorization: `Bearer ${token}` } })
      const data = await res.json()
      setFiles(Array.isArray(data?.files) ? data.files : [])
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

  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ color: '#9efc9e' }}>Terminal: {agent.name}</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button className="btn secondary" onClick={refreshStats}>Refresh Stats</button>
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
        <input className="input" value={input} onChange={(e) => setInput(e.target.value)} placeholder="Type a command and press Send" onKeyDown={(e) => { if (e.key === 'Enter') send() }} />
        <button className="btn" onClick={send}>Send</button>
      </div>
      {files.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <h4 style={{ margin: '0 0 6px', color: '#9efc9e', fontSize: 14 }}>Current Directory Files</h4>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr auto auto', gap: 6 }}>
            {files.map((f, i) => (
              <>
                <div style={{ color: '#ddd' }}>{f.name}</div>
                <div style={{ color: '#888', fontSize: 12 }}>{f.is_dir ? 'dir' : (f.size ?? 0) + ' B'}</div>
                <div style={{ color: '#666', fontSize: 12 }}>{f.modified ? new Date(f.modified * 1000).toLocaleString() : ''}</div>
              </>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}