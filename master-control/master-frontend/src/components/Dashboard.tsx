import { useEffect, useState } from 'react'
import AgentList from './AgentList'
import AgentTerminal from './AgentTerminal'
import CommandPanel from './CommandPanel'
import MastersPanel from './MastersPanel'
import { dashboardSocket } from '../utils/socket'

type Agent = { agent_id: string; name: string; has_camera?: boolean }

export default function Dashboard() {
  const [activeAgent, setActiveAgent] = useState<Agent | null>(null)
  const [mastersOpen, setMastersOpen] = useState(false)
  const [masters, setMasters] = useState<Array<{ url: string; online?: boolean; current?: boolean }>>([])

  const openMasters = () => {
    if (!activeAgent) return
    setMasters([])
    setMastersOpen(true)
    dashboardSocket.sendAgentJson(activeAgent.agent_id, { type: 'masters_list' })
  }

  useEffect(() => {
    if (!mastersOpen || !activeAgent) return
    dashboardSocket.connect()
    const handler = (line: string) => {
      try {
        if (line && line[0] === '{') {
          const obj = JSON.parse(line)
if (obj && obj.type === 'masters_list' && Array.isArray(obj.urls)) {
            const st = (obj as any).status || {}
            const cur = (obj as any).current || null
            setMasters((obj.urls as string[]).map((u) => ({ url: u, online: !!st[u], current: cur === u })))
          }
        }
      } catch {}
    }
    dashboardSocket.subscribe(activeAgent.agent_id, handler)
    return () => dashboardSocket.unsubscribe(activeAgent.agent_id, handler)
  }, [mastersOpen, activeAgent?.agent_id])

  return (
    <div className="content">
      <aside className="sidebar">
        <AgentList onOpenTerminal={setActiveAgent} />
      </aside>
      <main className="main">
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginBottom: 8 }}>
          <button className="btn secondary" onClick={openMasters} disabled={!activeAgent}>Agent URLs</button>
        </div>
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
      <MastersPanel
        open={mastersOpen}
        urls={masters}
        onRefresh={() => activeAgent && dashboardSocket.sendAgentJson(activeAgent.agent_id, { type: 'masters_list' })}
        onAdd={(url) => activeAgent && dashboardSocket.sendAgentJson(activeAgent.agent_id, { type: 'masters_add', url })}
        onUpdate={(oldUrl, newUrl) => activeAgent && dashboardSocket.sendAgentJson(activeAgent.agent_id, { type: 'masters_update', old: oldUrl, new: newUrl })}
        onDelete={(url) => activeAgent && dashboardSocket.sendAgentJson(activeAgent.agent_id, { type: 'masters_delete', url })}
        onReconnect={() => activeAgent && dashboardSocket.sendAgentJson(activeAgent.agent_id, { type: 'masters_reconnect' })}
        onClose={() => setMastersOpen(false)}
      />
    </div>
  )
}
