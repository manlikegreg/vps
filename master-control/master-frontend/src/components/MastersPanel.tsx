import { useEffect, useState } from 'react'

type MasterInfo = { url: string; online?: boolean; current?: boolean }

export default function MastersPanel({ open, urls, onRefresh, onAdd, onUpdate, onDelete, onReconnect, onClose }: {
  open: boolean
  urls: MasterInfo[]
  onRefresh: () => void
  onAdd: (url: string) => void
  onUpdate: (oldUrl: string, newUrl: string) => void
  onDelete: (url: string) => void
  onReconnect: () => void
  onClose: () => void
}) {
  const [newUrl, setNewUrl] = useState('')
  const [edits, setEdits] = useState<Record<string, string>>({})

  useEffect(() => { if (open) onRefresh() }, [open])

  return (
    <div style={{ position: 'fixed', top: 0, right: 0, bottom: 0, width: open ? 'min(420px, 100vw)' : 0, background: '#0f0f0f', borderLeft: '1px solid #222', overflow: 'hidden', transition: 'width 0.2s ease', zIndex: 1000 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: 10, borderBottom: '1px solid #222' }}>
        <div style={{ color: '#9efc9e' }}>Agent Masters</div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <button className="btn secondary" onClick={onRefresh}>Refresh</button>
          <button className="btn secondary" onClick={onReconnect}>Reconnect</button>
          <button className="btn" onClick={onClose}>Close</button>
        </div>
      </div>
      <div style={{ padding: 10, display: 'flex', flexDirection: 'column', gap: 10, height: 'calc(100% - 48px)' }}>
        <div style={{ display: 'flex', gap: 6 }}>
          <input className="input" placeholder="wss://host/ws/agent" value={newUrl} onChange={(e)=>setNewUrl(e.target.value)} />
          <button className="btn" onClick={() => { const u = newUrl.trim(); if (!u) return; onAdd(u); setNewUrl('') }}>Add</button>
        </div>
        <div style={{ flex: 1, minHeight: 0, border: '1px solid #222', borderRadius: 6, padding: 8, background: '#0b0b0b', overflowY: 'auto' }}>
          {urls.length === 0 && <div style={{ color: '#777' }}>(no masters)</div>}
          {urls.map((m) => (
            <div key={m.url} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
              <span title={m.online ? 'online' : 'offline'} style={{ width: 10, height: 10, borderRadius: 5, background: m.online ? '#3fb950' : '#555', display: 'inline-block' }} />
              {m.current && <span style={{ color: '#9efc9e', fontSize: 12 }} title="This master">(current)</span>}
              <input className="input" value={edits[m.url] ?? m.url} onChange={(e)=>setEdits((prev)=>({ ...prev, [m.url]: e.target.value }))} />
              <button className="btn" onClick={()=>{ const nu = (edits[m.url] ?? m.url).trim(); if (!nu) return; if (nu===m.url) return; onUpdate(m.url, nu) }}>Save</button>
              <button className="btn secondary" onClick={()=>{ if (confirm(`Delete this URL?\n${m.url}`)) onDelete(m.url) }}>Delete</button>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}