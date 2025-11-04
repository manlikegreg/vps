import { useEffect, useState } from 'react'

export default function MastersPanel({ open, urls, onRefresh, onAdd, onUpdate, onDelete, onReconnect, onClose }: {
  open: boolean
  urls: string[]
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
    <div style={{ position: 'fixed', top: 0, right: 0, bottom: 0, width: open ? 420 : 0, background: '#0f0f0f', borderLeft: '1px solid #222', overflow: 'hidden', transition: 'width 0.2s ease', zIndex: 1000 }}>
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
          {urls.map((u) => (
            <div key={u} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
              <input className="input" value={edits[u] ?? u} onChange={(e)=>setEdits((prev)=>({ ...prev, [u]: e.target.value }))} />
              <button className="btn" onClick={()=>{ const nu = (edits[u] ?? u).trim(); if (!nu) return; if (nu===u) return; onUpdate(u, nu) }}>Save</button>
              <button className="btn secondary" onClick={()=>{ if (confirm(`Delete this URL?\n${u}`)) onDelete(u) }}>Delete</button>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}