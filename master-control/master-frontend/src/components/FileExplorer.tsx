import React, { useEffect, useMemo, useRef, useState } from 'react'

export type FileItem = { name: string; is_dir: boolean; size?: number; modified?: number }

export default function FileExplorer({
  files,
  currentDir,
  selected,
  onToggle,
  onClearSelection,
  onSelectAll,
  onCopy,
  onCut,
  onPaste,
  clipboard,
  onUp,
  onCdTo,
  onDownload,
  onSetWallpaper,
}: {
  files: FileItem[]
  currentDir: string
  selected: Set<string>
  onToggle: (name: string) => void
  onClearSelection: () => void
  onSelectAll: () => void
  onCopy: () => void
  onCut: () => void
  onPaste: () => void
  clipboard: { items: string[]; mode: 'copy'|'cut'; dir: string } | null
  onUp: () => void
  onCdTo: (name: string) => void
  onDownload: (name: string) => void
  onSetWallpaper: (name: string) => void
}) {
  const [query, setQuery] = useState('')
  const [foldersFirst, setFoldersFirst] = useState(true)
  const [sortAsc, setSortAsc] = useState(true)
  const rowHeight = 36
  const viewportRef = useRef<HTMLDivElement | null>(null)
  const [viewportH, setViewportH] = useState(520)
  const [scrollTop, setScrollTop] = useState(0)

  const isImage = (name: string) => /\.(png|jpe?g|bmp|gif|webp|tiff?)$/i.test(name || '')

  useEffect(() => {
    const el = viewportRef.current
    if (!el) return
    const onResize = () => setViewportH(el.clientHeight || 520)
    onResize()
    const obs = new ResizeObserver(onResize)
    obs.observe(el)
    return () => obs.disconnect()
  }, [])

  const sorted = useMemo(() => {
    let arr = [...files]
    if (query.trim()) {
      const q = query.trim().toLowerCase()
      arr = arr.filter((f) => f.name.toLowerCase().includes(q))
    }
    arr.sort((a, b) => {
      if (foldersFirst) {
        if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1
      }
      const na = a.name.toLowerCase()
      const nb = b.name.toLowerCase()
      return sortAsc ? na.localeCompare(nb) : nb.localeCompare(na)
    })
    return arr
  }, [files, query, foldersFirst, sortAsc])

  const total = sorted.length + 1 // include parent row
  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - 10)
  const visibleCount = Math.ceil(viewportH / rowHeight) + 20
  const end = Math.min(total, start + visibleCount)

  const items: Array<{ type: 'parent' } | { type: 'file'; item: FileItem }> = []
  // Build sliced list with virtualization
  for (let i = start; i < end; i++) {
    if (i === 0) items.push({ type: 'parent' })
    else items.push({ type: 'file', item: sorted[i - 1] })
  }

  const parts = useMemo(() => {
    const dir = currentDir || ''
    const segs: { label: string; path: string }[] = []
    if (!dir) return segs
    const isWin = dir.includes('\\') || /:/.test(dir)
    const raw = isWin ? dir.split('\\') : dir.split('/')
    let acc = isWin && raw[0]?.endsWith(':') ? raw[0] + '\\' : (raw[0] || '')
    if (raw[0]) segs.push({ label: raw[0] || '', path: acc })
    for (let i = 1; i < raw.length; i++) {
      const p = raw[i]
      if (p === '') continue
      acc = isWin ? (acc.endsWith('\\') ? acc + p : acc + '\\' + p) : (acc.endsWith('/') ? acc + p : acc + '/' + p)
      segs.push({ label: p, path: acc })
    }
    return segs
  }, [currentDir])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ color: '#9efc9e', fontSize: 12 }}>Path:</span>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            {parts.map((p, idx) => (
              <span key={idx} style={{ color: '#ddd', cursor: 'pointer' }} onClick={() => onCdTo(p.path)}>
                {p.label}
                {idx < parts.length - 1 ? <span style={{ color: '#555' }}>{' / '}</span> : null}
              </span>
            ))}
          </div>
        </div>
        <button className="btn secondary" onClick={onUp}>Up</button>
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        <input className="input" placeholder="Search files..." value={query} onChange={(e) => setQuery(e.target.value)} />
        <button className="btn secondary" onClick={() => setFoldersFirst((v) => !v)}>{foldersFirst ? 'Folders ↑' : 'Mixed'}</button>
        <button className="btn secondary" onClick={() => setSortAsc((v) => !v)}>{sortAsc ? 'A→Z' : 'Z→A'}</button>
        <div style={{ marginLeft: 'auto', display: 'inline-flex', gap: 6 }}>
          <button className="btn secondary" onClick={onSelectAll} style={{ padding: '2px 6px', fontSize: 12 }}>Select all</button>
          <button className="btn secondary" onClick={onClearSelection} style={{ padding: '2px 6px', fontSize: 12 }}>Clear</button>
          <button className="btn" onClick={onCopy} disabled={!selected.size} style={{ padding: '2px 8px', fontSize: 12 }}>Copy</button>
          <button className="btn" onClick={onCut} disabled={!selected.size} style={{ padding: '2px 8px', fontSize: 12 }}>Cut</button>
          <button className="btn secondary" onClick={onPaste} disabled={!clipboard} style={{ padding: '2px 8px', fontSize: 12 }}>Paste</button>
        </div>
      </div>
      <div style={{ border: '1px solid #222', borderRadius: 6, overflow: 'hidden', background: '#0b0b0b' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr auto', gap: 6, position: 'sticky', top: 0, background: '#0b0b0b', padding: '6px 8px', borderBottom: '1px solid #222', zIndex: 1 }}>
          <div style={{ color: '#9efc9e' }}></div>
          <div style={{ color: '#9efc9e' }}>Name</div>
          <div style={{ color: '#9efc9e', textAlign: 'right' }}>Actions</div>
        </div>
        <div ref={viewportRef} style={{ position: 'relative', height: 520, overflowY: 'auto' }} onScroll={(e) => setScrollTop((e.target as HTMLDivElement).scrollTop)}>
          <div style={{ height: total * rowHeight, position: 'relative' }}>
            {items.map((it, idx) => {
              const realIndex = start + idx
              const top = realIndex * rowHeight
              if (it.type === 'parent') {
                return (
                  <div key={'parent'} style={{ position: 'absolute', top, left: 0, right: 0, height: rowHeight, display: 'grid', gridTemplateColumns: 'auto 1fr auto', gap: 6, alignItems: 'center', padding: '0 8px' }}>
                    <div></div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap', overflow: 'hidden' }}>
                      <button className="btn secondary" title="Up one folder" onClick={onUp} style={{ padding: '2px 6px', fontSize: 12 }}>Up</button>
                      <span onClick={onUp} style={{ color: '#9efc9e', cursor: 'pointer' }}>.. Parent folder</span>
                    </div>
                    <div style={{ display: 'inline-flex', gap: 6, justifyContent: 'flex-end', whiteSpace: 'nowrap' }}>
                      <button className="btn secondary" onClick={onUp} style={{ padding: '2px 6px', fontSize: 12 }}>Open</button>
                    </div>
                  </div>
                )
              }
              const f = it.item
              const title = f.is_dir ? 'dir' : `${f.size ?? 0} B${f.modified ? ` • ${new Date(f.modified * 1000).toLocaleString()}` : ''}`
              return (
                <div key={f.name + '-' + realIndex} style={{ position: 'absolute', top, left: 0, right: 0, height: rowHeight, display: 'grid', gridTemplateColumns: 'auto 1fr auto', gap: 6, alignItems: 'center', padding: '0 8px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <input type="checkbox" checked={selected.has(f.name)} onChange={() => onToggle(f.name)} />
                  </div>
                  <div title={title} style={{ color: f.is_dir ? '#9efc9e' : '#ddd', cursor: f.is_dir ? 'pointer' : 'default', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} onClick={() => f.is_dir && onCdTo(f.name)}>{f.name}</div>
                  <div style={{ display: 'inline-flex', gap: 6, justifyContent: 'flex-end', whiteSpace: 'nowrap', overflow: 'hidden' }}>
                    {!f.is_dir ? (
                      <>
                        <button className="btn secondary" onClick={() => onDownload(f.name)} style={{ padding: '2px 8px', fontSize: 12 }}>Download</button>
                        {isImage(f.name) && (
                          <button className="btn secondary" onClick={() => onSetWallpaper(f.name)} style={{ padding: '2px 6px', fontSize: 12 }}>WP</button>
                        )}
                      </>
                    ) : (
                      <button className="btn secondary" onClick={() => onCdTo(f.name)} style={{ padding: '2px 6px', fontSize: 12 }}>Open</button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}