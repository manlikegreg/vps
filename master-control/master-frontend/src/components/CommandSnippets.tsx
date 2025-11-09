import { useEffect, useMemo, useState } from 'react'

const DEFAULT_SNIPPETS = [
  // Windows networking
  'netsh wlan show profiles',
  'netsh interface ip show config',
  'ipconfig /all',
  // Files/dirs
  'dir',
  'cd ..',
  // Git
  'git status',
  // PC Specs: System Overview
  'systeminfo',
  'dxdiag /t %TEMP%\\dxdiag.txt',
  // PC Specs: CPU Info
  'wmic cpu get Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed,ProcessorId',
  // PC Specs: RAM Total
  'wmic computersystem get TotalPhysicalMemory',
  // PC Specs: RAM Modules
  'wmic memorychip get Manufacturer,PartNumber,Capacity,Speed,SerialNumber,BankLabel,DeviceLocator',
  // PC Specs: GPU Info
  'wmic path win32_videocontroller get Name,DriverVersion,AdapterRAM,VideoProcessor',
  // PC Specs: Storage Disks
  'wmic diskdrive get Model,Size,SerialNumber,MediaType,InterfaceType',
  // PC Specs: Volumes/Partitions
  'wmic logicaldisk get DeviceID,VolumeName,FileSystem,Size,FreeSpace',
  // PC Specs: Motherboard
  'wmic baseboard get Manufacturer,Product,SerialNumber,Version',
  // PC Specs: BIOS Info
  'wmic bios get Manufacturer,SMBIOSBIOSVersion,ReleaseDate',
  // PC Specs: OS Details
  'wmic os get Caption,Version,BuildNumber,OSArchitecture,SerialNumber',
  // PC Specs: Network Adapters
  'wmic nic where "NetEnabled=true" get Name,MACAddress,Speed',
  // PC Specs: Sound Devices
  'wmic sounddev get Name,Manufacturer',
  // PC Specs: Battery Status (Laptops)
  'wmic path win32_battery get Name,EstimatedChargeRemaining,BatteryStatus',
  // PC Specs: All Drivers
  'driverquery /v /fo table',
]

function useSnippets() {
  const [snippets, setSnippets] = useState<string[]>([])

  useEffect(() => {
    try {
      const raw = localStorage.getItem('command_snippets')
      if (raw) {
        const arr = JSON.parse(raw)
        if (Array.isArray(arr)) {
          setSnippets(arr.filter((s) => typeof s === 'string' && s.trim()))
          return
        }
      }
    } catch {}
    // seed defaults if none
    setSnippets(DEFAULT_SNIPPETS)
  }, [])

  useEffect(() => {
    try { localStorage.setItem('command_snippets', JSON.stringify(snippets)) } catch {}
  }, [snippets])

  const addSnippet = (s: string) => {
    const v = (s || '').trim()
    if (!v) return
    setSnippets((prev) => Array.from(new Set([...prev, v])))
  }

  const removeSnippet = (s: string) => {
    setSnippets((prev) => prev.filter((x) => x !== s))
  }

  return { snippets, addSnippet, removeSnippet }
}

export default function CommandSnippets({ onInsert }: { onInsert: (v: string) => void }) {
  const { snippets, addSnippet, removeSnippet } = useSnippets()
  const [filter, setFilter] = useState('')

  const shown = useMemo(() => {
    const f = filter.trim().toLowerCase()
    if (!f) return snippets
    return snippets.filter((s) => s.toLowerCase().includes(f))
  }, [snippets, filter])

  const onAdd = () => {
    const v = window.prompt('Add command snippet:')
    if (v && v.trim()) addSnippet(v)
  }

  const copy = async (s: string) => {
    try { await navigator.clipboard.writeText(s) } catch {}
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <h4 style={{ color: '#9efc9e', margin: 0 }}>Command Snippets</h4>
        <div style={{ display: 'flex', gap: 8 }}>
          <input className="input" placeholder="Filter..." value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: 180 }} />
          <button className="btn secondary" onClick={onAdd}>Add</button>
        </div>
      </div>
      <div style={{ maxHeight: 160, overflow: 'auto', border: '1px solid #222', borderRadius: 6 }}>
        {shown.map((s) => (
          <div key={s} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 8px', borderBottom: '1px solid #1b1b1b' }}>
            <code style={{ color: '#ddd', whiteSpace: 'pre-wrap' }}>{s}</code>
            <div style={{ display: 'flex', gap: 6 }}>
              <button className="btn secondary" onClick={() => onInsert(s)}>Insert</button>
              <button className="btn secondary" onClick={() => copy(s)}>Copy</button>
              <button className="btn secondary" onClick={() => removeSnippet(s)}>Remove</button>
            </div>
          </div>
        ))}
        {shown.length === 0 && (
          <div style={{ color: '#777', fontSize: 12, padding: 8 }}>(No snippets)</div>
        )}
      </div>
    </div>
  )
}
