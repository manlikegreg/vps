import { useEffect, useRef, useState } from 'react'

export default function TerminalPane({
  interactive,
  lines,
  onSend,
  stopInteractive,
  height = 280,
  fontSize = 13,
}: {
  interactive: boolean
  lines: string[]
  onSend: (cmd: string) => void
  stopInteractive: () => void
  height?: number
  fontSize?: number
}) {
  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const historyRef = useRef<string[]>([])
  const historyIndexRef = useRef<number>(0)
  const lastSendRef = useRef<{cmd:string, at:number}>({ cmd: '', at: 0 })

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [lines])

  const send = () => {
    const cmd = input
    if (!cmd.trim()) return
    const now = Date.now()
    const last = lastSendRef.current
    if (last.cmd === cmd && (now - last.at) < 400) { return }
    lastSendRef.current = { cmd, at: now }
    historyRef.current.push(cmd)
    historyIndexRef.current = historyRef.current.length
    onSend(cmd)
    setInput('')
  }
      <div className="terminal" ref={scrollRef} style={{ flex: 1, minHeight: 0, overflowY: 'auto', fontSize }}>
        {lines.map((l, i) => (
          <p key={i} className="line" style={{ margin: '2px 0' }}>{l}</p>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <input
          className="input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a command and press Enter"
          style={{ fontSize }}
          onKeyDown={(e) => {
            const k = e.key
            if (k === 'Enter') { e.preventDefault(); send(); return }
            if (e.ctrlKey && k.toLowerCase() === 'c') {
              e.preventDefault()
              onLocalEcho('^C')
              stopInteractive()
              setInput('')
              return
            }
            if (k === 'ArrowUp') {
              e.preventDefault()
              if (historyRef.current.length) {
                historyIndexRef.current = Math.max(0, historyIndexRef.current - 1)
                const cmd = historyRef.current[historyIndexRef.current] ?? ''
                setInput(cmd)
              }
              return
            }
            if (k === 'ArrowDown') {
              e.preventDefault()
              if (historyRef.current.length) {
                historyIndexRef.current = Math.min(historyRef.current.length, historyIndexRef.current + 1)
                const idx = historyIndexRef.current
                const cmd = idx < historyRef.current.length ? historyRef.current[idx] : ''
                setInput(cmd)
              }
              return
            }
          }}
        />
        <button className="btn" onClick={send}>Send</button>
      </div>
    </div>
  )
}