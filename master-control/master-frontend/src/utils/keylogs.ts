let db: IDBDatabase | null = null;

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (db) return resolve(db);
    const req = indexedDB.open('agent_keylogs', 1);
    req.onupgradeneeded = () => {
      const d = req.result;
      if (!d.objectStoreNames.contains('klog')) {
        d.createObjectStore('klog', { keyPath: 'id' });
      }
    };
    req.onsuccess = () => { db = req.result; resolve(db!); };
    req.onerror = () => reject(req.error);
  });
}

export async function saveKeylog(agentId: string, agentName: string, lines: string[]): Promise<string> {
  const d = await openDB();
  const id = `${agentId}-${Date.now()}`;
  const ts = Date.now();
  const tx = d.transaction('klog', 'readwrite');
  const store = tx.objectStore('klog');
  await new Promise((res, rej) => {
    const putReq = store.put({ id, agentId, agentName, ts, lines });
    putReq.onsuccess = () => res(null);
    putReq.onerror = () => rej(putReq.error);
  });
  await new Promise((res, rej) => { tx.oncomplete = () => res(null); tx.onerror = () => rej(tx.error); });
  return id;
}
