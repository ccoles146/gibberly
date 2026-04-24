(function () {
  // ── Convert WebSocket URL to HTTP for backend fetches ─────────────────────────
  const backendHttp = window.GIBBERLY_BACKEND
    .replace(/^ws:/, 'http:')
    .replace(/^wss:/, 'https:');

  // ── DOM refs ─────────────────────────────────────────────────────────────────
  const connectBtn         = document.getElementById('connect-btn');
  const refreshSessionBtn  = document.getElementById('refresh-session-btn');
  const muteBtn            = document.getElementById('mute-btn');
  const dlMp3Btn           = document.getElementById('dl-mp3');
  const dlJsonBtn          = document.getElementById('dl-json');
  const dlTranscriptEnBtn  = document.getElementById('dl-transcript-en');
  const dlTranscriptDeBtn  = document.getElementById('dl-transcript-de');
  const clearBtn           = document.getElementById('clear-btn');
  const statusText         = document.getElementById('dbg-status');
  const phraseBar       = document.getElementById('phrase-bar');
  const logBody         = document.getElementById('log-body');
  const transcriptBody  = document.getElementById('transcript-body');
  const transcriptCount = document.getElementById('transcript-count');
  const transcriptWrap  = document.getElementById('transcript-wrap');
  const copyTextBtn     = document.getElementById('copy-transcript');
  const copyCsvBtn      = document.getElementById('copy-csv');

  const sChunks     = document.getElementById('s-chunks');
  const sPhrases    = document.getElementById('s-phrases');
  const sFails      = document.getElementById('s-fails');
  const sEmpty      = document.getElementById('s-empty');
  const sAvgBytes   = document.getElementById('s-avgbytes');
  const sAvgDur     = document.getElementById('s-avgdur');
  const sTotalAudio = document.getElementById('s-totalaudio');
  const sMaxLag     = document.getElementById('s-maxlag');
  const sPosLags    = document.getElementById('s-poslags');
  const sMsgBinary  = document.getElementById('s-msg-binary');
  const sMsgJson    = document.getElementById('s-msg-json');
  const sMsgOther   = document.getElementById('s-msg-other');

  // ── Session ──────────────────────────────────────────────────────────────────
  const params  = new URLSearchParams(window.location.search);
  let session   = params.get('session');
  let debugLang = 'en'; // resolved to a valid target lang before connecting

  // ── Audio (Web Audio API — same as app.js, works everywhere) ─────────────────
  let audioCtx     = null;
  let gainNode     = null;
  let muted        = false;
  let nextPlayTime = 0;

  // ── WebSocket ────────────────────────────────────────────────────────────────
  let ws        = null;
  let connected = false;

  // ── Diagnostic accumulators ──────────────────────────────────────────────────
  let phraseCount   = 0;
  let chunkCount    = 0;   // audio blobs received (= phrase count after backend fix)
  let failCount     = 0;
  let emptyCount    = 0;
  let totalDur      = 0;   // seconds of decoded audio
  let totalBytes    = 0;
  let maxLagS       = -Infinity;
  let posLagCount   = 0;
  let firstArrival  = null;
  let lastArrival   = null;
  let msgBinary     = 0;   // raw WebSocket message counts by dataType
  let msgJson       = 0;
  let msgOther      = 0;

  const rawChunks = [];  // Uint8Array[] for MP3 download
  const eventLog  = [];  // structured for JSON download

  // ── Helpers ──────────────────────────────────────────────────────────────────
  function setStatus(msg) { statusText.textContent = msg; }

  function fmt(n, dec = 0) {
    if (n === null || n === undefined || isNaN(n) || !isFinite(n)) return '—';
    return n.toFixed(dec);
  }

  function escHtml(s) {
    return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function lagClass(lagMs) {
    if (lagMs < 0)   return 'lag-ok';
    if (lagMs < 50)  return 'lag-warn';
    return 'lag-bad';
  }

  function updateSummary() {
    sChunks.textContent     = chunkCount;
    sPhrases.textContent    = phraseCount;

    sFails.textContent  = failCount;
    sFails.className    = `card-value${failCount  > 0 ? ' bad'  : ''}`;
    sEmpty.textContent  = emptyCount;
    sEmpty.className    = `card-value${emptyCount > 0 ? ' warn' : ''}`;

    sAvgBytes.textContent   = chunkCount > 0 ? fmt(totalBytes / chunkCount) : '—';
    sAvgDur.textContent     = chunkCount > 0 ? fmt((totalDur / chunkCount) * 1000, 1) : '—';
    sTotalAudio.textContent = fmt(totalDur, 2);

    if (maxLagS === -Infinity) {
      sMaxLag.textContent = '—';
      sMaxLag.className   = 'card-value';
    } else {
      sMaxLag.textContent = fmt(maxLagS * 1000) + ' ms';
      sMaxLag.className   = `card-value ${maxLagS < 0 ? 'good' : maxLagS < 0.05 ? 'warn' : 'bad'}`;
    }

    sPosLags.textContent = posLagCount;
    sPosLags.className   = `card-value${posLagCount > 0 ? ' warn' : ''}`;

    sMsgBinary.textContent = msgBinary;
    sMsgJson.textContent   = msgJson;
    sMsgOther.textContent  = msgOther;
  }

  // ── Transcript table ─────────────────────────────────────────────────────────
  // Phrase store for copy buttons
  const phraseStore = [];  // [{index, raw_de, clean_de, en_text}]

  function addTranscriptRow(index, raw_de, clean_de, en_text) {
    phraseStore.push({ index, raw_de, clean_de, en_text });
    transcriptCount.textContent = `${index} phrase${index === 1 ? '' : 's'}`;

    const tr = document.createElement('tr');
    tr.style.borderBottom = '1px solid #1e293b';
    tr.innerHTML = `
      <td style="padding:.25rem .5rem;color:#6b7280;white-space:nowrap">${index}</td>
      <td style="padding:.25rem .5rem;color:#94a3b8">${escHtml(raw_de)}</td>
      <td style="padding:.25rem .5rem;color:#cbd5e1">${escHtml(clean_de)}</td>
      <td style="padding:.25rem .5rem;color:#93c5fd;font-weight:500">${escHtml(en_text)}</td>
    `;
    transcriptBody.appendChild(tr);
    // Auto-scroll to show latest entry
    transcriptWrap.scrollTop = transcriptWrap.scrollHeight;
  }

  // ── Chunk log table ──────────────────────────────────────────────────────────
  function addPhraseMarkerRow(text) {
    const tr = document.createElement('tr');
    tr.className = 'phrase-marker';
    tr.innerHTML = `<td colspan="9">⬇ PHRASE #${phraseCount}: ${escHtml(text)}</td>`;
    logBody.prepend(tr);
  }

  function addChunkRow(e) {
    const lagMs = e.lagS !== null ? e.lagS * 1000 : null;
    const durMs = e.durS !== null ? e.durS * 1000 : null;
    const decCell = e.decResult === 'ok'
      ? `<td class="str ok">ok</td>`
      : e.decResult === 'empty'
        ? `<td class="str empty">empty</td>`
        : `<td class="str fail">FAIL</td>`;

    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="str">${e.index}</td>
      <td>${fmt(e.arrMs)}</td>
      <td>${fmt(e.gapMs)}</td>
      <td>${e.bytes}</td>
      ${decCell}
      <td>${durMs !== null ? fmt(durMs, 1) : '—'}</td>
      <td class="${lagMs !== null ? lagClass(lagMs) : ''}">${lagMs !== null ? fmt(lagMs) : '—'}</td>
      <td>${fmt(e.ctxTimeS, 3)}</td>
      <td>${fmt(e.decTimeMs, 1)}</td>
    `;
    logBody.prepend(tr);
  }

  // ── Audio processing ─────────────────────────────────────────────────────────
  async function processAudioBlob(arrayBuffer) {
    const wallNow = performance.now();
    const bytes   = arrayBuffer.byteLength;
    const index   = ++chunkCount;

    rawChunks.push(new Uint8Array(arrayBuffer.slice(0)));
    totalBytes += bytes;

    const arrMs = firstArrival === null
      ? (firstArrival = wallNow, 0)
      : wallNow - firstArrival;
    const gapMs = lastArrival === null ? null : wallNow - lastArrival;
    lastArrival = wallNow;

    const ctxTimeS = audioCtx ? audioCtx.currentTime : null;
    const decStart = performance.now();
    let decResult  = 'fail';
    let durS       = null;
    let lagS       = null;

    try {
      // decodeAudioData consumes the buffer — pass a copy if we still need the original.
      // We already copied to rawChunks above, so pass the original here.
      const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
      durS = audioBuffer.duration;

      if (durS < 0.001) {
        decResult = 'empty';
        emptyCount++;
      } else {
        decResult  = 'ok';
        totalDur  += durS;

        const src     = audioCtx.createBufferSource();
        src.buffer    = audioBuffer;
        src.connect(gainNode);
        const now     = audioCtx.currentTime;
        lagS          = now - nextPlayTime;     // negative = buffer ahead (good)
        if (lagS > maxLagS) maxLagS = lagS;
        if (lagS > 0) posLagCount++;
        const startAt = Math.max(now, nextPlayTime);
        src.start(startAt);
        nextPlayTime  = startAt + durS;
      }
    } catch (_) {
      failCount++;
    }

    const decTimeMs = performance.now() - decStart;
    const entry = { index, arrMs, gapMs, bytes, decResult, durS, lagS, ctxTimeS, decTimeMs };
    eventLog.push(entry);
    addChunkRow(entry);
    updateSummary();
    dlMp3Btn.disabled  = false;
    dlJsonBtn.disabled = false;
  }

  // ── WebSocket / connection ───────────────────────────────────────────────────
  function base64ToArrayBuffer(b64) {
    const bin  = atob(b64);
    const buf  = new ArrayBuffer(bin.length);
    const view = new Uint8Array(buf);
    for (let i = 0; i < bin.length; i++) view[i] = bin.charCodeAt(i);
    return buf;
  }

  async function getNegotiateUrl() {
    const res = await fetch(backendHttp + '/negotiate?session=' + session + '&lang=' + debugLang);
    if (!res.ok) {
      const body = await res.text().catch(() => '');
      throw new Error(`negotiate ${res.status}: ${body} (session=${session}, lang=${debugLang})`);
    }
    const { url } = await res.json();
    return url;
  }

  async function connect() {
    connectBtn.disabled = true;
    setStatus('Connecting…');

    // Always sync to current session before connecting
    try {
      const res = await fetch(backendHttp + '/current-session');
      if (!res.ok) throw new Error('no active session');
      const { session_id } = await res.json();
      if (session_id !== session) {
        session = session_id;
        const url = new URL(window.location.href);
        url.searchParams.set('session', session_id);
        window.history.replaceState(null, '', url.toString());
      }
      // Pick a valid target language (not the source language)
      const infoRes = await fetch(backendHttp + '/session/' + session + '/info');
      const sourceLang = infoRes.ok ? (await infoRes.json()).source_lang.split('-')[0] : null;
      const langsRes = await fetch(backendHttp + '/languages');
      const langs = langsRes.ok ? await langsRes.json() : [];
      const targets = sourceLang ? langs.filter(l => l.code !== sourceLang) : langs;
      debugLang = targets.find(l => l.code === 'en')?.code || targets[0]?.code || 'en';
    } catch (e) {
      setStatus('No active session — start one from the operator.');
      connectBtn.disabled = false;
      return;
    }

    audioCtx     = new (window.AudioContext || window.webkitAudioContext)();
    gainNode     = audioCtx.createGain();
    gainNode.gain.value = muted ? 0 : 1;
    gainNode.connect(audioCtx.destination);
    nextPlayTime = 0;
    if (audioCtx.state === 'suspended') await audioCtx.resume();

    let pubsubUrl;
    try {
      pubsubUrl = await getNegotiateUrl();
    } catch (e) {
      if (audioCtx) { audioCtx.close(); audioCtx = null; }
      setStatus('Failed: ' + e.message);
      connectBtn.disabled = false;
      return;
    }

    console.log('[debug] Opening WebSocket to:', pubsubUrl.substring(0, 80) + '…');
    ws = new WebSocket(pubsubUrl, 'json.webpubsub.azure.v1');

    ws.onopen = () => {
      const group = `session-${session}-${debugLang}`;
      console.log('[debug] WS open — joining group:', group);
      connected              = true;
      connectBtn.textContent = 'Disconnect';
      connectBtn.className   = 'connected';
      connectBtn.disabled    = false;
      setStatus('Connected — listening…');
      ws.send(JSON.stringify({ type: 'joinGroup', group }));
    };

    ws.onmessage = (event) => {
      console.log('[debug] WS message:', event.data.substring ? event.data.substring(0, 200) : event.data);
      let msg;
      try { msg = JSON.parse(event.data); } catch { return; }

      if (msg.type === 'message' && msg.dataType === 'binary') {
        msgBinary++;
        processAudioBlob(base64ToArrayBuffer(msg.data));
      } else if (msg.type === 'message') {
        // Azure Web PubSub may deliver JSON data as dataType:"json" (parsed object)
        // or dataType:"text" (string). Handle both transparently.
        if (msg.dataType === 'json' || msg.dataType === 'text') {
          msgJson++;
        } else {
          msgOther++;
        }
        let d = msg.data;
        if (typeof d === 'string') {
          try { d = JSON.parse(d); } catch { d = null; }
        }
        if (d?.type === 'phrase') {
          phraseCount++;
          phraseBar.textContent = d.text || '(empty)';
          addPhraseMarkerRow(d.text || '(empty)');
          addTranscriptRow(phraseCount, d.clean_src || '', d.clean_src || '', d.text || '');
          eventLog.push({ type: 'phrase', raw_de: d.raw_de, clean_de: d.clean_de, text: d.text, wallNow: performance.now() });
          dlTranscriptEnBtn.disabled = false;
          dlTranscriptDeBtn.disabled = false;
          updateSummary();
        } else if (d?.type === 'close') {
          disconnect('Session ended.');
        }
        updateSummary();
      }
    };

    ws.onerror = (e) => { console.error('[debug] WS error:', e); setStatus('WebSocket error.'); };

    ws.onclose = (e) => { console.log('[debug] WS closed — code:', e.code, 'reason:', e.reason);
      connected              = false;
      connectBtn.textContent = 'Connect';
      connectBtn.className   = '';
      connectBtn.disabled    = false;
      if (statusText.textContent === 'Connected — listening…') setStatus('Disconnected.');
    };
  }

  function disconnect(reason) {
    if (ws && ws.readyState < WebSocket.CLOSING) ws.close();
    ws = null;
    if (audioCtx) { audioCtx.close(); audioCtx = null; }
    nextPlayTime           = 0;
    connected              = false;
    connectBtn.textContent = 'Connect';
    connectBtn.className   = '';
    connectBtn.disabled    = false;
    setStatus(reason || 'Disconnected.');
  }

  // ── Downloads ────────────────────────────────────────────────────────────────
  function triggerDownload(blob, filename) {
    const url = URL.createObjectURL(blob);
    Object.assign(document.createElement('a'), { href: url, download: filename }).click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }

  dlMp3Btn.addEventListener('click', () => {
    if (!rawChunks.length) return;
    const totalLen = rawChunks.reduce((n, c) => n + c.length, 0);
    const merged   = new Uint8Array(totalLen);
    let off        = 0;
    for (const c of rawChunks) { merged.set(c, off); off += c.length; }
    triggerDownload(new Blob([merged], { type: 'audio/mpeg' }), `gibberly-${session}-${Date.now()}.mp3`);
  });

  dlJsonBtn.addEventListener('click', () => {
    if (!eventLog.length) return;
    const summary = {
      session, capturedAt: new Date().toISOString(),
      chunkCount, phraseCount, failCount, emptyCount,
      totalDurS: totalDur, totalBytes,
      avgBytesPerChunk: chunkCount > 0 ? totalBytes / chunkCount : null,
      avgDurMsPerChunk: chunkCount > 0 ? (totalDur / chunkCount) * 1000 : null,
      maxLagS: maxLagS === -Infinity ? null : maxLagS,
      posLagCount,
    };
    triggerDownload(
      new Blob([JSON.stringify({ summary, events: eventLog }, null, 2)], { type: 'application/json' }),
      `gibberly-debug-${session}-${Date.now()}.json`
    );
  });

  // ── Transcript copy buttons ───────────────────────────────────────────────────
  copyTextBtn.addEventListener('click', () => {
    if (!phraseStore.length) return;
    const text = phraseStore.map(p =>
      `[${p.index}] DE: ${p.raw_de}\n     EN: ${p.en_text}`
    ).join('\n\n');
    navigator.clipboard.writeText(text).then(() => {
      copyTextBtn.textContent = 'Copied!';
      setTimeout(() => { copyTextBtn.textContent = 'Copy as text'; }, 2000);
    });
  });

  copyCsvBtn.addEventListener('click', () => {
    if (!phraseStore.length) return;
    const header = '#,DE raw,DE clean,EN';
    const rows   = phraseStore.map(p =>
      [p.index, p.raw_de, p.clean_de, p.en_text]
        .map(v => `"${String(v).replace(/"/g, '""')}"`)
        .join(',')
    );
    navigator.clipboard.writeText([header, ...rows].join('\n')).then(() => {
      copyCsvBtn.textContent = 'Copied!';
      setTimeout(() => { copyCsvBtn.textContent = 'Copy as CSV'; }, 2000);
    });
  });

  // ── Transcript downloads ──────────────────────────────────────────────────────
  function downloadText(content, filename) {
    const blob = new Blob([content], { type: 'text/plain' });
    triggerDownload(blob, filename);
  }

  dlTranscriptEnBtn.addEventListener('click', () => {
    if (!phraseStore.length) return;
    downloadText(phraseStore.map(p => p.en_text).join('\n'), `gibberly-en-${session}-${Date.now()}.txt`);
  });

  dlTranscriptDeBtn.addEventListener('click', () => {
    if (!phraseStore.length) return;
    downloadText(phraseStore.map(p => p.clean_de || p.raw_de).join('\n'), `gibberly-de-${session}-${Date.now()}.txt`);
  });

  // ── Refresh session ───────────────────────────────────────────────────────────
  refreshSessionBtn.addEventListener('click', async () => {
    refreshSessionBtn.disabled = true;
    refreshSessionBtn.textContent = 'Refreshing…';
    try {
      const res = await fetch(backendHttp + '/current-session');
      if (!res.ok) throw new Error('No active session');
      const { session_id } = await res.json();
      if (session_id !== session) {
        if (connected) disconnect('Switching to new session…');
        session = session_id;
        const url = new URL(window.location.href);
        url.searchParams.set('session', session_id);
        window.history.replaceState(null, '', url.toString());
        setStatus(`Session updated: ${session_id}`);
      } else {
        setStatus('Already on latest session.');
      }
    } catch (e) {
      setStatus('Refresh failed: ' + e.message);
    } finally {
      refreshSessionBtn.disabled = false;
      refreshSessionBtn.textContent = 'Refresh Session';
    }
  });

  // ── Clear ────────────────────────────────────────────────────────────────────
  clearBtn.addEventListener('click', () => {
    rawChunks.length         = 0;
    eventLog.length          = 0;
    phraseStore.length       = 0;
    chunkCount = phraseCount = failCount = emptyCount = posLagCount = 0;
    msgBinary = msgJson = msgOther = 0;
    totalDur = totalBytes    = 0;
    maxLagS                  = -Infinity;
    firstArrival = lastArrival = null;
    nextPlayTime             = 0;
    logBody.innerHTML        = '';
    transcriptBody.innerHTML = '';
    phraseBar.textContent    = 'Waiting for phrases…';
    transcriptCount.textContent = '0 phrases';
    dlMp3Btn.disabled            = true;
    dlJsonBtn.disabled           = true;
    dlTranscriptEnBtn.disabled   = true;
    dlTranscriptDeBtn.disabled   = true;
    updateSummary();
  });

  muteBtn.addEventListener('click', () => {
    muted = !muted;
    if (gainNode) gainNode.gain.value = muted ? 0 : 1;
    muteBtn.textContent = muted ? 'Unmute' : 'Mute';
    muteBtn.className   = muted ? 'muted' : '';
  });

  connectBtn.addEventListener('click', () => {
    if (connected) disconnect();
    else connect();
  });

  // On load, sync to the current session (handles stale ?session= after reconnect)
  (async () => {
    try {
      const res = await fetch(backendHttp + '/current-session');
      if (!res.ok) throw new Error('no session');
      const { session_id } = await res.json();
      if (session_id !== session) {
        session = session_id;
        const url = new URL(window.location.href);
        url.searchParams.set('session', session_id);
        window.history.replaceState(null, '', url.toString());
        setStatus(`Session updated: ${session_id}`);
      } else {
        setStatus('Ready.');
      }
      connectBtn.disabled = false;
    } catch {
      if (!session) {
        setStatus('No active session — start one from the operator.');
        connectBtn.disabled = true;
      } else {
        setStatus('Ready (could not verify session).');
        connectBtn.disabled = false;
      }
    }
  })();
})();
