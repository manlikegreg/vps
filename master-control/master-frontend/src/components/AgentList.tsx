import { useEffect, useState } from 'react'
import { dashboardSocket } from '../utils/socket'

type Agent = { agent_id: string; name: string }

type Props = {
  onOpenTerminal: (agent: Agent) => void
}

export default function AgentList({ onOpenTerminal }: Props) {
  const [agents, setAgents] = useState<Agent[]>([])

  useEffect(() => {
    dashboardSocket.connect()
    dashboardSocket.onAgents(setAgents)
  }, [])

  return (
    <div className="card">
      <h3 style={{ color: '#9efc9e', margin: '0 0 8px' }}>Agents</h3>
      <div>
        {agents.map((a) => (
          <div key={a.agent_id} className="agent-item">
            <div>
              <span className="status-dot" />
              <span className="agent-name">{a.name}</span>
              <div className="agent-id">{a.agent_id}</div>
            </div>
            <button className="btn" onClick={() => onOpenTerminal(a)}>Open Terminal</button>
          </div>
        ))}
        {agents.length === 0 && (
          <div style={{ color: '#777' }}>No agents connected</div>
        )}
      </div>
    </div>
  )
}