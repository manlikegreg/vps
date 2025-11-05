import { useEffect, useState } from 'react'
import Dashboard from './components/Dashboard'
import Login from './components/Login'
import { dashboardSocket } from './utils/socket'

const apiBase = (import.meta as any).env?.VITE_MASTER_API_URL || (typeof window !== 'undefined' ? window.location.origin : '')

export default function App() {
  const [status, setStatus] = useState<'connected' | 'disconnected'>('disconnected')
  const [token, setToken] = useState<string | null>(null)
  const [verified, setVerified] = useState<boolean>(false)
const [dbOk, setDbOk] = useState<boolean | null>(null)
  const [dbKind, setDbKind] = useState<string | null>(null)

  useEffect(() => {
    const existing = typeof localStorage !== 'undefined' ? localStorage.getItem('master_token') : null
    setToken(existing)
    dashboardSocket.setToken(existing)
    dashboardSocket.connect()
    dashboardSocket.onStatus(setStatus)
  }, [])

  useEffect(() => {
    const check = async () => {
      if (!token) { setVerified(false); setDbOk(null); return }
      try {
        const res = await fetch(`${apiBase}/admin/verify`, { headers: { Authorization: `Bearer ${token}` } })
        setVerified(res.ok)
      } catch {
        setVerified(false)
      }
try {
        const r = await fetch(`${apiBase}/admin/db/health`, { headers: { Authorization: `Bearer ${token}` } })
        if (r.ok) {
          const j = await r.json()
          const kind = String(j?.dialect ?? j?.database ?? '').toLowerCase() || null
          setDbKind(kind)
          setDbOk(true)
        } else {
          setDbOk(false)
          setDbKind(null)
        }
      } catch {
        setDbOk(false)
        setDbKind(null)
      }
    }
    check()
  }, [token])

  const onLoginSuccess = (tok: string) => {
    setToken(tok)
    dashboardSocket.setToken(tok)
    dashboardSocket.connect()
    setVerified(true)
  }

  const logout = () => {
    try { localStorage.removeItem('master_token') } catch {}
    setToken(null)
    setVerified(false)
    dashboardSocket.setToken(null)
  }

  return (
    <div className="app">
      <header className="header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <h1>Master Control</h1>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <span className={`status-dot ${status === 'connected' ? '' : 'red'}`} />
              <span style={{ color: '#aaa', fontSize: 12 }}>Backend {status}</span>
            </div>
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <span className={`status-dot ${dbOk ? '' : 'red'}`} />
<span style={{ color: '#aaa', fontSize: 12 }}>DB {dbOk === null ? '...' : (dbOk ? (dbKind || 'ok') : 'error')}</span>
            </div>
          </div>
          {verified && (
            <button className="btn" onClick={logout} style={{ marginLeft: 12 }}>Logout</button>
          )}
        </div>
        <p>Manage connected agents, send commands, and stream logs.</p>
      </header>
      {!verified ? (<Login onSuccess={onLoginSuccess} />) : (<Dashboard />)}
    </div>
  )
}
