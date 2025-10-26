import React, { useState } from 'react';

interface Props {
  onLogin: (token: string) => void;
}

const Login: React.FC<Props> = ({ onLogin }) => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await fetch(`${apiUrl}/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data?.error || 'Login failed');
      }
      const token = data?.token;
      if (!token) throw new Error('No token received');
      localStorage.setItem('terminal_token', token);
      onLogin(token);
    } catch (err: any) {
      setError(err?.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 360, margin: '40px auto', padding: 20, background: '#222', border: '1px solid #333', borderRadius: 8 }}>
      <h2 style={{ marginTop: 0, color: '#fff' }}>Login</h2>
      <p style={{ marginTop: 4, color: '#bbb', fontSize: 12 }}>Enter credentials to access the terminal</p>
      <form onSubmit={handleSubmit}>
        <div style={{ marginBottom: 12 }}>
          <label style={{ display: 'block', color: '#bbb', fontSize: 12, marginBottom: 6 }}>Username</label>
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="admin"
            style={{ width: '100%', padding: '8px 10px', borderRadius: 4, border: '1px solid #444', background: '#111', color: '#fff' }}
          />
        </div>
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: 'block', color: '#bbb', fontSize: 12, marginBottom: 6 }}>Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="admin"
            style={{ width: '100%', padding: '8px 10px', borderRadius: 4, border: '1px solid #444', background: '#111', color: '#fff' }}
          />
        </div>
        {error && <div style={{ color: '#ff6b6b', fontSize: 12, marginBottom: 8 }}>{error}</div>}
        <button type="submit" disabled={loading} style={{ width: '100%', padding: '10px 12px', background: '#4c8bf5', color: '#fff', border: 'none', borderRadius: 4, cursor: loading ? 'not-allowed' : 'pointer' }}>
          {loading ? 'Logging in...' : 'Login'}
        </button>
      </form>
      <div style={{ marginTop: 12, color: '#888', fontSize: 12 }}>
        Default: admin / admin (configurable in backend env)
      </div>
    </div>
  );
};

export default Login;
