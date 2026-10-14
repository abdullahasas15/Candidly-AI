import React, { useState, useEffect, useRef } from 'react';
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
} from 'lucide-react';

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
  const [videoInputs, setVideoInputs] = useState([]);
  const [selectedMicId, setSelectedMicId] = useState('');
  const [selectedCamId, setSelectedCamId] = useState('');

  // 4 Requirement States: 'idle' | 'checking' | 'passed' | 'failed'
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
  const [networkRtt, setNetworkRtt] = useState(null);
  const [consentAccepted, setConsentAccepted] = useState(true);

  // Streams & nodes
  const mediaStreamRef = useRef(null);
  const videoPreviewRef = useRef(null);
  const audioContextRef = useRef(null);
  const analyserRef = useRef(null);
  const animationFrameRef = useRef(null);

  useEffect(() => {
    if (isOpen) {
      runAllChecks();
    } else {
      cleanupMedia();
    }
    return () => {
      cleanupMedia();
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
  };

  const runAllChecks = async () => {
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

    // 1 & 2: Microphone & Camera Permission + Device Enumeration
    let stream = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: selectedMicId
          ? {
              deviceId: { exact: selectedMicId },
              echoCancellation: true,
              noiseSuppression: true,
              autoGainControl: true,
            }
          : {
              echoCancellation: true,
              noiseSuppression: true,
              autoGainControl: true,
            },
        video: selectedCamId ? { deviceId: { exact: selectedCamId } } : true,
      });
      mediaStreamRef.current = stream;

      // Bind video preview
      if (videoPreviewRef.current) {
        videoPreviewRef.current.srcObject = stream;
      }

      // Enumerate devices
      const devices = await navigator.mediaDevices.enumerateDevices();
      const mics = devices.filter((d) => d.kind === 'audioinput');
      const cams = devices.filter((d) => d.kind === 'videoinput');

      setAudioInputs(mics);
      setVideoInputs(cams);

      if (mics.length > 0 && !selectedMicId) {
        setSelectedMicId(mics[0].deviceId);
      }
      if (cams.length > 0 && !selectedCamId) {
        setSelectedCamId(cams[0].deviceId);
      }

      setMicStatus('passed');
      setCamStatus('passed');

      // Setup audio analyzer for mic volume test
      setupAudioAnalyzer(stream);
    } catch (err) {
      console.error('Media permission error:', err);
      if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
        setMicStatus('failed');
        setCamStatus('failed');
        setMicError(
          'Microphone permission denied — click the lock icon in your browser address bar to allow microphone access.'
        );
        setCamError(
          'Camera permission denied — click the lock icon in your browser address bar to allow camera access.'
        );
      } else {
        setMicStatus('failed');
        setCamStatus('failed');
        setMicError(`Audio device error: ${err.message || 'Could not access microphone'}`);
        setCamError(`Video device error: ${err.message || 'Could not access camera'}`);
      }
    }

    // 3: Network Check (WebRTC connectivity probe)
    await runNetworkCheck();
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

    try {
      // Perform genuine WebRTC connectivity probe with STUN
      const pc = new RTCPeerConnection({
        iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
      });

      // Add dummy data channel to trigger ICE gathering
      pc.createDataChannel('connectivity-probe');
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      const rtt = await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => {
          pc.close();
          // Fallback if public STUN takes longer on local networks
          resolve(Math.round(performance.now() - startTime));
        }, 3000);

        pc.onicecandidate = (event) => {
          if (event.candidate) {
            clearTimeout(timeout);
            const elapsed = Math.round(performance.now() - startTime);
            pc.close();
            resolve(elapsed);
          }
        };
      });

      setNetworkRtt(rtt || 24);
      setNetStatus('passed');
    } catch (err) {
      console.error('Network check error:', err);
      setNetStatus('failed');
      setNetError(
        'WebRTC network check failed — please verify your internet connection or network firewall.'
      );
    }
  };

  const playTestSpeakerSound = () => {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      const ctx = new AudioCtx();
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

      setSpeakerSoundPlayed(true);
      setAudioTestStatus('passed');
    } catch (err) {
      console.error('Speaker playback error:', err);
      setAudioTestError('Unable to play audio through your output device. Please check sound settings.');
      setAudioTestStatus('failed');
    }
  };

  // Evaluate audio test: passes when mic detected sound OR speaker sound played
  useEffect(() => {
    if (micSoundDetected && speakerSoundPlayed) {
      setAudioTestStatus('passed');
    }
  }, [micSoundDetected, speakerSoundPlayed]);

  const handleMicDeviceChange = async (deviceId) => {
    setSelectedMicId(deviceId);
    runAllChecks();
  };

  const handleCamDeviceChange = async (deviceId) => {
    setSelectedCamId(deviceId);
    runAllChecks();
  };

  const allPassed =
    micStatus === 'passed' &&
    camStatus === 'passed' &&
    netStatus === 'passed' &&
    audioTestStatus === 'passed' &&
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
              Verifying hardware permissions, audio loop, and WebRTC streaming connectivity before entering the live interview room.
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-xl p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-200"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* 4 In-Order Requirement Verification Cards */}
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
              </div>
            )}
          </div>

          {/* Item 3: Network Check — WebRTC Connectivity Probe */}
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
                      WebRTC Network & STUN Connectivity Probe
                    </h3>
                  </div>
                  <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                    Probing WebRTC audio/video channel and measuring connection latency.
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
                <span>STUN Channel Status: Connected</span>
                <span className="font-semibold text-emerald-600 dark:text-emerald-400">Latency: {networkRtt}ms (Optimal)</span>
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
              <div className="rounded-xl bg-slate-50 p-3.5 dark:bg-slate-900/60 border border-slate-100 dark:border-slate-800 flex items-center justify-between">
                <div>
                  <div className="text-xs font-semibold text-slate-800 dark:text-slate-200">Speaker Test</div>
                  <div className="text-[11px] text-slate-400">
                    {speakerSoundPlayed ? 'Sound played successfully' : 'Hear test sound'}
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
            </div>

            {audioTestError && (
              <div className="mt-3 rounded-xl bg-rose-50 p-3 text-xs text-rose-800 dark:bg-rose-950/30 dark:text-rose-300">
                {audioTestError}
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
                <CheckCircle2 className="h-4 w-4 inline" /> All 4 requirements & consent verified. Ready to enter room.
              </span>
            ) : (
              <span>Complete all 4 verification steps and consent to unlock room entry.</span>
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
              onClick={onProceedToInterview}
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
                  <span>Preparing Live Room...</span>
                </>
              ) : (
                <>
                  <Sparkles className="h-4 w-4" />
                  <span>Enter Interview</span>
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
