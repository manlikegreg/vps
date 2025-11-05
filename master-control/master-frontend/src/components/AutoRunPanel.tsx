import { useEffect, useState } from 'react'

type Item = { id: string; command: string; mode: 'interactive' | 'command'; enabled: boolean }

export default function AutoRunPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [items, setItems] = useState<Item[]>([])
  const [newCmd, setNewCmd] = useState('')
  const [newMode, setNewMode] = useState<'interactive'|'command'>('interactive')
  const [newEnabled, setNewEnabled] = useState(true)

  const apiBase = (import.meta as any).env?.VITE_MASTER_API_URL || (typeof window !== 'undefined' ? window.location.origin : '')
  const token = (typeof localStorage !== 'undefined' ? localStorage.getItem('master_token') : null) || ''

  const load = async () => {
    try {
      const r = await fetch(`${apiBase}/admin/autorun`, { headers: { Authorization: `Bearer ${token}` } })
      const j = await r.json()
      setItems(Array.isArray(j?.items) ? j.items : [])
    } catch {}
  }

  useEffect(() => { if (open) load() }, [open])

  const add = async () => {
    const command = newCmd.trim(); if (!command) return
    try {
      await fetch(`${apiBase}/admin/autorun`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify({ command, mode: newMode, enabled: newEnabled }) })
      setNewCmd(''); setNewMode('interactive'); setNewEnabled(true)
      load()
    } catch {}
  }

  const save = async (it: Item) => {
    try {
      await fetch(`${apiBase}/admin/autorun/${encodeURIComponent(it.id)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify(it) })
      load()
    } catch {}
  }

  const del = async (id: string) => {
    try {
      await fetch(`${apiBase}/admin/autorun/${encodeURIComponent(id)}`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } })
      load()
    } catch {}
  }

  return (
    <div style={{ position: 'fixed', top: 0, right: 0, bottom: 0, width: open ? 'min(460px, 100vw)' : 0, background: '#0f0f0f', borderLeft: '1px solid #222', overflow: 'hidden', transition: 'width 0.2s ease', zIndex: 1000 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: 10, borderBottom: '1px solid #222' }}>
        <div style={{ color: '#9efc9e' }}>Auto-run on Connect</div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <button className="btn secondary" onClick={load}>Refresh</button>
          <button className="btn" onClick={onClose}>Close</button>
        </div>
      </div>
      <div style={{ padding: 10, display: 'flex', flexDirection: 'column', gap: 10, height: 'calc(100% - 48px)' }}>
        <div style={{ display: 'flex', gap: 6 }}>
          <input className="input" placeholder="e.g., python -V" value={newCmd} onChange={(e)=>setNewCmd(e.target.value)} />
          <select className="input" style={{ width: 140 }} value={newMode} onChange={(e)=>setNewMode((e.target.value as any) || 'interactive')}>
            <option value="interactive">interactive</option>
            <option value="command">command</option>
          </select>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: '#ddd' }}>
            <input type="checkbox" checked={newEnabled} onChange={(e)=>setNewEnabled(e.target.checked)} /> enabled
          </label>
          <button className="btn" onClick={add}>Add</button>
        </div>
        <div style={{ flex: 1, minHeight: 0, border: '1px solid #222', borderRadius: 6, padding: 8, background: '#0b0b0b', overflowY: 'auto' }}>
          {items.length === 0 && <div style={{ color: '#777' }}>(no autorun commands)</div>}
          {items.map((it) => (
            <div key={it.id} style={{ display: 'grid', gridTemplateColumns: '1fr auto auto auto', gap: 6, alignItems: 'center', marginBottom: 8 }}>
              <input className="input" value={it.command} onChange={(e)=>setItems(prev=>prev.map(p=>p.id===it.id?{...p, command:e.target.value}:p))} />
              <select className="input" style={{ width: 140 }} value={it.mode} onChange={(e)=>setItems(prev=>prev.map(p=>p.id===it.id?{...p, mode:(e.target.value as any)}:p))}>
                <option value="interactive">interactive</option>
                <option value="command">command</option>
              </select>
              <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: '#ddd' }}>
                <input type="checkbox" checked={!!it.enabled} onChange={(e)=>setItems(prev=>prev.map(p=>p.id===it.id?{...p, enabled:e.target.checked}:p))} /> enabled
              </label>
              <div style={{ display: 'inline-flex', gap: 6 }}>
                <button className="btn secondary" onClick={()=>save(it)}>Save</button>
                <button className="btn secondary" onClick={()=>{ if (confirm('Delete this autorun entry?')) del(it.id) }}>Delete</button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}