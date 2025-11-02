import { useEffect, useState } from 'react'
import { dashboardSocket } from '../utils/socket'
import { savePhoto, saveVideo } from '../utils/cameraMedia'
import CameraMediaPanel from './CameraMediaPanel'

export default function CameraView({ agentId, enabled, onStarted, onStopped }: { agentId: string; enabled: boolean; onStarted?: () => void; onStopped?: () => void }) {
  const [frame, setFrame] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const [recording, setRecording] = useState(false)
  const [showPanel, setShowPanel] = useState(false)
  const [agentName, setAgentName] = useState('')
  const canvasRef = useState<HTMLCanvasElement | null>(null)[0] || null
  // Workaround: create canvas element on demand
  const getCanvas = () => {
    let c = document.getElementById('cam-canvas') as HTMLCanvasElement | null
    if (!c) {
      c = document.createElement('canvas')
      c.id = 'cam-canvas'
      c.style.display = 'none'
      document.body.appendChild(c)
    }
    return c
  }
  const recorderRef = useState<MediaRecorder | null>(null)[0] || null
  let _recorder: MediaRecorder | null = (recorderRef as any)
  let _chunks: Blob[] = []

  useEffect(() => {
    const cb = (f: { data: string; w?: number; h?: number }) => {
      setFrame(f.data)
      const cvs = getCanvas()
      const img = new Image()
      img.onload = () => {
        cvs.width = img.width; cvs.height = img.height
        const ctx = cvs.getContext('2d')!
        ctx.drawImage(img, 0, 0)
      }
      img.src = f.data
    }
    dashboardSocket.onCamera(agentId, cb)
    return () => dashboardSocket.offCamera(agentId, cb)
  }, [agentId])

  const start = () => { if (!enabled) return; dashboardSocket.startCamera(agentId, { fps: 8, quality: 60 }); setRunning(true); try { onStarted && onStarted() } catch {} }
  const stop = () => { dashboardSocket.stopCamera(agentId); setRunning(false); setFrame(null); try { onStopped && onStopped() } catch {} }

  const takePhoto = async () => {
    try {
      const cvs = getCanvas()
      const blob: Blob = await new Promise((res) => cvs.toBlob((b) => res(b || new Blob()), 'image/jpeg', 0.9)!)
      const id = await savePhoto(agentId, agentName || agentId, blob)
      // auto-download
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = `camera-${(agentName||agentId).replace(/[^\w\-\. ]+/g, '_')}-${Date.now()}.jpg`
      document.body.appendChild(a); a.click(); a.remove()
      URL.revokeObjectURL(url)
    } catch {}
  }

  const startRecord = () => {
    if (recording) return
    const cvs = getCanvas()
    const stream = (cvs as any).captureStream ? (cvs as any).captureStream(8) : null
    if (!stream) return
    const rec = new MediaRecorder(stream, { mimeType: 'video/webm;codecs=vp9' })
    _chunks = []
    rec.ondataavailable = (e) => { if (e.data && e.data.size) _chunks.push(e.data) }
    rec.onstop = async () => {
      const blob = new Blob(_chunks, { type: 'video/webm' })
      await saveVideo(agentId, agentName || agentId, blob)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = `camera-${(agentName||agentId).replace(/[^\w\-\. ]+/g, '_')}-${Date.now()}.webm`
      document.body.appendChild(a); a.click(); a.remove()
      URL.revokeObjectURL(url)
    }
    rec.start()
    ;(recorderRef as any) = rec
    setRecording(true)
  }
  const stopRecord = () => {
    try { ((recorderRef as any) as MediaRecorder)?.stop() } catch {}
    setRecording(false)
  }

  return (
    <div className="card" style={{ marginTop: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <h3 style={{ color: '#9efc9e', margin: 0 }}>Camera</h3>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button className="btn" onClick={start} disabled={!enabled || running}>Start</button>
          <button className="btn secondary" onClick={stop} disabled={!running}>Stop</button>
          <button className="btn" onClick={takePhoto} disabled={!running}>Take Photo</button>
          {!recording ? (
            <button className="btn" onClick={startRecord} disabled={!running}>Start Record</button>
          ) : (
            <button className="btn secondary" onClick={stopRecord}>Stop Record</button>
          )}
          <button className="btn secondary" onClick={() => setShowPanel(true)}>Media</button>
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
      <CameraMediaPanel open={showPanel} onClose={() => setShowPanel(false)} agentId={agentId} />
    </div>
  )
}
