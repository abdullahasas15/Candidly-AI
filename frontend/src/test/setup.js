import '@testing-library/jest-dom';

// Polyfill window.HTMLMediaElement.prototype
window.HTMLMediaElement.prototype.play = () => Promise.resolve();
window.HTMLMediaElement.prototype.pause = () => {};
window.HTMLMediaElement.prototype.load = () => {};

// Polyfill AudioContext and AudioWorklet
class MockAudioContext {
  constructor() {
    this.sampleRate = 24000;
    this.currentTime = 0;
    this.state = 'running';
    this.audioWorklet = {
      addModule: async () => {},
    };
    this.destination = {};
  }
  createMediaStreamSource() {
    return { connect: () => {} };
  }
  createOscillator() {
    return {
      type: 'sine',
      frequency: { setValueAtTime: () => {}, exponentialRampToValueAtTime: () => {} },
      connect: () => {},
      start: () => {},
      stop: () => {},
    };
  }
  createGain() {
    return {
      gain: { setValueAtTime: () => {}, exponentialRampToValueAtTime: () => {} },
      connect: () => {},
    };
  }
  close() {
    return Promise.resolve();
  }
  resume() {
    return Promise.resolve();
  }
}

class MockAudioWorkletNode {
  constructor() {
    this.port = {
      onmessage: null,
      postMessage: () => {},
    };
  }
  connect() {}
  disconnect() {}
}

window.AudioContext = window.AudioContext || MockAudioContext;
window.webkitAudioContext = window.webkitAudioContext || MockAudioContext;
window.AudioWorkletNode = window.AudioWorkletNode || MockAudioWorkletNode;

// Polyfill navigator.mediaDevices
if (!navigator.mediaDevices) {
  navigator.mediaDevices = {};
}
if (!navigator.mediaDevices.getUserMedia) {
  navigator.mediaDevices.getUserMedia = async () => ({
    getTracks: () => [{ stop: () => {}, enabled: true, kind: 'audio' }],
    getAudioTracks: () => [{ stop: () => {}, enabled: true, kind: 'audio' }],
    getVideoTracks: () => [{ stop: () => {}, enabled: true, kind: 'video' }],
  });
}
if (!navigator.mediaDevices.enumerateDevices) {
  navigator.mediaDevices.enumerateDevices = async () => [
    { deviceId: 'default', kind: 'audioinput', label: 'Default Microphone' },
    { deviceId: 'default', kind: 'audiooutput', label: 'Default Speaker' },
    { deviceId: 'default', kind: 'videoinput', label: 'Default Camera' },
  ];
}
