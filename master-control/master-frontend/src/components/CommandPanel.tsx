import { useEffect, useMemo, useState } from 'react'
import { dashboardSocket } from '../utils/socket'

type Agent = { agent_id: string; name: string }

export default function CommandPanel() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [command, setCommand] = useState('')

  useEffect(() => {
    dashboardSocket.connect()
    dashboardSocket.onAgents((list) => {
      setAgents(list)
      setSelected((prev) => {
        const next: Record<string, boolean> = { ...prev }
        list.forEach((a) => { if (next[a.agent_id] === undefined) next[a.agent_id] = false })
        // cleanup removed agents
        Object.keys(next).forEach((id) => { if (!list.find((a) => a.agent_id === id)) delete next[id] })
        return next
      })
    })
  }, [])

  const selectedIds = useMemo(() => Object.keys(selected).filter((id) => selected[id]), [selected])

  const toggleAll = (value: boolean) => {
    const next: Record<string, boolean> = {}
    agents.forEach((a) => { next[a.agent_id] = value })
    setSelected(next)
  }

  const runOnSelected = () => {
    if (!command.trim() || selectedIds.length === 0) return
    dashboardSocket.sendCommandToMany(selectedIds, command)
    setCommand('')
  }

  const runOnAll = () => {
    if (!command.trim() || agents.length === 0) return
    dashboardSocket.sendCommandToMany(agents.map((a) => a.agent_id), command)
    setCommand('')
  }

  return (
    <div className="card" style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <h3 style={{ color: '#9efc9e', margin: 0 }}>Command Panel</h3>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn secondary" onClick={() => toggleAll(true)}>Select All</button>
          <button className="btn secondary" onClick={() => toggleAll(false)}>Clear</button>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 10 }}>
        <div style={{ flex: 1 }}>
          <input className="input" placeholder="Enter command" value={command} onChange={(e) => setCommand(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') runOnSelected() }} />
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button className="btn" onClick={runOnSelected} disabled={selectedIds.length === 0 || !command.trim()}>Run on Selected</button>
            <button className="btn" onClick={runOnAll} disabled={agents.length === 0 || !command.trim()}>Run on All</button>
          </div>
        </div>
        <div style={{ width: 320, maxHeight: 160, overflow: 'auto', borderLeft: '1px solid #222', paddingLeft: 10 }}>
          {agents.map((a) => (
            <label key={a.agent_id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '4px 0' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span className="status-dot" />
                <span className="agent-name">{a.name}</span>
              </div>
              <input type="checkbox" checked={!!selected[a.agent_id]} onChange={(e) => setSelected((prev) => ({ ...prev, [a.agent_id]: e.target.checked }))} />
            </label>
          ))}
          {agents.length === 0 && (
            <div style={{ color: '#777' }}>No agents</div>
          )}
        </div>
      </div>
    </div>
  )
}
