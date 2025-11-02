let db: IDBDatabase | null = null;

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (db) return resolve(db);
    const req = indexedDB.open('agent_camera', 1);
    req.onupgradeneeded = () => {
      const d = req.result;
      if (!d.objectStoreNames.contains('media')) {
        const store = d.createObjectStore('media', { keyPath: 'id' });
        store.createIndex('by_agent', 'agentId', { unique: false });
        store.createIndex('by_ts', 'ts', { unique: false });
      }
    };
    req.onsuccess = () => { db = req.result; resolve(db!); };
    req.onerror = () => reject(req.error);
  });
}

export type CameraMediaMeta = { id: string; agentId: string; agentName: string; ts: number; kind: 'photo'|'video'; size: number; mime: string };

export async function savePhoto(agentId: string, agentName: string, blob: Blob): Promise<string> {
  const d = await openDB();
  const id = `${agentId}-photo-${Date.now()}`;
  const tx = d.transaction('media', 'readwrite');
  const store = tx.objectStore('media');
  await new Promise((res, rej) => {
    const putReq = store.put({ id, agentId, agentName, ts: Date.now(), kind: 'photo', size: blob.size, mime: 'image/jpeg', blob });
    putReq.onsuccess = () => res(null);
    putReq.onerror = () => rej(putReq.error);
  });
  await new Promise((res, rej) => { tx.oncomplete = () => res(null); tx.onerror = () => rej(tx.error); });
  return id;
}

export async function saveVideo(agentId: string, agentName: string, blob: Blob, mime='video/webm'): Promise<string> {
  const d = await openDB();
  const id = `${agentId}-video-${Date.now()}`;
  const tx = d.transaction('media', 'readwrite');
  const store = tx.objectStore('media');
  await new Promise((res, rej) => {
    const putReq = store.put({ id, agentId, agentName, ts: Date.now(), kind: 'video', size: blob.size, mime, blob });
    putReq.onsuccess = () => res(null);
    putReq.onerror = () => rej(putReq.error);
  });
  await new Promise((res, rej) => { tx.oncomplete = () => res(null); tx.onerror = () => rej(tx.error); });
  return id;
}

export async function listMedia(agentId?: string): Promise<CameraMediaMeta[]> {
  const d = await openDB();
  const tx = d.transaction('media', 'readonly');
  const store = tx.objectStore('media');
  const out: CameraMediaMeta[] = [];
  await new Promise<void>((res, rej) => {
    const req = store.openCursor();
    req.onsuccess = () => {
      const cur = req.result;
      if (!cur) { res(); return; }
      const v: any = cur.value;
      if (!agentId || v.agentId === agentId) out.push({ id: v.id, agentId: v.agentId, agentName: v.agentName, ts: v.ts, kind: v.kind, size: v.size, mime: v.mime });
      cur.continue();
    };
    req.onerror = () => rej(req.error);
  });
  return out.sort((a,b) => b.ts - a.ts);
}

export async function getMediaBlob(id: string): Promise<Blob | null> {
  const d = await openDB();
  const tx = d.transaction('media', 'readonly');
  const store = tx.objectStore('media');
  return await new Promise((res, rej) => {
    const r = store.get(id);
    r.onsuccess = () => res(r.result ? (r.result as any).blob as Blob : null);
    r.onerror = () => rej(r.error);
  });
}

export async function deleteMedia(id: string): Promise<void> {
  const d = await openDB();
  const tx = d.transaction('media', 'readwrite');
  const store = tx.objectStore('media');
  await new Promise((res, rej) => {
    const r = store.delete(id);
    r.onsuccess = () => res(null);
    r.onerror = () => rej(r.error);
  });
}
