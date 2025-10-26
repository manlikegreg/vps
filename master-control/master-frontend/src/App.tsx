import { useEffect, useState } from 'react'
import Dashboard from './components/Dashboard'
import Login from './components/Login'
import { dashboardSocket } from './utils/socket'

const apiBase = (import.meta as any).env?.VITE_MASTER_API_URL || 'http://localhost:9000'

export default function App() {
  const [status, setStatus] = useState<'connected' | 'disconnected'>('disconnected')
  const [token, setToken] = useState<string | null>(null)
  const [verified, setVerified] = useState<boolean>(false)

  useEffect(() => {
    const existing = typeof localStorage !== 'undefined' ? localStorage.getItem('master_token') : null
    setToken(existing)
    dashboardSocket.setToken(existing)
    dashboardSocket.connect()
    dashboardSocket.onStatus(setStatus)
  }, [])

  useEffect(() => {
    const check = async () => {
      if (!token) { setVerified(false); return }
      try {
        const res = await fetch(`${apiBase}/admin/verify`, { headers: { Authorization: `Bearer ${token}` } })
        setVerified(res.ok)
      } catch {
        setVerified(false)
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

  return (
    <div className="app">
      <header className="header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <h1>Master Control</h1>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span className={`status-dot ${status === 'connected' ? '' : 'red'}`} />
            <span style={{ color: '#aaa', fontSize: 12 }}>Backend {status}</span>
          </div>
        </div>
        <p>Manage connected agents, send commands, and stream logs.</p>
      </header>
      {!verified ? (<Login onSuccess={onLoginSuccess} />) : (<Dashboard />)}
    </div>
  )
}
