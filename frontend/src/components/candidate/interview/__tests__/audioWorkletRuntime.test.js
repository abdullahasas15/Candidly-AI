import { describe, it, expect, vi } from 'vitest';
import { PLAYBACK_WORKLET_CODE } from '../audioWorklet';

function instantiatePlaybackProcessor({ sampleRate = 24000 } = {}) {
  const registeredProcessors = {};
  class MockAudioWorkletProcessor {
    constructor() {
      this.port = {
        postMessage: vi.fn(),
        onmessage: null,
      };
    }
  }

  const fn = new Function(
    'AudioWorkletProcessor',
    'sampleRate',
    'registerProcessor',
    `${PLAYBACK_WORKLET_CODE}; return PlaybackProcessor;`
  );

  const ProcessorClass = fn(
    MockAudioWorkletProcessor,
    sampleRate,
    (name, proc) => { registeredProcessors[name] = proc; }
  );

  return new ProcessorClass();
}

function feedChunk(processor, speechId, sampleCount = 1000, value = 16000) {
  const int16 = new Int16Array(sampleCount);
  int16.fill(value);
  processor.port.onmessage({
    data: {
      type: 'chunk',
      speechId,
      pcm16: int16.buffer,
    },
  });
}

function runProcess(processor, outputSize = 128) {
  const out = new Float32Array(outputSize);
  const outputs = [[out]];
  const inputs = [];
  const keepAlive = processor.process(inputs, outputs);
  return { keepAlive, out };
}

describe('PlaybackProcessor Runtime Tests', () => {
  it('resets prebuffer cleanly when transitioning between two speech IDs', () => {
    const processor = instantiatePlaybackProcessor();

    // 1. First speech: feed 6000 samples (> 5400 threshold)
    feedChunk(processor, 'speech_1', 6000);
    expect(processor.hasStarted).toBe(false);

    // Process once to trigger playback start
    runProcess(processor, 128);
    expect(processor.hasStarted).toBe(true);
    expect(processor.currentSpeechId).toBe('speech_1');
    expect(processor.port.postMessage).toHaveBeenCalledWith({
      type: 'playback_started',
      speechId: 'speech_1',
    });

    // 2. Second speech arrives: feed only 1000 samples (< 5400 threshold)
    feedChunk(processor, 'speech_2', 1000);
    expect(processor.currentSpeechId).toBe('speech_2');
    expect(processor.hasStarted).toBe(false); // Cleanly reset

    // Process: should not have started speech_2 yet
    const { out } = runProcess(processor, 128);
    expect(processor.hasStarted).toBe(false);
    expect(out.every((s) => s === 0)).toBe(true);
    expect(processor.port.postMessage).not.toHaveBeenCalledWith({
      type: 'playback_started',
      speechId: 'speech_2',
    });

    // Feed remaining samples (4500 samples -> total 5500 > 5400)
    feedChunk(processor, 'speech_2', 4500);
    runProcess(processor, 128);
    expect(processor.hasStarted).toBe(true);
    expect(processor.port.postMessage).toHaveBeenCalledWith({
      type: 'playback_started',
      speechId: 'speech_2',
    });
  });

  it('handles transient underrun without resetting hasStarted or requiring 225ms prebuffer mid-sentence', () => {
    const processor = instantiatePlaybackProcessor();

    // Start speech with 5500 samples
    feedChunk(processor, 'speech_turn_1', 5500, 20000);
    runProcess(processor, 128);
    expect(processor.hasStarted).toBe(true);

    // Consume all samples until buffer is completely drained
    while (processor.writeIdx - processor.readIdx > 0) {
      runProcess(processor, 512);
    }
    expect(processor.writeIdx - processor.readIdx).toBe(0);

    // Run process on empty buffer without tts_done (transient underrun)
    const { out: silenceOut } = runProcess(processor, 128);
    expect(silenceOut.every((s) => s === 0)).toBe(true);
    // CRITICAL: hasStarted remains true during transient underrun, playback_drained is NOT emitted
    expect(processor.hasStarted).toBe(true);
    const drainedCalls = processor.port.postMessage.mock.calls.filter(
      ([msg]) => msg.type === 'playback_drained'
    );
    expect(drainedCalls.length).toBe(0);

    // Next chunk arrives mid-sentence (only 256 samples, far below the 5400 threshold)
    feedChunk(processor, 'speech_turn_1', 256, 25000);
    const { out: resumeOut } = runProcess(processor, 128);

    // Audio plays immediately without re-buffering 5400 samples
    expect(resumeOut[0]).not.toBe(0);
    expect(resumeOut[0]).toBeCloseTo(25000 / 32768.0, 3);
  });

  it('emits playback_drained only after tts_done is received and buffer reaches 0', () => {
    const processor = instantiatePlaybackProcessor();

    // Start speech with 6000 samples
    feedChunk(processor, 'speech_final', 6000);
    runProcess(processor, 128);
    expect(processor.hasStarted).toBe(true);

    // tts_done arrives while 4000 samples remain in buffer
    processor.port.onmessage({
      data: { type: 'tts_done', speechId: 'speech_final' },
    });
    expect(processor.isTtsDone).toBe(true);

    // Should NOT have drained yet
    let drainedCalls = processor.port.postMessage.mock.calls.filter(
      ([msg]) => msg.type === 'playback_drained'
    );
    expect(drainedCalls.length).toBe(0);

    // Process until drained
    while (processor.writeIdx - processor.readIdx > 0) {
      runProcess(processor, 512);
    }

    // Now playback_drained should be emitted
    drainedCalls = processor.port.postMessage.mock.calls.filter(
      ([msg]) => msg.type === 'playback_drained'
    );
    expect(drainedCalls.length).toBe(1);
    expect(drainedCalls[0][0]).toEqual({
      type: 'playback_drained',
      speechId: 'speech_final',
    });
    expect(processor.hasStarted).toBe(false);
    expect(processor.isTtsDone).toBe(false);
  });

  it('flush immediately cancels playback, drains ring buffer, and resets state', () => {
    const processor = instantiatePlaybackProcessor();

    feedChunk(processor, 'speech_cancelled', 8000);
    runProcess(processor, 128);
    expect(processor.hasStarted).toBe(true);

    // Send flush
    processor.port.onmessage({ data: { type: 'flush' } });
    expect(processor.readIdx).toBe(processor.writeIdx);
    expect(processor.hasStarted).toBe(false);
    expect(processor.isTtsDone).toBe(false);

    // Subsequent process outputs zero and does not start
    const { out } = runProcess(processor, 128);
    expect(out.every((s) => s === 0)).toBe(true);
    expect(processor.hasStarted).toBe(false);
  });
});
