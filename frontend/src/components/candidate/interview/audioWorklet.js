/**
 * AudioWorklet Setup for Interview V2
 * Pure Web Audio Worklets for low-latency mic streaming (16kHz PCM16)
 * and Aura-2 TTS playback (24kHz PCM16) with ring-buffering.
 */

const CAPTURE_WORKLET_CODE = `
class CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Int16Array(480);
    this.bufferIdx = 0;
    this.sampleCount = 0;
    this.energySum = 0;
  }
  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;
    const channel = input[0];

    // Downsample from Context sampleRate to 16,000 Hz
    const ratio = 16000 / sampleRate;
    const outLength = Math.floor(channel.length * ratio);

    for (let i = 0; i < outLength; i++) {
      const srcIdx = Math.floor(i / ratio);
      const s = Math.max(-1, Math.min(1, channel[srcIdx]));
      const val = s < 0 ? s * 0x8000 : s * 0x7FFF;
      this.energySum += Math.abs(s);
      this.buffer[this.bufferIdx++] = val;

      if (this.bufferIdx >= 480) { // 30ms @ 16kHz = 480 samples = 960 bytes
        const chunk = this.buffer.slice(0, 480);
        this.port.postMessage({ type: 'pcm_chunk', buffer: chunk.buffer }, [chunk.buffer]);
        this.bufferIdx = 0;
      }
    }

    this.sampleCount += outLength;
    if (this.sampleCount >= 800) { // ~50ms interval for level telemetry
      const avg = this.energySum / this.sampleCount;
      this.port.postMessage({ type: 'mic_level', level: Math.min(1, avg * 4.5) });
      this.sampleCount = 0;
      this.energySum = 0;
    }

    return true;
  }
}
registerProcessor('capture-processor', CaptureProcessor);
`;

const PLAYBACK_WORKLET_CODE = `
class PlaybackProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    // 30 seconds circular buffer at 24kHz
    this.ring = new Float32Array(24000 * 30);
    this.writeIdx = 0;
    this.readIdx = 0;
    this.hasStarted = false;
    this.currentSpeechId = null;
    this.sampleRatio = 24000 / sampleRate; // Aura-2 is 24kHz
    this.resamplePos = 0;
    this.levelEmitCounter = 0;

    this.port.onmessage = (e) => {
      const { type, speechId, pcm16 } = e.data;
      if (type === 'chunk' && pcm16) {
        const arr = new Int16Array(pcm16);
        for (let i = 0; i < arr.length; i++) {
          this.ring[this.writeIdx % this.ring.length] = arr[i] / 32768.0;
          this.writeIdx++;
        }
        if (speechId) this.currentSpeechId = speechId;
      } else if (type === 'flush') {
        this.readIdx = this.writeIdx;
        this.hasStarted = false;
        this.resamplePos = 0;
      }
    };
  }

  process(inputs, outputs) {
    const out = outputs[0][0];
    const buffered = this.writeIdx - this.readIdx;

    // Pre-buffer threshold: 150ms at 24kHz is 3600 samples
    if (!this.hasStarted && buffered >= 3600) {
      this.hasStarted = true;
      this.port.postMessage({ type: 'playback_started', speechId: this.currentSpeechId });
    }

    if (this.hasStarted && buffered > 0) {
      let sumSq = 0;
      for (let i = 0; i < out.length; i++) {
        if (this.readIdx < this.writeIdx) {
          const sample = this.ring[this.readIdx % this.ring.length];
          out[i] = sample;
          sumSq += sample * sample;

          this.resamplePos += this.sampleRatio;
          while (this.resamplePos >= 1.0) {
            this.readIdx++;
            this.resamplePos -= 1.0;
          }
        } else {
          out[i] = 0;
        }
      }

      this.levelEmitCounter++;
      if (this.levelEmitCounter % 3 === 0) {
        const rms = Math.sqrt(sumSq / out.length);
        this.port.postMessage({ type: 'bot_level', level: Math.min(1, rms * 3.5) });
      }

      if (this.readIdx >= this.writeIdx) {
        this.hasStarted = false;
        this.port.postMessage({ type: 'playback_ended', speechId: this.currentSpeechId });
      }
    } else {
      out.fill(0);
    }
    return true;
  }
}
registerProcessor('playback-processor', PlaybackProcessor);
`;

/**
 * Initializes and registers the AudioWorklets on an AudioContext
 */
export async function initAudioPipeline({
  audioCtx,
  micStream,
  onPcmChunk,
  onPlaybackStarted,
  onPlaybackEnded,
  onMicLevel,
  onBotLevel,
}) {
  // Create object URLs from the embedded scripts
  const captureBlob = new Blob([CAPTURE_WORKLET_CODE], { type: 'application/javascript' });
  const playbackBlob = new Blob([PLAYBACK_WORKLET_CODE], { type: 'application/javascript' });

  const captureUrl = URL.createObjectURL(captureBlob);
  const playbackUrl = URL.createObjectURL(playbackBlob);

  try {
    await Promise.all([
      audioCtx.audioWorklet.addModule(captureUrl),
      audioCtx.audioWorklet.addModule(playbackUrl),
    ]);
  } finally {
    URL.revokeObjectURL(captureUrl);
    URL.revokeObjectURL(playbackUrl);
  }

  // Create worklet nodes
  const captureNode = new AudioWorkletNode(audioCtx, 'capture-processor');
  const playbackNode = new AudioWorkletNode(audioCtx, 'playback-processor');

  const micSource = audioCtx.createMediaStreamSource(micStream);
  micSource.connect(captureNode);
  playbackNode.connect(audioCtx.destination);

  captureNode.port.onmessage = (e) => {
    const { type, buffer, level } = e.data;
    if (type === 'pcm_chunk' && onPcmChunk) {
      onPcmChunk(buffer);
    } else if (type === 'mic_level' && onMicLevel) {
      onMicLevel(level);
    }
  };

  playbackNode.port.onmessage = (e) => {
    const { type, speechId, level } = e.data;
    if (type === 'playback_started' && onPlaybackStarted) {
      onPlaybackStarted(speechId);
    } else if (type === 'playback_ended' && onPlaybackEnded) {
      onPlaybackEnded(speechId);
    } else if (type === 'bot_level' && onBotLevel) {
      onBotLevel(level);
    }
  };

  return {
    captureNode,
    playbackNode,
    micSource,
    feedPlaybackChunk: (speechId, arrayBuffer) => {
      playbackNode.port.postMessage(
        { type: 'chunk', speechId, pcm16: arrayBuffer },
        [arrayBuffer]
      );
    },
    flushPlayback: () => {
      playbackNode.port.postMessage({ type: 'flush' });
    },
  };
}
