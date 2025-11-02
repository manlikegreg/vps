import { useEffect, useState } from 'react'
import { dashboardSocket } from '../utils/socket'

export default function CameraView({ agentId, enabled }: { agentId: string; enabled: boolean }) {
  const [frame, setFrame] = useState<string | null>(null)
  const [running, setRunning] = useState(false)

  useEffect(() => {
    const cb = (f: { data: string }) => setFrame(f.data)
    dashboardSocket.onCamera(agentId, cb)
    return () => dashboardSocket.offCamera(agentId, cb)
  }, [agentId])

  const start = () => { if (!enabled) return; dashboardSocket.startCamera(agentId, { fps: 8, quality: 60 }); setRunning(true) }
  const stop = () => { dashboardSocket.stopCamera(agentId); setRunning(false); setFrame(null) }

  return (
    <div className="card" style={{ marginTop: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <h3 style={{ color: '#9efc9e', margin: 0 }}>Camera</h3>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn" onClick={start} disabled={!enabled || running}>Start</button>
          <button className="btn secondary" onClick={stop} disabled={!running}>Stop</button>
        </div>
      </div>
      {!enabled && <div style={{ color: '#ffb347', fontSize: 12, marginBottom: 6 }}>Camera not available on this agent.</div>}
      <div style={{ border: '1px solid #222', borderRadius: 6, background: '#000', display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 240 }}>
        {frame ? (
          <img src={frame} style={{ maxWidth: '100%', width: '100%', objectFit: 'contain' }} />
        ) : (
          <div style={{ color: '#777', padding: 20 }}>{running ? 'Waiting for frames...' : 'Not running'}</div>
        )}
      </div>
    </div>
  )
}
