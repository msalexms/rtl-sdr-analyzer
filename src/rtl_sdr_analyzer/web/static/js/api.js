async function request(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { detail: text };
  }
  if (!res.ok) {
    const msg = (data && data.detail) || `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

export const api = {
  getState: () => request('/api/state'),
  getDevices: () => request('/api/devices'),
  patchReceiver: (body) => request('/api/receiver', { method: 'PATCH', body: JSON.stringify(body) }),
  patchDsp: (body) => request('/api/dsp', { method: 'PATCH', body: JSON.stringify(body) }),
  patchDetector: (body) => request('/api/detector', { method: 'PATCH', body: JSON.stringify(body) }),
  switchSource: (body) => request('/api/source', { method: 'POST', body: JSON.stringify(body) }),
  pauseStream: () => request('/api/stream/pause', { method: 'POST' }),
  resumeStream: () => request('/api/stream/resume', { method: 'POST' }),
  startRecording: (format = 'raw') =>
    request('/api/recording/start', { method: 'POST', body: JSON.stringify({ format }) }),
  stopRecording: () => request('/api/recording/stop', { method: 'POST' }),
  startSweep: (body) => request('/api/sweep', { method: 'POST', body: JSON.stringify(body) }),
  getSweep: () => request('/api/sweep'),
  cancelSweep: () => request('/api/sweep/cancel', { method: 'POST' }),
  getEvents: (limit = 100) => request(`/api/events?limit=${limit}`),
  getStats: () => request('/api/stats'),
  clearEvents: () => request('/api/events', { method: 'DELETE' }),
};

const LITTLE_ENDIAN = new Uint8Array(new Uint16Array([1]).buffer)[0] === 1;

/** Decode base64 little-endian Int16 (dB x 10) bins into a Float32Array of dBFS. */
export function decodeBinsB64(b64) {
  const binary = atob(b64);
  const count = binary.length >> 1;
  const bytes = new Uint8Array(count * 2);
  for (let i = 0; i < bytes.length; i += 1) bytes[i] = binary.charCodeAt(i);
  const out = new Float32Array(count);
  if (LITTLE_ENDIAN) {
    const ints = new Int16Array(bytes.buffer);
    for (let i = 0; i < count; i += 1) out[i] = ints[i] / 10;
  } else {
    const view = new DataView(bytes.buffer);
    for (let i = 0; i < count; i += 1) out[i] = view.getInt16(i * 2, true) / 10;
  }
  return out;
}
