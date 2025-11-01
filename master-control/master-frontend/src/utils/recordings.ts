let db: IDBDatabase | null = null;

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (db) return resolve(db);
    const req = indexedDB.open('agent_recordings', 1);
    req.onupgradeneeded = () => {
      const d = req.result;
      if (!d.objectStoreNames.contains('recs')) {
        const store = d.createObjectStore('recs', { keyPath: 'id' });
        store.createIndex('by_agent', 'agentId', { unique: false });
        store.createIndex('by_ts', 'ts', { unique: false });
      }
    };
    req.onsuccess = () => { db = req.result; resolve(db!); };
    req.onerror = () => reject(req.error);
  });
}

export type RecordingMeta = { id: string; agentId: string; agentName: string; ts: number; size: number };

export async function saveRecording(agentId: string, agentName: string, blob: Blob): Promise<string> {
  const d = await openDB();
  const id = `${agentId}-${Date.now()}`;
  const tx = d.transaction('recs', 'readwrite');
  const store = tx.objectStore('recs');
  await new Promise((res, rej) => {
    const putReq = store.put({ id, agentId, agentName, ts: Date.now(), size: blob.size, blob });
    putReq.onsuccess = () => res(null);
    putReq.onerror = () => rej(putReq.error);
  });
  await new Promise((res, rej) => { tx.oncomplete = () => res(null); tx.onerror = () => rej(tx.error); });
  return id;
}

export async function listRecordings(agentId?: string): Promise<RecordingMeta[]> {
  const d = await openDB();
  const tx = d.transaction('recs', 'readonly');
  const store = tx.objectStore('recs');
  const out: RecordingMeta[] = [];
  await new Promise<void>((res, rej) => {
    const req = store.openCursor();
    req.onsuccess = () => {
      const cur = req.result;
      if (!cur) { res(); return; }
      const v: any = cur.value;
      if (!agentId || v.agentId === agentId) out.push({ id: v.id, agentId: v.agentId, agentName: v.agentName, ts: v.ts, size: v.size });
      cur.continue();
    };
    req.onerror = () => rej(req.error);
  });
  return out.sort((a,b) => b.ts - a.ts);
}

export async function getRecordingBlob(id: string): Promise<Blob | null> {
  const d = await openDB();
  const tx = d.transaction('recs', 'readonly');
  const store = tx.objectStore('recs');
  return await new Promise((res, rej) => {
    const r = store.get(id);
    r.onsuccess = () => res(r.result ? (r.result as any).blob as Blob : null);
    r.onerror = () => rej(r.error);
  });
}

export async function deleteRecording(id: string): Promise<void> {
  const d = await openDB();
  const tx = d.transaction('recs', 'readwrite');
  const store = tx.objectStore('recs');
  await new Promise((res, rej) => {
    const r = store.delete(id);
    r.onsuccess = () => res(null);
    r.onerror = () => rej(r.error);
  });
}
