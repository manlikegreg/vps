import { useEffect, useRef, useState } from 'react'
import { dashboardSocket } from '../utils/socket'
import RecordingsPanel from './RecordingsPanel'

export default function RemoteView({ agentId, agentName, onClose }: { agentId: string; agentName: string; onClose?: () => void }) {
  const [frame, setFrame] = useState<string | null>(null)
  const [nativeW, setNativeW] = useState<number | undefined>(undefined)
  const [nativeH, setNativeH] = useState<number | undefined>(undefined)
  const [running, setRunning] = useState(false)
  const [expanded, setExpanded] = useState(true)
  const [recording, setRecording] = useState(false)
  const [res, setRes] = useState<number>(720)
  const [q, setQ] = useState<number>(70)
  const [fps, setFps] = useState<number | 'default'>('default')
  const imgRef = useRef<HTMLImageElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const [showRecs, setShowRecs] = useState(false)
  const [control, setControl] = useState(false)
  const [cursorXY, setCursorXY] = useState<{x:number,y:number}|null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])

  useEffect(() => {
    const cb = (f: { data: string; w?: number; h?: number }) => {
      setFrame(f.data)
      setNativeW(f.w)
      setNativeH(f.h)
    }
    dashboardSocket.onScreen(agentId, cb)
    return () => dashboardSocket.offScreen(agentId, cb)
  }, [agentId])

  useEffect(() => {
    // Draw to canvas for recording when a new frame arrives
    const cvs = canvasRef.current
    if (!cvs || !frame || !recording) return
    if (!nativeW || !nativeH) return
    if (cvs.width !== nativeW || cvs.height !== nativeH) { cvs.width = nativeW; cvs.height = nativeH }
    const img = new Image()
    img.onload = () => {
      const ctx = cvs.getContext('2d')!
      ctx.drawImage(img, 0, 0, nativeW, nativeH)
    }
    img.src = frame
  }, [frame, recording, nativeW, nativeH])

  const startScreen = () => { dashboardSocket.startScreen(agentId, { fps: fps === 'default' ? undefined : fps, quality: q, height: res }); setRunning(true) }
  const stopScreen = () => { dashboardSocket.stopScreen(agentId); setRunning(false); setFrame(null); if (recording) { try { recorderRef.current?.stop() } catch {} ; setRecording(false) } }

  const startRecord = () => {
    if (recording) return
    const cvs = canvasRef.current
    if (!cvs) { console.warn('No canvas for recording'); return }
    const capture = (cvs as any).captureStream ? (cvs as any).captureStream(8) : null
    if (!capture) { console.warn('Canvas captureStream not supported'); return }
    try {
      const rec = new MediaRecorder(capture, { mimeType: 'video/webm;codecs=vp9' })
      chunksRef.current = []
      rec.ondataavailable = (e) => { if (e.data && e.data.size) chunksRef.current.push(e.data) }
      rec.onstart = () => setRecording(true)
      rec.onerror = () => { setRecording(false) }
      rec.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: 'video/webm' })
        // Store to local recordings DB
        try {
          const mod = await import('../utils/recordings')
          await mod.saveRecording(agentId, agentName, blob)
        } catch {}
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        const safeName = agentName?.trim() ? agentName.replace(/[^\w\-\. ]+/g, '_') : agentId
        a.href = url; a.download = `screen-${safeName}-${Date.now()}.webm`
        document.body.appendChild(a); a.click(); a.remove()
        URL.revokeObjectURL(url)
        setRecording(false)
      }
      // Optimistic toggle so the button changes immediately
      setRecording(true)
      rec.start()
      recorderRef.current = rec
    } catch (e) {
      console.error('Failed to start recording', e)
      setRecording(false)
    }
  }
  const stopRecord = () => {
    try { if (recorderRef.current && (recorderRef.current as any).state !== 'inactive') recorderRef.current.stop() } catch {}
    setRecording(false)
  }

  const handleClick = (e: React.MouseEvent) => {
    // clicks handled via down/up; keep for single-click fallback
    if (!control || !imgRef.current || !nativeW || !nativeH) return
    const rect = imgRef.current.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top
    const realX = Math.round((x / rect.width) * nativeW)
    const realY = Math.round((y / rect.height) * nativeH)
    dashboardSocket.sendMouse(agentId, { action: 'click', x: realX, y: realY, button: e.button === 2 ? 'right' : 'left' })
  }

  const onMouseDown = (e: React.MouseEvent<HTMLImageElement>) => {
    if (!control || !imgRef.current || !nativeW || !nativeH) return
    e.preventDefault()
    const rect = imgRef.current.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top
    const realX = Math.round((x / rect.width) * nativeW)
    const realY = Math.round((y / rect.height) * nativeH)
    const button = e.button === 2 ? 'right' : 'left'
    dashboardSocket.sendMouse(agentId, { action: 'down', x: realX, y: realY, button })
  }

  const onMouseUp = (e: React.MouseEvent<HTMLImageElement>) => {
    if (!control || !imgRef.current || !nativeW || !nativeH) return
    e.preventDefault()
    const rect = imgRef.current.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top
    const realX = Math.round((x / rect.width) * nativeW)
    const realY = Math.round((y / rect.height) * nativeH)
    const button = e.button === 2 ? 'right' : 'left'
    dashboardSocket.sendMouse(agentId, { action: 'up', x: realX, y: realY, button })
  }

  const onMouseMove = (e: React.MouseEvent<HTMLImageElement>) => {
    if (!imgRef.current || !nativeW || !nativeH) return
    const rect = imgRef.current.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top
    setCursorXY({ x, y })
    if (!control) return
    if ((e.buttons & 1) === 0 && (e.buttons & 2) === 0) return // only send while a button is held
    const realX = Math.round((x / rect.width) * nativeW)
    const realY = Math.round((y / rect.height) * nativeH)
    dashboardSocket.sendMouse(agentId, { action: 'move', x: realX, y: realY })
  }

  const onWheel = (e: React.WheelEvent<HTMLImageElement>) => {
    if (!control) return
    e.preventDefault()
    const dy = Math.sign(e.deltaY) * -1 // invert to feel natural
    dashboardSocket.sendMouse(agentId, { action: 'scroll', dx: 0, dy })
  }

  const sendKeys = () => {
    const txt = window.prompt('Type text to send:')
    if (!txt) return
    dashboardSocket.sendKeyboard(agentId, { text: txt })
  }

  // Keyboard listeners when control is enabled
  useEffect(() => {
    if (!control) return
    const onDown = (e: KeyboardEvent) => {
      if (e.target && (e.target as HTMLElement).closest('input,textarea')) return
      e.preventDefault()
      const key = e.key
      if (key.length === 1 && !e.ctrlKey && !e.metaKey) {
        dashboardSocket.sendKeyboard(agentId, { text: key })
      } else {
        const map: Record<string,string> = {
          Enter: 'enter', Backspace: 'backspace', Tab: 'tab', Escape: 'escape', ' ': 'space',
          ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down', Delete: 'delete', Home: 'home', End: 'end', PageUp: 'pageup', PageDown: 'pagedown',
          Shift: 'shift', Control: 'ctrl', Alt: 'alt', Meta: 'meta',
        }
        const name = map[key] || key.toLowerCase()
        dashboardSocket.sendKeyboard(agentId, { key: name, action: 'down' })
      }
    }
    const onUp = (e: KeyboardEvent) => {
      if (e.target && (e.target as HTMLElement).closest('input,textarea')) return
      e.preventDefault()
      const map: Record<string,string> = {
        Enter: 'enter', Backspace: 'backspace', Tab: 'tab', Escape: 'escape', ' ': 'space',
        ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down', Delete: 'delete', Home: 'home', End: 'end', PageUp: 'pageup', PageDown: 'pagedown',
        Shift: 'shift', Control: 'ctrl', Alt: 'alt', Meta: 'meta',
      }
      const key = e.key
      const name = map[key] || key.toLowerCase()
      dashboardSocket.sendKeyboard(agentId, { key: name, action: 'up' })
    }
    window.addEventListener('keydown', onDown)
    window.addEventListener('keyup', onUp)
    return () => {
      window.removeEventListener('keydown', onDown)
      window.removeEventListener('keyup', onUp)
    }
  }, [control, agentId])

  return (
    <div className="card" style={{ marginTop: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <h3 style={{ color: '#9efc9e', margin: 0 }}>Remote View</h3>
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
            <input className="input" type="number" min={10} max={95} step={1} value={q} onChange={(e) => setQ(Math.max(10, Math.min(95, parseInt(e.target.value)||70)))} style={{ width: 80 }} title="JPEG quality" />
          </div>
          {!running ? (
            <button className="btn" onClick={startScreen}>Start Remote Screen</button>
          ) : (
            <button className="btn secondary" onClick={stopScreen}>Stop</button>
          )}
          {!recording ? (
            <button className="btn" onClick={startRecord} disabled={!running}>Start Screen Record</button>
          ) : (
            <button className="btn secondary" onClick={stopRecord}>Stop Record</button>
          )}
          <button className="btn secondary" onClick={() => setExpanded((v) => !v)}>{expanded ? 'Shrink' : 'Enlarge'}</button>
          <button className="btn secondary" onClick={() => setShowRecs(true)}>Recordings</button>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: '#ddd' }}>
            <input type="checkbox" checked={control} onChange={(e) => setControl(e.target.checked)} /> Control
          </label>
          <button className="btn secondary" onClick={sendKeys} disabled={!control}>Send Keys</button>
          <button className="btn secondary" onClick={() => { const url = `${window.location.origin}/remote.html?agentId=${encodeURIComponent(agentId)}&agentName=${encodeURIComponent(agentName)}`; window.open(url, '_blank'); }}>Open in New Tab</button>
          {onClose && <button className="btn secondary" onClick={onClose}>Close</button>}
        </div>
      </div>
      <div style={{ position: 'relative', border: '1px solid #222', borderRadius: 6, background: '#000', display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: expanded ? 520 : 280, height: expanded ? 520 : 280 }}>
        {frame ? (
          <img ref={imgRef} src={frame} style={{ maxWidth: '100%', width: '100%', height: '100%', objectFit: 'contain', cursor: control ? 'none' : 'default' }} onClick={handleClick} onMouseDown={onMouseDown} onMouseUp={onMouseUp} onMouseMove={onMouseMove} onWheel={onWheel} onContextMenu={(e) => { if (control) e.preventDefault() }} />
        ) : (
          <div style={{ color: '#777', padding: 20 }}>{running ? 'Waiting for frames...' : 'Not running'}</div>
        )}
        {cursorXY && (
          <div style={{ position: 'absolute', left: cursorXY.x - 6, top: cursorXY.y - 6, width: 12, height: 12, borderRadius: 6, background: control ? '#ffeb3b' : '#9e9e9e', opacity: 0.9, pointerEvents: 'none' }} />
        )}
        {/* hidden canvas used for recording */}
        <canvas ref={canvasRef} style={{ display: 'none' }} />
      </div>
      <RecordingsPanel open={showRecs} onClose={() => setShowRecs(false)} agentId={agentId} />
    </div>
  )
}
