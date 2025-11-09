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
  const [msgText, setMsgText] = useState<string>('Test message from Master Control')
  const [msgTarget, setMsgTarget] = useState<string>('active')
  const [msgSilent, setMsgSilent] = useState<boolean>(false)

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }

  const [whUrl, setWhUrl] = useState<string | null>(null)
  const [whInfo, setWhInfo] = useState<any>(null)
  const [whBase, setWhBase] = useState<string>('')

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
    }
    try {
      const r2 = await fetch(`${apiBase}/admin/telegram/webhook`, { headers })
      const j2 = await r2.json()
      setWhUrl(j2?.url || null)
      setWhInfo(j2?.info || null)
    } catch {}
    finally {
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

            <div className="card">
              <h4>Webhook</h4>
              {whUrl ? (
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <span>Active:</span>
                  <code style={{ fontSize: 12 }}>{whUrl}</code>
                  <button className="btn small" onClick={() => navigator.clipboard?.writeText(whUrl)}>Copy</button>
                  <button className="btn small danger" onClick={async () => {
                    setError(null)
                    try {
                      const r = await fetch(`${apiBase}/admin/telegram/webhook/delete`, { method: 'POST', headers })
                      const j = await r.json()
                      if (!j?.ok) throw new Error(j?.error || 'Remove failed')
                      await load()
                    } catch (e: any) {
                      setError(String(e?.message || e))
                    }
                  }}>Remove</button>
                </div>
              ) : (
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <input placeholder="Public base URL (e.g. https://mastervpsback.onrender.com)" value={whBase} onChange={(e) => setWhBase(e.target.value)} style={{ minWidth: 420 }} />
                  <button className="btn" onClick={async () => {
                    setError(null)
                    try {
                      const r = await fetch(`${apiBase}/admin/telegram/webhook/set`, { method: 'POST', headers, body: JSON.stringify({ base_url: whBase }) })
                      const j = await r.json()
                      if (!j?.ok) throw new Error(j?.error || 'Setup failed')
                      await load()
                    } catch (e: any) {
                      setError(String(e?.message || e))
                    }
                  }}>Set Webhook</button>
                </div>
              )}
              <div style={{ marginTop: 6, color: '#888', fontSize: 12 }}>
                {(whInfo?.result || whInfo)?.url ? `Telegram: ${(whInfo?.result || whInfo)?.url}` : 'Telegram webhook info unavailable'}
              </div>
            </div>

            <div className="card">
              <h4>Send Test Message</h4>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr auto auto auto', gap: 8, alignItems: 'center' }}>
                <input placeholder="Message" value={msgText} onChange={(e) => setMsgText(e.target.value)} />
                <select value={msgTarget} onChange={(e) => setMsgTarget(e.target.value)}>
                  <option value="active">Active bot</option>
                  {bots.map((b) => (
                    <option key={b.id} value={b.id}>{b.label || b.id}</option>
                  ))}
                </select>
                <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
                  <input type="checkbox" checked={msgSilent} onChange={(e) => setMsgSilent(e.target.checked)} />
                  Silent
                </label>
                <button className="btn" onClick={async () => {
                  setError(null)
                  try {
                    const body: any = { text: msgText }
                    if (msgTarget !== 'active') body.id = msgTarget
                    if (msgSilent) body.disable_notification = true
                    const r = await fetch(`${apiBase}/admin/telegram/send`, { method: 'POST', headers, body: JSON.stringify(body) })
                    const j = await r.json()
                    if (!j?.ok) throw new Error(j?.error || 'Send failed')
                    alert('Message sent')
                  } catch (e: any) {
                    setError(String(e?.message || e))
                  }
                }}>Send</button>
              </div>
              <div style={{ marginTop: 8 }}>
                <button className="btn secondary" onClick={() => test()}>
                  Test Active (typing/ping)
                </button>
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }}>
              <span style={{ color: '#888', fontSize: 12 }}>Tips: You can also set TELEGRAM_* env vars as a fallback.</span>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
