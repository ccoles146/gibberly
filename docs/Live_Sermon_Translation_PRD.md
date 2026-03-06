# Product Requirements Document
## Live Sermon Translation Service
### German → English Real-Time Audio Translation
**MVP Scope — March 2026**

| | |
|---|---|
| **Status** | Draft |
| **Version** | 0.1 |
| **Date** | 6 March 2026 |
| **Platform** | macOS (Mac Mini) |
| **Cloud** | Microsoft Azure |
| **Est. Annual Cost** | $78–$115 (within $2k nonprofit grant) |

---

## 1. Problem Statement

A German-speaking church needs to provide real-time English translation of its weekly sermon to 1–2 listeners who do not speak German. Listeners access the translation on their personal mobile phones over mobile data (there is no public WiFi at the venue).

The church has a Dante audio network feeding a Mac Mini via a virtual sound card. The AV/sound booth operator will start and monitor the system each week. The solution must be low-cost, low-maintenance, and require minimal technical intervention once running.

---

## 2. Goals and Non-Goals

### 2.1 MVP Goals

- Translate a live German audio stream into English in near-real-time (target latency under 5 seconds).
- Deliver translated audio to 1–2 mobile phone listeners over the public internet.
- Provide a simple operator interface: select audio input, start/stop session, display QR code for listeners.
- Run entirely within the Azure $2,000/year nonprofit credit grant.
- Keep the translation pipeline inside Azure's network — the Mac Mini only uploads audio once; it never receives and re-serves translated audio.

### 2.2 Non-Goals (Future Phases)

- Multiple simultaneous target languages.
- On-screen captions or text-based translation.
- Recording or transcription of sermons.
- Support for more than ~10 concurrent listeners.
- Native mobile app (MVP is browser-only).

---

## 3. System Architecture

### 3.1 Design Principle

The Mac Mini uploads raw German audio to Azure exactly once. All translation, speech synthesis, and listener delivery happen inside Azure's network. This avoids double-bandwidth on the church's internet connection and minimises latency.

### 3.2 Components

**Component 1: Operator Console (Mac Mini — Python)**

- Enumerates macOS audio input devices; operator selects the Dante virtual sound card from a dropdown.
- Captures audio (16kHz, 16-bit mono PCM) and streams it to the Azure Function backend via WebSocket.
- Displays a QR code encoding the listener URL for the current session.
- Shows status: connection state, audio level, listener count, elapsed time, last translated phrase.
- Single start/stop button. Designed for a non-technical AV booth operator.

**Component 2: Azure Function Backend (Python)**

A lightweight backend deployed as an Azure Function App (or Azure Container App) that runs the translation pipeline:

- Receives raw German audio from the Mac Mini via WebSocket.
- Feeds it to Azure Speech Translation SDK (`de-DE → en`, continuous recognition mode).
- Sends each translated English text segment to Azure TTS (Neural voice) for audio synthesis.
- Pushes synthesised English audio chunks to connected listeners via Azure Web PubSub.
- All inter-service communication stays inside Azure's network.

**Component 3: Listener Web Page (Static HTML/JS)**

Hosted on Azure Static Web Apps (free tier). The listener scans the QR code, the page connects to Web PubSub, and translated audio plays via the Web Audio API. No app install, no login, no account. A single tap-to-start button handles the iOS autoplay restriction.

---

## 4. Data Flow

1. Dante network delivers German sermon audio to the Mac Mini via the virtual sound card.
2. Python console captures audio and streams PCM chunks over WebSocket to the Azure Function.
3. Azure Function feeds audio into Speech Translation (continuous recognition). Translated text segments are sent to Azure TTS.
4. TTS returns synthesised English audio. The Function pushes it to listeners via Azure Web PubSub.
5. Listener's browser receives audio over Web PubSub WebSocket and plays it through the Web Audio API.

The Mac Mini's internet connection only carries the upstream raw audio (~128kbps). All downstream delivery to listeners is handled by Azure's global edge network.

---

## 5. Azure Services and Cost Estimate

| Service | Purpose | Cost/Session (1hr) | Annual (52 wks) |
|---|---|---|---|
| Speech Translation | German STT + translate | ~$1.00–$1.40 | ~$52–$73 |
| Text-to-Speech (Neural) | English audio synthesis | ~$0.50–$0.80 | ~$26–$42 |
| Web PubSub | Audio relay to listeners | Free tier | $0 |
| Function App | Backend orchestration | Free tier | $0 |
| Static Web Apps | Listener page hosting | Free tier | $0 |
| **TOTAL** | | **~$1.50–$2.20** | **~$78–$115** |

All costs fall within the $2,000/year Azure nonprofit grant, leaving ~$1,900 headroom for future expansion.

---

## 6. Operator Console Specification

### 6.1 Technology and Packaging

The Mac Mini is a production machine with no Python installed and macOS Gatekeeper restrictions on unsigned apps. This rules out simply running a `.py` script and makes packaging a first-class concern. Three approaches are evaluated below, in order of recommendation.

**Option A: Electron app with Node.js (Recommended)**

Build the operator console as an Electron desktop app. Electron bundles Chromium and Node.js into a self-contained `.app`, which can be signed and notarized with an Apple Developer ID ($99/year) so Gatekeeper allows it without any workarounds. The Azure Speech SDK has a JavaScript/Node.js variant, and audio capture can use the Web Audio API or a native Node addon. The GUI is HTML/CSS — trivial to build. Electron apps are straightforward to sign, notarize, and distribute as a `.dmg`.

- **Pros**: No Python dependency. Standard macOS app distribution. Easy to sign and notarize. Rich UI for free.
- **Cons**: Larger bundle size (~150–200MB). Requires familiarity with Node.js/Electron.

**Option B: PyInstaller + Apple Developer signing**

Write the app in Python and bundle it into a standalone `.app` using PyInstaller (which embeds the Python runtime). Then code-sign and notarize it with an Apple Developer ID certificate. This is well-documented but fiddly — PyInstaller apps require specific entitlements (`com.apple.security.cs.allow-unsigned-executable-memory`) and careful signing of all embedded binaries. Once notarized, Gatekeeper accepts it normally.

- **Pros**: Python ecosystem (mature Azure Speech SDK). Smaller bundle (~50–80MB).
- **Cons**: Signing/notarizing PyInstaller bundles is notoriously fragile. Requires an Apple Developer account ($99/year). Ongoing maintenance when dependencies change.

**Option C: Terminal script with Gatekeeper bypass (Testing only)**

For early testing before investing in signing, install Python via Homebrew on the Mac Mini and run the script directly from Terminal. On macOS Sequoia, Gatekeeper can be bypassed per-app via System Settings → Privacy & Security → Allow. This is acceptable for a developer testing locally but not suitable for a production handoff to an AV operator.

- **Pros**: Fastest path to a working prototype. No signing needed.
- **Cons**: Requires Homebrew + Python install on the production Mac. Not operator-friendly. Gatekeeper re-enables itself periodically.

**Recommendation**

For MVP, start with Option C for rapid prototyping and testing, then move to Option A (Electron) for the production operator-facing build. Electron gives the cleanest path to a signed, notarized `.app` that any AV operator can double-click. The Apple Developer Program fee ($99/year) is a worthwhile investment for proper distribution.

### 6.2 Audio Input

On launch, enumerates audio devices via `sounddevice` or `PyAudio`. Operator selects the Dante virtual sound card. Selection persists in a local config file.

### 6.3 Session Controls

- **Start**: begins audio capture, opens WebSocket to Azure, generates session ID and listener URL.
- **Stop**: closes stream and WebSocket, sends close message to listeners.
- **QR Code**: displays large QR code encoding the listener URL. Can be shown on a screen or printed.

### 6.4 Status Panel

- Connection indicator (green/red).
- Audio input level meter.
- Connected listener count.
- Session elapsed time.
- Last translated phrase (sanity check).

### 6.5 Audio Format

16kHz, 16-bit mono PCM. Chunked into ~100ms frames for WebSocket transmission. Continuous stream during session (no silence gating for MVP).

---

## 7. Azure Backend Specification

### 7.1 Deployment

Azure Function App (Python, Consumption plan) with WebSocket trigger. If the ~10 min execution limit on Consumption plan is problematic for a 1-hour sermon, switch to Azure Container Apps (still covered by the grant).

### 7.2 Translation Pipeline

Uses the Azure Speech SDK `SpeechTranslationConfig` with source language `de-DE` and target `en`. Continuous recognition mode produces translated text segments as they are recognised.

Each translated text segment is immediately sent to Azure TTS (e.g. `en-US-JennyNeural` or `en-GB-SoniaNeural`) for synthesis. Streaming synthesis is used to minimise wait time.

### 7.3 Listener Delivery

Synthesised audio is pushed to listeners via Azure Web PubSub. Binary audio messages are published to a group named by the session ID. Only listeners in that session receive the audio.

### 7.4 Session Management

- Unique UUID per session, generated at start.
- Listener URL encodes session ID as query parameter.
- On stop, a close message is sent to all listeners.
- Auto-timeout after 3 hours as a safety net.

---

## 8. Listener Page Specification

Single-page static HTML/JS hosted on Azure Static Web Apps (free tier).

### 8.1 User Flow

1. Scan QR code with phone camera.
2. Browser opens listener page with session ID in URL.
3. Page connects to Azure Web PubSub and joins session group.
4. Tap "Listen" button (required for iOS). Translated English audio plays.

### 8.2 Requirements

- No login, no app install, no account. Scan and listen.
- Works on iOS Safari, Android Chrome, and any modern browser.
- Handles iOS autoplay restriction with a tap-to-start button.
- Minimal UI: status indicator, volume slider, mute button.
- Auto-reconnect on network interruption (brief audio gap is acceptable).

---

## 9. Latency Budget

Target: spoken German word to English audio in the listener's ear in under 5 seconds.

| Stage | Latency | Notes |
|---|---|---|
| Audio capture + upload | 100–300ms | Depends on upload speed |
| Speech Translation (STT + translate) | 500–2000ms | Waits for phrase boundary |
| TTS synthesis | 200–500ms | Neural voice, streaming |
| Web PubSub to listener | 50–200ms | Azure edge |
| Browser audio buffer + playback | 200–500ms | Jitter buffer |
| **TOTAL** | **~1–3.5 seconds** | Well within 5s target |

---

## 10. Prerequisites

### 10.1 Azure

- Register church as Microsoft nonprofit; claim $2,000/year Azure grant.
- Create: Speech resource (S0), Web PubSub (free tier), Function App (Consumption), Static Web App (free).

### 10.2 Mac Mini

- macOS 12+ (no Python required for production Electron build).
- Dante Virtual Soundcard or Dante Via configured to receive the audio feed.
- Stable internet (128kbps upload minimum for 16kHz mono audio).
- For prototyping only: Homebrew + Python 3.11+ (can be removed after Electron migration).

### 10.3 Developer Machine

- Apple Developer Program membership ($99/year) for code signing and notarization.
- Node.js 18+ and Electron tooling for building the `.app` bundle.
- Access to the Mac Mini (or equivalent macOS hardware) for testing audio device enumeration.

### 10.4 Listener Devices

- Any smartphone with camera and modern browser.
- Mobile data connection.
- Earphones recommended in-venue.

---

## 11. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Function cold start latency | High | Pre-warm with a ping before the service. Use Always On or Container Apps if needed. |
| German theological vocabulary not recognised | Medium | Test with sample sermons. Azure Custom Speech models available if accuracy is poor. |
| Mac Mini internet drops mid-service | High | Auto-reconnect in the Python app. Consider 4G/5G failover dongle. |
| iOS autoplay blocks audio | Low | Tap-to-start button satisfies user gesture requirement. |
| Function 10-min timeout on Consumption plan | Medium | Switch to Container Apps or Premium plan (still within grant budget). |
| Azure nonprofit grant not approved | Low | Total cost is ~$100–$200/year even without the grant. |

---

## 12. Future Enhancements

- **Multi-language**: language selector on listener page, parallel translation pipelines.
- **Caption mode**: translated text as on-screen subtitles alongside or instead of audio.
- **Sermon archive**: store translated text for newsletters or later distribution.
- **Custom speech model**: train on German theological vocabulary for higher accuracy.
- **Analytics**: track weekly listener count and usage for reporting.
- **Public WiFi**: add local fallback path for lower latency if WiFi is added.

---

## 13. Development Estimate

| Task | Hours | Notes |
|---|---|---|
| Azure setup + nonprofit registration | 2–4 | One-time. |
| Prototype operator console (Python) | 10–14 | Rapid prototyping. Audio capture, WebSocket, basic UI. |
| Azure Function backend | 10–16 | Translation pipeline + Web PubSub integration. |
| Listener web page | 6–8 | Static HTML/JS + Web Audio. Cross-browser testing. |
| Electron migration + signing/notarization | 8–12 | Rewrite console as Electron app. Sign and notarize. |
| End-to-end testing with Dante audio | 4–8 | On-site with live sermon. |
| Documentation + operator guide | 2–4 | Runbook for AV operator. |
| **TOTAL** | **42–66 hrs** | ~2–3 weeks focused dev. |

---

## 14. Success Criteria

- Listener scans QR code and hears translated English audio within 5 seconds of the German original, for a full 1-hour sermon without interruption.
- AV operator starts/stops with a single click; no technical knowledge needed beyond selecting the audio input.
- Monthly Azure cost stays under $15 (within the $2,000 annual grant).
- System runs reliably for 4 consecutive weekly services before being deemed production-ready.
