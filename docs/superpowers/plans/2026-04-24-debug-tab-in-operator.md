# Debug Tab in Operator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the standalone `listener/debug.html` page into the operator UI as a navigable tab, accessible via a tab bar in the operator header.

**Architecture:** Add a two-tab header nav (Operator / Debug) to `operator/index.html`. The existing operator content wraps into `#tab-operator`; a new `#tab-debug` panel contains the diagnostic content. A new `operator/debug.js` (adapted from `listener/debug.js`) runs alongside `operator/app.js` in the same page. `listener/debug.html` and `listener/debug.js` are deleted.

**Tech Stack:** Vanilla HTML/CSS/JS. No build step. `operator/debug.js` derives `backendHttp` from `window.GIBBERLY_BACKEND` (same as `app.js`) because the operator page may be served from a different origin than the backend.

**Status:** Implemented

---

## File Map

| Action | File | What changes |
|--------|------|-------------|
| Modify | `operator/index.html` | Add tab nav CSS + HTML, debug panel CSS + HTML, load `debug.js` |
| Create | `operator/debug.js` | `listener/debug.js` adapted: add `backendHttp`, prefix all `fetch` calls, rename `#status-text` → `#dbg-status` |
| Modify | `operator/app.js` | Remove 3 `debugLinkEl` references, add tab-switching event listener |
| Modify | `docs/superpowers/specs/2026-04-21-freemium-architecture-design.md` | Update "Debug page" bullet in Security section |
| Delete | `listener/debug.html` | No longer served — removed |
| Delete | `listener/debug.js` | Moved to `operator/debug.js` |

---

### Task 1: Update the spec

**Files:**
- Modify: `docs/superpowers/specs/2026-04-21-freemium-architecture-design.md`

- [ ] **Step 1: Replace the Debug page bullet in the Security section**

Find this block (around line 243–246):

```markdown
### Debug page

`/listen/debug.html` is only served when `DEBUG=true` in `.env`. In production it returns 404.
```

Replace with:

```markdown
### Debug page

The Audio Diagnostics view is a tab inside `operator/index.html`, not a separate URL. It is therefore already behind operator access — no `DEBUG` gate is needed and there is no `listener/debug.html` to serve or 404.
```

Also remove the Verification bullet that says:
```
- `/listen/debug.html` returns 404 when `DEBUG=false`
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-04-21-freemium-architecture-design.md
git commit -m "docs: debug page is now a tab in the operator, not a separate listener URL"
```

---

### Task 2: Create operator/debug.js

**Files:**
- Create: `operator/debug.js`

This is `listener/debug.js` with three changes:
1. `backendHttp` derived from `window.GIBBERLY_BACKEND` at the top
2. All `fetch('/')` calls prefixed with `backendHttp`
3. `statusText` DOM ref renamed from `#status-text` to `#dbg-status` (avoids clash with operator's own `#status-text`)

- [ ] **Step 1: Write operator/debug.js**

```js
(function () {
  // ── DOM refs ─────────────────────────────────────────────────────────────────
  const connectBtn         = document.getElementById('connect-btn');
  const refreshSessionBtn  = document.getElementById('refresh-session-btn');
  const muteBtn            = document.getElementById('mute-btn');
  const dlMp3Btn           = document.getElementById('dl-mp3');
  const dlJsonBtn          = document.getElementById('dl-json');
  const dlTranscriptEnBtn  = document.getElementById('dl-transcript-en');
  const dlTranscriptDeBtn  = document.getElementById('dl-transcript-de');
  const clearBtn           = document.getElementById('clear-btn');
  const statusText         = document.getElementById('dbg-status');   // renamed from #status-text
  const phraseBar       = document.getElementById('phrase-bar');
  const logBody         = document.getElementById('log-body');
  const transcriptBody  = document.getElementById('transcript-body');
  const transcriptCount = document.getElementById('transcript-count');
  const transcriptWrap  = document.querySelector('.transcript-wrap');
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

  // ── Backend URL (same derivation as app.js) ──────────────────────────────────
  const backendHttp = window.GIBBERLY_BACKEND
    .replace(/^ws:/, 'http:')
    .replace(/^wss:/, 'https:');

  // ── Session ──────────────────────────────────────────────────────────────────
  const params  = new URLSearchParams(window.location.search);
  let session   = params.get('session');
  let debugLang = 'en';

  // ── Audio ─────────────────────────────────────────────────────────────────────
  let audioCtx     = null;
  let gainNode     = null;
  let muted        = false;
  let nextPlayTime = 0;

  // ── WebSocket ────────────────────────────────────────────────────────────────
  let ws        = null;
  let connected = false;

  // ── Diagnostic accumulators ──────────────────────────────────────────────────
  let phraseCount   = 0;
  let chunkCount    = 0;
  let failCount     = 0;
  let emptyCount    = 0;
  let totalDur      = 0;
  let totalBytes    = 0;
  let maxLagS       = -Infinity;
  let posLagCount   = 0;
  let firstArrival  = null;
  let lastArrival   = null;
  let msgBinary     = 0;
  let msgJson       = 0;
  let msgOther      = 0;

  const rawChunks = [];
  const eventLog  = [];

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
  const phraseStore = [];

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
        lagS          = now - nextPlayTime;
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
    const res = await fetch(backendHttp + `/negotiate?session=${session}&lang=${debugLang}`);
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
      const infoRes = await fetch(backendHttp + `/session/${session}/info`);
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

    ws.onclose = (e) => {
      console.log('[debug] WS closed — code:', e.code, 'reason:', e.reason);
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
```

- [ ] **Step 2: Verify the file was created**

```bash
wc -l operator/debug.js
```

Expected: ~280 lines.

- [ ] **Step 3: Commit**

```bash
git add operator/debug.js
git commit -m "feat: add operator/debug.js (adapted from listener/debug.js with backendHttp prefix)"
```

---

### Task 3: Update operator/index.html — add tab nav CSS + HTML

**Files:**
- Modify: `operator/index.html`

This task has three parts: (A) add CSS, (B) restructure the layout to use tab panels, (C) add the debug panel HTML.

- [ ] **Step 1: Add tab nav + debug panel CSS**

Inside the existing `<style>` block in `operator/index.html`, append the following CSS before the closing `</style>` tag (after the `#pause-btn.active:hover:not(:disabled)` block):

```css
    /* ── TAB NAVIGATION ─────────────────────────────────────────────── */
    .tab-nav {
      display: flex;
      gap: 2px;
      align-items: center;
    }

    .tab-btn {
      padding: 4px 12px;
      border: 1px solid var(--border);
      border-radius: var(--r-xs);
      cursor: pointer;
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      font-family: var(--ui);
      background: transparent;
      color: var(--text-dim);
      transition: all 0.15s;
    }
    .tab-btn:hover { color: var(--text-soft); border-color: var(--border-mid); }
    .tab-btn.active {
      background: var(--amber-glow);
      border-color: rgba(232,154,14,0.3);
      color: var(--amber);
    }

    /* ── TAB PANELS ──────────────────────────────────────────────────── */
    .tab-panel {
      display: flex;
      flex-direction: column;
      flex: 1;
      overflow: hidden;
    }
    .tab-panel[hidden] { display: none; }

    /* ── DEBUG PANEL ─────────────────────────────────────────────────── */
    .debug-panel .dbg-controls {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px;
      padding: 10px 16px;
      border-bottom: 1px solid var(--border);
      background: var(--bg-mid);
      flex-shrink: 0;
    }

    .debug-panel button {
      padding: 5px 12px;
      border: 1px solid var(--border-mid);
      border-radius: var(--r-sm);
      cursor: pointer;
      font-size: 12px;
      font-weight: 500;
      font-family: var(--ui);
      background: var(--bg-card);
      color: var(--text-soft);
      transition: all 0.15s;
      white-space: nowrap;
    }
    .debug-panel button:hover:not(:disabled)  { border-color: var(--text-soft); color: var(--text); }
    .debug-panel button:disabled               { opacity: 0.35; cursor: default; }
    .debug-panel #connect-btn           { border-color: rgba(232,154,14,0.4); color: var(--amber); }
    .debug-panel #connect-btn:hover     { background: var(--amber-glow); }
    .debug-panel #connect-btn.connected { border-color: rgba(232,84,84,0.4); color: var(--red); }
    .debug-panel #refresh-session-btn:hover { border-color: var(--blue, #60a5fa); color: var(--blue, #60a5fa); }
    .debug-panel #mute-btn.muted            { border-color: rgba(232,84,84,0.4); color: var(--red); }
    .debug-panel #dl-mp3:hover     { border-color: var(--teal); color: var(--teal); }
    .debug-panel #dl-json:hover    { border-color: var(--text-soft); color: var(--text); }
    .debug-panel #clear-btn:hover  { border-color: var(--red); color: var(--red); }

    #dbg-status {
      font-size: 11px;
      color: var(--text-dim);
      font-family: var(--mono);
      flex: 1;
      text-align: right;
    }

    .debug-panel .dbg-content {
      flex: 1;
      padding: 14px 16px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .debug-panel .dbg-content::-webkit-scrollbar { width: 3px; }
    .debug-panel .dbg-content::-webkit-scrollbar-track { background: transparent; }
    .debug-panel .dbg-content::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

    .dbg-summary {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
      gap: 6px;
      flex-shrink: 0;
    }

    .dbg-card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--r);
      padding: 8px 12px;
      transition: border-color 0.2s;
    }
    .dbg-card:hover { border-color: var(--border-mid); }

    .dbg-card-label {
      font-size: 9px;
      font-weight: 700;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: var(--text-dim);
      margin-bottom: 4px;
    }

    .card-value {
      font-family: var(--mono);
      font-size: 18px;
      font-weight: 500;
      color: var(--text);
      font-variant-numeric: tabular-nums;
      line-height: 1;
    }
    .card-value.warn { color: var(--orange); }
    .card-value.bad  { color: var(--red); }
    .card-value.good { color: var(--green); }

    #phrase-bar {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--r);
      padding: 10px 14px;
      font-size: 13px;
      color: #60a5fa;
      min-height: 40px;
      flex-shrink: 0;
      font-family: var(--mono);
    }

    .dbg-section {
      display: flex;
      flex-direction: column;
      gap: 6px;
      flex-shrink: 0;
    }

    .dbg-section-label {
      font-size: 9px;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--text-dim);
    }

    .debug-panel details {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--r);
      overflow: hidden;
    }

    .debug-panel details > summary {
      cursor: pointer;
      padding: 10px 14px;
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 0.04em;
      color: var(--text-soft);
      user-select: none;
      list-style: none;
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid var(--border);
    }
    .debug-panel details > summary::-webkit-details-marker { display: none; }
    .debug-panel details > summary::after {
      content: '▼';
      font-size: 9px;
      color: var(--text-dim);
      transition: transform 0.2s;
    }
    .debug-panel details[open] > summary::after { transform: rotate(180deg); }

    .transcript-actions {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      padding: 8px 12px;
      border-bottom: 1px solid var(--border);
      background: var(--bg-surface);
    }

    .transcript-wrap {
      max-height: 40vh;
      overflow-y: auto;
    }
    .transcript-wrap::-webkit-scrollbar { width: 3px; }
    .transcript-wrap::-webkit-scrollbar-track { background: transparent; }
    .transcript-wrap::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

    .table-wrap {
      overflow-x: auto;
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--r);
    }
    .table-wrap::-webkit-scrollbar { height: 4px; }
    .table-wrap::-webkit-scrollbar-track { background: transparent; }
    .table-wrap::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }

    .debug-panel table {
      width: 100%;
      border-collapse: collapse;
      font-family: var(--mono);
      font-size: 11px;
      white-space: nowrap;
    }

    .debug-panel thead th {
      background: var(--bg-surface);
      color: var(--text-dim);
      padding: 6px 10px;
      text-align: right;
      border-bottom: 1px solid var(--border);
      position: sticky;
      top: 0;
      font-size: 9px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }
    .debug-panel thead th:first-child,
    .debug-panel thead th.str   { text-align: left; }

    .debug-panel tbody tr:nth-child(even) { background: #0d1320; }
    .debug-panel tbody tr:hover            { background: #131d30; }

    .debug-panel td {
      padding: 4px 10px;
      border-bottom: 1px solid rgba(30, 44, 68, 0.5);
      text-align: right;
      color: var(--text-soft);
    }
    .debug-panel td:first-child,
    .debug-panel td.str { text-align: left; color: var(--text); }

    .ok       { color: var(--green); }
    .fail     { color: var(--red); }
    .empty    { color: var(--orange); }
    .lag-ok   { color: var(--green); }
    .lag-warn { color: var(--orange); }
    .lag-bad  { color: var(--red); }

    .debug-panel .phrase-marker td {
      background: rgba(96, 165, 250, 0.08) !important;
      color: #60a5fa !important;
      font-style: italic;
    }

    .table-note {
      font-size: 10px;
      color: var(--text-dim);
      padding: 8px 12px;
      font-family: var(--mono);
      border-top: 1px solid var(--border);
      background: var(--bg-surface);
    }
```

- [ ] **Step 2: Add tab nav to the header**

In `operator/index.html`, find the `<div class="header-meta">` block:

```html
    <div class="header-meta">
      <span id="stat-listeners">👥 <span id="listener-count">0</span></span>
      <span id="stat-elapsed"><span id="elapsed">00:00</span></span>
    </div>
```

Replace with:

```html
    <div class="header-meta">
      <span id="stat-listeners">👥 <span id="listener-count">0</span></span>
      <span id="stat-elapsed"><span id="elapsed">00:00</span></span>
    </div>

    <nav class="tab-nav">
      <button class="tab-btn active" data-tab="operator">Operator</button>
      <button class="tab-btn" data-tab="debug">Debug</button>
    </nav>
```

- [ ] **Step 3: Wrap operator content in a tab panel**

Find the comment `<!-- MAIN GRID -->` followed by `<div class="op-grid">`. The operator content spans from that `<div class="op-grid">` through to the closing `</footer>` at the bottom. Wrap it:

Before `<!-- MAIN GRID -->`, insert:
```html
  <!-- OPERATOR TAB -->
  <div id="tab-operator" class="tab-panel">
```

After the closing `</footer>` tag (which currently ends the file before the scripts), insert:
```html
  </div><!-- /#tab-operator -->
```

So the structure becomes:
```html
  </header>

  <!-- OPERATOR TAB -->
  <div id="tab-operator" class="tab-panel">

    <!-- MAIN GRID -->
    <div class="op-grid">
      ...existing grid content...
    </div>

    <!-- FOOTER -->
    <footer class="op-footer">
      ...existing footer...
    </footer>

  </div><!-- /#tab-operator -->
```

- [ ] **Step 4: Add the debug panel**

After the `</div><!-- /#tab-operator -->` line, insert the full debug panel HTML:

```html
  <!-- DEBUG TAB -->
  <div id="tab-debug" class="tab-panel debug-panel" hidden>

    <!-- CONTROLS -->
    <div class="dbg-controls">
      <button id="connect-btn">Connect</button>
      <button id="refresh-session-btn">Refresh Session</button>
      <button id="mute-btn">Mute</button>
      <button id="dl-mp3" disabled>↓ MP3</button>
      <button id="dl-json" disabled>↓ JSON Log</button>
      <button id="clear-btn">Clear</button>
      <span id="dbg-status">Not connected</span>
    </div>

    <!-- CONTENT -->
    <div class="dbg-content">

      <!-- SUMMARY CARDS -->
      <div class="dbg-summary">
        <div class="dbg-card"><div class="dbg-card-label">Chunks</div>       <div class="card-value" id="s-chunks">0</div></div>
        <div class="dbg-card"><div class="dbg-card-label">Phrases</div>      <div class="card-value" id="s-phrases">0</div></div>
        <div class="dbg-card"><div class="dbg-card-label">Decode fails</div> <div class="card-value" id="s-fails">0</div></div>
        <div class="dbg-card"><div class="dbg-card-label">Empty decodes</div><div class="card-value" id="s-empty">0</div></div>
        <div class="dbg-card"><div class="dbg-card-label">Avg bytes</div>    <div class="card-value" id="s-avgbytes">—</div></div>
        <div class="dbg-card"><div class="dbg-card-label">Avg dur ms</div>   <div class="card-value" id="s-avgdur">—</div></div>
        <div class="dbg-card"><div class="dbg-card-label">Total audio s</div><div class="card-value" id="s-totalaudio">0</div></div>
        <div class="dbg-card"><div class="dbg-card-label">Max sched lag</div><div class="card-value" id="s-maxlag">—</div></div>
        <div class="dbg-card"><div class="dbg-card-label">Positive lags</div><div class="card-value" id="s-poslags">0</div></div>
        <div class="dbg-card"><div class="dbg-card-label">WS binary</div>    <div class="card-value" id="s-msg-binary">0</div></div>
        <div class="dbg-card"><div class="dbg-card-label">WS json/text</div> <div class="card-value" id="s-msg-json">0</div></div>
        <div class="dbg-card"><div class="dbg-card-label">WS other</div>     <div class="card-value" id="s-msg-other">0</div></div>
      </div>

      <!-- CURRENT PHRASE -->
      <div id="phrase-bar">Waiting for phrases…</div>

      <!-- TRANSCRIPT -->
      <details id="transcript-section" open>
        <summary>
          <span>Transcript — <span id="transcript-count">0 phrases</span></span>
          <span>(only phrases received while connected)</span>
        </summary>
        <div class="transcript-actions">
          <button id="copy-transcript">Copy as text</button>
          <button id="copy-csv">Copy as CSV</button>
          <button id="dl-transcript-en" disabled>↓ EN transcript</button>
          <button id="dl-transcript-de" disabled>↓ DE transcript</button>
        </div>
        <div class="transcript-wrap">
          <table>
            <thead>
              <tr>
                <th class="str">#</th>
                <th class="str">DE (raw)</th>
                <th class="str">DE (clean)</th>
                <th class="str">EN</th>
              </tr>
            </thead>
            <tbody id="transcript-body"></tbody>
          </table>
        </div>
      </details>

      <!-- CHUNK LOG -->
      <div class="dbg-section">
        <div class="dbg-section-label">Chunk Log</div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th class="str">#</th>
                <th>Arr +ms</th>
                <th>Gap ms</th>
                <th>Bytes</th>
                <th class="str">Decode</th>
                <th>Dur ms</th>
                <th>Sched lag ms</th>
                <th>CtxTime s</th>
                <th>DecTime ms</th>
              </tr>
            </thead>
            <tbody id="log-body"></tbody>
          </table>
          <div class="table-note">
            Sched lag = audioCtx.currentTime − nextPlayTime at schedule time. Negative = buffer ahead of playback (good). Positive = gap in audio.
          </div>
        </div>
      </div>

    </div><!-- /.dbg-content -->
  </div><!-- /#tab-debug -->
```

- [ ] **Step 5: Add debug.js script tag**

In `operator/index.html`, find the closing script tags:

```html
  <script src="config.js"></script>
  <script src="qrcode.min.js"></script>
  <script src="app.js"></script>
```

Add `debug.js` after `app.js`:

```html
  <script src="config.js"></script>
  <script src="qrcode.min.js"></script>
  <script src="app.js"></script>
  <script src="debug.js"></script>
```

- [ ] **Step 6: Remove the debug-link anchor from the session panel**

Find in the `<!-- LEFT: Session info -->` aside:

```html
        <a id="debug-link" href="/listen/debug.html" target="_blank">Open debug page</a>
```

Delete this line.

- [ ] **Step 7: Commit**

```bash
git add operator/index.html
git commit -m "feat: add debug tab to operator UI with tab navigation"
```

---

### Task 4: Update operator/app.js — remove debugLinkEl, add tab switching

**Files:**
- Modify: `operator/app.js`

- [ ] **Step 1: Remove the debugLinkEl DOM ref (line 20)**

Find:
```js
  const debugLinkEl    = document.getElementById('debug-link');
```
Delete this line.

- [ ] **Step 2: Remove debugLinkEl usage in startSession (around line 219)**

Find:
```js
        debugLinkEl.href = `${backendHttp}/listen/debug.html?session=${session_id}`;
```
Delete this line.

- [ ] **Step 3: Remove debugLinkEl usage in the WebSocket onmessage handler (around line 351)**

Find:
```js
          debugLinkEl.href = `${backendHttp}/listen/debug.html?session=${msg.session_id}`;
```
Delete this line.

- [ ] **Step 4: Add tab-switching event listener**

At the end of `operator/app.js`, inside the outer IIFE and before the closing `})();`, add:

```js
  // ── Tab navigation ─────────────────────────────────────────────────────────
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.tab;
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b === btn));
      document.querySelectorAll('.tab-panel').forEach(p => { p.hidden = p.id !== 'tab-' + tab; });
    });
  });
```

- [ ] **Step 5: Commit**

```bash
git add operator/app.js
git commit -m "feat: remove debug-link ref, wire up tab navigation in operator"
```

---

### Task 5: Delete listener/debug.html and listener/debug.js

**Files:**
- Delete: `listener/debug.html`
- Delete: `listener/debug.js`

- [ ] **Step 1: Remove the files**

```bash
git rm listener/debug.html listener/debug.js
```

- [ ] **Step 2: Commit**

```bash
git commit -m "chore: remove standalone debug page — moved into operator tab"
```

---

### Task 6: Manual verification

No automated tests for frontend layout — verify manually by opening the operator in a browser.

- [ ] **Step 1: Serve the operator**

```bash
cd /home/chris/gibberly
python3 -m http.server 5501 --directory operator
```

Open `http://localhost:5501` in a browser.

- [ ] **Step 2: Verify tab nav appears**

The header should show two small pill buttons at the right: **Operator** (active, amber) and **Debug** (dim).

- [ ] **Step 3: Verify Operator tab content is unchanged**

The operator view (teleprompter, controls, QR area, Start/Stop footer) should look exactly as before. The "Open debug page" link should be gone from the session panel.

- [ ] **Step 4: Click Debug tab**

The operator content should disappear (Start button, teleprompter, etc.). The debug panel should appear with the controls bar, summary cards, phrase bar, and log table.

- [ ] **Step 5: Verify no console errors on tab switch**

Open browser DevTools → Console. Switch between tabs. There should be no JS errors.

- [ ] **Step 6: Click Operator tab**

The operator view should return. Status and session state should be unaffected.

- [ ] **Step 7: Verify debug.js loads**

In DevTools → Network, confirm `debug.js` loaded with 200.

- [ ] **Step 8: Commit clean state if any fixups were needed**

```bash
git status
# if any untracked fixes:
git add -p
git commit -m "fix: <describe any fixup>"
```
