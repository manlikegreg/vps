import Terminal from './components/Terminal'
import Login from './components/Login'
import './App.css'
import React, { useEffect, useState } from 'react'

function App() {
  const [token, setToken] = useState<string | null>(null)

  useEffect(() => {
    const t = localStorage.getItem('terminal_token')
    if (t) setToken(t)
  }, [])

  const handleLogout = () => {
    localStorage.removeItem('terminal_token')
    setToken(null)
  }

  return (
    <div style={{ 
      minHeight: '100vh', 
      backgroundColor: '#1e1e1e', 
      color: '#ffffff',
      fontFamily: 'Arial, sans-serif',
      display: 'flex',
      flexDirection: 'column'
    }}>
      <header style={{ 
        padding: '16px 20px', 
        borderBottom: '1px solid #333',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between'
      }}>
        <div>
          <h1 style={{ margin: 0, fontSize: '20px' }}>Web Terminal</h1>
          <p style={{ margin: '6px 0 0 0', fontSize: '12px', opacity: 0.8 }}>Interactive terminal interface</p>
        </div>
        {token && (
          <button onClick={handleLogout} style={{ background: 'transparent', border: '1px solid #444', color: '#fff', padding: '6px 10px', borderRadius: 4, cursor: 'pointer' }}>
            Logout
          </button>
        )}
      </header>
      <main style={{ flex: 1, padding: '12px 20px 20px 20px' }}>
        {token ? <Terminal /> : <Login onLogin={(t) => setToken(t)} />}
      </main>
    </div>
  )
}

export default App
