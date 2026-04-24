(function () {
  // ── DOM refs ────────────────────────────────────────────────────────────────
  const statusDot      = document.getElementById('status-dot');
  const statusText     = document.getElementById('status-text');
  const statListeners  = document.getElementById('stat-listeners');
  const statElapsed    = document.getElementById('stat-elapsed');
  const listenerCount  = document.getElementById('listener-count');
  const elapsedEl      = document.getElementById('elapsed');
  const qrCanvas       = document.getElementById('qr-canvas');
  const liveUrlEl      = document.getElementById('live-url');
  const srcInnerEl     = document.getElementById('src-inner');
  const tgtInnerEl     = document.getElementById('tgt-inner');
  const tpSrcLabel     = document.getElementById('tp-src-label');
  const tpTgtLabel     = document.getElementById('tp-tgt-label');
  const deviceSelect   = document.getElementById('device-select');
  const channelSelect  = document.getElementById('channel-select');
  const fileInput      = document.getElementById('file-input');
  const actionBtn      = document.getElementById('action-btn');
  const pauseBtn       = document.getElementById('pause-btn');
  const sourceLangSelect = document.getElementById('source-lang-select');
  const audioMeter    = document.getElementById('audio-meter');
  const audioMeterBar = document.getElementById('audio-meter-bar');

  // ── Config ──────────────────────────────────────────────────────────────────
  const backendWs  = window.GIBBERLY_BACKEND;
  const backendHttp = backendWs.replace(/^ws:/, 'http:').replace(/^wss:/, 'https:');
  const liveUrl    = backendHttp + '/listen/live';

  // ── QR code ─────────────────────────────────────────────────────────────────
  (function renderQr() {
    const qr = qrcode(0, 'M');
    qr.addData(liveUrl);
    qr.make();
    qrCanvas.innerHTML = qr.createTableTag(4, 0);
    liveUrlEl.textContent = liveUrl;
    liveUrlEl.href = liveUrl;
  })();

  // ── Language labels ────────────────────────────────────────────────────────
  const LANG_NAMES = {
    'de-DE': 'Deutsch', 'de':    'Deutsch',
    'en-US': 'English', 'en-GB': 'English', 'en': 'English',
    'fr-FR': 'Français', 'es-ES': 'Español',
  };

  function updateTpLabels() {
    const srcCode = (sourceLangSelect ? sourceLangSelect.value : 'de-DE').split('-')[0];
    tpSrcLabel.textContent = LANG_NAMES[sourceLangSelect?.value] || LANG_NAMES[srcCode] || 'Source';
    tpTgtLabel.textContent = 'Translation';
  }
  if (sourceLangSelect) sourceLangSelect.addEventListener('change', updateTpLabels);
  updateTpLabels();

  // ── Teleprompter engine ────────────────────────────────────────────────────
  function makeTeleprompter(innerEl, lineClass, placeholderText) {
    const MAX_LINES   = 8;
    const MS_PER_WORD = 220;
    let queue     = [];
    let timer     = null;
    let currentEl = null;
    let lines     = [];
    let isFirst   = true;

    function tick() {
      if (!queue.length) { timer = null; return; }
      const item = queue.shift();
      if (item.newLine) {
        currentEl = null;
      } else {
        if (!currentEl) {
          const p = document.createElement('p');
          p.className = lineClass;
          innerEl.appendChild(p);
          lines.push(p);
          while (lines.length > MAX_LINES) lines.shift().remove();
          currentEl = p;
        }
        currentEl.textContent += (currentEl.textContent ? ' ' : '') + item.word;
      }
      timer = queue.length ? setTimeout(tick, MS_PER_WORD) : null;
    }

    return {
      onPhrase(text) {
        const words = text.trim().split(/\s+/).filter(Boolean);
        if (!words.length) return;
        if (!isFirst) {
          const last = queue[queue.length - 1];
          if (!last || !last.newLine) queue.push({ newLine: true });
        }
        isFirst = false;
        words.forEach(w => queue.push({ word: w }));
        if (timer === null) timer = setTimeout(tick, MS_PER_WORD);
      },
      clear() {
        queue = []; currentEl = null; lines = []; isFirst = true;
        if (timer) { clearTimeout(timer); timer = null; }
        innerEl.innerHTML = '';
        const p = document.createElement('p');
        p.className = 'tp-placeholder';
        p.textContent = placeholderText;
        innerEl.appendChild(p);
      },
    };
  }

  const srcTp = makeTeleprompter(srcInnerEl, 'tp-line-de', 'Waiting for audio…');
  const tgtTp = makeTeleprompter(tgtInnerEl, 'tp-line-en', 'Waiting for translation…');

  // ── State machine ──────────────────────────────────────────────────────────
  let state           = 'idle';
  let levelDecayTimer = null;   // declared early — clearAudioLevel() called by setState('idle') below
  let paused          = false;  // declared early — setState('idle') resets this
  let activeWs        = null;
  let resumeCapture   = null;
  let keepaliveTimer  = null;

  function setState(s, msg) {
    state = s;
    statusDot.className = s === 'live' ? 'live' : s === 'connecting' ? 'connecting' : s === 'error' ? 'error' : '';
    statusText.textContent = msg || { idle: 'OFFLINE', connecting: 'CONNECTING…', live: 'LIVE', error: 'ERROR' }[s];
    actionBtn.disabled = s === 'connecting';
    actionBtn.textContent = s === 'live' ? '■ Stop' : s === 'error' ? '▶ Retry' : '▶ Start';
    actionBtn.className = s === 'live' ? 'stop' : '';
    statListeners.style.display = s === 'live' ? '' : 'none';
    statElapsed.style.display   = s === 'live' ? '' : 'none';
    if (sourceLangSelect) sourceLangSelect.disabled = (s === 'live' || s === 'connecting');
    pauseBtn.style.display = s === 'live' ? 'inline-block' : 'none';
    audioMeter.style.display = s === 'live' ? '' : 'none';
    if (s !== 'live') clearAudioLevel();
    if (s !== 'live') {
      paused = false;
      pauseBtn.textContent = '⏸ Pause';
      pauseBtn.className = '';
      pauseBtn.disabled = true;
    }
  }

  setState('idle');

  // ── Device enumeration ─────────────────────────────────────────────────────
  const FILE_OPTION_VALUE = '__file__';
  const STORAGE_DEVICE    = 'gibberly_device';
  const STORAGE_CHANNEL   = 'gibberly_channel';

  async function populateDevices() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach(t => t.stop());
    } catch (_) {}

    let devices;
    try {
      devices = await navigator.mediaDevices.enumerateDevices();
    } catch (err) {
      deviceSelect.innerHTML = '<option value="">No audio devices found</option>';
      const fileOpt = document.createElement('option');
      fileOpt.value = '__file__';
      fileOpt.textContent = 'Browse file…';
      deviceSelect.appendChild(fileOpt);
      updateChannelVisibility(false);
      return;
    }
    const inputs = devices.filter(d => d.kind === 'audioinput');

    deviceSelect.innerHTML = '';
    inputs.forEach(d => {
      const opt = document.createElement('option');
      opt.value = d.deviceId;
      opt.textContent = d.label || `Microphone (${d.deviceId.slice(0, 8)})`;
      deviceSelect.appendChild(opt);
    });

    const fileOpt = document.createElement('option');
    fileOpt.value = FILE_OPTION_VALUE;
    fileOpt.textContent = 'Browse file…';
    deviceSelect.appendChild(fileOpt);

    const saved = localStorage.getItem(STORAGE_DEVICE);
    if (saved && [...deviceSelect.options].some(o => o.value === saved)) {
      deviceSelect.value = saved;
    }

    updateChannelVisibility(false);
  }

  function updateChannelVisibility(fromUserAction = true) {
    const isFile = deviceSelect.value === FILE_OPTION_VALUE;
    channelSelect.style.display = isFile ? 'none' : '';
    if (isFile) {
      if (fromUserAction) fileInput.click();
    } else {
      localStorage.setItem(STORAGE_DEVICE, deviceSelect.value);
    }
    const savedCh = localStorage.getItem(STORAGE_CHANNEL);
    if (savedCh) channelSelect.value = savedCh;
  }

  deviceSelect.addEventListener('change', updateChannelVisibility);
  channelSelect.addEventListener('change', () => {
    localStorage.setItem(STORAGE_CHANNEL, channelSelect.value);
  });
  fileInput.addEventListener('change', () => {
    if (!fileInput.files.length) {
      deviceSelect.selectedIndex = 0;
      updateChannelVisibility();
    }
  });

  populateDevices();

  // ── Elapsed timer ──────────────────────────────────────────────────────────
  let elapsedTimer = null;
  let startTime    = 0;

  function startTimer() {
    startTime = Date.now();
    elapsedTimer = setInterval(() => {
      const s = Math.floor((Date.now() - startTime) / 1000);
      const m = Math.floor(s / 60);
      elapsedEl.textContent = `${String(m).padStart(2,'0')}:${String(s % 60).padStart(2,'0')}`;
    }, 1000);
  }

  function stopTimer() {
    if (elapsedTimer) clearInterval(elapsedTimer);
    elapsedTimer = null;
    elapsedEl.textContent = '00:00';
  }

  // ── Pause / keepalive ──────────────────────────────────────────────────────

  function setAudioLevel(rms) {
    const visual = Math.min(1, rms * 6);
    audioMeterBar.style.width = (visual * 100) + '%';
    if (levelDecayTimer) clearTimeout(levelDecayTimer);
    levelDecayTimer = setTimeout(() => {
      audioMeterBar.style.width = '0%';
      levelDecayTimer = null;
    }, 150);
  }

  function clearAudioLevel() {
    if (levelDecayTimer) { clearTimeout(levelDecayTimer); levelDecayTimer = null; }
    audioMeterBar.style.width = '0%';
  }

  function startKeepalive() {
    keepaliveTimer = setInterval(() => {
      if (activeWs && activeWs.readyState === WebSocket.OPEN) {
        activeWs.send(JSON.stringify({ type: 'keepalive' }));
      }
    }, 30000);
  }

  function stopKeepalive() {
    if (keepaliveTimer) clearInterval(keepaliveTimer);
    keepaliveTimer = null;
  }

  pauseBtn.addEventListener('click', () => {
    if (!activeWs || activeWs.readyState !== WebSocket.OPEN) return;
    if (!paused) {
      paused = true;
      pauseBtn.textContent = '▶ Resume';
      pauseBtn.className = 'active';
      activeWs.send(JSON.stringify({ type: 'pause' }));
      startKeepalive();
    } else {
      paused = false;
      pauseBtn.textContent = '⏸ Pause';
      pauseBtn.className = '';
      stopKeepalive();
      activeWs.send(JSON.stringify({ type: 'resume' }));
      if (resumeCapture) resumeCapture();
    }
  });

  // ── Status message handler ─────────────────────────────────────────────────
  function handleStatusMessage(msg) {
    console.log('[gibberly] msg:', msg.type, msg);
    if (msg.type === 'phrase') {
      const src = msg.raw_src || msg.raw_de || msg.clean_src || msg.clean_de || '';
      const tgt = msg.en_text || msg.text || '';
      if (src) srcTp.onPhrase(src);
      if (tgt) tgtTp.onPhrase(tgt);
    } else if (msg.type === 'llm_fallback') {
      console.warn(`[gibberly] LLM fallback — chunk: ${msg.chunk}`);
    } else if (msg.type === 'tts_error') {
      console.error(`[gibberly] TTS failed — ${msg.error}`);
    } else if (msg.type === 'pubsub_error') {
      console.error(`[gibberly] PubSub publish failed — ${msg.error}`);
    } else if (msg.type === 'listeners') {
      listenerCount.textContent = msg.count;
    } else if (msg.type === 'debug_audio_start') {
      console.log('[gibberly] synthesis started — first audio chunk, bytes:', msg.size);
    }
  }

  // ── Session management ─────────────────────────────────────────────────────
  let stopSession = null;

  actionBtn.addEventListener('click', () => {
    if (state === 'live' && stopSession) {
      stopSession();
    } else if (state !== 'connecting') {
      startSession();
    }
  });

  function startSession() {
    setState('connecting');
    const isFile = deviceSelect.value === FILE_OPTION_VALUE;
    if (isFile) {
      startFileSession();
    } else {
      startDeviceSession();
    }
  }

  // ── Shared WebSocket session setup ─────────────────────────────────────────
  function openWebSocket(onOpen) {
    const sourceLang = sourceLangSelect ? sourceLangSelect.value : 'de-DE';
    const ws = new WebSocket(`${backendWs}/ws/stream?source_lang=${sourceLang}`);
    ws.binaryType = 'arraybuffer';
    activeWs = ws;

    ws.onmessage = (evt) => {
      if (typeof evt.data === 'string') {
        let msg;
        try { msg = JSON.parse(evt.data); } catch { return; }
        if (msg.type === 'session_created') {
          setState('live');
          pauseBtn.disabled = false;
          startTimer();
          srcTp.clear();
          tgtTp.clear();
          listenerCount.textContent = '0';
          onOpen(ws);
        } else {
          handleStatusMessage(msg);
        }
      }
    };

    ws.onerror = () => {
      setState('error', 'Connection error');
    };

    ws.onclose = () => {
      activeWs = null;
      stopKeepalive();
      clearAudioLevel();
      paused = false;
      resumeCapture = null;
      if (state === 'live' || state === 'connecting') setState('idle');
      stopTimer();
      stopSession = null;
    };

    return ws;
  }

  // ── Device audio pipeline ──────────────────────────────────────────────────
  async function startDeviceSession() {
    const deviceId    = deviceSelect.value;
    const channelMode = channelSelect.value || 'left';
    let audioCtx, workletNode, stream;
    resumeCapture = null;  // device mode resumes automatically via paused flag; only file mode needs this

    const ws = openWebSocket(async (activeWsRef) => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            deviceId: { exact: deviceId },
            echoCancellation: false,
            noiseSuppression: false,
            autoGainControl: false,
            sampleRate: { ideal: 48000 },
          }
        });

        audioCtx = new AudioContext();
        await audioCtx.audioWorklet.addModule('worklet.js');

        workletNode = new AudioWorkletNode(audioCtx, 'gibberly-resampler', {
          processorOptions: { channelMode },
        });

        workletNode.port.onmessage = (e) => {
          if (e.data instanceof ArrayBuffer) {
            if (activeWsRef.readyState === WebSocket.OPEN && !paused) {
              activeWsRef.send(e.data);
            }
          } else if (e.data?.type === 'level') {
            setAudioLevel(e.data.rms);
          }
        };

        const source = audioCtx.createMediaStreamSource(stream);
        source.connect(workletNode);

      } catch (err) {
        setState('error', err.message);
        stopSession = null;
        activeWsRef.close();
      }
    });

    stopSession = () => {
      stopKeepalive();
      if (workletNode) workletNode.disconnect();
      if (stream) stream.getTracks().forEach(t => t.stop());
      if (audioCtx) audioCtx.close();
      ws.close();
      setState('idle');
      stopTimer();
      stopSession = null;
    };
  }

  // ── File audio pipeline ────────────────────────────────────────────────────
  function startFileSession() {
    const file = fileInput.files[0];
    if (!file) { setState('idle'); return; }

    let driveTimer = null;

    const ws = openWebSocket((activeWsRef) => {
      const reader = new FileReader();
      reader.onload = (e) => {
        const buf  = e.target.result;
        const pcm  = new Int16Array(buf, 44);
        let offset = 0;
        const CHUNK = 320;

        function sendNext() {
          if (offset >= pcm.length || activeWsRef.readyState !== WebSocket.OPEN) {
            if (activeWsRef.readyState === WebSocket.OPEN) activeWsRef.close();
            driveTimer = null;
            return;
          }
          if (paused) {
            driveTimer = null;
            return;
          }
          const chunk = pcm.slice(offset, offset + CHUNK);
          let sumSq = 0;
          for (let i = 0; i < chunk.length; i++) {
            const s = chunk[i] / 32768;
            sumSq += s * s;
          }
          setAudioLevel(Math.sqrt(sumSq / chunk.length));
          activeWsRef.send(chunk.buffer);
          offset += CHUNK;
          driveTimer = setTimeout(sendNext, 20);
        }

        resumeCapture = () => { if (driveTimer === null) sendNext(); };
        sendNext();
      };
      reader.readAsArrayBuffer(file);
    });

    stopSession = () => {
      stopKeepalive();
      clearAudioLevel();
      clearTimeout(driveTimer);
      resumeCapture = null;
      ws.close();
      setState('idle');
      stopTimer();
      stopSession = null;
    };
  }

  // ── Tab navigation ─────────────────────────────────────────────────────────
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.tab;
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b === btn));
      document.querySelectorAll('.tab-panel').forEach(p => { p.hidden = p.id !== 'tab-' + tab; });
    });
  });
})();
