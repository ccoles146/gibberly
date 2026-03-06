# Option C Prototype Design — Live Sermon Translation

**Date**: 2026-03-06
**Status**: Approved
**Scope**: MVP Python prototype (Approach A — local backend + real Azure SDK)

---

## Architecture

```
[Console - Python]──WebSocket──▶[FastAPI Backend - Linux]──▶[Azure Speech Translation]
                                        │                              │
                                        │                    translated text
                                        │                              ▼
                                        │                    [Azure TTS]
                                        │                              │
                                        │                    synthesised audio
                                        ▼                              ▼
                               [Azure Web PubSub]◀──────────────────────
                                        │
                                        ▼
                              [Listener Browser]
```

---

## Directory Structure

```
gibberly/
├── backend/
│   ├── main.py           # FastAPI + WebSocket endpoint
│   ├── translation.py    # Azure Speech Translation (continuous)
│   ├── tts.py            # Azure TTS → audio bytes
│   ├── pubsub.py         # Web PubSub publisher
│   └── requirements.txt
├── console/
│   ├── main.py           # CLI: device select, start/stop, QR, status
│   ├── audio.py          # sounddevice (mic) or file playback
│   └── requirements.txt
├── listener/
│   ├── index.html        # Static page
│   └── app.js            # Web Audio API + PubSub WebSocket
├── docs/
│   ├── Live_Sermon_Translation_PRD.md
│   ├── azure-setup.md    # Step-by-step provisioning guide
│   └── 2026-03-06-option-c-prototype-design.md
├── .env.example
└── README.md
```

---

## Data Flow

1. Console captures 100ms PCM chunks (16kHz, 16-bit mono) from mic or file
2. Streams chunks over WebSocket to FastAPI backend
3. Backend feeds audio into Azure Speech Translation SDK (continuous recognition, `de-DE → en`)
4. On each translated segment → Azure TTS (`en-US-JennyNeural`) → audio bytes
5. Backend publishes bytes to Web PubSub group keyed by session UUID
6. Listener browser receives binary frames → Web Audio API → plays translated audio

---

## Key Decisions

| Decision | Choice | Reason |
|---|---|---|
| Backend framework | FastAPI + WebSocket | Lightweight, async, easy WebSocket support |
| Session identity | UUID at backend startup | Simple, URL-safe, unique per service |
| Listener page hosting | Served by FastAPI (static mount) | No separate static host needed for prototype |
| Console UI | CLI only (terminal output + ASCII QR) | Option C is non-production; GUI is Electron phase |
| Config | `.env` file | Azure Speech key/region + Web PubSub connection string |
| Audio format | 16kHz, 16-bit mono PCM, 100ms chunks | Matches PRD spec and Azure Speech SDK requirements |
| TTS voice | `en-US-JennyNeural` | Natural, low-latency neural voice |

---

## Azure Resources Required

| Resource | Tier | Purpose |
|---|---|---|
| Azure Speech | S0 | STT + translation (de-DE → en) |
| Azure Web PubSub | Free | Audio relay to listeners |

Provisioning instructions: `docs/azure-setup.md`

---

## Out of Scope (Option C)

- Electron operator console (production phase)
- Azure Function App / Container App deployment (production phase)
- Azure Static Web Apps hosting (production phase)
- Multiple languages, captions, recording
