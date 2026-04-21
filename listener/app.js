(function () {
  const connectBtn      = document.getElementById('connect-btn');
  const audioBtn        = document.getElementById('audio-btn');
  const statusEl        = document.getElementById('status');
  const readingPaneEl   = document.getElementById('reading-pane');
  const pausedPill      = document.getElementById('paused-pill');
  const speedRow        = document.getElementById('speed-row');
  const speedSlider     = document.getElementById('speed-slider');
  const speedLabel      = document.getElementById('speed-label');
  const debugEl         = document.getElementById('debug');
  const muteWarningEl   = document.getElementById('mute-warning');
  const langSelect      = document.getElementById('lang-select');
  const transcriptList  = document.getElementById('transcript-list');
  const transcriptCount = document.getElementById('transcript-count');
  const dlTranscriptBtn = document.getElementById('dl-transcript');

  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);

  const params  = new URLSearchParams(window.location.search);
  const session = params.get('session');
  if (!session) {
    statusEl.textContent = 'No session ID in URL.';
    connectBtn.disabled = true;
    return;
  }

  // ── Transcript ─────────────────────────────────────────────────────────────
  const phrases = [];

  function addPhrase(text) {
    phrases.push(text);
    transcriptCount.textContent = phrases.length;
    const div = document.createElement('div');
    div.className = 'transcript-phrase';
    div.textContent = text;
    transcriptList.appendChild(div);
    dlTranscriptBtn.disabled = false;
  }

  dlTranscriptBtn.addEventListener('click', () => {
    if (!phrases.length) return;
    const blob = new Blob([phrases.join('\n')], { type: 'text/plain' });
    const url  = URL.createObjectURL(blob);
    Object.assign(document.createElement('a'), {
      href: url, download: `gibberly-transcript-${session}-${Date.now()}.txt`
    }).click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  });

  // ── Word queue / sliding window ────────────────────────────────────────────
  const MAX_DISPLAY_WORDS = 30;
  const DEFAULT_BASE_MS   = 400;   // fallback: 150 wpm
  const SPEED_KEY         = 'gibberly_word_speed_multiplier';

  let displayWords  = [];
  let wordQueue     = [];
  let tickTimer     = null;
  const phraseHistory = [];   // [{ts: ms, count: n}]

  function estimateBaseMsPerWord() {
    const now    = Date.now();
    const cutoff = now - 60000;
    while (phraseHistory.length && phraseHistory[0].ts < cutoff) phraseHistory.shift();
    if (phraseHistory.length < 2) return DEFAULT_BASE_MS;
    const totalWords = phraseHistory.reduce((s, e) => s + e.count, 0);
    const windowMs   = phraseHistory[phraseHistory.length - 1].ts - phraseHistory[0].ts;
    if (windowMs < 1000) return DEFAULT_BASE_MS;
    return windowMs / totalWords;
  }

  function getTrickleInterval() {
    const multiplier = parseFloat(speedSlider.value);
    return estimateBaseMsPerWord() / multiplier;
  }

  function startTick() {
    if (tickTimer !== null) return;
    function tick() {
      if (wordQueue.length > 0) {
        const word = wordQueue.shift();
        displayWords.push(word);
        if (displayWords.length > MAX_DISPLAY_WORDS) displayWords.shift();
        readingPaneEl.textContent = displayWords.join(' ');
      }
      if (wordQueue.length > 0) {
        tickTimer = setTimeout(tick, getTrickleInterval());
      } else {
        tickTimer = null;
      }
    }
    tickTimer = setTimeout(tick, getTrickleInterval());
  }

  function onPhrase(text) {
    const words = text.trim().split(/\s+/).filter(Boolean);
    if (!words.length) return;
    phraseHistory.push({ ts: Date.now(), count: words.length });
    wordQueue.push(...words);
    addPhrase(text);
    startTick();
  }

  function clearReadingPane() {
    wordQueue    = [];
    displayWords = [];
    if (tickTimer !== null) { clearTimeout(tickTimer); tickTimer = null; }
    readingPaneEl.textContent = '';
  }

  // ── Speed slider ───────────────────────────────────────────────────────────
  const savedSpeed = parseFloat(localStorage.getItem(SPEED_KEY) || '1');
  speedSlider.value = savedSpeed;
  speedLabel.textContent = savedSpeed + '×';

  speedSlider.addEventListener('input', () => {
    const v = parseFloat(speedSlider.value);
    speedLabel.textContent = v + '×';
    localStorage.setItem(SPEED_KEY, v);
  });

  // ── Language selector ──────────────────────────────────────────────────────
  let chosenLang = 'en';

  async function loadLanguages() {
    try {
      const [langsRes, infoRes] = await Promise.all([
        fetch('/languages'),
        fetch(`/session/${session}/info`),
      ]);
      const langs = langsRes.ok ? await langsRes.json() : [];
      const sourceLang = infoRes.ok ? (await infoRes.json()).source_lang : null;
      const sourceCode = sourceLang ? sourceLang.split('-')[0] : null;

      const filtered = sourceCode ? langs.filter(l => l.code !== sourceCode) : langs;

      langSelect.innerHTML = '';
      filtered.forEach(l => {
        const opt = document.createElement('option');
        opt.value = l.code;
        opt.textContent = l.name;
        langSelect.appendChild(opt);
      });

      const enOpt = filtered.find(l => l.code === 'en');
      chosenLang = enOpt ? 'en' : (filtered[0]?.code || 'en');
      langSelect.value = chosenLang;
    } catch (e) {
      langSelect.innerHTML = '<option value="en">English</option>';
    }
  }

  langSelect.addEventListener('change', () => { chosenLang = langSelect.value; });
  loadLanguages();

  // ── Connection state ───────────────────────────────────────────────────────
  function dbg(msg) { if (debugEl) debugEl.textContent = msg; }

  let audioCtx     = null;
  let nextPlayTime = 0;
  let ws           = null;
  let connected    = false;
  let audioActive  = false;

  function setStatus(msg) { statusEl.textContent = msg; }

  function setConnected(state) {
    connected              = state;
    connectBtn.textContent = state ? 'Disconnect' : 'Connect';
    connectBtn.className   = state ? 'stop' : '';
    connectBtn.disabled    = false;
    langSelect.disabled    = state;
    audioBtn.style.display = state ? 'block' : 'none';
    speedRow.style.display = state ? '' : 'none';
    if (!state) {
      audioBtn.textContent = '\uD83D\uDD0A Unmute audio';
      audioBtn.className = '';
      pausedPill.style.display = 'none';
      clearReadingPane();
    }
  }

  // ── Audio playback ─────────────────────────────────────────────────────────
  async function playAudio(arrayBuffer) {
    if (!audioCtx) return;
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

  function base64ToArrayBuffer(b64) {
    const bin  = atob(b64);
    const buf  = new ArrayBuffer(bin.length);
    const view = new Uint8Array(buf);
    for (let i = 0; i < bin.length; i++) view[i] = bin.charCodeAt(i);
    return buf;
  }

  // ── Audio mute/unmute ──────────────────────────────────────────────────────
  audioBtn.addEventListener('click', async () => {
    if (!audioActive) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      if (audioCtx.state === 'suspended') await audioCtx.resume();
      nextPlayTime = 0;
      fetch(`/session/${session}/audio/join?lang=${chosenLang}`, { method: 'POST' }).catch(() => {});
      audioActive = true;
      audioBtn.textContent = '\uD83D\uDD07 Mute audio';
      audioBtn.className = 'active';
      if (isIOS && muteWarningEl) muteWarningEl.style.display = 'block';
    } else {
      if (audioCtx) { audioCtx.suspend(); }
      fetch(`/session/${session}/audio/leave?lang=${chosenLang}`, { method: 'POST' }).catch(() => {});
      audioActive = false;
      audioBtn.textContent = '\uD83D\uDD0A Unmute audio';
      audioBtn.className = '';
      if (muteWarningEl) muteWarningEl.style.display = 'none';
    }
  });

  // ── Connect / disconnect ───────────────────────────────────────────────────
  function disconnect(reason) {
    if (muteWarningEl) muteWarningEl.style.display = 'none';
    if (audioActive && audioCtx) {
      audioCtx.close();
      audioCtx = null;
      fetch(`/session/${session}/audio/leave?lang=${chosenLang}`, { method: 'POST' }).catch(() => {});
      audioActive = false;
    }
    nextPlayTime = 0;
    if (ws && ws.readyState < WebSocket.CLOSING) ws.close();
    ws = null;
    setStatus(reason || 'Disconnected.');
    setConnected(false);
  }

  async function connect() {
    connectBtn.disabled = true;
    setStatus('Connecting…');
    nextPlayTime = 0;

    let pubsubUrl;
    try {
      const res = await fetch(`/negotiate?session=${session}&lang=${chosenLang}`);
      if (!res.ok) throw new Error('Session not found');
      pubsubUrl = (await res.json()).url;
    } catch (e) {
      setStatus('Failed to connect: ' + e.message);
      connectBtn.disabled = false;
      return;
    }

    ws = new WebSocket(pubsubUrl, 'json.webpubsub.azure.v1');

    ws.onopen = () => {
      setConnected(true);
      setStatus('Connected — reading transcript…');
      ws.send(JSON.stringify({ type: 'joinGroup', group: `session-${session}-${chosenLang}` }));
      fetch(`/session/${session}/join?lang=${chosenLang}`, { method: 'POST' }).catch(() => {});
    };

    ws.onmessage = (event) => {
      let msg;
      try { msg = JSON.parse(event.data); } catch { return; }

      if (msg.type === 'message' && msg.dataType === 'binary') {
        const buf = base64ToArrayBuffer(msg.data);
        dbg(`audio bytes: ${buf.byteLength} | ctx: ${audioCtx?.state}`);
        playAudio(buf);
      }

      if (msg.type === 'message' && (msg.dataType === 'json' || msg.dataType === 'text')) {
        let d = msg.data;
        if (typeof d === 'string') { try { d = JSON.parse(d); } catch { d = null; } }
        if (d?.type === 'close') {
          disconnect('Session ended.');
        } else if (d?.type === 'phrase') {
          const text = d.text || '';
          if (text) onPhrase(text);
        } else if (d?.type === 'paused') {
          pausedPill.style.display = 'block';
        } else if (d?.type === 'resumed') {
          pausedPill.style.display = 'none';
        }
      }
    };

    ws.onerror = () => setStatus('Connection error.');

    ws.onclose = (evt) => {
      fetch(`/session/${session}/leave?lang=${chosenLang}`, { method: 'POST' }).catch(() => {});
      const wasConnected = connected;
      connected = false;
      if (muteWarningEl) muteWarningEl.style.display = 'none';
      if (wasConnected) {
        setStatus('Disconnected.');
      } else {
        const reason = evt.code ? ` (code ${evt.code})` : '';
        setStatus(`Could not connect${reason}. Try again.`);
      }
      setConnected(false);
    };
  }

  connectBtn.addEventListener('click', () => {
    if (connected) disconnect();
    else connect();
  });
})();
