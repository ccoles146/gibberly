(function () {
  const btn           = document.getElementById('listen-btn');
  const statusEl      = document.getElementById('status');
  const phraseEl      = document.getElementById('last-phrase');
  const debugEl       = document.getElementById('debug');
  const muteWarningEl = document.getElementById('mute-warning');
  let audioChunkCount = 0;

  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);

  function dbg(msg) { if (debugEl) debugEl.textContent = msg; }

  const params  = new URLSearchParams(window.location.search);
  const session = params.get('session');
  if (!session) {
    statusEl.textContent = 'No session ID in URL.';
    btn.disabled = true;
    return;
  }

  let audioCtx     = null;
  let nextPlayTime = 0;
  let ws           = null;
  let connected    = false;

  function setStatus(msg) { statusEl.textContent = msg; }

  function setConnected(state) {
    connected            = state;
    btn.textContent      = state ? 'Stop' : 'Listen';
    btn.style.background = state ? '#dc2626' : '#2563eb';
    btn.disabled         = false;
  }

  async function getNegotiateUrl() {
    const res = await fetch(`/negotiate?session=${session}`);
    if (!res.ok) throw new Error('Session not found');
    const { url } = await res.json();
    return url;
  }

  function base64ToArrayBuffer(b64) {
    const bin  = atob(b64);
    const buf  = new ArrayBuffer(bin.length);
    const view = new Uint8Array(buf);
    for (let i = 0; i < bin.length; i++) view[i] = bin.charCodeAt(i);
    return buf;
  }

  // Each message is now a complete MP3 file — decodeAudioData is reliable.
  async function playAudio(arrayBuffer) {
    let audioBuffer;
    try {
      audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
    } catch (e) {
      dbg('decode error: ' + e.message);
      return;
    }
    const src    = audioCtx.createBufferSource();
    src.buffer   = audioBuffer;
    src.connect(audioCtx.destination);
    const now     = audioCtx.currentTime;
    const startAt = Math.max(now, nextPlayTime);
    src.start(startAt);
    nextPlayTime = startAt + audioBuffer.duration;
  }

  function disconnect(reason) {
    if (muteWarningEl) muteWarningEl.style.display = 'none';
    phraseEl.textContent = '';
    audioChunkCount      = 0;
    nextPlayTime         = 0;
    if (ws && ws.readyState < WebSocket.CLOSING) ws.close();
    ws = null;
    if (audioCtx) { audioCtx.close(); audioCtx = null; }
    setStatus(reason || 'Stopped.');
    setConnected(false);
  }

  async function connect() {
    btn.disabled = true;
    setStatus('Connecting…');
    audioChunkCount = 0;
    nextPlayTime    = 0;

    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === 'suspended') await audioCtx.resume();

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
      setConnected(true);
      setStatus('Connected — waiting for audio…');
      if (isIOS && muteWarningEl) muteWarningEl.style.display = 'block';
      ws.send(JSON.stringify({ type: 'joinGroup', group: `session-${session}` }));
      fetch(`/session/${session}/join`, { method: 'POST' }).catch(() => {});
    };

    ws.onmessage = (event) => {
      let msg;
      try { msg = JSON.parse(event.data); } catch { return; }

      if (msg.type === 'message' && msg.dataType === 'binary') {
        audioChunkCount++;
        const buf = base64ToArrayBuffer(msg.data);
        dbg(`phrases: ${audioChunkCount} | bytes: ${buf.byteLength} | ctx: ${audioCtx?.state}`);
        playAudio(buf);
      }

      if (msg.type === 'message' && msg.dataType === 'json') {
        if (msg.data?.type === 'close') {
          disconnect('Session ended.');
        } else if (msg.data?.type === 'phrase') {
          phraseEl.textContent = msg.data.text;
        }
      }
    };

    ws.onerror = () => setStatus('Connection error.');

    ws.onclose = (evt) => {
      fetch(`/session/${session}/leave`, { method: 'POST' }).catch(() => {});
      const wasConnected = connected;
      connected = false;
      if (muteWarningEl) muteWarningEl.style.display = 'none';
      if (wasConnected) {
        setStatus('Disconnected.');
      } else {
        const reason = evt.code ? ` (code ${evt.code})` : '';
        setStatus(`Could not connect to audio stream${reason}. Try again.`);
      }
      btn.textContent      = 'Listen';
      btn.style.background = '#2563eb';
      btn.disabled         = false;
    };
  }

  btn.addEventListener('click', () => {
    if (connected) disconnect();
    else connect();
  });
})();
