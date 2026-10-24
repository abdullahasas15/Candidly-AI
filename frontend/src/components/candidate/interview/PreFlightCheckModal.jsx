import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Mic,
  MicOff,
  Camera,
  CameraOff,
  Wifi,
  Volume2,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Sparkles,
  ArrowRight,
  RefreshCw,
  X,
  VolumeX,
  Headphones,
} from 'lucide-react';

// R3.5 Part 4: sentence read by the candidate during the STT speech check.
const SPEECH_CHECK_SENTENCE =
  'I am ready to begin my interview and my audio is clear.';

const RECORD_TARGET_SECONDS = 15; // auto-stop (ample time to read comfortably)
const RECORD_MIN_SECONDS = 2; // candidate can stop after reading
const RECORD_HARD_STOP_SECONDS = 20; // safety hard stop
const SPEECH_MAX_ATTEMPTS = 5; // generous retakes
const SPEECH_PASS_RATIO = 0.75;
const STT_STATUS_CACHE_MS = 15000;

// Module-level cache of /api/stt/status ("cache it" across the step mount)
let sttStatusCache = { data: null, fetchedAt: 0 };

const isAppleProvider = (provider) =>
  provider === 'apple_speechanalyzer' || provider === 'apple_sfspeech';

const describeSttProvider = (provider) =>
  isAppleProvider(provider) ? 'Apple Speech (on-device)' : provider || 'Unknown';

// Downmix to mono + resample to 16 kHz with linear interpolation.
const toMono16kFloat32 = (audioBuffer) => {
  const channels = audioBuffer.numberOfChannels;
  const inLen = audioBuffer.length;
  const outLen = Math.max(1, Math.floor((inLen * 16000) / audioBuffer.sampleRate));

  // Downmix all channels into mono
  const mono = new Float32Array(inLen);
  for (let c = 0; c < channels; c++) {
    const data = audioBuffer.getChannelData(c);
    for (let i = 0; i < inLen; i++) {
      mono[i] += data[i];
    }
  }
  if (channels > 1) {
    for (let i = 0; i < inLen; i++) {
      mono[i] /= channels;
    }
  }

  // Linear-interpolation resample to 16 kHz
  const out = new Float32Array(outLen);
  if (outLen === 1) {
    out[0] = mono[0];
    return out;
  }
  const step = (inLen - 1) / (outLen - 1);
  for (let i = 0; i < outLen; i++) {
    const pos = i * step;
    const i0 = Math.floor(pos);
    const i1 = Math.min(inLen - 1, i0 + 1);
    const frac = pos - i0;
    out[i] = mono[i0] + (mono[i1] - mono[i0]) * frac;
  }
  return out;
};

// Float32 -> Int16 PCM bytes -> base64 (chunked to avoid call-stack issues)
const float32ToPcm16Base64 = (samples) => {
  const pcm = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  const bytes = new Uint8Array(pcm.buffer);
  let binary = '';
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    const slice = bytes.subarray(i, Math.min(i + CHUNK, bytes.length));
    binary += String.fromCharCode.apply(null, slice);
  }
  return btoa(binary);
};

export default function PreFlightCheckModal({
  isOpen,
  onClose,
  onProceedToInterview,
  jobTitle,
  candidateName,
  isEntering = false,
}) {
  // Device lists
  const [audioInputs, setAudioInputs] = useState([]);
  const [audioOutputs, setAudioOutputs] = useState([]);
  const [videoInputs, setVideoInputs] = useState([]);
  const [selectedMicId, setSelectedMicId] = useState('');
  const [selectedCamId, setSelectedCamId] = useState('');
  const [selectedSpeakerId, setSelectedSpeakerId] = useState('');

  // 5 Requirement States: 'idle' | 'checking' | 'passed' | 'failed'
  const [micStatus, setMicStatus] = useState('idle');
  const [camStatus, setCamStatus] = useState('idle');
  const [netStatus, setNetStatus] = useState('idle');
  const [audioTestStatus, setAudioTestStatus] = useState('idle');

  // Error messages
  const [micError, setMicError] = useState('');
  const [camError, setCamError] = useState('');
  const [netError, setNetError] = useState('');
  const [audioTestError, setAudioTestError] = useState('');

  // Audio test states
  const [micVolume, setMicVolume] = useState(0);
  const [micSoundDetected, setMicSoundDetected] = useState(false);
  const [speakerSoundPlayed, setSpeakerSoundPlayed] = useState(false);
  // A chime can "play" successfully from the browser's perspective while the
  // tab/site is muted or the output device is wrong — no JS API can detect
  // either. The candidate's explicit confirmation is the only honest pass gate.
  const [speakerConfirmed, setSpeakerConfirmed] = useState(false);
  const [networkRtt, setNetworkRtt] = useState(null);
  // Consent must be an explicit opt-in action, never pre-checked.
  const [consentAccepted, setConsentAccepted] = useState(false);

  // Voice-first interviews can proceed without a camera.
  const [cameraSkipped, setCameraSkipped] = useState(false);
  const cameraSkippedRef = useRef(false);

  // R3.5 Part 4: speech transcription check states
  const [sttStatus, setSttStatus] = useState(null); // {provider, ready, helper_built, detail, ...}
  const [sttStatusLoading, setSttStatusLoading] = useState(false);
  const [sttStatusError, setSttStatusError] = useState('');
  const [speechState, setSpeechState] = useState('idle'); // idle | recording | processing | passed | failed
  const [speechResult, setSpeechResult] = useState(null); // {transcript, match_ratio, latency_ms, provider}
  const [speechError, setSpeechError] = useState('');
  const [speechAttempts, setSpeechAttempts] = useState(0); // evaluated (failed) takes so far
  // Explicit candidate opt-in after exhausting speech retakes (device/STT quirks
  // must not permanently lock a candidate out of their interview).
  const [speechOverride, setSpeechOverride] = useState(false);
  const [countdownSeconds, setCountdownSeconds] = useState(RECORD_TARGET_SECONDS);

  // Streams & nodes
  const mediaStreamRef = useRef(null);
  const camStreamRef = useRef(null);
  const videoPreviewRef = useRef(null);
  const audioContextRef = useRef(null);
  const analyserRef = useRef(null);
  const animationFrameRef = useRef(null);

  // Speech-check recording refs
  const speechStreamRef = useRef(null);
  const speechRecorderRef = useRef(null);
  const recordTimerRef = useRef(null);
  const hardStopTimerRef = useRef(null);
  const recordStartRef = useRef(0);
  const isMountedRef = useRef(true);

  useEffect(() => {
    isMountedRef.current = true;
    if (isOpen) {
      runAllChecks();
      setSpeechState('idle');
      setSpeechResult(null);
      setSpeechError('');
      setSpeechAttempts(0);
      setSpeechOverride(false);
      loadSttStatus(false);
    } else {
      cleanupMedia();
      cleanupSpeechRecording();
    }
    return () => {
      isMountedRef.current = false;
      cleanupMedia();
      cleanupSpeechRecording();
    };
  }, [isOpen]);

  const cleanupMedia = () => {
    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current);
    }
    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
      audioContextRef.current.close().catch(() => {});
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }
    if (camStreamRef.current) {
      camStreamRef.current.getTracks().forEach((track) => track.stop());
      camStreamRef.current = null;
    }
  };

  const loadSttStatus = useCallback(async (force = false) => {
    const now = Date.now();
    if (!force && sttStatusCache.data && now - sttStatusCache.fetchedAt < STT_STATUS_CACHE_MS) {
      setSttStatus(sttStatusCache.data);
      setSttStatusError('');
      return;
    }
    setSttStatusLoading(true);
    setSttStatusError('');
    try {
      const res = await fetch('/api/stt/status');
      if (!res.ok) throw new Error(`Service responded with ${res.status}`);
      const data = await res.json();
      sttStatusCache = { data, fetchedAt: now };
      setSttStatus(data);
    } catch (e) {
      setSttStatusError(e.message || 'Could not reach the transcription service.');
    } finally {
      setSttStatusLoading(false);
    }
  }, []);

  const runAllChecks = async (micIdOverride, camIdOverride) => {
    cleanupMedia();
    setMicStatus('checking');
    setCamStatus('checking');
    setNetStatus('checking');
    setAudioTestStatus('checking');

    setMicError('');
    setCamError('');
    setNetError('');
    setAudioTestError('');
    setMicSoundDetected(false);
    setSpeakerSoundPlayed(false);

    const micId = micIdOverride !== undefined ? micIdOverride : selectedMicId;
    const camId = camIdOverride !== undefined ? camIdOverride : selectedCamId;

    // 1: Microphone permission + device enumeration (audio-only request so a
    // missing/blocked camera can never fail the mic check in a voice interview).
    let stream = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: micId
          ? {
              deviceId: { exact: micId },
              echoCancellation: true,
              noiseSuppression: true,
              autoGainControl: true,
            }
          : {
              echoCancellation: true,
              noiseSuppression: true,
              autoGainControl: true,
            },
      });
      mediaStreamRef.current = stream;

      // Enumerate devices
      const devices = await navigator.mediaDevices.enumerateDevices();
      const mics = devices.filter((d) => d.kind === 'audioinput');
      const speakers = devices.filter((d) => d.kind === 'audiooutput');
      const cams = devices.filter((d) => d.kind === 'videoinput');

      setAudioInputs(mics);
      setAudioOutputs(speakers);
      setVideoInputs(cams);

      if (mics.length > 0 && !micId) {
        setSelectedMicId(mics[0].deviceId);
      }
      if (cams.length > 0 && !camId) {
        setSelectedCamId(cams[0].deviceId);
      }
      if (speakers.length > 0 && !selectedSpeakerId) {
        setSelectedSpeakerId(speakers[0].deviceId);
      }

      setMicStatus('passed');

      // Setup audio analyzer for mic volume test
      setupAudioAnalyzer(stream);
    } catch (err) {
      console.error('Microphone permission error:', err);
      setMicStatus('failed');
      setMicError(
        err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError'
          ? 'Microphone permission denied — click the lock icon in your browser address bar to allow microphone access.'
          : `Audio device error: ${err.message || 'Could not access microphone'}`
      );
    }

    // 2: Camera — optional for a voice-first interview. Only requested when the
    // candidate has not skipped it; a failure here no longer blocks entry.
    if (cameraSkippedRef.current) {
      setCamStatus('skipped');
    } else {
      try {
        const camStream = await navigator.mediaDevices.getUserMedia({
          video: camId ? { deviceId: { exact: camId } } : true,
        });
        camStreamRef.current = camStream;
        if (videoPreviewRef.current) {
          videoPreviewRef.current.srcObject = camStream;
        }
        setCamStatus('passed');
      } catch (err) {
        console.warn('Camera permission error:', err);
        setCamStatus('failed');
        setCamError(
          err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError'
            ? 'Camera permission denied. You can enable it in your browser, or skip the camera — this is a voice-first interview.'
            : `Video device error: ${err.message || 'Could not access camera'}. You can skip the camera — this is a voice-first interview.`
        );
      }
    }

    // 3: Network Check (backend connectivity + latency probe)
    await runNetworkCheck();
  };

  const handleSkipCamera = () => {
    setCameraSkipped(true);
    cameraSkippedRef.current = true;
    setCamError('');
    setCamStatus('skipped');
    if (camStreamRef.current) {
      camStreamRef.current.getTracks().forEach((t) => t.stop());
      camStreamRef.current = null;
    }
    if (videoPreviewRef.current) {
      videoPreviewRef.current.srcObject = null;
    }
  };

  const handleUseCamera = () => {
    setCameraSkipped(false);
    cameraSkippedRef.current = false;
    runAllChecks(selectedMicId, selectedCamId);
  };

  const setupAudioAnalyzer = (stream) => {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      const audioCtx = new AudioCtx();
      audioContextRef.current = audioCtx;

      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      analyserRef.current = analyser;

      const source = audioCtx.createMediaStreamSource(stream);
      source.connect(analyser);

      const bufferLength = analyser.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);

      const checkVolume = () => {
        if (!analyserRef.current) return;
        analyserRef.current.getByteFrequencyData(dataArray);

        let sum = 0;
        for (let i = 0; i < bufferLength; i++) {
          sum += dataArray[i];
        }
        const average = sum / bufferLength;
        const normalized = Math.min(100, Math.round((average / 128) * 100));
        setMicVolume(normalized);

        if (normalized > 15) {
          setMicSoundDetected(true);
        }

        animationFrameRef.current = requestAnimationFrame(checkVolume);
      };

      checkVolume();
    } catch (e) {
      console.warn('AudioContext analysis not supported or blocked:', e);
      // Fallback pass if stream has active audio track
      const hasAudio = stream.getAudioTracks().some((t) => t.readyState === 'live');
      if (hasAudio) setMicSoundDetected(true);
    }
  };

  const runNetworkCheck = async () => {
    setNetStatus('checking');
    setNetError('');
    const startTime = performance.now();

    // Real backend reachability probe: measures the round-trip to /api/health
    // (which performs a live database check server-side). A dead backend or a
    // network timeout fails the check honestly instead of being masked by a
    // fabricated RTT that would surface later as a mid-interview reconnect.
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 4000);
      let res;
      try {
        res = await fetch('/api/health', { signal: controller.signal, cache: 'no-store' });
      } finally {
        clearTimeout(timeoutId);
      }
      if (!isMountedRef.current) return;

      if (!res.ok) {
        throw new Error(`Interview backend responded with ${res.status}`);
      }
      const rtt = Math.round(performance.now() - startTime);
      setNetworkRtt(rtt);
      setNetStatus('passed');
    } catch (err) {
      if (!isMountedRef.current) return;
      const isTimeout = err?.name === 'AbortError';
      console.error('Network check error:', err);
      setNetStatus('failed');
      setNetworkRtt(null);
      setNetError(
        isTimeout
          ? 'The interview backend did not respond within 4 seconds — check your internet connection, VPN, or firewall, then retry.'
          : `Network check failed: ${err.message || 'could not reach the interview backend'}. Verify your connection and retry.`
      );
    }
  };

  const playTestSpeakerSound = async () => {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      const ctx = new AudioCtx();
      if (selectedSpeakerId && typeof ctx.setSinkId === 'function') {
        try {
          await ctx.setSinkId(selectedSpeakerId);
        } catch (sinkErr) {
          console.warn('Could not route preflight chime to selected speaker:', sinkErr);
        }
      }
      if (ctx.state === 'suspended') {
        await ctx.resume().catch(() => {});
      }
      const now = ctx.currentTime;

      // Harmonious double chime
      const osc1 = ctx.createOscillator();
      const gain1 = ctx.createGain();
      osc1.type = 'sine';
      osc1.frequency.setValueAtTime(587.33, now); // D5
      gain1.gain.setValueAtTime(0.2, now);
      gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.35);
      osc1.connect(gain1);
      gain1.connect(ctx.destination);
      osc1.start(now);
      osc1.stop(now + 0.35);

      const osc2 = ctx.createOscillator();
      const gain2 = ctx.createGain();
      osc2.type = 'sine';
      osc2.frequency.setValueAtTime(880, now + 0.18); // A5
      gain2.gain.setValueAtTime(0.2, now + 0.18);
      gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.6);
      osc2.connect(gain2);
      gain2.connect(ctx.destination);
      osc2.start(now + 0.18);
      osc2.stop(now + 0.6);

      setTimeout(() => {
        try {
          ctx.close().catch(() => {});
        } catch (e) {}
      }, 1000);

      if (ctx.state !== 'running') {
        // Autoplay policy kept the context suspended: nothing was audible.
        // Never mark this green — that false pass follows the candidate into
        // the live interview as a silent interviewer.
        setSpeakerSoundPlayed(false);
        setSpeakerConfirmed(false);
        setAudioTestStatus('failed');
        setAudioTestError(
          'Your browser blocked audio playback. Click "Play Sound" again directly (not via keyboard), and if it still fails, right-click the site and check sound permissions or the speaker icon in the address bar.'
        );
        return;
      }

      // Context is running, so the chime reached the output route. Whether it
      // was AUDIBLE (tab not muted, correct device, volume up) only the
      // candidate can confirm — ask explicitly below.
      setSpeakerSoundPlayed(true);
      setSpeakerConfirmed(false);
      setAudioTestError('');
    } catch (err) {
      console.error('Speaker playback error:', err);
      setAudioTestError('Unable to play audio through your output device. Please check sound settings.');
      setAudioTestStatus('failed');
    }
  };

  const confirmSpeakerHeard = () => {
    setSpeakerConfirmed(true);
    setAudioTestStatus('passed');
    setAudioTestError('');
  };

  const reportSpeakerNotHeard = () => {
    setSpeakerConfirmed(false);
    setAudioTestStatus('failed');
    setAudioTestError(
      'Check these in order: (1) the speaker icon in the browser address bar — sound must not be muted for this site; ' +
        '(2) your system volume/output is up and unmuted; (3) the selected output device below is where you expect to hear sound; ' +
        '(4) pick a different output device and play the chime again. The interviewer\'s voice uses this same output during the interview.'
    );
  };

  const handleMicDeviceChange = async (deviceId) => {
    setSelectedMicId(deviceId);
    setSpeechState('idle');
    setSpeechResult(null);
    setSpeechError('');
    runAllChecks(deviceId, selectedCamId);
  };

  const handleCamDeviceChange = async (deviceId) => {
    setSelectedCamId(deviceId);
    runAllChecks(selectedMicId, deviceId);
  };

  const handleSpeakerDeviceChange = (deviceId) => {
    setSelectedSpeakerId(deviceId);
    setSpeakerSoundPlayed(false);
    setSpeakerConfirmed(false);
    setAudioTestError('');
    setAudioTestStatus('idle');
  };

  // ------------------------------------------------------------------ R3.5 Part 4
  // STT readiness gate: the transcript engine must report ready before entering.
  const appleProvider = isAppleProvider(sttStatus?.provider);
  const sttGateReady = Boolean(
    sttStatus &&
      sttStatus.ready === true &&
      (!appleProvider || sttStatus.helper_built === true)
  );
  const speechPassed = sttGateReady && (speechState === 'passed' || speechOverride);
  const speechRetakesExhausted = speechAttempts >= SPEECH_MAX_ATTEMPTS;

  const cleanupSpeechRecording = () => {
    if (recordTimerRef.current) {
      clearInterval(recordTimerRef.current);
      recordTimerRef.current = null;
    }
    if (hardStopTimerRef.current) {
      clearTimeout(hardStopTimerRef.current);
      hardStopTimerRef.current = null;
    }
    if (speechStreamRef.current) {
      speechStreamRef.current.getTracks().forEach((t) => t.stop());
      speechStreamRef.current = null;
    }
  };

  const evaluateSpeechRecording = async (blob) => {
    setSpeechState('processing');
    setSpeechError('');

    let pcmBase64 = '';
    let recordedMs = 0;
    try {
      const arrayBuffer = await blob.arrayBuffer();
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      const ctx = new AudioCtx();
      const audioBuffer = await ctx.decodeAudioData(arrayBuffer);
      recordedMs = Math.round(audioBuffer.duration * 1000);
      const floats = toMono16kFloat32(audioBuffer);
      pcmBase64 = float32ToPcm16Base64(floats);
      ctx.close().catch(() => {});
    } catch (e) {
      console.warn('Speech recording decode error:', e);
      setSpeechState('failed');
      setSpeechError('Could not process the recording in this browser. Try recording again.');
      return;
    }

    if (!pcmBase64) {
      setSpeechState('failed');
      setSpeechError('The recording came through empty. Try recording again.');
      return;
    }

    if (recordedMs < RECORD_MIN_SECONDS * 1000) {
      setSpeechState('failed');
      setSpeechError(
        `The recording was only ${(recordedMs / 1000).toFixed(1)}s — read the whole sentence through the full countdown (at least ${RECORD_MIN_SECONDS}s).`
      );
      return;
    }

    try {
      const res = await fetch('/api/stt/preflight-check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ expected: SPEECH_CHECK_SENTENCE, audio_base64: pcmBase64 }),
      });

      if (!res.ok) {
        // Service-side failure: show the error + retry, never auto-enter, never burn a retake.
        let detail = `Speech check service error (${res.status}).`;
        try {
          const errData = await res.json();
          if (errData?.detail) detail = `Speech check service error (${res.status}): ${errData.detail}`;
        } catch (e) {}
        setSpeechState('failed');
        setSpeechError(detail);
        return;
      }

      const data = await res.json();
      const ratio = typeof data.match_ratio === 'number' ? data.match_ratio : 0;
      const passed = data.pass === true || ratio >= SPEECH_PASS_RATIO;
      setSpeechResult({
        transcript: data.transcript || '',
        match_ratio: ratio,
        latency_ms: data.latency_ms,
        provider: data.provider || sttStatus?.provider,
        expected: data.expected || SPEECH_CHECK_SENTENCE,
      });

      if (data.error || data.provider === 'unavailable') {
        // Engine failure inside a 200: surface the error and allow a retry.
        setSpeechState('failed');
        setSpeechError(data.error || 'The transcription engine returned an error. Please try again.');
        return;
      }

      if (passed) {
        setSpeechState('passed');
        return;
      }

      // Genuine evaluated failure against the sentence → consumes a retake.
      setSpeechAttempts((prev) => prev + 1);
      setSpeechState('failed');
      setSpeechError(
        'Match too low — your words did not line up with the sentence. Speak clearly and at a steady pace.'
      );
    } catch (e) {
      console.warn('Preflight speech check network error:', e);
      setSpeechState('failed');
      setSpeechError(`Network error during the speech check: ${e.message || 'unknown'}`);
    }
  };

  const stopSpeechRecording = () => {
    if (speechRecorderRef.current && speechRecorderRef.current.state !== 'inactive') {
      speechRecorderRef.current.stop();
    }
    if (recordTimerRef.current) {
      clearInterval(recordTimerRef.current);
      recordTimerRef.current = null;
    }
    if (hardStopTimerRef.current) {
      clearTimeout(hardStopTimerRef.current);
      hardStopTimerRef.current = null;
    }
  };

  const startSpeechRecording = async () => {
    setSpeechError('');
    setSpeechResult(null);
    setSpeechState('recording');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: selectedMicId
          ? { deviceId: { exact: selectedMicId }, echoCancellation: true, noiseSuppression: true }
          : { echoCancellation: true, noiseSuppression: true },
      });
      speechStreamRef.current = stream;

      const mimeType =
        typeof MediaRecorder !== 'undefined' &&
        MediaRecorder.isTypeSupported &&
        MediaRecorder.isTypeSupported('audio/webm')
          ? 'audio/webm'
          : undefined;
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      speechRecorderRef.current = recorder;

      const chunks = [];
      recorder.ondataavailable = (ev) => {
        if (ev.data && ev.data.size > 0) chunks.push(ev.data);
      };
      recorder.onstop = () => {
        cleanupSpeechRecording();
        const blob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' });
        evaluateSpeechRecording(blob);
      };

      recorder.start();
      recordStartRef.current = Date.now();
      setCountdownSeconds(RECORD_TARGET_SECONDS);

      let elapsed = 0;
      recordTimerRef.current = setInterval(() => {
        elapsed += 1;
        if (elapsed <= RECORD_TARGET_SECONDS) {
          setCountdownSeconds(Math.max(0, RECORD_TARGET_SECONDS - elapsed));
        }
        if (elapsed >= RECORD_TARGET_SECONDS) {
          stopSpeechRecording();
        }
      }, 1000);
      // Hard stop safety net in case the interval drifts or is throttled
      hardStopTimerRef.current = setTimeout(
        () => stopSpeechRecording(),
        (RECORD_HARD_STOP_SECONDS + 0.5) * 1000
      );
    } catch (err) {
      console.error('Speech recording error:', err);
      cleanupSpeechRecording();
      setSpeechState('failed');
      setSpeechError(
        err && (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError')
          ? 'Microphone permission denied — allow microphone access and retry.'
          : `Could not start recording: ${err?.message || err}`
      );
    }
  };

  const allPassed =
    micStatus === 'passed' &&
    (camStatus === 'passed' || camStatus === 'skipped') &&
    netStatus === 'passed' &&
    audioTestStatus === 'passed' &&
    speechPassed &&
    consentAccepted;

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-md p-4 overflow-y-auto">
      <div className="w-full max-w-3xl rounded-3xl border border-slate-200 bg-white p-6 sm:p-8 shadow-2xl dark:border-slate-800 dark:bg-slate-900 my-8">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-slate-100 pb-5 dark:border-slate-800">
          <div>
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center rounded-md bg-indigo-50 px-2.5 py-1 text-xs font-semibold text-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-400">
                Pre-Flight Hardware & Network Verification
              </span>
            </div>
            <h2 className="mt-2 text-2xl font-black text-slate-900 dark:text-white">
              System Readiness Check
            </h2>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              Verifying hardware permissions, audio loop, backend audio streaming connectivity, and live transcription before entering the interview room.
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-xl p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-200"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Headphones Recommendation Notice */}
        <div className="mt-4 flex items-center gap-3 rounded-2xl border border-teal-500/30 bg-teal-950/20 p-3.5 dark:border-teal-800/40">
          <div className="rounded-xl bg-teal-500/10 p-2 text-teal-400">
            <Headphones className="h-5 w-5" />
          </div>
          <div>
            <h4 className="text-xs font-bold text-teal-400 uppercase tracking-wide">
              Headphones Recommended
            </h4>
            <p className="mt-0.5 text-xs text-slate-600 dark:text-slate-300">
              For optimal acoustic clarity, natural voice turn-taking, and echo prevention, wearing headphones or earbuds is strongly recommended.
            </p>
          </div>
        </div>

        {/* 5 In-Order Requirement Verification Cards */}
        <div className="mt-6 space-y-4">
          {/* Item 1: Microphone Permission & Device Picker */}
          <div className="rounded-2xl border border-slate-200 p-4 dark:border-slate-800 dark:bg-slate-800/40">
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-start gap-3">
                <div
                  className={`rounded-xl p-2.5 ${
                    micStatus === 'passed'
                      ? 'bg-emerald-50 text-emerald-600 dark:bg-emerald-950/40 dark:text-emerald-400'
                      : micStatus === 'failed'
                      ? 'bg-rose-50 text-rose-600 dark:bg-rose-950/40 dark:text-rose-400'
                      : 'bg-indigo-50 text-indigo-600 dark:bg-indigo-950/40 dark:text-indigo-400'
                  }`}
                >
                  <Mic className="h-5 w-5" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold uppercase tracking-wider text-slate-400">Step 1</span>
                    <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                      Microphone Access & Device Selection
                    </h3>
                  </div>
                  <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                    Verify input authorization and select your preferred microphone.
                  </p>
                </div>
              </div>

              {micStatus === 'checking' && (
                <span className="flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" /> Checking...
                </span>
              )}
              {micStatus === 'passed' && (
                <span className="flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-400">
                  <CheckCircle2 className="h-3.5 w-3.5" /> Passed
                </span>
              )}
              {micStatus === 'failed' && (
                <span className="flex items-center gap-1.5 rounded-full bg-rose-50 px-3 py-1 text-xs font-semibold text-rose-700 dark:bg-rose-950/50 dark:text-rose-400">
                  <AlertCircle className="h-3.5 w-3.5" /> Failed
                </span>
              )}
            </div>

            {micStatus === 'passed' && audioInputs.length > 0 && (
              <div className="mt-3.5">
                <label className="text-[11px] font-semibold text-slate-500 dark:text-slate-400">
                  Input Source ({audioInputs.length} available):
                </label>
                <select
                  value={selectedMicId}
                  onChange={(e) => handleMicDeviceChange(e.target.value)}
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-800 shadow-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
                >
                  {audioInputs.map((d, i) => (
                    <option key={d.deviceId || i} value={d.deviceId}>
                      {d.label || `Microphone ${i + 1}`}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {micStatus === 'failed' && (
              <div className="mt-3 rounded-xl bg-rose-50 p-3 text-xs text-rose-800 dark:bg-rose-950/30 dark:text-rose-300">
                {micError}
              </div>
            )}
          </div>

          {/* Item 2: Camera Permission & Device Picker + Live Preview */}
          <div className="rounded-2xl border border-slate-200 p-4 dark:border-slate-800 dark:bg-slate-800/40">
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-start gap-3">
                <div
                  className={`rounded-xl p-2.5 ${
                    camStatus === 'passed'
                      ? 'bg-emerald-50 text-emerald-600 dark:bg-emerald-950/40 dark:text-emerald-400'
                      : camStatus === 'failed'
                      ? 'bg-rose-50 text-rose-600 dark:bg-rose-950/40 dark:text-rose-400'
                      : 'bg-indigo-50 text-indigo-600 dark:bg-indigo-950/40 dark:text-indigo-400'
                  }`}
                >
                  <Camera className="h-5 w-5" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold uppercase tracking-wider text-slate-400">Step 2</span>
                    <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                      Camera Permission & Live Video Preview
                    </h3>
                  </div>
                  <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                    Verify video authorization, camera device feed, and framing.
                  </p>
                </div>
              </div>

              {camStatus === 'checking' && (
                <span className="flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" /> Checking...
                </span>
              )}
              {camStatus === 'passed' && (
                <span className="flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-400">
                  <CheckCircle2 className="h-3.5 w-3.5" /> Passed
                </span>
              )}
              {camStatus === 'skipped' && (
                <span className="flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                  <CameraOff className="h-3.5 w-3.5" /> Skipped (voice-only)
                </span>
              )}
              {camStatus === 'failed' && (
                <span className="flex items-center gap-1.5 rounded-full bg-rose-50 px-3 py-1 text-xs font-semibold text-rose-700 dark:bg-rose-950/50 dark:text-rose-400">
                  <AlertCircle className="h-3.5 w-3.5" /> Failed
                </span>
              )}
            </div>

            {camStatus === 'passed' && (
              <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-4 items-center">
                <div className="relative aspect-video w-full overflow-hidden rounded-xl bg-slate-950 border border-slate-200 dark:border-slate-700">
                  <video
                    ref={videoPreviewRef}
                    autoPlay
                    playsInline
                    muted
                    className="h-full w-full object-cover transform -scale-x-100"
                  />
                  <div className="absolute bottom-2 left-2 flex items-center gap-1.5 rounded-full bg-slate-900/80 px-2 py-0.5 text-[10px] font-medium text-white backdrop-blur-sm">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
                    Live Mirror Preview
                  </div>
                </div>

                <div className="space-y-2">
                  <label className="text-[11px] font-semibold text-slate-500 dark:text-slate-400">
                    Camera Device:
                  </label>
                  <select
                    value={selectedCamId}
                    onChange={(e) => handleCamDeviceChange(e.target.value)}
                    className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-800 shadow-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
                  >
                    {videoInputs.map((d, i) => (
                      <option key={d.deviceId || i} value={d.deviceId}>
                        {d.label || `Camera ${i + 1}`}
                      </option>
                    ))}
                  </select>
                  <p className="text-[11px] text-slate-400">
                    Ensure your face is well-lit and centered in frame.
                  </p>
                </div>
              </div>
            )}

            {camStatus === 'failed' && (
              <div className="mt-3 rounded-xl bg-rose-50 p-3 text-xs text-rose-800 dark:bg-rose-950/30 dark:text-rose-300">
                {camError}
                <button
                  type="button"
                  onClick={handleSkipCamera}
                  data-testid="skip-camera-button"
                  className="mt-2.5 flex items-center gap-1.5 rounded-xl border border-rose-300 bg-white px-4 py-2 text-[11px] font-bold text-rose-700 hover:bg-rose-50 dark:border-rose-800 dark:bg-slate-900 dark:text-rose-300 dark:hover:bg-slate-800"
                >
                  <CameraOff className="h-3.5 w-3.5" /> Skip camera — continue voice-only
                </button>
              </div>
            )}

            {camStatus === 'skipped' && (
              <div className="mt-3 flex items-center justify-between gap-3 rounded-xl bg-slate-50 p-3 text-xs text-slate-600 dark:bg-slate-900/60 dark:text-slate-300">
                <span>
                  Camera skipped — this is a voice-first interview, so the camera is optional.
                  Your interviewer will not see video.
                </span>
                <button
                  type="button"
                  onClick={handleUseCamera}
                  className="flex shrink-0 items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-[11px] font-bold text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
                >
                  <Camera className="h-3.5 w-3.5" /> Use camera
                </button>
              </div>
            )}
          </div>

          {/* Item 3: Network Check — WebSocket Audio Channel Probe */}
          <div className="rounded-2xl border border-slate-200 p-4 dark:border-slate-800 dark:bg-slate-800/40">
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-start gap-3">
                <div
                  className={`rounded-xl p-2.5 ${
                    netStatus === 'passed'
                      ? 'bg-emerald-50 text-emerald-600 dark:bg-emerald-950/40 dark:text-emerald-400'
                      : netStatus === 'failed'
                      ? 'bg-rose-50 text-rose-600 dark:bg-rose-950/40 dark:text-rose-400'
                      : 'bg-indigo-50 text-indigo-600 dark:bg-indigo-950/40 dark:text-indigo-400'
                  }`}
                >
                  <Wifi className="h-5 w-5" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold uppercase tracking-wider text-slate-400">Step 3</span>
                    <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                      Backend Connectivity & Latency Probe
                    </h3>
                  </div>
                  <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                    Probing the interview backend (including its database) and measuring round-trip latency.
                  </p>
                </div>
              </div>

              {netStatus === 'checking' && (
                <span className="flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" /> Probing...
                </span>
              )}
              {netStatus === 'passed' && (
                <span className="flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-400">
                  <CheckCircle2 className="h-3.5 w-3.5" /> Passed ({networkRtt}ms)
                </span>
              )}
              {netStatus === 'failed' && (
                <span className="flex items-center gap-1.5 rounded-full bg-rose-50 px-3 py-1 text-xs font-semibold text-rose-700 dark:bg-rose-950/50 dark:text-rose-400">
                  <AlertCircle className="h-3.5 w-3.5" /> Failed
                </span>
              )}
            </div>

            {netStatus === 'passed' && (
              <div className="mt-3 flex items-center justify-between text-xs text-slate-600 dark:text-slate-400 bg-slate-50 dark:bg-slate-900/60 p-2.5 rounded-xl border border-slate-100 dark:border-slate-800">
                <span>Interview Backend: Reachable</span>
                <span className="font-semibold text-emerald-600 dark:text-emerald-400">Latency: {networkRtt}ms</span>
              </div>
            )}

            {netStatus === 'failed' && (
              <div className="mt-3 rounded-xl bg-rose-50 p-3 text-xs text-rose-800 dark:bg-rose-950/30 dark:text-rose-300">
                {netError}
              </div>
            )}
          </div>

          {/* Item 4: Mic / Speaker Audio Verification */}
          <div className="rounded-2xl border border-slate-200 p-4 dark:border-slate-800 dark:bg-slate-800/40">
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-start gap-3">
                <div
                  className={`rounded-xl p-2.5 ${
                    audioTestStatus === 'passed'
                      ? 'bg-emerald-50 text-emerald-600 dark:bg-emerald-950/40 dark:text-emerald-400'
                      : audioTestStatus === 'failed'
                      ? 'bg-rose-50 text-rose-600 dark:bg-rose-950/40 dark:text-rose-400'
                      : 'bg-indigo-50 text-indigo-600 dark:bg-indigo-950/40 dark:text-indigo-400'
                  }`}
                >
                  <Volume2 className="h-5 w-5" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold uppercase tracking-wider text-slate-400">Step 4</span>
                    <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                      Microphone Pickup & Speaker Output Test
                    </h3>
                  </div>
                  <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                    Speak to confirm mic level, then click below to play a test chime through your speakers.
                  </p>
                </div>
              </div>

              {audioTestStatus === 'passed' ? (
                <span className="flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-400">
                  <CheckCircle2 className="h-3.5 w-3.5" /> Audio Loop Verified
                </span>
              ) : (
                <span className="flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700 dark:bg-amber-950/50 dark:text-amber-400">
                  Pending Verification
                </span>
              )}
            </div>

            <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
              {/* Mic pickup level meter */}
              <div className="rounded-xl bg-slate-50 p-3.5 dark:bg-slate-900/60 border border-slate-100 dark:border-slate-800">
                <div className="flex items-center justify-between text-xs font-medium text-slate-600 dark:text-slate-300">
                  <span>Speak: "Hello Candidly"</span>
                  <span className={micSoundDetected ? 'text-emerald-600 font-bold' : 'text-slate-400'}>
                    {micSoundDetected ? 'Voice Detected' : 'Listening...'}
                  </span>
                </div>
                {/* Visualizer bar */}
                <div className="mt-2.5 h-3 w-full rounded-full bg-slate-200 dark:bg-slate-800 overflow-hidden">
                  <div
                    className={`h-full transition-all duration-75 ${
                      micVolume > 15 ? 'bg-emerald-500' : 'bg-indigo-500'
                    }`}
                    style={{ width: `${micVolume}%` }}
                  />
                </div>
              </div>

              {/* Speaker sound test */}
              <div className="rounded-xl bg-slate-50 p-3.5 dark:bg-slate-900/60 border border-slate-100 dark:border-slate-800">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <div className="text-xs font-semibold text-slate-800 dark:text-slate-200">Speaker Test</div>
                    <div className="text-[11px] text-slate-400">
                      {speakerConfirmed
                        ? 'Chime confirmed — output verified'
                        : speakerSoundPlayed
                          ? 'Did you hear the chime?'
                          : 'Hear test sound'}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={playTestSpeakerSound}
                    className="flex items-center gap-1.5 rounded-xl bg-indigo-600 px-3 py-2 text-xs font-bold text-white hover:bg-indigo-700 transition-colors shadow-sm"
                  >
                    <Volume2 className="h-4 w-4" />
                    {speakerSoundPlayed ? 'Play Again' : 'Play Sound'}
                  </button>
                </div>
                {speakerSoundPlayed && !speakerConfirmed && (
                  <div className="mt-2.5 flex items-center gap-2">
                    <button
                      type="button"
                      data-testid="speaker-heard-yes"
                      onClick={confirmSpeakerHeard}
                      className="rounded-lg bg-emerald-600 px-3 py-1.5 text-[11px] font-bold text-white hover:bg-emerald-500 transition-colors"
                    >
                      Yes, I heard it
                    </button>
                    <button
                      type="button"
                      data-testid="speaker-heard-no"
                      onClick={reportSpeakerNotHeard}
                      className="rounded-lg bg-rose-600 px-3 py-1.5 text-[11px] font-bold text-white hover:bg-rose-500 transition-colors"
                    >
                      No sound
                    </button>
                  </div>
                )}
              </div>
            </div>

            {audioOutputs.length > 0 && (
              <div className="mt-3">
                <label
                  htmlFor="preflight-speaker-select"
                  className="text-[11px] font-semibold text-slate-500 dark:text-slate-400"
                >
                  Output Speaker ({audioOutputs.length} available):
                </label>
                <select
                  id="preflight-speaker-select"
                  data-testid="preflight-speaker-select"
                  value={selectedSpeakerId}
                  onChange={(e) => handleSpeakerDeviceChange(e.target.value)}
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-800 shadow-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
                >
                  {audioOutputs.map((d, i) => (
                    <option key={d.deviceId || i} value={d.deviceId}>
                      {d.label || `Speaker ${i + 1}`}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-[11px] text-slate-400">
                  Test chime and interview audio will use this output device.
                </p>
              </div>
            )}

            {audioTestError && (
              <div className="mt-3 rounded-xl bg-rose-50 p-3 text-xs text-rose-800 dark:bg-rose-950/30 dark:text-rose-300">
                {audioTestError}
              </div>
            )}
          </div>

          {/* Item 5: R3.5 Speech Transcription Check (STT readiness gate) */}
          <div className="rounded-2xl border border-slate-200 p-4 dark:border-slate-800 dark:bg-slate-800/40">
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-start gap-3">
                <div
                  className={`rounded-xl p-2.5 ${
                    speechPassed
                      ? 'bg-emerald-50 text-emerald-600 dark:bg-emerald-950/40 dark:text-emerald-400'
                      : speechState === 'failed'
                      ? 'bg-rose-50 text-rose-600 dark:bg-rose-950/40 dark:text-rose-400'
                      : 'bg-indigo-50 text-indigo-600 dark:bg-indigo-950/40 dark:text-indigo-400'
                  }`}
                >
                  <Mic className="h-5 w-5" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold uppercase tracking-wider text-slate-400">Step 5</span>
                    <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                      Speech Transcription Check
                    </h3>
                  </div>
                  <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                    Verify the transcription engine can hear your words accurately — room entry stays locked until it passes.
                  </p>
                </div>
              </div>

              {sttStatusLoading && (
                <span className="flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" /> Checking engine...
                </span>
              )}
              {!sttStatusLoading && speechPassed && (
                <span className="flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-400">
                  <CheckCircle2 className="h-3.5 w-3.5" /> Passed ({Math.round((speechResult?.match_ratio ?? 0) * 100)}%)
                </span>
              )}
              {!sttStatusLoading && !speechPassed && speechState === 'failed' && (
                <span className="flex items-center gap-1.5 rounded-full bg-rose-50 px-3 py-1 text-xs font-semibold text-rose-700 dark:bg-rose-950/50 dark:text-rose-400">
                  <AlertCircle className="h-3.5 w-3.5" /> Failed
                </span>
              )}
              {!sttStatusLoading && !speechPassed && speechState !== 'failed' && !sttGateReady && (
                <span className="flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700 dark:bg-amber-950/50 dark:text-amber-400">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" /> Engine Not Ready
                </span>
              )}
            </div>

            <div className="mt-3 flex items-center gap-2 rounded-xl bg-slate-50 dark:bg-slate-900/60 border border-slate-100 dark:border-slate-800 px-3 py-2.5 text-xs text-slate-600 dark:text-slate-300">
              <span className={`h-2 w-2 rounded-full shrink-0 ${sttGateReady ? 'bg-emerald-500' : 'bg-amber-500'}`} />
              <span>
                Transcription engine: <strong className="font-bold text-slate-800 dark:text-slate-100">{describeSttProvider(sttStatus?.provider)}</strong>
              </span>
              {sttStatus?.locale && <span className="text-slate-400">({sttStatus.locale})</span>}
            </div>

            {/* Blocking notice while the engine is not ready */}
            {!sttStatusLoading && !sttGateReady && (
              <div className="mt-3 rounded-xl bg-amber-50 p-3 text-xs text-amber-800 dark:bg-amber-950/30 dark:text-amber-300">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-bold">Transcription engine is starting up… first run can take a minute.</p>
                    {(sttStatusError || sttStatus?.detail) && (
                      <p className="mt-1 opacity-80 break-words">
                        {sttStatusError || (appleProvider && sttStatus?.helper_built === false
                          ? 'Apple speech helper is being prepared on the interview host.'
                          : sttStatus?.detail)}
                      </p>
                    )}
                    {sttStatusError && (
                      <p className="mt-1 opacity-80">Room entry stays disabled until the engine is verified.</p>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => loadSttStatus(true)}
                    className="flex shrink-0 items-center gap-1.5 rounded-xl border border-amber-300 bg-white px-3 py-1.5 text-[11px] font-bold text-amber-700 hover:bg-amber-100 dark:border-amber-800 dark:bg-slate-900 dark:text-amber-300 dark:hover:bg-slate-800"
                  >
                    <RefreshCw className="h-3.5 w-3.5" /> Retry
                  </button>
                </div>
              </div>
            )}

            {/* Speech read-along + recording (only when the engine is ready) */}
            {sttGateReady && speechState !== 'passed' && (
              <div className="mt-3.5">
                <div className="grid grid-cols-1 sm:grid-cols-[minmax(0,1fr)_auto] gap-3 items-center rounded-xl bg-slate-50 dark:bg-slate-900/60 border border-slate-100 dark:border-slate-800 p-3.5">
                  <div>
                    <p className="text-sm font-semibold leading-relaxed text-slate-800 dark:text-slate-100">
                      “{SPEECH_CHECK_SENTENCE}”
                    </p>
                    <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                      Press record and read this sentence out loud — you have up to {RECORD_TARGET_SECONDS}s, or click Stop when finished.
                    </p>
                  </div>

                  <div className="flex items-center gap-2 justify-self-start sm:justify-self-end">
                    {speechState === 'recording' ? (
                      <>
                        <span className="flex items-center gap-1.5 rounded-full bg-rose-50 dark:bg-rose-950/40 px-3 py-1.5 text-xs font-bold text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-800/60">
                          <span className="h-2 w-2 rounded-full bg-rose-500 animate-pulse" />
                          {countdownSeconds}s
                        </span>
                        <button
                          type="button"
                          onClick={stopSpeechRecording}
                          disabled={RECORD_TARGET_SECONDS - countdownSeconds < RECORD_MIN_SECONDS}
                          className="rounded-xl bg-rose-600 px-4 py-2 text-xs font-bold text-white hover:bg-rose-700 transition-colors shadow-sm disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                          Stop
                        </button>
                      </>
                    ) : (
                      <button
                        type="button"
                        onClick={startSpeechRecording}
                        disabled={speechState === 'processing'}
                        className="flex items-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-2 text-xs font-bold text-white hover:bg-indigo-700 transition-colors shadow-sm disabled:opacity-50"
                      >
                        <Mic className="h-4 w-4" /> Record
                      </button>
                    )}
                  </div>
                </div>

                {speechState === 'processing' && (
                  <div className="mt-3 flex items-center gap-2 rounded-xl bg-slate-50 dark:bg-slate-900/60 border border-slate-100 dark:border-slate-800 px-3 py-2.5 text-xs font-semibold text-slate-600 dark:text-slate-300">
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-indigo-500" />
                    Transcribing your sample and matching words…
                  </div>
                )}

                {speechState === 'failed' && (
                  <div className="mt-3 rounded-xl bg-rose-50 p-3 text-xs text-rose-800 dark:bg-rose-950/30 dark:text-rose-300">
                    {!speechRetakesExhausted ? (
                      <>
                        <p className="font-bold">{speechError}</p>
                        {speechResult?.transcript && (
                          <p className="mt-1.5">
                            Transcript heard: <span className="italic">"{speechResult.transcript}"</span>
                            {typeof speechResult.match_ratio === 'number' && (
                              <> Match: {Math.round(speechResult.match_ratio * 100)}% (needs {Math.round(SPEECH_PASS_RATIO * 100)}%).</>
                            )}
                          </p>
                        )}
                        <button
                          type="button"
                          onClick={startSpeechRecording}
                          className="mt-2.5 flex items-center gap-1.5 rounded-xl bg-rose-600 px-4 py-2 text-[11px] font-bold text-white hover:bg-rose-700 transition-colors"
                        >
                          <RefreshCw className="h-3.5 w-3.5" /> Retake
                          {speechAttempts > 0 && ` (${Math.max(0, SPEECH_MAX_ATTEMPTS - speechAttempts)} left)`}
                        </button>
                      </>
                    ) : (
                      <>
                        <p className="font-bold text-rose-700 dark:text-rose-200">
                          Speech verification failed after multiple attempts.
                        </p>
                        {speechResult?.transcript && (
                          <p className="mt-1.5">
                            Last transcript heard: <span className="italic">"{speechResult.transcript}"</span>
                            {typeof speechResult.match_ratio === 'number' && (
                              <> ({Math.round(speechResult.match_ratio * 100)}% match)</>
                            )}
                          </p>
                        )}
                        {!speechOverride ? (
                          <>
                            <p className="mt-1.5 opacity-90">
                              This is usually caused by accent variation, background noise, or a
                              device quirk — not your fault. You can still continue: the live
                              interview uses a different streaming engine, but transcription quality
                              may affect your evaluation, so we recommend headphones and a quiet room.
                              For guaranteed accommodation, contact <strong>support@candidly.ai</strong> to
                              schedule a phone interview.
                            </p>
                            <div className="mt-2.5 flex flex-wrap items-center gap-2">
                              <button
                                type="button"
                                onClick={() => setSpeechOverride(true)}
                                data-testid="continue-anyway-button"
                                className="flex items-center gap-1.5 rounded-xl bg-amber-600 px-4 py-2 text-[11px] font-bold text-white hover:bg-amber-700 transition-colors"
                              >
                                <ArrowRight className="h-3.5 w-3.5" /> Continue anyway
                              </button>
                              <button
                                type="button"
                                onClick={startSpeechRecording}
                                className="flex items-center gap-1.5 rounded-xl border border-rose-300 bg-white px-4 py-2 text-[11px] font-bold text-rose-700 hover:bg-rose-50 dark:border-rose-800 dark:bg-slate-900 dark:text-rose-300 dark:hover:bg-slate-800"
                              >
                                <RefreshCw className="h-3.5 w-3.5" /> Try again
                              </button>
                            </div>
                          </>
                        ) : (
                          <p className="mt-1.5 font-semibold text-amber-700 dark:text-amber-300">
                            Continuing without a verified speech check — transcription quality may
                            affect your evaluation.
                          </p>
                        )}
                      </>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Passed */}
            {sttGateReady && speechState === 'passed' && (
              <div className="mt-3 rounded-xl bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800/50 p-3 text-xs text-emerald-800 dark:text-emerald-300">
                <div className="flex items-center gap-2 font-bold text-emerald-700 dark:text-emerald-400">
                  <CheckCircle2 className="h-4 w-4" /> Speech check passed — {Math.round((speechResult?.match_ratio ?? 0) * 100)}% match
                  {typeof speechResult?.latency_ms === 'number' && (
                    <span className="font-normal opacity-80">· {Math.round(speechResult.latency_ms)}ms</span>
                  )}
                </div>
                {speechResult?.transcript && (
                  <p className="mt-1.5 opacity-90">
                    Transcript: <span className="italic">"{speechResult.transcript}"</span>
                  </p>
                )}
                <p className="mt-1 opacity-80">Engine: {describeSttProvider(speechResult?.provider || sttStatus?.provider)}</p>
              </div>
            )}
          </div>

          {/* Integrity & Recording Policy Consent Notice (Part F2 & F3) */}
          <div className="rounded-2xl border border-indigo-200/80 bg-indigo-50/50 p-4 dark:border-indigo-900/50 dark:bg-indigo-950/20">
            <label className="flex items-start gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={consentAccepted}
                onChange={(e) => setConsentAccepted(e.target.checked)}
                className="mt-0.5 h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
              />
              <span className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed">
                <strong className="font-bold text-slate-900 dark:text-white">Integrity & Privacy Notice:</strong>{' '}
                I consent to lightweight session integrity monitoring (tab switches, window focus, clipboard paste, camera/mic status, and single-face presence checks) during this live interview. Full audio/video recording is <strong>OFF by default</strong> — only text transcripts and integrity timestamps are stored for evaluation.
              </span>
            </label>
          </div>
        </div>

        {/* Footer & Enter Interview Action */}
        <div className="mt-6 flex flex-col sm:flex-row items-center justify-between gap-4 border-t border-slate-100 pt-5 dark:border-slate-800">
          <div className="text-xs text-slate-500 dark:text-slate-400">
            {allPassed ? (
              <span className="text-emerald-600 dark:text-emerald-400 font-semibold flex items-center gap-1">
                <CheckCircle2 className="h-4 w-4 inline" /> All 5 requirements & consent verified. Ready to enter room.
              </span>
            ) : !sttGateReady ? (
              <span>The transcription engine must be ready before entering.</span>
            ) : !speechPassed ? (
              <span>Pass the speech check to unlock room entry.</span>
            ) : (
              <span>Complete all 5 verification steps and consent to unlock room entry.</span>
            )}
          </div>

          <div className="flex items-center gap-3 w-full sm:w-auto">
            <button
              type="button"
              onClick={runAllChecks}
              className="flex-1 sm:flex-initial inline-flex items-center justify-center gap-1.5 rounded-xl border border-slate-200 px-4 py-2.5 text-xs font-bold text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              <RefreshCw className="h-3.5 w-3.5" /> Re-check
            </button>

            <button
              type="button"
              onClick={() =>
                onProceedToInterview &&
                onProceedToInterview({
                  selectedAudioInput: selectedMicId,
                  selectedVideoInput: cameraSkipped ? '' : selectedCamId,
                  selectedAudioOutput: selectedSpeakerId,
                })
              }
              disabled={!allPassed || isEntering}
              className={`flex-1 sm:flex-initial inline-flex items-center justify-center gap-2 rounded-xl px-6 py-2.5 text-xs font-bold text-white transition-all shadow-md ${
                allPassed && !isEntering
                  ? 'bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 hover:shadow-indigo-500/25 cursor-pointer'
                  : 'bg-slate-300 dark:bg-slate-800 text-slate-500 cursor-not-allowed shadow-none'
              }`}
            >
              {isEntering ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span>Setting up the interview environment...</span>
                </>
              ) : (
                <>
                  <Sparkles className="h-4 w-4" />
                  <span>Start Interview</span>
                  <ArrowRight className="h-4 w-4" />
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
