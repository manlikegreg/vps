import { useEffect, useState } from 'react'
import Dashboard from './components/Dashboard'
import { dashboardSocket } from './utils/socket'

export default function App() {
  const [status, setStatus] = useState<'connected' | 'disconnected'>('disconnected')

  useEffect(() => {
    dashboardSocket.connect()
    dashboardSocket.onStatus(setStatus)
  }, [])

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
      <Dashboard />
    </div>
  )
}
