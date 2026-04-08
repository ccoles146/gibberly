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

  // Azure TranslationRecognizer synthesizing output: 16kHz 16-bit mono PCM
  const PCM_SAMPLE_RATE = 16000;

  function playPcm(arrayBuffer) {
    const samples = new Int16Array(arrayBuffer);
    if (samples.length === 0) return;
    const audioBuffer = audioCtx.createBuffer(1, samples.length, PCM_SAMPLE_RATE);
    const channel = audioBuffer.getChannelData(0);
    for (let i = 0; i < samples.length; i++) {
      channel[i] = samples[i] / 32768;
    }
    const src = audioCtx.createBufferSource();
    src.buffer = audioBuffer;
    src.connect(audioCtx.destination);
    const now = audioCtx.currentTime;
    const startAt = Math.max(now, nextPlayTime);
    src.start(startAt);
    nextPlayTime = startAt + audioBuffer.duration;
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
      fetch(`/session/${session}/join`, { method: 'POST' }).catch(() => {});
    };

    ws.onmessage = async (event) => {
      let msg;
      try { msg = JSON.parse(event.data); } catch { return; }

      if (msg.type === 'message' && msg.dataType === 'binary') {
        console.log('[gibberly] binary audio arrived, b64 length:', msg.data?.length);
        if (audioCtx.state === 'suspended') await audioCtx.resume();
        const buf = base64ToArrayBuffer(msg.data);
        console.log('[gibberly] playPcm, bytes:', buf.byteLength, 'ctx state:', audioCtx.state);
        playPcm(buf);
      }

      if (msg.type === 'message' && msg.dataType === 'json') {
        if (msg.data?.type === 'close') {
          setStatus('Session ended.');
          ws.close();
        } else if (msg.data?.type === 'phrase') {
          phraseEl.textContent = msg.data.text;
        }
      }
    };

    ws.onerror = () => setStatus('Connection error. Retrying…');

    ws.onclose = () => {
      fetch(`/session/${session}/leave`, { method: 'POST' }).catch(() => {});
      setStatus('Disconnected. Reload to reconnect.');
    };
  }

  btn.addEventListener('click', connect);
})();
