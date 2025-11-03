import { createRoot } from 'react-dom/client'
import React, { useEffect } from 'react'
import CameraView from './components/CameraView'
import './styles.css'
import { dashboardSocket } from './utils/socket'

function CameraOnly() {
  useEffect(() => { dashboardSocket.connect() }, [])
  const params = new URLSearchParams(location.search)
  const agentId = params.get('agentId') || ''
  const agentName = params.get('agentName') || agentId
  return (
    <div className="app">
      <header className="header">
        <h1>Camera Viewer</h1>
        <p>Agent: {agentName} ({agentId})</p>
      </header>
      <div className="content" style={{ padding: 10 }}>
        <CameraView agentId={agentId} agentName={agentName} enabled={true} />
      </div>
    </div>
  )
}

createRoot(document.getElementById('root')!).render(<CameraOnly />)
