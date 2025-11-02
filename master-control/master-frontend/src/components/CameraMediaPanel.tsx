import { useEffect, useState } from 'react'
import { listMedia, getMediaBlob, deleteMedia, type CameraMediaMeta } from '../utils/cameraMedia'

export default function CameraMediaPanel({ open, onClose, agentId }: { open: boolean; onClose: () => void; agentId?: string }) {
  const [items, setItems] = useState<CameraMediaMeta[]>([])
  const [loading, setLoading] = useState(false)

  const refresh = async () => {
    setLoading(true)
    try { setItems(await listMedia(agentId)) } catch {}
    setLoading(false)
  }

  useEffect(() => { if (open) refresh() }, [open, agentId])

  const download = async (id: string, fallbackName: string, mime: string) => {
    const blob = await getMediaBlob(id)
    if (!blob) return
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = fallbackName
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  const del = async (id: string) => { await deleteMedia(id); await refresh() }

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
          const base = `${(m.agentName || m.agentId).replace(/[^\w\-\. ]+/g, '_')}-${m.kind}-${m.ts}`
          const fname = m.kind === 'photo' ? `${base}.jpg` : `${base}.webm`
          return (
            <div key={m.id} style={{ borderBottom: '1px solid #1b1b1b', padding: '8px 0' }}>
              <div style={{ color: '#ddd' }}>{m.agentName || m.agentId}</div>
              <div style={{ color: '#777', fontSize: 12 }}>{m.kind.toUpperCase()} • {date} • {(m.size/1024/1024).toFixed(2)} MB</div>
              <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
                <button className="btn" onClick={() => download(m.id, fname, m.mime)}>Download</button>
                <button className="btn secondary" onClick={() => del(m.id)}>Delete</button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
