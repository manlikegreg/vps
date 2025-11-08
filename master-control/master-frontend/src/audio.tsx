import React from 'react'
import { createRoot } from 'react-dom/client'
import AudioPanel from './components/AudioPanel'
import './styles.css'

function App() {
  const params = new URLSearchParams(typeof window !== 'undefined' ? window.location.search : '')
  const agentId = params.get('agentId') || ''
  const agentName = params.get('agentName') || agentId
  if (!agentId) return <div style={{ padding: 20, color: '#ccc' }}>Missing agentId</div>
  return (
    <div className="app">
      <header className="header"><h2>Audio Control - {agentName}</h2></header>
      <main className="main"><AudioPanel agentId={agentId} agentName={agentName} /></main>
    </div>
  )
}

const root = createRoot(document.getElementById('root')!)
root.render(<App />)
