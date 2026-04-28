(function () {
  const connectBtn      = document.getElementById('connect-btn');
  const reconnectBtn    = document.getElementById('reconnect-btn');
  const muteBtn         = document.getElementById('mute-btn');
  const sizeSBtn        = document.getElementById('size-s');
  const sizeMBtn        = document.getElementById('size-m');
  const sizeLBtn        = document.getElementById('size-l');
  const statusEl        = document.getElementById('status');
  const readingPaneEl   = document.getElementById('reading-pane');
  const readingInnerEl  = document.getElementById('reading-pane-inner');
  const pausedPill      = document.getElementById('paused-pill');
  const livePill        = document.getElementById('live-pill');
  const speedRow        = document.getElementById('speed-row');
  const speedSlider     = document.getElementById('speed-slider');
  const speedLabel      = document.getElementById('speed-label');
  const muteWarningEl   = document.getElementById('mute-warning');
  const langSelect      = document.getElementById('lang-select');
  const dlTranscriptBtn = document.getElementById('dl-transcript');

  // ── Debug panel ────────────────────────────────────────────────────────────
  const debugPanelEl  = document.getElementById('debug-panel');
  const dbgQEl        = document.getElementById('dbg-q');
  const dbgIvEl       = document.getElementById('dbg-iv');
  const dbgPcEl       = document.getElementById('dbg-pc');
  const dbgLogEl      = document.getElementById('dbg-log');

  const isDebugUrl   = new URLSearchParams(window.location.search).has('debug');
  let   debugVisible = isDebugUrl;
  let   debugEntries = [];
  let   debugPhraseCount = 0;

  function setDebugVisible(v) {
    debugVisible = v;
    debugPanelEl.classList.toggle('active', v);
  }
  if (isDebugUrl) setDebugVisible(true);

  document.addEventListener('keydown', (e) => {
    if (e.key === 'd' || e.key === 'D') setDebugVisible(!debugVisible);
  });

  function dbgLogPhrase(text, wordCount, queueBefore, intervalMs) {
    debugPhraseCount++;
    dbgPcEl.textContent = debugPhraseCount;

    const ts      = new Date().toISOString().slice(11, 23);
    const isFast  = intervalMs < 220;
    const isBurst = (queueBefore + wordCount) > 25;
    const cls     = isFast ? 'dbg-alert' : isBurst ? 'dbg-warn' : '';
    const flags   = [isFast ? '⚡ FAST interval' : '', isBurst ? '📚 BURST queue' : '']
                      .filter(Boolean).join('  ');

    const entry = document.createElement('div');
    entry.className = `dbg-entry ${cls}`;
    entry.innerHTML =
      `<span class="dbg-ts">${ts}</span>  ` +
      `<span class="dbg-count">${wordCount}w</span>  ` +
      `<span class="dbg-q">Q:${queueBefore}→${queueBefore + wordCount}</span>  ` +
      `<span class="dbg-ms">${Math.round(intervalMs)}ms/w</span>` +
      (flags ? `  <span class="dbg-flag">${flags}</span>` : '') +
      `<br><span class="dbg-txt">"${text.substring(0, 80)}"</span>`;

    debugEntries.push(entry);
    if (debugEntries.length > 60) debugEntries.shift().remove();
    dbgLogEl.appendChild(entry);
    dbgLogEl.scrollTop = dbgLogEl.scrollHeight;
  }

  function dbgUpdateStats() {
    if (!debugVisible) return;
    dbgQEl.textContent  = wordQueue.length;
    dbgIvEl.textContent = Math.round(getTrickleInterval());
  }

  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);

  const params  = new URLSearchParams(window.location.search);
  let   session = params.get('session');

  // ── Transcript (in-memory for download only) ───────────────────────────────
  const phrases = [];

  function addPhrase(text) {
    phrases.push(text);
    dlTranscriptBtn.disabled = false;
  }

  dlTranscriptBtn.addEventListener('click', () => {
    if (!phrases.length) return;
    const blob = new Blob([phrases.join('\n')], { type: 'text/plain' });
    const url  = URL.createObjectURL(blob);
    Object.assign(document.createElement('a'), {
      href: url, download: `gibberly-transcript-${session || 'session'}-${Date.now()}.txt`
    }).click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  });

  // ── Text size ──────────────────────────────────────────────────────────────
  const TEXT_SIZE_KEY = 'gibberly_text_size';

  function applyTextSize(size) {
    document.body.dataset.textSize = size;
    localStorage.setItem(TEXT_SIZE_KEY, size);
    sizeSBtn.classList.toggle('active', size === 's');
    sizeMBtn.classList.toggle('active', size === 'm');
    sizeLBtn.classList.toggle('active', size === 'l');
  }

  applyTextSize(localStorage.getItem(TEXT_SIZE_KEY) || 'm');
  sizeSBtn.addEventListener('click', () => applyTextSize('s'));
  sizeMBtn.addEventListener('click', () => applyTextSize('m'));
  sizeLBtn.addEventListener('click', () => applyTextSize('l'));

  // ── Live scroll tracking ───────────────────────────────────────────────────
  function isNearBottom() {
    return readingPaneEl.scrollHeight - readingPaneEl.scrollTop - readingPaneEl.clientHeight < 150;
  }

  function scrollToBottom(smooth) {
    readingPaneEl.scrollTo({ top: readingPaneEl.scrollHeight, behavior: smooth ? 'smooth' : 'instant' });
  }

  readingPaneEl.addEventListener('scroll', () => {
    livePill.style.display = (connected && !isNearBottom()) ? 'block' : 'none';
  });

  livePill.addEventListener('click', () => scrollToBottom(true));

  // ── Teleprompter display ───────────────────────────────────────────────────
  // Keep enough history for a full sermon; DOM growth of plain text is trivial
  const MAX_LINES       = 500;
  const DEFAULT_BASE_MS = 400;
  const MIN_BASE_MS     = 280;
  const SPEED_KEY       = 'gibberly_word_speed_multiplier';

  let wordQueue     = [];
  let tickTimer     = null;
  let currentLineEl = null;
  let lineElements  = [];
  let placeholderEl = readingInnerEl.querySelector('.reading-placeholder');
  let isFirstPhrase = true;
  const phraseHistory = [];

  function estimateBaseMsPerWord() {
    const now    = Date.now();
    const cutoff = now - 60000;
    while (phraseHistory.length && phraseHistory[0].ts < cutoff) phraseHistory.shift();
    if (phraseHistory.length < 2) return DEFAULT_BASE_MS;
    const totalWords = phraseHistory.reduce((s, e) => s + e.count, 0);
    const windowMs   = phraseHistory[phraseHistory.length - 1].ts - phraseHistory[0].ts;
    if (windowMs < 1000) return DEFAULT_BASE_MS;
    return Math.max(windowMs / totalWords, MIN_BASE_MS);
  }

  function getTrickleInterval() {
    return estimateBaseMsPerWord() / parseFloat(speedSlider.value);
  }

  function addWordToLine(word) {
    if (!currentLineEl) {
      if (placeholderEl) { placeholderEl.remove(); placeholderEl = null; }
      const p = document.createElement('p');
      p.className = 'reading-line';
      readingInnerEl.appendChild(p);
      lineElements.push(p);
      if (lineElements.length > MAX_LINES) lineElements.shift().remove();
      currentLineEl = p;
    }

    currentLineEl.textContent += (currentLineEl.textContent ? ' ' : '') + word;

    // Keep pinned to bottom while user hasn't scrolled away
    if (isNearBottom()) readingPaneEl.scrollTop = readingPaneEl.scrollHeight;
  }

  function startTick() {
    if (tickTimer !== null) return;
    function tick() {
      if (wordQueue.length > 0) {
        const item = wordQueue.shift();
        if (item.newLine) {
          currentLineEl = null;
        } else {
          addWordToLine(item.word);
        }
        dbgUpdateStats();
      }
      if (wordQueue.length > 0) {
        tickTimer = setTimeout(tick, getTrickleInterval());
      } else {
        tickTimer = null;
        dbgUpdateStats();
      }
    }
    tickTimer = setTimeout(tick, getTrickleInterval());
  }

  function onPhrase(text) {
    const words = text.trim().split(/\s+/).filter(Boolean);
    if (!words.length) return;
    phraseHistory.push({ ts: Date.now(), count: words.length });

    if (debugVisible) dbgLogPhrase(text, words.length, wordQueue.length, getTrickleInterval());

    if (!isFirstPhrase) {
      const last = wordQueue[wordQueue.length - 1];
      if (!last || !last.newLine) wordQueue.push({ newLine: true });
    }
    isFirstPhrase = false;
    words.forEach(w => wordQueue.push({ word: w }));

    addPhrase(text);
    startTick();
  }

  function clearReadingPane() {
    wordQueue     = [];
    currentLineEl = null;
    lineElements  = [];
    isFirstPhrase = true;
    if (tickTimer !== null) { clearTimeout(tickTimer); tickTimer = null; }
    readingInnerEl.innerHTML = '';
    const p = document.createElement('p');
    p.className = 'reading-placeholder';
    p.textContent = 'Waiting for translation…';
    readingInnerEl.appendChild(p);
    placeholderEl = p;
    debugPhraseCount = 0;
    dbgPcEl.textContent = '0';
    dbgQEl.textContent  = '0';
    dbgIvEl.textContent = '—';
  }

  // ── Speed slider ───────────────────────────────────────────────────────────
  const savedSpeed = Math.min(1.0, parseFloat(localStorage.getItem(SPEED_KEY) || '1'));
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
      const fetches = [fetch('/languages')];
      if (session) fetches.push(fetch(`/session/${session}/info`));
      const [langsRes, infoRes] = await Promise.all(fetches);
      const langs      = langsRes.ok ? await langsRes.json() : [];
      const sourceLang = (infoRes && infoRes.ok) ? (await infoRes.json()).source_lang : null;
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
    } catch {
      langSelect.innerHTML = '<option value="en">English</option>';
    }
  }

  langSelect.addEventListener('change', () => { chosenLang = langSelect.value; });

  // ── Connection state ───────────────────────────────────────────────────────
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
    speedRow.style.display = state ? 'flex' : 'none';
    muteBtn.disabled       = !state;
    if (!state) {
      if (audioActive) {
        audioActive         = false;
        muteBtn.textContent = '🔊 Enable audio';
        muteBtn.className   = '';
      }
      pausedPill.style.display = 'none';
      livePill.style.display   = 'none';
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
      console.warn('audio decode error:', e.message);
      return;
    }
    const src     = audioCtx.createBufferSource();
    src.buffer    = audioBuffer;
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

  // ── Mute / Enable audio ────────────────────────────────────────────────────
  muteBtn.addEventListener('click', async () => {
    if (!audioActive) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      if (audioCtx.state === 'suspended') await audioCtx.resume();
      nextPlayTime = 0;
      fetch(`/session/${session}/audio/join?lang=${chosenLang}`, { method: 'POST' }).catch(() => {});
      audioActive         = true;
      muteBtn.textContent = '🔇 Mute audio';
      muteBtn.className   = 'active';
      if (isIOS && muteWarningEl) muteWarningEl.style.display = 'block';
    } else {
      if (audioCtx) audioCtx.suspend();
      fetch(`/session/${session}/audio/leave?lang=${chosenLang}`, { method: 'POST' }).catch(() => {});
      audioActive         = false;
      muteBtn.textContent = '🔊 Enable audio';
      muteBtn.className   = '';
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
    if (!session) {
      setStatus('No session — tap ↻ to find an active stream.');
      return;
    }
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
      scrollToBottom(false);
      ws.send(JSON.stringify({ type: 'joinGroup', group: `session-${session}-${chosenLang}` }));
      fetch(`/session/${session}/join?lang=${chosenLang}`, { method: 'POST' }).catch(() => {});
    };

    ws.onmessage = (event) => {
      let msg;
      try { msg = JSON.parse(event.data); } catch { return; }

      if (msg.type === 'message' && msg.dataType === 'binary') {
        const buf = base64ToArrayBuffer(msg.data);
        if (debugVisible) console.debug(`audio bytes: ${buf.byteLength} | ctx: ${audioCtx?.state}`);
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

  // ── Reconnect — pick up latest session from backend ────────────────────────
  reconnectBtn.addEventListener('click', async () => {
    reconnectBtn.disabled = true;
    setStatus('Finding latest stream…');
    try {
      const res = await fetch('/current-session');
      if (!res.ok) throw new Error('No active session');
      const { session_id } = await res.json();
      if (connected) disconnect('Switching session…');
      session = session_id;
      const url = new URL(window.location.href);
      url.searchParams.set('session', session_id);
      window.history.replaceState(null, '', url.toString());
      await loadLanguages();
      connect();
    } catch {
      setStatus('No active stream found.');
    } finally {
      reconnectBtn.disabled = false;
    }
  });

  // ── Auto-connect on load ───────────────────────────────────────────────────
  (async () => {
    if (!session) {
      setStatus('Looking for active stream…');
      try {
        const res = await fetch('/current-session');
        if (res.ok) {
          const { session_id } = await res.json();
          session = session_id;
          const url = new URL(window.location.href);
          url.searchParams.set('session', session_id);
          window.history.replaceState(null, '', url.toString());
        }
      } catch {}
    }

    await loadLanguages();

    if (session) {
      connect();
    } else {
      setStatus('No active stream — use the operator link or tap ↻ to reconnect.');
    }
  })();
})();
