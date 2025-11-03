import { createRoot } from 'react-dom/client'
import React, { useEffect } from 'react'
import RemoteView from './components/RemoteView'
import './styles.css'
import { dashboardSocket } from './utils/socket'

function RemoteOnly() {
  useEffect(() => { dashboardSocket.connect() }, [])
  const params = new URLSearchParams(location.search)
  const agentId = params.get('agentId') || ''
  const agentName = params.get('agentName') || agentId
  return (
    <div className="app">
      <header className="header">
        <h1>Remote Viewer</h1>
        <p>Agent: {agentName} ({agentId})</p>
      </header>
      <div className="content" style={{ padding: 10 }}>
        <RemoteView agentId={agentId} agentName={agentName} />
      </div>
    </div>
  )
}

createRoot(document.getElementById('root')!).render(<RemoteOnly />)
