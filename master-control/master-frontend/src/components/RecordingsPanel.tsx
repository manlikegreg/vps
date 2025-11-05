import { useEffect, useState } from 'react'

// Backend-driven recordings list (screen_video) from history DB
export default function RecordingsPanel({ open, onClose, agentId }: { open: boolean; onClose: () => void; agentId?: string }) {
  type Item = { id: string; ts: string; agent_id: string; kind: string; storage_url: string; size_bytes?: number }
  const [items, setItems] = useState<Item[]>([])
  const [loading, setLoading] = useState(false)
  const apiBase = (import.meta as any).env?.VITE_MASTER_API_URL || (typeof window !== 'undefined' ? window.location.origin : '')
  const token = (typeof localStorage !== 'undefined' ? localStorage.getItem('master_token') : null) || ''

  const refresh = async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ kind: 'screen_video' })
      if (agentId) params.set('agent_id', agentId)
      const r = await fetch(`${apiBase}/admin/history?${params.toString()}`, { headers: { Authorization: `Bearer ${token}` } })
      const j = await r.json()
      setItems(Array.isArray(j?.items) ? j.items : [])
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
        <div style={{ color: '#9efc9e' }}>Recordings</div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn secondary" onClick={refresh} disabled={loading}>{loading ? '...' : 'Refresh'}</button>
          <button className="btn" onClick={onClose}>Close</button>
        </div>
      </div>
      <div style={{ padding: 10, overflowY: 'auto', height: 'calc(100% - 48px)' }}>
        {items.length === 0 && <div style={{ color: '#777' }}>No recordings</div>}
        {items.map((r) => {
          const date = new Date(r.ts).toLocaleString()
          const nameBase = (r.agent_id || 'agent').replace(/[^\w\-\. ]+/g, '_')
          const href = `${apiBase}${r.storage_url}`
          const sizeMb = typeof r.size_bytes === 'number' ? (r.size_bytes / 1024 / 1024).toFixed(2) : '0.00'
          return (
            <div key={r.id} style={{ borderBottom: '1px solid #1b1b1b', padding: '8px 0' }}>
              <div style={{ color: '#ddd' }}>{r.agent_id}</div>
              <div style={{ color: '#777', fontSize: 12 }}>{date} • {sizeMb} MB</div>
              <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
                <a className="btn" href={href} download={`screen-${nameBase}-${Date.now()}.webm`} target="_blank" rel="noreferrer">Download</a>
                <button className="btn secondary" onClick={() => del(r.id)}>Delete</button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
