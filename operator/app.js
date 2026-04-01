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
  const lastPhraseEl   = document.getElementById('last-phrase');
  const deviceSelect   = document.getElementById('device-select');
  const channelSelect  = document.getElementById('channel-select');
  const fileInput      = document.getElementById('file-input');
  const actionBtn      = document.getElementById('action-btn');

  // ── Config ──────────────────────────────────────────────────────────────────
  const backendWs  = window.GIBBERLY_BACKEND;                     // e.g. ws://host:8000
  const backendHttp = backendWs.replace(/^ws:/, 'http:').replace(/^wss:/, 'https:');
  const liveUrl    = backendHttp + '/listen/live';

  // ── QR code (rendered once on load, never changes) ──────────────────────────
  (function renderQr() {
    const qr = qrcode(0, 'M');
    qr.addData(liveUrl);
    qr.make();
    qrCanvas.innerHTML = qr.createTableTag(4, 0);
    liveUrlEl.textContent = liveUrl;
    liveUrlEl.href = liveUrl;
  })();

  // ── State machine ──────────────────────────────────────────────────────────
  // States: idle | connecting | live | error
  let state = 'idle';

  function setState(s, msg) {
    state = s;
    statusDot.className = s === 'live' ? 'live' : s === 'connecting' ? 'connecting' : s === 'error' ? 'error' : '';
    statusText.textContent = msg || { idle: 'OFFLINE', connecting: 'CONNECTING…', live: 'LIVE', error: 'ERROR' }[s];
    actionBtn.disabled = s === 'connecting';
    actionBtn.textContent = s === 'live' ? '■ Stop' : s === 'error' ? '▶ Retry' : '▶ Start';
    actionBtn.className = s === 'live' ? 'stop' : '';
    statListeners.style.display = s === 'live' ? '' : 'none';
    statElapsed.style.display   = s === 'live' ? '' : 'none';
  }

  setState('idle');

  // ── Device enumeration ─────────────────────────────────────────────────────
  const FILE_OPTION_VALUE = '__file__';
  const STORAGE_DEVICE    = 'gibberly_device';
  const STORAGE_CHANNEL   = 'gibberly_channel';

  async function populateDevices() {
    // Request permission so device labels are populated
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach(t => t.stop());
    } catch (_) { /* permission denied — labels will be generic */ }

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
    const inputs  = devices.filter(d => d.kind === 'audioinput');

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

    // Restore saved device
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
      // User cancelled — revert to first real device
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

  // ── Status message handler (filled in Task 6) ─────────────────────────────
  function handleStatusMessage(msg) {
    if (msg.type === 'phrase') {
      lastPhraseEl.textContent = `"${msg.text}"`;
    } else if (msg.type === 'listeners') {
      listenerCount.textContent = msg.count;
    }
  }

  // ── Session management (filled in Tasks 6–7) ──────────────────────────────
  let stopSession = null;  // set when a session is active; call to stop it

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
    const ws = new WebSocket(backendWs + '/ws/stream');
    ws.binaryType = 'arraybuffer';

    ws.onmessage = (evt) => {
      if (typeof evt.data === 'string') {
        let msg;
        try { msg = JSON.parse(evt.data); } catch { return; }
        if (msg.type === 'session_created') {
          setState('live');
          startTimer();
          lastPhraseEl.textContent = '';
          listenerCount.textContent = '0';
          onOpen(ws);
        } else {
          handleStatusMessage(msg);
        }
      }
    };

    ws.onerror = () => {
      setState('error', 'Connection error');
      stopSession = null;
    };

    ws.onclose = () => {
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

    const ws = openWebSocket(async (activeWs) => {
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
          if (activeWs.readyState === WebSocket.OPEN) {
            activeWs.send(e.data);
          }
        };

        const source = audioCtx.createMediaStreamSource(stream);
        source.connect(workletNode);
        // Do NOT connect workletNode to destination — no local playback echo

      } catch (err) {
        setState('error', err.message);
        stopSession = null;
        activeWs.close();
      }
    });

    stopSession = () => {
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

    const ws = openWebSocket((activeWs) => {
      const reader = new FileReader();
      reader.onload = (e) => {
        // Standard PCM WAV: skip 44-byte header, treat rest as 16kHz 16-bit mono Int16
        const buf   = e.target.result;
        const pcm   = new Int16Array(buf, 44);   // skip WAV header
        let offset  = 0;
        const CHUNK = 320;   // 20 ms at 16kHz

        function sendNext() {
          if (offset >= pcm.length || activeWs.readyState !== WebSocket.OPEN) {
            if (activeWs.readyState === WebSocket.OPEN) activeWs.close();
            return;
          }
          const chunk = pcm.slice(offset, offset + CHUNK);
          activeWs.send(chunk.buffer);
          offset += CHUNK;
          setTimeout(sendNext, 20);
        }

        sendNext();
      };
      reader.readAsArrayBuffer(file);
    });

    stopSession = () => {
      ws.close();
      setState('idle');
      stopTimer();
      stopSession = null;
    };
  }
})();
