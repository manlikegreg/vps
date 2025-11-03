import { useEffect, useState } from 'react'
import { dashboardSocket } from '../utils/socket'

type Agent = { agent_id: string; name: string; has_camera?: boolean }

type Props = {
  onOpenTerminal: (agent: Agent) => void
}

export default function AgentList({ onOpenTerminal }: Props) {
  const [agents, setAgents] = useState<Agent[]>([])
  const [blacklist, setBlacklist] = useState<string[]>([])

  useEffect(() => {
    dashboardSocket.connect()
    dashboardSocket.onAgents(setAgents)
    // Load blacklist
    const token = (typeof localStorage !== 'undefined' ? localStorage.getItem('master_token') : null) || ''
    const apiBase = (import.meta as any).env?.VITE_MASTER_API_URL || 'http://localhost:9000'
    const loadBL = async () => {
      try {
        const r = await fetch(`${apiBase}/admin/blacklist`, { headers: { Authorization: `Bearer ${token}` } })
        const j = await r.json(); setBlacklist(Array.isArray(j?.blacklist) ? j.blacklist : [])
      } catch {}
    }
    loadBL()
  }, [])

  const toggleBlacklist = async (agentId: string, makeBlack: boolean) => {
    const token = (typeof localStorage !== 'undefined' ? localStorage.getItem('master_token') : null) || ''
    const apiBase = (import.meta as any).env?.VITE_MASTER_API_URL || 'http://localhost:9000'
    try {
      const url = makeBlack ? `${apiBase}/admin/agents/${encodeURIComponent(agentId)}/blacklist` : `${apiBase}/admin/agents/${encodeURIComponent(agentId)}/whitelist`
      const r = await fetch(url, { method: 'POST', headers: { Authorization: `Bearer ${token}` } })
      if (r.ok) {
        setBlacklist((prev) => makeBlack ? Array.from(new Set([...prev, agentId])) : prev.filter((x) => x !== agentId))
      }
    } catch {}
  }


  return (
    <div className="card">
      <h3 style={{ color: '#9efc9e', margin: '0 0 8px' }}>Agents</h3>
      <div>
        {agents.map((a) => {
          const isBlack = blacklist.includes(a.agent_id)
          return (
            <div key={a.agent_id} className="agent-item">
              <div>
                <span className="status-dot" />
                <span className="agent-name">{a.name} {a.country_code ? (<span style={{ color: '#9efc9e', fontSize: 12 }}>({a.country_code})</span>) : null}</span>
                <div className="agent-id">{a.agent_id}</div>
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                <button className="btn" onClick={() => onOpenTerminal(a)}>Open Terminal</button>
                <button className="btn secondary" onClick={async () => { if (!confirm('Disconnect this agent?')) return; try { const token = (typeof localStorage !== 'undefined' ? localStorage.getItem('master_token') : null) || ''; const apiBase = (import.meta as any).env?.VITE_MASTER_API_URL || 'http://localhost:9000'; await fetch(`${apiBase}/admin/agents/${encodeURIComponent(a.agent_id)}/disconnect`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }); } catch {} }}>Disconnect</button>
                {!isBlack ? (
                  <button className="btn secondary" onClick={() => { if (confirm('Blacklist this agent? It will be refused until whitelisted.')) toggleBlacklist(a.agent_id, true) }}>Blacklist</button>
                ) : (
                  <button className="btn secondary" onClick={() => { if (confirm('Whitelist this agent?')) toggleBlacklist(a.agent_id, false) }}>Whitelist</button>
                )}
              </div>
            </div>
          )
        })}
        {agents.length === 0 && (
          <div style={{ color: '#777' }}>No agents connected</div>
        )}
      </div>
      <div style={{ marginTop: 12 }}>
        <h3 style={{ color: '#ffb347', margin: '8px 0' }}>Blacklisted</h3>
        <div>
          {blacklist.map((id) => (
            <div key={id} className="agent-item">
              <div>
                <span className="agent-name">{id}</span>
                <div className="agent-id" style={{ color: '#999' }}>blocked</div>
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                <button className="btn secondary" onClick={() => { if (confirm('Whitelist this agent?')) toggleBlacklist(id, false) }}>Whitelist</button>
              </div>
            </div>
          ))}
          {blacklist.length === 0 && (
            <div style={{ color: '#777' }}>No blacklisted agents</div>
          )}
        </div>
      </div>
    </div>
  )
}