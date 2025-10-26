import { useState } from 'react'
import AgentList from './AgentList'
import AgentTerminal from './AgentTerminal'
import CommandPanel from './CommandPanel'

type Agent = { agent_id: string; name: string }

export default function Dashboard() {
  const [activeAgent, setActiveAgent] = useState<Agent | null>(null)

  return (
    <div className="content">
      <aside className="sidebar">
        <AgentList onOpenTerminal={setActiveAgent} />
      </aside>
      <main className="main">
        <CommandPanel />
        {!activeAgent && (
          <div className="card" style={{ color: '#777' }}>
            Select an agent to open a terminal.
          </div>
        )}
        {activeAgent && (
          <AgentTerminal agent={activeAgent} onClose={() => setActiveAgent(null)} />
        )}
      </main>
    </div>
  )
}
