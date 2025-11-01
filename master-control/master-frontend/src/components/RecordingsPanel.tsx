import { useEffect, useState } from 'react'
import { listRecordings, getRecordingBlob, deleteRecording, type RecordingMeta } from '../utils/recordings'

export default function RecordingsPanel({ open, onClose, agentId }: { open: boolean; onClose: () => void; agentId?: string }) {
  const [items, setItems] = useState<RecordingMeta[]>([])
  const [loading, setLoading] = useState(false)

  const refresh = async () => {
    setLoading(true)
    try { setItems(await listRecordings(agentId)) } catch {}
    setLoading(false)
  }

  useEffect(() => { if (open) refresh() }, [open, agentId])

  const download = async (id: string, name: string) => {
    const blob = await getRecordingBlob(id)
    if (!blob) return
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = name
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  const del = async (id: string) => { await deleteRecording(id); await refresh() }

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
          const fname = `screen-${(r.agentName || r.agentId).replace(/[^\w\-\. ]+/g, '_')}-${r.ts}.webm`
          return (
            <div key={r.id} style={{ borderBottom: '1px solid #1b1b1b', padding: '8px 0' }}>
              <div style={{ color: '#ddd' }}>{r.agentName || r.agentId}</div>
              <div style={{ color: '#777', fontSize: 12 }}>{date} • {(r.size/1024/1024).toFixed(2)} MB</div>
              <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
                <button className="btn" onClick={() => download(r.id, fname)}>Download</button>
                <button className="btn secondary" onClick={() => del(r.id)}>Delete</button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
