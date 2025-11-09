import { useEffect, useState } from 'react'

const apiBase = (import.meta as any).env?.VITE_MASTER_API_URL || (typeof window !== 'undefined' ? window.location.origin : '')

type Bot = {
  id: string
  label?: string | null
  chat_id?: string | null
  thread_id?: number | null
  token_last4?: string | null
  has_token?: boolean
}

type Props = {
  open: boolean
  token: string
  onClose: () => void
}

export default function TelegramPanel({ open, token, onClose }: Props) {
  const [bots, setBots] = useState<Bot[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [hasEnv, setHasEnv] = useState<boolean>(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [newLabel, setNewLabel] = useState('')
  const [newToken, setNewToken] = useState('')
  const [newChatId, setNewChatId] = useState('')
  const [newThreadId, setNewThreadId] = useState<string>('')

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const r = await fetch(`${apiBase}/admin/telegram`, { headers })
      const j = await r.json()
      setBots(Array.isArray(j?.bots) ? j.bots : [])
      setActiveId(j?.active_id || null)
      setHasEnv(!!j?.has_env)
    } catch (e: any) {
      setError(String(e?.message || e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { if (open) load() }, [open])

  const addBot = async () => {
    setAdding(true)
    setError(null)
    try {
      const body: any = { label: newLabel || undefined, token: newToken, chat_id: newChatId }
      if (newThreadId) body.thread_id = Number(newThreadId)
      const r = await fetch(`${apiBase}/admin/telegram/bots`, { method: 'POST', headers, body: JSON.stringify(body) })
      if (!r.ok) throw new Error('Add failed')
      setNewLabel(''); setNewToken(''); setNewChatId(''); setNewThreadId('')
      await load()
    } catch (e: any) {
      setError(String(e?.message || e))
    } finally {
      setAdding(false)
    }
  }

  const updateBot = async (id: string, patch: Partial<Bot> & { token?: string; chat_id?: string; thread_id?: number | null }) => {
    setError(null)
    try {
      const r = await fetch(`${apiBase}/admin/telegram/bots/${id}`, { method: 'PUT', headers, body: JSON.stringify(patch) })
      if (!r.ok) throw new Error('Update failed')
      await load()
    } catch (e: any) {
      setError(String(e?.message || e))
    }
  }

  const removeBot = async (id: string) => {
    setError(null)
    try {
      const r = await fetch(`${apiBase}/admin/telegram/bots/${id}`, { method: 'DELETE', headers })
      if (!r.ok) throw new Error('Delete failed')
      await load()
    } catch (e: any) {
      setError(String(e?.message || e))
    }
  }

  const activate = async (id: string) => {
    setError(null)
    try {
      const r = await fetch(`${apiBase}/admin/telegram/activate`, { method: 'POST', headers, body: JSON.stringify({ id }) })
      if (!r.ok) throw new Error('Activate failed')
      await load()
    } catch (e: any) {
      setError(String(e?.message || e))
    }
  }

  const test = async (id?: string) => {
    setError(null)
    try {
      const r = await fetch(`${apiBase}/admin/telegram/test`, { method: 'POST', headers, body: JSON.stringify({ id }) })
      const j = await r.json()
      if (!j?.ok) throw new Error(j?.error || 'Test failed')
      alert('Test OK (sent typing/ping)')
    } catch (e: any) {
      setError(String(e?.message || e))
    }
  }

  if (!open) return null

  return (
    <div className="modal-backdrop">
      <div className="modal">
        <div className="modal-header">
          <h3>Telegram Bots</h3>
          <button className="btn" onClick={onClose}>Close</button>
        </div>
        {loading ? (<div>Loading…</div>) : (
          <>
            {error && (<div className="error" style={{ color: '#c00' }}>{error}</div>)}
            <div className="card">
              <div style={{ marginBottom: 8, color: '#888', fontSize: 12 }}>
                {hasEnv ? 'Environment variables detected (fallback bot available)' : 'No env fallback detected'}
              </div>
              <table className="table">
                <thead>
                  <tr>
                    <th>Active</th>
                    <th>Label</th>
                    <th>Chat ID</th>
                    <th>Thread</th>
                    <th>Token</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {bots.length === 0 && (
                    <tr><td colSpan={6} style={{ color: '#777' }}>No bots configured</td></tr>
                  )}
                  {bots.map((b) => (
                    <tr key={b.id}>
                      <td>
                        <input type="radio" checked={activeId === b.id} onChange={() => activate(b.id)} />
                      </td>
                      <td>
                        <input value={b.label || ''} onChange={(e) => updateBot(b.id, { label: e.target.value })} />
                      </td>
                      <td>
                        <input value={b.chat_id || ''} onChange={(e) => updateBot(b.id, { chat_id: e.target.value })} />
                      </td>
                      <td>
                        <input value={String(b.thread_id ?? '')} onChange={(e) => updateBot(b.id, { thread_id: e.target.value ? Number(e.target.value) : null })} />
                      </td>
                      <td>
                        <span style={{ fontFamily: 'monospace' }}>{b.has_token ? `…${b.token_last4 || ''}` : '—'}</span>
                        <button className="btn small" style={{ marginLeft: 6 }} onClick={() => {
                          const v = prompt('Enter new token (will replace stored token)', '')
                          if (v != null && v.trim()) updateBot(b.id, { token: v.trim(), chat_id: b.chat_id || undefined, thread_id: b.thread_id ?? undefined, label: b.label || undefined })
                        }}>Set Token</button>
                      </td>
                      <td>
                        <button className="btn small" onClick={() => test(b.id)}>Test</button>
                        <button className="btn small danger" onClick={() => removeBot(b.id)} style={{ marginLeft: 6 }}>Delete</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="card">
              <h4>Add Bot</h4>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr auto', gap: 8, alignItems: 'center' }}>
                <input placeholder="Label (optional)" value={newLabel} onChange={(e) => setNewLabel(e.target.value)} />
                <input placeholder="Chat ID" value={newChatId} onChange={(e) => setNewChatId(e.target.value)} />
                <input placeholder="Thread ID (optional)" value={newThreadId} onChange={(e) => setNewThreadId(e.target.value)} />
                <input placeholder="Bot Token" value={newToken} onChange={(e) => setNewToken(e.target.value)} />
                <button className="btn" onClick={addBot} disabled={adding || !newToken || !newChatId}>{adding ? 'Adding…' : 'Add'}</button>
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }}>
              <button className="btn secondary" onClick={() => test()}>Test Active</button>
              <span style={{ color: '#888', fontSize: 12 }}>Tips: You can also set TELEGRAM_* env vars as a fallback.</span>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
