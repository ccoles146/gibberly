# Audio-Text Sync + Late-Join Transcript Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver translated text and TTS audio together (text no longer races ahead of audio), trickle text at the spoken word rate, let late joiners see all prior phrases, and keep the reading pane intact after the stream stops.

**Architecture:**
1. **Backend publish order:** When audio listeners are present the session synthesises TTS first, then publishes phrase JSON (tagged `phrase_id = chunk_num`) followed immediately by `audio_start` JSON + audio bytes — so both arrive at the listener within milliseconds of each other. When no audio listeners are present the phrase is published immediately as before. On TTS failure the phrase is published without `phrase_id` so the listener trickles immediately.
2. **Backend transcript:** `SessionHandler` accumulates translated text per language in `_transcript`. A new `GET /session/{id}/transcript?lang=X` endpoint serves the history. `stop()` clears it.
3. **Listener sync:** Phrases with a `phrase_id` are buffered. When the matching audio arrives it is decoded; the word trickle starts at `audioBuffer.duration / wordCount` ms per word — exactly matching the spoken rate. Phrases without `phrase_id` (no-audio or fallback) trickle at the existing adaptive rate.
4. **Listener late-join + persistent pane:** On successful WebSocket open the listener fetches the transcript and displays all historical phrases instantly (no trickle). The reading pane is only cleared when connecting to a *new* session; it stays visible after disconnect or stream end so the download button keeps working.
5. **Screen-lock resilience:** iOS/Android throttle `setTimeout` in hidden tabs (~1/min), so the word queue fills up while locked but doesn't drain. On page becoming visible again: (a) if the audio context has a backlog >2 s, it is closed and recreated so the next chunk plays from "now" (discards stale scheduled buffers); (b) `flushPendingState()` immediately renders all queued text to DOM; (c) the backend transcript endpoint is queried and any phrases missed by the WebSocket are shown via `showHistoricalPhrases()`. Audio delivery while locked relies on the existing `<audio>` element MediaStream routing (media-session API keeps iOS audio alive in the background).

**Tech Stack:** Python 3.13 / FastAPI (`backend/session.py`, `backend/pubsub.py`, `backend/main.py`); vanilla JS (`listener/app.js`); pytest; Azure Web PubSub.

**Status:** Implemented - testing

---

## File Map

| File | What changes |
|---|---|
| `backend/pubsub.py` | Add optional `phrase_id` to `publish_phrase()`; add `publish_audio_start()`; add `publish_audio_sequence()` |
| `backend/session.py` | `phrase_id = str(chunk_num)`; reorder audio-active path (synthesise → publish phrase + audio); TTS-failure fallback; `_transcript` dict; `get_transcript()`; `stop()` clears transcript |
| `backend/main.py` | Add `GET /session/{id}/transcript?lang=X` endpoint |
| `listener/app.js` | `pendingPhrases` + `pendingAudioPhrase` state; `getItemDelay()` helper; refactor `tick` out of `startTick` closure; `playAudioSynced()`; `audio_start` message handler; buffer phrases with `phrase_id`; `showHistoricalPhrases()`; `flushPendingState()`; `clearQueueState()` (replaces `clearReadingPane()` on disconnect); clear pane only in `ws.onopen` on new session; async `ws.onopen` fetches transcript; updated `visibilitychange` handler (audio backlog reset + text flush + transcript delta) |
| `tests/backend/test_pubsub.py` | Tests for `publish_phrase` with/without `phrase_id`; `publish_audio_start`; `publish_audio_sequence` |
| `tests/backend/test_session.py` | Update existing audio test; add: synthesise-before-publish order; `publish_audio_sequence` called; TTS-error fallback; transcript storage; `stop()` clears transcript |
| `tests/backend/test_main.py` | Add transcript endpoint test |

---

## Task 1: `backend/pubsub.py` — phrase_id + audio_start + audio_sequence

**Files:**
- Modify: `backend/pubsub.py`
- Modify: `tests/backend/test_pubsub.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/backend/test_pubsub.py`:

```python
@patch("backend.pubsub.WebPubSubServiceClient")
def test_publish_phrase_includes_phrase_id_when_provided(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.from_connection_string.return_value = mock_client

    from backend.pubsub import PubSubPublisher
    publisher = PubSubPublisher("Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;")
    publisher.publish_phrase("s1", "en", "Gott ist gut.", "God is good.", phrase_id="42")

    payload = json.loads(mock_client.send_to_group.call_args[0][1])
    assert payload["phrase_id"] == "42"


@patch("backend.pubsub.WebPubSubServiceClient")
def test_publish_phrase_omits_phrase_id_when_not_provided(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.from_connection_string.return_value = mock_client

    from backend.pubsub import PubSubPublisher
    publisher = PubSubPublisher("Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;")
    publisher.publish_phrase("s1", "en", "Gott ist gut.", "God is good.")

    payload = json.loads(mock_client.send_to_group.call_args[0][1])
    assert "phrase_id" not in payload


@patch("backend.pubsub.WebPubSubServiceClient")
def test_publish_audio_start_sends_correct_json(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.from_connection_string.return_value = mock_client

    from backend.pubsub import PubSubPublisher
    publisher = PubSubPublisher("Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;")
    publisher.publish_audio_start("s1", "en", "7", 4)

    mock_client.send_to_group.assert_called_once()
    args = mock_client.send_to_group.call_args
    assert args[0][0] == "session-s1-en"
    payload = json.loads(args[0][1])
    assert payload == {"type": "audio_start", "phrase_id": "7", "word_count": 4}
    assert args[1]["content_type"] == "application/json"


@patch("backend.pubsub.WebPubSubServiceClient")
def test_publish_audio_sequence_sends_audio_start_then_audio(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.from_connection_string.return_value = mock_client

    from backend.pubsub import PubSubPublisher
    publisher = PubSubPublisher("Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;")
    publisher.publish_audio_sequence("s1", "en", "7", 3, [b"\x01\x02\x03"])

    assert mock_client.send_to_group.call_count == 2
    first, second = mock_client.send_to_group.call_args_list

    first_payload = json.loads(first[0][1])
    assert first_payload["type"] == "audio_start"
    assert first_payload["phrase_id"] == "7"
    assert first_payload["word_count"] == 3

    assert second[0][1] == b"\x01\x02\x03"
    assert second[1]["content_type"] == "application/octet-stream"
```

- [ ] **Step 2: Run tests to confirm they fail**

```
cd ~/gibberly && source .venv/bin/activate && pytest tests/backend/test_pubsub.py::test_publish_phrase_includes_phrase_id_when_provided tests/backend/test_pubsub.py::test_publish_phrase_omits_phrase_id_when_not_provided tests/backend/test_pubsub.py::test_publish_audio_start_sends_correct_json tests/backend/test_pubsub.py::test_publish_audio_sequence_sends_audio_start_then_audio -v
```

Expected: 4 failures (TypeError / AttributeError).

- [ ] **Step 3: Implement in `backend/pubsub.py`**

Replace `publish_phrase` with:

```python
def publish_phrase(self, session_id: str, lang: str, clean_src: str, text: str, phrase_id: Optional[str] = None) -> None:
    group = f"session-{session_id}-{lang}"
    payload_dict: dict = {"type": "phrase", "clean_src": clean_src, "text": text}
    if phrase_id:
        payload_dict["phrase_id"] = phrase_id
    payload = json.dumps(payload_dict)
    t0 = time.monotonic()
    try:
        self._client.send_to_group(group, payload, content_type="application/json")
        elapsed_ms = (time.monotonic() - t0) * 1000
        log.info(
            "PubSub phrase — group=%s phrase_id=%s %.0fms: %r",
            group, phrase_id or "none", elapsed_ms, text[:80],
        )
    except Exception as exc:
        elapsed_ms = (time.monotonic() - t0) * 1000
        log.error("PubSub phrase publish FAILED — group=%s %.0fms: %s", group, elapsed_ms, exc)
        raise
```

Add after `publish_phrase`:

```python
def publish_audio_start(self, session_id: str, lang: str, phrase_id: str, word_count: int) -> None:
    group = f"session-{session_id}-{lang}"
    payload = json.dumps({"type": "audio_start", "phrase_id": phrase_id, "word_count": word_count})
    t0 = time.monotonic()
    try:
        self._client.send_to_group(group, payload, content_type="application/json")
        elapsed_ms = (time.monotonic() - t0) * 1000
        log.debug(
            "PubSub audio_start — group=%s phrase_id=%s words=%d %.0fms",
            group, phrase_id, word_count, elapsed_ms,
        )
    except Exception as exc:
        elapsed_ms = (time.monotonic() - t0) * 1000
        log.error("PubSub audio_start FAILED — group=%s %.0fms: %s", group, elapsed_ms, exc)
        raise

def publish_audio_sequence(self, session_id: str, lang: str, phrase_id: str, word_count: int, audio_chunks: list[bytes]) -> None:
    """Publish audio_start JSON then each audio binary chunk in one synchronous call (guarantees ordering)."""
    self.publish_audio_start(session_id, lang, phrase_id, word_count)
    for chunk in audio_chunks:
        self.publish_audio(session_id, lang, chunk)
```

- [ ] **Step 4: Run all pubsub tests**

```
cd ~/gibberly && source .venv/bin/activate && pytest tests/backend/test_pubsub.py -v
```

Expected: all 9 pass.

- [ ] **Step 5: Commit**

```bash
git add backend/pubsub.py tests/backend/test_pubsub.py
git commit -m "feat: add phrase_id to publish_phrase and audio_start/sequence to PubSubPublisher"
```

---

## Task 2: `backend/session.py` — reorder, phrase_id, transcript

**Files:**
- Modify: `backend/session.py`
- Modify: `tests/backend/test_session.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/backend/test_session.py`:

```python
@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_process_chunk_synthesizes_before_publishing_phrase_when_audio_active(
    mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class
):
    """With audio listeners, TTS synthesis must complete before phrase is published."""
    mock_pub = MagicMock()
    mock_pub_class.return_value = mock_pub
    mock_pub.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()
    mock_llm = MagicMock()
    mock_llm_class.return_value = mock_llm
    mock_llm.translate = AsyncMock(return_value={"clean_src": "Gut.", "en_text": "Good."})

    call_order = []

    def fake_synthesize(text, on_chunk, tone="calm"):
        call_order.append("synthesize")
        on_chunk(b"\x01\x02")

    def fake_publish_phrase(*args, **kwargs):
        call_order.append("publish_phrase")

    mock_tts = MagicMock()
    mock_tts.synthesize.side_effect = fake_synthesize
    mock_tts_class.return_value = mock_tts
    mock_pub.publish_phrase.side_effect = fake_publish_phrase

    loop = asyncio.new_event_loop()
    handler = _make_handler(loop)
    handler.audio_join("en")
    loop.run_until_complete(handler._process_chunk("Gut."))

    assert call_order.index("synthesize") < call_order.index("publish_phrase"), \
        "TTS must run before phrase is published so text and audio arrive together"
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_process_chunk_calls_publish_audio_sequence_when_audio_active(
    mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class
):
    """With audio listeners, publish_audio_sequence must be called with the collected bytes."""
    mock_pub = MagicMock()
    mock_pub_class.return_value = mock_pub
    mock_pub.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()
    mock_llm = MagicMock()
    mock_llm_class.return_value = mock_llm
    mock_llm.translate = AsyncMock(return_value={"clean_src": "Gut.", "en_text": "Good."})

    def fake_synthesize(text, on_chunk, tone="calm"):
        on_chunk(b"\x01\x02")

    mock_tts = MagicMock()
    mock_tts.synthesize.side_effect = fake_synthesize
    mock_tts_class.return_value = mock_tts

    loop = asyncio.new_event_loop()
    handler = _make_handler(loop)
    handler.audio_join("en")
    loop.run_until_complete(handler._process_chunk("Gut."))

    mock_pub.publish_audio_sequence.assert_called_once()
    _session_id, lang, phrase_id, word_count, chunks = mock_pub.publish_audio_sequence.call_args[0]
    assert lang == "en"
    assert chunks == [b"\x01\x02"]
    assert phrase_id == "1"   # first chunk == chunk_num 1
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_process_chunk_publishes_phrase_without_phrase_id_on_tts_error(
    mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class
):
    """When TTS fails, phrase is published without phrase_id (listener trickles immediately)."""
    mock_pub = MagicMock()
    mock_pub_class.return_value = mock_pub
    mock_pub.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()
    mock_llm = MagicMock()
    mock_llm_class.return_value = mock_llm
    mock_llm.translate = AsyncMock(return_value={"clean_src": "Gut.", "en_text": "Good."})

    mock_tts = MagicMock()
    mock_tts.synthesize.side_effect = RuntimeError("TTS unavailable")
    mock_tts_class.return_value = mock_tts

    statuses = []
    loop = asyncio.new_event_loop()

    async def capture_status(msg):
        statuses.append(msg)

    handler = _make_handler(loop, on_status=capture_status)
    handler.audio_join("en")
    loop.run_until_complete(handler._process_chunk("Gut."))

    mock_pub.publish_phrase.assert_called_once()
    assert not mock_pub.publish_phrase.call_args.kwargs.get("phrase_id"), \
        "fallback phrase must not carry a phrase_id"
    mock_pub.publish_audio_sequence.assert_not_called()
    assert any(m.get("type") == "tts_error" for m in statuses)
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_process_chunk_stores_translated_text_in_transcript(
    mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class
):
    mock_pub = MagicMock()
    mock_pub_class.return_value = mock_pub
    mock_pub.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()
    mock_llm = MagicMock()
    mock_llm_class.return_value = mock_llm
    mock_llm.translate = AsyncMock(return_value={"clean_src": "Gott ist gut.", "en_text": "God is good."})
    mock_tts_class.return_value = MagicMock()

    loop = asyncio.new_event_loop()
    handler = _make_handler(loop)
    loop.run_until_complete(handler._process_chunk("Gott ist gut."))

    assert handler.get_transcript("en") == ["God is good."]
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_stop_clears_transcript(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub = MagicMock()
    mock_pub_class.return_value = mock_pub
    mock_pub.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()
    mock_llm_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()

    loop = asyncio.new_event_loop()
    handler = _make_handler(loop)
    handler._transcript["en"] = ["God is good."]
    handler.stop()

    assert handler.get_transcript("en") == []
    loop.close()
```

- [ ] **Step 2: Run tests to confirm they fail**

```
cd ~/gibberly && source .venv/bin/activate && pytest tests/backend/test_session.py::test_process_chunk_synthesizes_before_publishing_phrase_when_audio_active tests/backend/test_session.py::test_process_chunk_calls_publish_audio_sequence_when_audio_active tests/backend/test_session.py::test_process_chunk_publishes_phrase_without_phrase_id_on_tts_error tests/backend/test_session.py::test_process_chunk_stores_translated_text_in_transcript tests/backend/test_session.py::test_stop_clears_transcript -v
```

Expected: 5 failures.

- [ ] **Step 3: Add `_transcript` state and `get_transcript()` to `SessionHandler.__init__` and class**

In `__init__`, after `self._stopped = False` (around line 52), add:

```python
        self._transcript: dict[str, list[str]] = {}
```

Add `get_transcript` method after `_publish_phrase_fallback` (will be added in next step):

```python
    def get_transcript(self, lang: str) -> list[str]:
        return list(self._transcript.get(lang, []))
```

In `stop()`, after `self._stopped = True`, add:

```python
        self._transcript.clear()
```

- [ ] **Step 4: Rewrite the `_process_chunk` per-language block**

Replace `tone = result.get("tone", "calm")` through the end of the `async with self._tts_lock:` block (lines 174–241 in the current file) with:

```python
        tone = result.get("tone", "calm")
        loop = asyncio.get_running_loop()

        async with self._tts_lock:
            for lang in self._target_languages:
                lang_code = lang["code"]
                text = result.get(lang["llm_key"], "")
                if not text:
                    log.debug(
                        "Session %s — chunk #%d no translation for lang=%s",
                        self.session_id, chunk_num, lang_code,
                    )
                    continue

                self._transcript.setdefault(lang_code, []).append(text)
                audio_listeners = self.audio_active_count.get(lang_code, 0)

                if audio_listeners > 0:
                    tts = self._tts[lang_code]
                    audio_chunks: list[bytes] = []

                    def collect_chunk(audio_bytes: bytes) -> None:
                        audio_chunks.append(audio_bytes)

                    try:
                        await asyncio.wait_for(
                            loop.run_in_executor(
                                None,
                                lambda t=text, s=tts, oc=collect_chunk, tn=tone: s.synthesize(t, oc, tone=tn),
                            ),
                            timeout=15.0,
                        )
                    except asyncio.TimeoutError:
                        log.error(
                            "Session %s — chunk #%d TTS TIMED OUT lang=%s after 15s — "
                            "publishing phrase without phrase_id as fallback",
                            self.session_id, chunk_num, lang_code,
                        )
                        await self._publish_phrase_fallback(loop, lang_code, clean_src, text, chunk_num)
                        continue
                    except Exception as exc:
                        log.error(
                            "Session %s — chunk #%d TTS failed lang=%s: %s",
                            self.session_id, chunk_num, lang_code, exc,
                        )
                        await self._send_status({"type": "tts_error", "error": str(exc)})
                        await self._publish_phrase_fallback(loop, lang_code, clean_src, text, chunk_num)
                        continue

                    log.debug(
                        "Session %s — chunk #%d publishing synced phrase+audio lang=%s phrase_id=%s",
                        self.session_id, chunk_num, lang_code, phrase_id,
                    )
                    try:
                        await asyncio.wait_for(
                            loop.run_in_executor(
                                None,
                                lambda lc=lang_code, cs=clean_src, t=text, pid=phrase_id: (
                                    self._publisher.publish_phrase(self.session_id, lc, cs, t, phrase_id=pid)
                                ),
                            ),
                            timeout=5.0,
                        )
                    except asyncio.TimeoutError:
                        log.error(
                            "Session %s — chunk #%d phrase publish TIMED OUT lang=%s after 5s",
                            self.session_id, chunk_num, lang_code,
                        )
                    except Exception as exc:
                        log.error(
                            "Session %s — chunk #%d phrase publish failed lang=%s: %s",
                            self.session_id, chunk_num, lang_code, exc,
                        )

                    word_count = len(text.split())
                    try:
                        await asyncio.wait_for(
                            loop.run_in_executor(
                                None,
                                lambda lc=lang_code, pid=phrase_id, wc=word_count, chunks=list(audio_chunks): (
                                    self._publisher.publish_audio_sequence(
                                        self.session_id, lc, pid, wc, chunks
                                    )
                                ),
                            ),
                            timeout=10.0,
                        )
                    except asyncio.TimeoutError:
                        log.error(
                            "Session %s — chunk #%d audio publish TIMED OUT lang=%s after 10s",
                            self.session_id, chunk_num, lang_code,
                        )
                    except Exception as exc:
                        log.error(
                            "Session %s — chunk #%d audio publish failed lang=%s: %s",
                            self.session_id, chunk_num, lang_code, exc,
                        )

                else:
                    log.debug(
                        "Session %s — chunk #%d TTS skipped lang=%s (no audio listeners)",
                        self.session_id, chunk_num, lang_code,
                    )
                    try:
                        await asyncio.wait_for(
                            loop.run_in_executor(
                                None,
                                lambda lc=lang_code, cs=clean_src, t=text: (
                                    self._publisher.publish_phrase(self.session_id, lc, cs, t)
                                ),
                            ),
                            timeout=5.0,
                        )
                    except asyncio.TimeoutError:
                        log.error(
                            "Session %s — chunk #%d phrase publish TIMED OUT lang=%s after 5s",
                            self.session_id, chunk_num, lang_code,
                        )
                    except Exception as exc:
                        log.error(
                            "Session %s — chunk #%d phrase publish failed lang=%s: %s",
                            self.session_id, chunk_num, lang_code, exc,
                        )
```

- [ ] **Step 5: Add `phrase_id` generation and `_publish_phrase_fallback` helper**

In `_process_chunk`, after `chunk_num = self._chunk_count` (line 138), add:

```python
        phrase_id = str(chunk_num)
```

Add `_publish_phrase_fallback` method after `_send_status`:

```python
    async def _publish_phrase_fallback(
        self,
        loop: asyncio.AbstractEventLoop,
        lang_code: str,
        clean_src: str,
        text: str,
        chunk_num: int,
    ) -> None:
        """Publish phrase without phrase_id so the listener trickles text immediately."""
        try:
            await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda lc=lang_code, cs=clean_src, t=text: (
                        self._publisher.publish_phrase(self.session_id, lc, cs, t)
                    ),
                ),
                timeout=5.0,
            )
        except Exception as exc:
            log.error(
                "Session %s — chunk #%d fallback phrase publish failed lang=%s: %s",
                self.session_id, chunk_num, lang_code, exc,
            )
```

- [ ] **Step 6: Update the existing audio test that checks `publish_audio` directly**

The test `test_process_chunk_synthesizes_when_audio_listener_present` (currently at line 163) checks `mock_pub.publish_audio.assert_called_once_with(...)`. With the reorder, `publish_audio_sequence` is called instead. Replace its assertions with:

```python
    mock_tts.synthesize.assert_called_once()
    mock_pub.publish_audio_sequence.assert_called_once()
    _sid, lang, _pid, _wc, chunks = mock_pub.publish_audio_sequence.call_args[0]
    assert lang == "en"
    assert chunks == [b"\x01\x02"]
```

- [ ] **Step 7: Run all session tests**

```
cd ~/gibberly && source .venv/bin/activate && pytest tests/backend/test_session.py -v
```

Expected: all pass (5 new + updated existing ≈ 15 total).

- [ ] **Step 8: Commit**

```bash
git add backend/session.py tests/backend/test_session.py
git commit -m "feat: synthesise before publish, phrase_id=chunk_num, store transcript per language"
```

---

## Task 3: `backend/main.py` — transcript endpoint

**Files:**
- Modify: `backend/main.py`
- Modify: `tests/backend/test_main.py`

- [ ] **Step 1: Write failing test**

Add to `tests/backend/test_main.py` (check existing fixture/client pattern in that file first):

```python
def test_transcript_endpoint_returns_phrases_for_active_session(client, mock_session):
    mock_session.get_transcript.return_value = ["God is good.", "Jesus loves you."]
    res = client.get(f"/session/{mock_session.session_id}/transcript?lang=en")
    assert res.status_code == 200
    assert res.json() == {"phrases": ["God is good.", "Jesus loves you."]}
    mock_session.get_transcript.assert_called_once_with("en")


def test_transcript_endpoint_returns_404_for_unknown_session(client):
    res = client.get("/session/no-such-id/transcript?lang=en")
    assert res.status_code == 404
```

- [ ] **Step 2: Run tests to confirm they fail**

```
cd ~/gibberly && source .venv/bin/activate && pytest tests/backend/test_main.py::test_transcript_endpoint_returns_phrases_for_active_session tests/backend/test_main.py::test_transcript_endpoint_returns_404_for_unknown_session -v
```

Expected: 2 failures.

- [ ] **Step 3: Add endpoint to `backend/main.py`**

Add after the `GET /session/{session_id}/info` endpoint (after line 81):

```python
@app.get("/session/{session_id}/transcript")
def get_transcript(session_id: str, lang: str = "en"):
    handler = app.state.sessions.get(session_id)
    if not handler:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"phrases": handler.get_transcript(lang)}
```

- [ ] **Step 4: Run tests**

```
cd ~/gibberly && source .venv/bin/activate && pytest tests/backend/test_main.py -v
```

Expected: all pass including the 2 new ones.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py tests/backend/test_main.py
git commit -m "feat: add GET /session/{id}/transcript endpoint for late-join history"
```

---

## Task 4: `listener/app.js` — sync, late-join, persistent pane

**Files:**
- Modify: `listener/app.js`

No automated tests — verify manually using the browser debug panel (`?debug=1` or press `D`).

- [ ] **Step 1: Add new state variables**

After `let placeholderEl = ...` (around line 140), add:

```js
  const pendingPhrases    = new Map();  // phrase_id → { words: string[], text: string }
  let   pendingAudioPhrase = null;      // { phrase_id, word_count } from audio_start message
  let   displayedSession   = null;      // session id currently shown in the reading pane
```

- [ ] **Step 2: Add `clearQueueState()` helper**

Add after `clearReadingPane()`:

```js
  function clearQueueState() {
    wordQueue = [];
    if (tickTimer !== null) { clearTimeout(tickTimer); tickTimer = null; }
    pendingPhrases.clear();
    pendingAudioPhrase = null;
    phraseHistory.length = 0;
  }
```

- [ ] **Step 3: Add `showHistoricalPhrases()` helper**

Add after `clearQueueState()`:

```js
  function showHistoricalPhrases(phraseList) {
    if (!phraseList.length) return;
    if (placeholderEl) { placeholderEl.remove(); placeholderEl = null; }
    phraseList.forEach(text => {
      const words = text.trim().split(/\s+/).filter(Boolean);
      if (!words.length) return;
      phrases.push(text);
      const p = document.createElement('p');
      p.className = 'reading-line';
      p.textContent = words.join(' ');
      readingInnerEl.appendChild(p);
      lineElements.push(p);
      if (lineElements.length > MAX_LINES) lineElements.shift().remove();
    });
    isFirstPhrase = false;
    currentLineEl = lineElements[lineElements.length - 1] || null;
    dlTranscriptBtn.disabled = false;
    scrollToBottom(false);
  }
```

- [ ] **Step 4: Add `getItemDelay` helper and refactor `tick` + `startTick`**

Replace the entire `startTick` function (the one that starts with `function startTick()`) with:

```js
  function getItemDelay(item) {
    return (item && item.delay !== undefined) ? item.delay : getTrickleInterval();
  }

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
      tickTimer = setTimeout(tick, getItemDelay(wordQueue[0]));
    } else {
      tickTimer = null;
      dbgUpdateStats();
    }
  }

  function startTick() {
    if (tickTimer !== null) return;
    if (wordQueue.length > 0) {
      tickTimer = setTimeout(tick, getItemDelay(wordQueue[0]));
    }
  }
```

- [ ] **Step 5: Add `playAudioSynced` function**

Add immediately after the existing `playAudio` function:

```js
  async function playAudioSynced(arrayBuffer, phraseId, wordCount) {
    const pending = pendingPhrases.get(phraseId);
    pendingPhrases.delete(phraseId);

    if (!audioCtx) {
      if (pending) onPhrase(pending.text);
      return;
    }

    let audioBuffer;
    try {
      audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
    } catch (e) {
      console.warn('[gibberly] audio decode error:', e.message);
      if (pending) onPhrase(pending.text);
      return;
    }

    const src     = audioCtx.createBufferSource();
    src.buffer    = audioBuffer;
    src.connect(mediaStreamDest || audioCtx.destination);
    const now     = audioCtx.currentTime;
    const startAt = Math.max(now, nextPlayTime);
    src.start(startAt);
    nextPlayTime  = startAt + audioBuffer.duration;

    if (!pending) return;
    const { words, text } = pending;
    const msPerWord = words.length > 0
      ? (audioBuffer.duration * 1000) / words.length
      : getTrickleInterval();

    phraseHistory.push({ ts: Date.now(), count: words.length });

    if (!isFirstPhrase) {
      wordQueue.push({ newLine: true, delay: 0 });
    }
    isFirstPhrase = false;
    words.forEach(w => wordQueue.push({ word: w, delay: msPerWord }));
    addPhrase(text);
    startTick();
  }
```

- [ ] **Step 6: Replace `clearReadingPane()` call in `setConnected(false)` with `clearQueueState()`**

In `setConnected`, replace:

```js
    clearReadingPane();
```

with:

```js
    clearQueueState();
```

- [ ] **Step 7: Update `ws.onmessage` — binary handler uses `playAudioSynced`**

Replace the binary handling block:

```js
      if (msg.type === 'message' && msg.dataType === 'binary') {
        const buf = base64ToArrayBuffer(msg.data);
        if (debugVisible) console.debug(`audio bytes: ${buf.byteLength} | ctx: ${audioCtx?.state}`);
        if (audioActive && pendingAudioPhrase) {
          const { phrase_id, word_count } = pendingAudioPhrase;
          pendingAudioPhrase = null;
          playAudioSynced(buf, phrase_id, word_count);
        } else {
          playAudio(buf);
        }
      }
```

- [ ] **Step 8: Update `ws.onmessage` — JSON handlers for `phrase` and `audio_start`**

Replace the `} else if (d?.type === 'phrase') {` branch (and add `audio_start`). The full if/else-if chain inside the JSON block becomes:

```js
        if (d?.type === 'close') {
          console.log('[gibberly] received close message from backend — will try to reconnect');
          disconnect('Stream ended — reconnecting…');
          setTimeout(async () => {
            try {
              const res = await fetch('/current-session');
              if (res.ok) {
                const { session_id } = await res.json();
                session = session_id;
                const url = new URL(window.location.href);
                url.searchParams.set('session', session_id);
                window.history.replaceState(null, '', url.toString());
                await loadLanguages();
                connect();
              } else {
                setStatus('Stream ended.');
              }
            } catch {
              setStatus('Stream ended.');
            }
          }, 1500);
        } else if (d?.type === 'phrase') {
          const text = d.text || '';
          if (text) {
            if (d.phrase_id && audioActive) {
              const words = text.trim().split(/\s+/).filter(Boolean);
              pendingPhrases.set(d.phrase_id, { words, text });
            } else {
              onPhrase(text);
            }
          }
        } else if (d?.type === 'audio_start') {
          pendingAudioPhrase = { phrase_id: d.phrase_id, word_count: d.word_count };
        } else if (d?.type === 'paused') {
          pausedPill.style.display = 'block';
        } else if (d?.type === 'resumed') {
          pausedPill.style.display = 'none';
        }
```

- [ ] **Step 9: Make `ws.onopen` async, clear pane on new session, fetch historical transcript**

Replace `ws.onopen = () => {` with `ws.onopen = async () => {`.

At the start of `ws.onopen`, just before `setConnected(true)`, add the new-session clear and the transcript fetch. The full `ws.onopen` becomes:

```js
    ws.onopen = async () => {
      if (session !== displayedSession) {
        clearReadingPane();
        displayedSession = session;
      }
      setConnected(true);
      setStatus('Connected — reading transcript…');
      scrollToBottom(false);
      ws.send(JSON.stringify({ type: 'joinGroup', group: `session-${session}-${chosenLang}` }));

      try {
        const res = await fetch(`/session/${session}/transcript?lang=${chosenLang}`);
        if (res.ok) {
          const { phrases: historical } = await res.json();
          if (historical && historical.length) showHistoricalPhrases(historical);
        }
      } catch { /* best effort */ }

      fetch(`/session/${session}/join?lang=${chosenLang}`, { method: 'POST' }).catch(() => {});
    };
```

- [ ] **Step 10: Add `flushPendingState()` helper**

Add after `showHistoricalPhrases()`:

```js
  function flushPendingState() {
    // Flush any phrases buffered waiting for audio (phrase_id path) and show them immediately
    for (const { words, text } of pendingPhrases.values()) {
      addPhrase(text);
      if (!isFirstPhrase) wordQueue.push({ newLine: true });
      isFirstPhrase = false;
      words.forEach(w => wordQueue.push({ word: w }));
    }
    pendingPhrases.clear();
    pendingAudioPhrase = null;

    // Drain the word queue to DOM all at once (no trickle)
    while (wordQueue.length > 0) {
      const item = wordQueue.shift();
      if (item.newLine) {
        currentLineEl = null;
      } else {
        addWordToLine(item.word);
      }
    }
    if (tickTimer !== null) { clearTimeout(tickTimer); tickTimer = null; }
    if (lineElements.length > 0) scrollToBottom(false);
  }
```

- [ ] **Step 11: Update `visibilitychange` handler for screen-unlock recovery**

Replace the existing `visibilitychange` handler:

```js
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && connected) requestWakeLock();
    if (document.visibilityState === 'visible' && audioActive && audioCtx) {
      audioCtx.resume().catch(() => {});
    }
  });
```

with:

```js
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible') return;

    if (connected) requestWakeLock();

    if (audioActive && audioCtx) {
      // If audio context has a significant backlog (scheduled while tab was hidden),
      // close and recreate it so the next chunk plays from "now" rather than replaying
      // everything that queued up while locked.
      const backlogS = nextPlayTime - audioCtx.currentTime;
      if (backlogS > 2) {
        const oldCtx = audioCtx;
        oldCtx.close().catch(() => {});
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        audioCtx.addEventListener('statechange', () => {
          if (audioCtx && audioCtx.state === 'suspended' && audioActive) {
            audioCtx.resume().catch(() => {});
          }
        });
        mediaStreamDest = audioCtx.createMediaStreamDestination();
        if (audioBypassEl) {
          audioBypassEl.srcObject = mediaStreamDest.stream;
          audioBypassEl.play().catch(() => {});
        }
        nextPlayTime = 0;
      } else {
        audioCtx.resume().catch(() => {});
      }
    }

    if (connected) {
      // Immediately render any text that queued up while setTimeout was throttled
      flushPendingState();
      // Fetch transcript delta for anything the WebSocket may have dropped while backgrounded
      if (session) {
        fetch(`/session/${session}/transcript?lang=${chosenLang}`)
          .then(r => r.ok ? r.json() : null)
          .then(data => {
            if (data?.phrases) {
              const delta = data.phrases.slice(phrases.length);
              if (delta.length) showHistoricalPhrases(delta);
            }
          })
          .catch(() => {});
      }
    }
  });
```

- [ ] **Step 12: Manual verification checklist**

Start backend (`uvicorn backend.main:app --reload`) and open the listener. Test each scenario:

1. **Audio sync:** Enable audio, speak/play audio through the operator. Verify text trickles at the same rate as audio speech — neither racing ahead nor lagging behind.
2. **No-audio:** With audio disabled, verify text trickles immediately as before.
3. **TTS failure simulation:** Temporarily break the TTS endpoint in `.env`, verify text still appears (text-only fallback).
4. **Late join:** Open a second browser tab mid-sermon. Verify all prior phrases appear immediately (no trickle), then live phrases continue from the current point.
5. **Persistent pane:** Stop the session from the operator. Verify the reading pane stays intact. Click "Download transcript" — verify it downloads the full text.
6. **Reconnect clears pane:** Start a new session from the operator. Verify the pane clears and the new session's transcript begins fresh.
7. **Screen lock (iOS):** Lock the screen for 30+ seconds while a session is running with audio enabled. Unlock — verify: (a) audio resumes at the current live position (no burst of old audio); (b) all missed text appears immediately; (c) live trickle resumes normally.
8. **Debug panel (`?debug=1`):** Verify phrase queue (Q) stays at 0 or low when audio is active, confirming buffered phrases are released on audio arrival.

- [ ] **Step 13: Commit**

```bash
git add listener/app.js
git commit -m "feat: audio-paced trickle, late-join transcript, persistent pane, screen-lock recovery"
```

---

## Self-Review

**Spec coverage:**

| Requirement | Task |
|---|---|
| Text and audio delivered together when audio requested | Task 2 (backend reorder) |
| Audio does not lead text by more than a few words | Task 4 (phrases buffered until audio arrives) |
| Text does not lead audio by more than a few words | Task 4 (`playAudioSynced` trickles at `duration/wordCount` ms per word) |
| `phrase_id` is the chunk number | Task 2 (`phrase_id = str(chunk_num)`) |
| No-audio path unchanged | Task 2 (else branch publishes phrase immediately without `phrase_id`) |
| TTS failure still shows text | Task 2 (`_publish_phrase_fallback` on timeout + RuntimeError) |
| `audioCtx` unavailable fallback | Task 4 (`playAudioSynced` guard + `onPhrase` call) |
| Backend stores transcript per language | Task 2 (`_transcript` dict, `get_transcript()`) |
| Transcript cleared on session stop | Task 2 (`stop()` calls `_transcript.clear()`) |
| Late joiners see prior phrases | Tasks 3 + 4 (endpoint + `ws.onopen` fetch + `showHistoricalPhrases`) |
| Reading pane stays after stream stops | Task 4 (`clearQueueState()` instead of `clearReadingPane()` on disconnect) |
| Download transcript works after stream ends | Task 4 (pane + `phrases` array preserved) |
| Pane clears when new session starts | Task 4 (`ws.onopen` clears when `session !== displayedSession`) |
| Existing tests continue to pass | Tasks 1–3 (backward-compatible: `phrase_id` optional; existing `publish_audio` test updated) |
| Audio picks up at live position after screen lock | Task 4 Step 11 (audio context recreated if backlog > 2 s; `nextPlayTime = 0`) |
| All missed text shown after screen unlock | Task 4 Steps 10–11 (`flushPendingState()` + transcript delta fetch) |
| WebSocket-dropped phrases recovered on unlock | Task 4 Step 11 (transcript delta: `data.phrases.slice(phrases.length)`) |

**Placeholder scan:** All steps include complete code. No TBDs.

**Type consistency:**
- `phrase_id`: `str` in Python (`str(chunk_num)`) → `string` in JS (`d.phrase_id`, `pendingAudioPhrase.phrase_id`). ✓
- `word_count`: `int` in Python → `number` in JS (`d.word_count`, `pendingAudioPhrase.word_count`). ✓
- `publish_audio_sequence(session_id, lang, phrase_id, word_count, audio_chunks)` — same signature in `pubsub.py` and call in `session.py`. ✓
- `playAudioSynced(arrayBuffer, phraseId, wordCount)` — matches all call sites. ✓
- `showHistoricalPhrases(phraseList)` — `phraseList` is `string[]`, matches `res.json().phrases`. ✓
