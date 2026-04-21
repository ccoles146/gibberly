/**
 * gibberly-resampler AudioWorklet processor.
 *
 * Accepts audio at the browser's native sample rate, selects a channel,
 * resamples to 16000 Hz using linear interpolation, accumulates samples,
 * and posts a 320-sample Int16Array (20 ms) to the main thread each tick.
 *
 * Constructor options:
 *   channelMode: "left" | "right" | "mix"  (default: "left")
 */
class GibberlyResampler extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this._channelMode = (options.processorOptions || {}).channelMode || "left";
    this._targetRate = 16000;
    this._accumulator = [];   // float samples waiting to be posted
    this._phase = 0;          // fractional position in the input stream
    this._prevSample = 0;     // last sample from previous block (for interpolation)
    this._levelCounter  = 0;
    this._levelInterval = 20;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;

    // Select / mix channels
    let mono;
    if (this._channelMode === "mix" && input.length >= 2) {
      const l = input[0], r = input[1];
      mono = new Float32Array(l.length);
      for (let i = 0; i < l.length; i++) mono[i] = (l[i] + r[i]) * 0.5;
    } else if (this._channelMode === "right" && input.length >= 2) {
      mono = input[1];
    } else {
      mono = input[0];
    }

    // Linear interpolation resample: native rate → 16000 Hz
    const ratio = sampleRate / this._targetRate;  // sampleRate is global in AudioWorklet
    let phase = this._phase;
    let prev = this._prevSample;

    while (phase < mono.length) {
      const idx = Math.floor(phase);
      const frac = phase - idx;
      const curr = idx < mono.length ? mono[idx] : mono[mono.length - 1];
      const interp = prev + frac * (curr - prev);
      this._accumulator.push(interp);
      phase += ratio;

      // Update prev for next interpolation step
      if (Math.floor(phase) > idx) {
        prev = idx < mono.length ? mono[idx] : prev;
      }
    }

    this._prevSample = mono[mono.length - 1];
    this._phase = phase - mono.length;  // carry over fractional phase

    // Post 320-sample chunks (20 ms at 16kHz)
    while (this._accumulator.length >= 320) {
      const chunk = this._accumulator.splice(0, 320);
      const int16 = new Int16Array(320);
      for (let i = 0; i < 320; i++) {
        const s = Math.max(-1, Math.min(1, chunk[i]));
        int16[i] = s < 0 ? s * 32768 : s * 32767;
      }
      this.port.postMessage(int16.buffer, [int16.buffer]);
    }

    this._levelCounter++;
    if (this._levelCounter >= this._levelInterval) {
      this._levelCounter = 0;
      let sumSq = 0;
      for (let i = 0; i < mono.length; i++) sumSq += mono[i] * mono[i];
      this.port.postMessage({ type: 'level', rms: Math.sqrt(sumSq / mono.length) });
    }

    return true;  // keep processor alive
  }
}

registerProcessor("gibberly-resampler", GibberlyResampler);
