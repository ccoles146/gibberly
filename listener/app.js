(function () {
  const btn = document.getElementById('listen-btn');
  const statusEl = document.getElementById('status');
  const phraseEl = document.getElementById('last-phrase');

  const params = new URLSearchParams(window.location.search);
  const session = params.get('session');
  if (!session) {
    statusEl.textContent = 'No session ID in URL.';
    btn.disabled = true;
    return;
  }

  let audioCtx = null;
  let nextPlayTime = 0;
  let ws = null;

  function setStatus(msg) { statusEl.textContent = msg; }

  async function getNegotiateUrl() {
    const res = await fetch(`/negotiate?session=${session}`);
    if (!res.ok) throw new Error('Session not found');
    const { url } = await res.json();
    return url;
  }

  function base64ToArrayBuffer(b64) {
    const bin = atob(b64);
    const buf = new ArrayBuffer(bin.length);
    const view = new Uint8Array(buf);
    for (let i = 0; i < bin.length; i++) view[i] = bin.charCodeAt(i);
    return buf;
  }

  async function playWav(arrayBuffer) {
    try {
      const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
      const src = audioCtx.createBufferSource();
      src.buffer = audioBuffer;
      src.connect(audioCtx.destination);
      const now = audioCtx.currentTime;
      const startAt = Math.max(now, nextPlayTime);
      src.start(startAt);
      nextPlayTime = startAt + audioBuffer.duration;
    } catch (e) {
      console.warn('Audio decode error:', e);
    }
  }

  async function connect() {
    btn.disabled = true;
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    setStatus('Connecting…');

    let pubsubUrl;
    try {
      pubsubUrl = await getNegotiateUrl();
    } catch (e) {
      setStatus('Failed to get session: ' + e.message);
      btn.disabled = false;
      return;
    }

    ws = new WebSocket(pubsubUrl, 'json.webpubsub.azure.v1');

    ws.onopen = () => {
      setStatus('Connected — waiting for audio…');
      ws.send(JSON.stringify({ type: 'joinGroup', group: `session-${session}` }));
    };

    ws.onmessage = async (event) => {
      let msg;
      try { msg = JSON.parse(event.data); } catch { return; }

      if (msg.type === 'message' && msg.dataType === 'binary') {
        const buf = base64ToArrayBuffer(msg.data);
        await playWav(buf);
      }

      if (msg.type === 'message' && msg.dataType === 'json' && msg.data?.type === 'close') {
        setStatus('Session ended.');
        ws.close();
      }
    };

    ws.onerror = () => setStatus('Connection error. Retrying…');

    ws.onclose = () => {
      setStatus('Disconnected. Reload to reconnect.');
    };
  }

  btn.addEventListener('click', connect);
})();
