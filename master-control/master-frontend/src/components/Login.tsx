import { useState } from 'react'

const apiBase = (import.meta as any).env?.VITE_MASTER_API_URL || 'http://localhost:9000'

export default function Login({ onSuccess }: { onSuccess: (token: string) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const res = await fetch(`${apiBase}/admin/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      if (!res.ok) throw new Error('Invalid credentials')
      const data = await res.json()
      const token = data?.token
      if (!token) throw new Error('No token returned')
      localStorage.setItem('master_token', token)
      onSuccess(token)
    } catch (e: any) {
      setError(e?.message || 'Login failed')
    }
    setLoading(false)
  }

  return (
    <div className="content" style={{ minHeight: 'calc(100vh - 140px)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
      <div className="card" style={{ width: '100%', maxWidth: 520 }}>
        <h3 style={{ color: '#9efc9e', margin: '0 0 12px' }}>Admin Login</h3>
        <form onSubmit={submit}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <input className="input" style={{ width: '100%' }} placeholder="Username" value={username} onChange={(e) => setUsername(e.target.value)} />
            <input className="input" style={{ width: '100%' }} type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} />
            {error && <div style={{ color: '#ff6b6b', fontSize: 13 }}>{error}</div>}
            <button className="btn" style={{ width: '100%' }} type="submit" disabled={loading}>{loading ? 'Signing in...' : 'Sign In'}</button>
            <div style={{ color: '#888', fontSize: 12, textAlign: 'center' }}>Default: admin / admin</div>
          </div>
        </form>
      </div>
    </div>
  )
}