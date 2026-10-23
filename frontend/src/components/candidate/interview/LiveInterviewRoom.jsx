import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Mic,
  MicOff,
  Video,
  VideoOff,
  Sliders,
  FileText,
  X,
  Volume2,
  CheckCircle2,
  AlertTriangle,
  Loader2,
  RefreshCw,
  PhoneOff,
} from 'lucide-react';
import AudioDomeVisualizer from './AudioDomeVisualizer';
import { initAudioPipeline } from './audioWorklet';

/**
 * LiveInterviewRoom (Interview V2 Architecture)
 *
 * Full-screen candidate interview room:
 * - Pure WebSocket connection to /ws/interview/{session_id}
 * - AudioWorklet capture (16kHz linear16 PCM) + Aura-2 playback (24kHz linear16 PCM ring buffer)
 * - Reactive dotted wave/dome canvas visualizer (neutral grey idle, teal when speaking/talking, wave when thinking)
 * - Left: fading bot captions, dimmed previous caption, candidate answer bubble (no scrolling chat log)
 * - Status line: Listening / Thinking / Speaking with animated dot grid
 * - Right: mirrored local camera tile with mic level indicator
 * - Bottom pill bar: Mic mute, Device settings popover, Transcript drawer toggle
 * - Top bar: thin section progress indicator (n of N), End Interview button with confirm dialog
 * - Completely hands-free (voice-driven, optional accelerators)
 */
const MAX_RECONNECT_ATTEMPTS = 5;
const PERSISTENCE_FAILURE_EXIT_DELAY_MS = 2500;
const INTERVIEW_EXIT_NOTICE_KEY = 'candidly-interview-exit-notice';

export default function LiveInterviewRoom({
  sessionId,
  session,
  jobTitle = 'Technical Interview',
  candidateName = 'Candidate',
  durationMins = 20,
  token,
  initialAudioDeviceId = '',
  initialVideoDeviceId = '',
  initialAudioOutputId = '',
  onExit,
  onEndInterview,
  isPractice = false,
  mockState = null,
}) {
  const canonicalSessionId = sessionId || session?.id;
  const canonicalOnExit = useCallback(() => {
    if (onExit) {
      onExit();
    } else if (onEndInterview) {
      onEndInterview();
    }
  }, [onExit, onEndInterview]);

  // Connection states: 'connecting' | 'preparing_audio' | 'connected' | 'reconnecting' | 'completed' | 'error'
  const [connectionState, setConnectionState] = useState(mockState?.connectionState || (canonicalSessionId ? 'preparing_audio' : 'error'));
  const [errorMessage, setErrorMessage] = useState(mockState?.errorMessage || (!canonicalSessionId ? 'Interview session identifier is missing or invalid.' : ''));

  // Interview state from conductor
  const [phase, setPhase] = useState(mockState?.phase || 'greeting');
  const [status, setStatus] = useState(mockState?.status || 'speaking'); // 'listening' | 'thinking' | 'speaking' | 'preparing_audio' | 'completed' | 'failed'
  const statusRef = useRef(status);
  const [currentSection, setCurrentSection] = useState(mockState?.currentSection || 1);
  const [totalSections, setTotalSections] = useState(mockState?.totalSections || 5);
  const totalSectionsRef = useRef(totalSections);
  useEffect(() => {
    totalSectionsRef.current = totalSections;
  }, [totalSections]);
  const [skillName, setSkillName] = useState(mockState?.skillName || '');
  const [botTransitionText, setBotTransitionText] = useState('');
  const [topicIndex, setTopicIndex] = useState(0);
  const [topicCount, setTopicCount] = useState(0);

  // Captions
  const [currentBotCaption, setCurrentBotCaption] = useState(
    mockState?.currentBotCaption || 'Preparing your interview environment and audio pipeline...'
  );
  const currentBotCaptionRef = useRef(currentBotCaption);
  useEffect(() => {
    currentBotCaptionRef.current = currentBotCaption;
  }, [currentBotCaption]);
  const [previousBotCaption, setPreviousBotCaption] = useState(mockState?.previousBotCaption || '');
  const [candidateLiveTranscript, setCandidateLiveTranscript] = useState(mockState?.candidateLiveTranscript || '');
  const [lastCandidateAnswer, setLastCandidateAnswer] = useState(mockState?.lastCandidateAnswer || '');
  const [transcriptHistory, setTranscriptHistory] = useState(mockState?.transcriptHistory || []);

  // Hardware & Audio state
  const [isMicMuted, setIsMicMuted] = useState(mockState?.isMicMuted || false);
  const isMicMutedRef = useRef(isMicMuted);
  const [isVideoOff, setIsVideoOff] = useState(mockState?.isVideoOff || false);
  const [micLevel, setMicLevel] = useState(mockState?.micLevel || 0); // 0 to 1
  const [botLevel, setBotLevel] = useState(mockState?.botLevel || 0); // 0 to 1
  const [audioLevel, setAudioLevel] = useState(mockState?.audioLevel || 0); // Combined for visualizer

  const stableTimerRef = useRef(null);
  const ttsDoneMapRef = useRef({});
  const bufferDrainedMapRef = useRef({});

  const updateStatus = useCallback((newStatus) => {
    statusRef.current = newStatus;
    setStatus(newStatus);
    if (newStatus === 'listening') {
      if (!stableTimerRef.current) {
        stableTimerRef.current = setTimeout(() => {
          if (isComponentMountedRef.current && !isTerminatedRef.current) {
            reconnectAttemptsRef.current = 0;
          }
          stableTimerRef.current = null;
        }, 10000);
      }
    } else {
      if (stableTimerRef.current) {
        clearTimeout(stableTimerRef.current);
        stableTimerRef.current = null;
      }
    }
  }, []);

  const completePlaybackForSpeech = useCallback((speechId) => {
    updateStatus('listening');
    setBotLevel(0);
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'playback_ended', speech_id: speechId }));
    }
    delete ttsDoneMapRef.current[speechId];
    delete bufferDrainedMapRef.current[speechId];
  }, [updateStatus]);

  const handleAudioPlaybackDrained = useCallback((speechId) => {
    const sid = speechId || currentSpeechIdRef.current;
    bufferDrainedMapRef.current[sid] = true;
    if (ttsDoneMapRef.current[sid]) {
      completePlaybackForSpeech(sid);
    }
  }, [completePlaybackForSpeech]);

  useEffect(() => {
    statusRef.current = status;
  }, [status]);

  useEffect(() => {
    isMicMutedRef.current = isMicMuted;
  }, [isMicMuted]);

  // Device selectors
  const [audioInputDevices, setAudioInputDevices] = useState([]);
  const [audioOutputDevices, setAudioOutputDevices] = useState([]);
  const [videoInputDevices, setVideoInputDevices] = useState([]);
  const [selectedMicId, setSelectedMicId] = useState(initialAudioDeviceId || '');
  const [selectedSpeakerId, setSelectedSpeakerId] = useState(initialAudioOutputId || '');
  const [selectedCameraId, setSelectedCameraId] = useState(initialVideoDeviceId || '');

  // Modals & Popovers
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isTranscriptOpen, setIsTranscriptOpen] = useState(false);
  const [confirmExitOpen, setConfirmExitOpen] = useState(mockState?.confirmExitOpen || false);
  const [isEndingSession, setIsEndingSession] = useState(false);
  const [audioActivationRequired, setAudioActivationRequired] = useState(false);

  // Refs
  const wsRef = useRef(null);
  const audioCtxRef = useRef(null);
  const micStreamRef = useRef(null);
  const cameraStreamRef = useRef(null);
  const videoElementRef = useRef(null);
  const audioPipelineRef = useRef(null);
  const currentSpeechIdRef = useRef(null);
  const reconnectAttemptsRef = useRef(0);
  const isComponentMountedRef = useRef(true);
  const earlyAudioBufferRef = useRef([]);
  // Tracks which socket completed the readiness handshake. A ref that only
  // stores a boolean is unsafe: React StrictMode (and a fast reconnect) can
  // create a second socket while the first is still opening, leaving the new
  // server-side runner waiting forever for client_ready.
  const clientReadySocketRef = useRef(null);
  const clientConnectionRef = useRef(0);
  const startupWatchdogRef = useRef(null);
  const audioStateListenerRef = useRef(null);
  const isHandshakeCompleteRef = useRef(false);
  const isTerminatedRef = useRef(false);
  const reconnectTimerRef = useRef(null);
  const endTimeoutRef = useRef(null);
  const completionFallbackTimerRef = useRef(null);
  const fallbackExitTimerRef = useRef(null);
  const endFallbackAttemptedRef = useRef(false);
  const performRestFallbackRef = useRef(null);

  // Determine active visualizer level
  useEffect(() => {
    if (status === 'speaking') {
      setAudioLevel(botLevel);
    } else if (status === 'listening' || status === 'talking') {
      setAudioLevel(micLevel);
    } else {
      setAudioLevel(0);
    }
  }, [status, botLevel, micLevel]);

  // Load available media devices
  const refreshDevices = useCallback(async () => {
    try {
      if (!navigator.mediaDevices?.enumerateDevices) return;
      const devices = await navigator.mediaDevices.enumerateDevices();
      setAudioInputDevices(devices.filter((d) => d.kind === 'audioinput'));
      setAudioOutputDevices(devices.filter((d) => d.kind === 'audiooutput'));
      setVideoInputDevices(devices.filter((d) => d.kind === 'videoinput'));
    } catch (err) {
      console.warn('Failed to enumerate devices:', err);
    }
  }, []);

  // Listen for device changes (plug/unplug)
  useEffect(() => {
    if (navigator.mediaDevices && typeof navigator.mediaDevices.addEventListener === 'function') {
      const handleDeviceChange = () => {
        refreshDevices();
      };
      navigator.mediaDevices.addEventListener('devicechange', handleDeviceChange);
      return () => {
        navigator.mediaDevices.removeEventListener('devicechange', handleDeviceChange);
      };
    }
  }, [refreshDevices]);

  // Initialize camera video stream
  const initCamera = useCallback(async (cameraId = '') => {
    try {
      if (cameraStreamRef.current) {
        cameraStreamRef.current.getTracks().forEach((t) => t.stop());
      }
      if (!navigator.mediaDevices?.getUserMedia) return;
      const stream = await navigator.mediaDevices.getUserMedia({
        video: cameraId ? { deviceId: { exact: cameraId } } : { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' },
        audio: false,
      });
      cameraStreamRef.current = stream;
      if (videoElementRef.current) {
        videoElementRef.current.srcObject = stream;
      }
      setIsVideoOff(false);
    } catch (err) {
      console.warn('Could not access camera:', err);
      setIsVideoOff(true);
    }
  }, []);

  // Send client_ready exactly once per WebSocket. The handshake is scoped to
  // the socket instead of a global boolean so a reconnect (or a second socket
  // created by StrictMode) always performs its own handshake.
  const sendClientReadyIfReady = useCallback((socket = wsRef.current) => {
    if (!socket || socket !== wsRef.current || socket.readyState !== WebSocket.OPEN) {
      return false;
    }
    if (clientReadySocketRef.current === socket) {
      return true;
    }

    const audioContext = audioCtxRef.current;
    if (!audioPipelineRef.current || !audioContext || audioContext.state !== 'running') {
      // The server deliberately waits for this handshake before speaking.
      // Surface an actionable prompt instead of silently waiting for timeout.
      setAudioActivationRequired(true);
      return false;
    }

    clientReadySocketRef.current = socket;
    setAudioActivationRequired(false);
    socket.send(
      JSON.stringify({
        type: 'client_ready',
        sample_rate: audioContext.sampleRate || 24000,
      })
    );
    return true;
  }, []);

  const clearStartupWatchdog = useCallback(() => {
    if (startupWatchdogRef.current) {
      clearTimeout(startupWatchdogRef.current);
      startupWatchdogRef.current = null;
    }
  }, []);

  const detachAudioStateListener = useCallback(() => {
    const listener = audioStateListenerRef.current;
    if (listener?.context?.removeEventListener && listener.handler) {
      try {
        listener.context.removeEventListener('statechange', listener.handler);
      } catch (err) {
        // Context may already be closed.
      }
    }
    audioStateListenerRef.current = null;
  }, []);

  const attachAudioStateListener = useCallback(
    (audioContext) => {
      if (!audioContext || typeof audioContext.addEventListener !== 'function') return;
      if (audioStateListenerRef.current?.context === audioContext) return;
      detachAudioStateListener();
      const handler = () => {
        if (audioContext === audioCtxRef.current && audioContext.state === 'running') {
          setAudioActivationRequired(false);
          sendClientReadyIfReady();
        }
      };
      audioContext.addEventListener('statechange', handler);
      audioStateListenerRef.current = { context: audioContext, handler };
    },
    [detachAudioStateListener, sendClientReadyIfReady]
  );

  // Terminal cleanup stops all hardware and invokes exit
  const handleTerminalCleanup = useCallback(() => {
    // SessionEnded and the REST fallback can race. Terminal cleanup must run
    // once so the parent does not receive duplicate onExit callbacks.
    if (isTerminatedRef.current) return;
    isTerminatedRef.current = true;
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (endTimeoutRef.current) {
      clearTimeout(endTimeoutRef.current);
      endTimeoutRef.current = null;
    }
    if (completionFallbackTimerRef.current) {
      clearTimeout(completionFallbackTimerRef.current);
      completionFallbackTimerRef.current = null;
    }
    if (stableTimerRef.current) {
      clearTimeout(stableTimerRef.current);
      stableTimerRef.current = null;
    }
    if (fallbackExitTimerRef.current) {
      clearTimeout(fallbackExitTimerRef.current);
      fallbackExitTimerRef.current = null;
    }
    clearStartupWatchdog();
    detachAudioStateListener();
    earlyAudioBufferRef.current = [];
    if (audioPipelineRef.current?.dispose) {
      audioPipelineRef.current.dispose();
      audioPipelineRef.current = null;
    }
    if (micStreamRef.current) {
      micStreamRef.current.getTracks().forEach((track) => track.stop());
      micStreamRef.current = null;
    }
    if (cameraStreamRef.current) {
      cameraStreamRef.current.getTracks().forEach((track) => track.stop());
      cameraStreamRef.current = null;
    }
    if (audioCtxRef.current && audioCtxRef.current.state !== 'closed') {
      try {
        audioCtxRef.current.close().catch(() => {});
      } catch (e) {}
    }
    audioCtxRef.current = null;
    if (wsRef.current) {
      try {
        wsRef.current.close();
      } catch (e) {}
      wsRef.current = null;
    }
    canonicalOnExit();
  }, [canonicalOnExit, clearStartupWatchdog, detachAudioStateListener]);

  // Terminal session error handler stops all hardware and halts reconnection
  const terminateSession = useCallback((msg) => {
    isTerminatedRef.current = true;
    setConnectionState('error');
    updateStatus('failed');
    if (msg) setErrorMessage(msg);
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (endTimeoutRef.current) {
      clearTimeout(endTimeoutRef.current);
      endTimeoutRef.current = null;
    }
    if (completionFallbackTimerRef.current) {
      clearTimeout(completionFallbackTimerRef.current);
      completionFallbackTimerRef.current = null;
    }
    if (stableTimerRef.current) {
      clearTimeout(stableTimerRef.current);
      stableTimerRef.current = null;
    }
    if (fallbackExitTimerRef.current) {
      clearTimeout(fallbackExitTimerRef.current);
      fallbackExitTimerRef.current = null;
    }
    clearStartupWatchdog();
    detachAudioStateListener();
    setAudioActivationRequired(false);
    earlyAudioBufferRef.current = [];
    if (audioPipelineRef.current?.dispose) {
      audioPipelineRef.current.dispose();
      audioPipelineRef.current = null;
    }
    if (micStreamRef.current) {
      micStreamRef.current.getTracks().forEach((track) => track.stop());
      micStreamRef.current = null;
    }
    if (cameraStreamRef.current) {
      cameraStreamRef.current.getTracks().forEach((track) => track.stop());
      cameraStreamRef.current = null;
    }
    if (audioCtxRef.current && audioCtxRef.current.state !== 'closed') {
      try {
        audioCtxRef.current.close().catch(() => {});
      } catch (e) {}
    }
    audioCtxRef.current = null;
    if (wsRef.current) {
      try {
        wsRef.current.close();
      } catch (e) {}
      wsRef.current = null;
    }
  }, [updateStatus, clearStartupWatchdog, detachAudioStateListener]);

  // Switch microphone device dynamically and rebuild pipeline
  const switchMicrophone = useCallback(async (newDeviceId) => {
    setSelectedMicId(newDeviceId);
    if (!navigator.mediaDevices?.getUserMedia) return;
    try {
      if (audioPipelineRef.current?.dispose) {
        audioPipelineRef.current.dispose();
        audioPipelineRef.current = null;
      }
      if (micStreamRef.current) {
        micStreamRef.current.getTracks().forEach((t) => t.stop());
        micStreamRef.current = null;
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
          deviceId: newDeviceId ? { exact: newDeviceId } : undefined,
        },
      });
      micStreamRef.current = stream;
      if (isMicMutedRef.current) {
        stream.getAudioTracks().forEach((t) => { t.enabled = false; });
      }
      if (audioCtxRef.current && stream) {
        if (audioCtxRef.current.state === 'suspended') {
          await audioCtxRef.current.resume();
        }
        const pipeline = await initAudioPipeline({
          audioCtx: audioCtxRef.current,
          micStream: stream,
          onPcmChunk: (buffer) => {
            const currentStatus = statusRef.current;
            const isGateOpen = currentStatus === 'listening' || currentStatus === 'talking' || currentStatus === 'opening_listening';
            if (
              wsRef.current &&
              wsRef.current.readyState === WebSocket.OPEN &&
              !isMicMutedRef.current &&
              isHandshakeCompleteRef.current &&
              isGateOpen
            ) {
              wsRef.current.send(buffer);
            }
          },
          onPlaybackStarted: (speechId) => {
            updateStatus('speaking');
            if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
              wsRef.current.send(JSON.stringify({ type: 'playback_started', speech_id: speechId }));
            }
          },
          onPlaybackDrained: (speechId) => {
            handleAudioPlaybackDrained(speechId);
          },
          onPlaybackEnded: (speechId) => {
            completePlaybackForSpeech(speechId);
          },
          onMicLevel: (lvl) => {
            setMicLevel(isMicMutedRef.current ? 0 : lvl);
          },
          onBotLevel: (lvl) => {
            setBotLevel(lvl);
          },
        });
        audioPipelineRef.current = pipeline;
      }
    } catch (err) {
      console.warn('Failed to switch microphone:', err);
      setErrorMessage('Could not switch microphone device: ' + (err.message || 'Access error'));
    }
  }, [updateStatus]);

  // Switch speaker output device
  const switchSpeaker = useCallback(async (newDeviceId) => {
    setSelectedSpeakerId(newDeviceId);
    if (audioCtxRef.current && typeof audioCtxRef.current.setSinkId === 'function') {
      try {
        await audioCtxRef.current.setSinkId(newDeviceId);
      } catch (err) {
        console.warn('setSinkId failed on audioCtx:', err);
      }
    }
  }, []);

  // Connect WebSocket & audio pipeline
  const connectSession = useCallback(async () => {
    if (!canonicalSessionId || mockState?.skipConnect) return;

    // A single in-flight connection attempt owns the room. React StrictMode
    // mounts effects twice in development and a retry can overlap the previous
    // asynchronous startup; without this generation guard both attempts open a
    // WebSocket, and the second one can replace the server-side runner without
    // sending its own client_ready handshake.
    const attemptId = clientConnectionRef.current + 1;
    clientConnectionRef.current = attemptId;
    const isAttemptActive = () =>
      attemptId === clientConnectionRef.current &&
      isComponentMountedRef.current &&
      !isTerminatedRef.current;

    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    clearStartupWatchdog();

    // Reset or close existing WS
    if (wsRef.current) {
      try {
        wsRef.current.close();
      } catch (e) {}
      wsRef.current = null;
    }

    isHandshakeCompleteRef.current = false;
    setAudioActivationRequired(false);
    setConnectionState('preparing_audio');

    // 1. Initialize Audio Pipeline first (once per room, reuse across reconnections)
    try {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      const createdAudioContext = !audioCtxRef.current || audioCtxRef.current.state === 'closed';
      if (createdAudioContext) {
        audioCtxRef.current = new AudioContextClass({ sampleRate: 24000 });
        // Preflight speaker selection must be applied to the actual playback
        // context, not just stored in the dropdown state.
        if (initialAudioOutputId && typeof audioCtxRef.current.setSinkId === 'function') {
          try {
            await audioCtxRef.current.setSinkId(initialAudioOutputId);
          } catch (sinkErr) {
            console.warn('Could not apply preflight speaker selection:', sinkErr);
          }
        }
        if (!isAttemptActive()) return;
      }

      if (audioCtxRef.current) {
        attachAudioStateListener(audioCtxRef.current);
      }

      if (audioCtxRef.current?.state === 'suspended') {
        try {
          await audioCtxRef.current.resume();
        } catch (resumeErr) {
          // Browser autoplay policy is waiting for a user gesture. Keep the
          // pipeline setup below; the room will show an explicit activation
          // button instead of silently waiting for the server timeout.
          console.warn('AudioContext resume requires a user gesture:', resumeErr);
        }
        if (!isAttemptActive()) return;
      }

      // Microphone stream
      if (!micStreamRef.current && navigator.mediaDevices?.getUserMedia) {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({
            audio: {
              echoCancellation: true,
              noiseSuppression: true,
              autoGainControl: true,
              channelCount: 1,
              deviceId: selectedMicId ? { exact: selectedMicId } : undefined,
            },
          });
          if (!isAttemptActive()) {
            stream.getTracks().forEach((track) => track.stop());
            return;
          }
          micStreamRef.current = stream;
        } catch (micErr) {
          if (!isAttemptActive()) return;
          console.warn('Initial microphone access failed:', micErr);
          setConnectionState('error');
          setErrorMessage(
            micErr.name === 'NotAllowedError' || micErr.name === 'PermissionDeniedError'
              ? 'Microphone permission denied — please allow microphone access and click Retry.'
              : 'Could not access your microphone: ' + (micErr.message || 'Device unavailable') + '. Please check audio settings and click Retry.'
          );
          updateStatus('failed');
          return; // Stop here: do not connect WebSocket if microphone cannot be acquired
        }
      }

      if (!isAttemptActive()) return;

      // Initialize Audio Worklets only once if not yet initialized
      if (!audioPipelineRef.current && audioCtxRef.current && micStreamRef.current) {
        let pipeline;
        try {
          pipeline = await initAudioPipeline({
            audioCtx: audioCtxRef.current,
            micStream: micStreamRef.current,
            onPcmChunk: (buffer) => {
              // Microphone gate: never transmit candidate PCM until startup handshake completes and bot is listening
              const currentStatus = statusRef.current;
              const isGateOpen = currentStatus === 'listening' || currentStatus === 'talking' || currentStatus === 'opening_listening';
              if (
                wsRef.current &&
                wsRef.current.readyState === WebSocket.OPEN &&
                !isMicMutedRef.current &&
                isHandshakeCompleteRef.current &&
                isGateOpen
              ) {
                wsRef.current.send(buffer);
              }
            },
            onPlaybackStarted: (speechId) => {
              updateStatus('speaking');
              if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
                wsRef.current.send(JSON.stringify({ type: 'playback_started', speech_id: speechId }));
              }
            },
            onPlaybackDrained: (speechId) => {
              handleAudioPlaybackDrained(speechId);
            },
            onPlaybackEnded: (speechId) => {
              completePlaybackForSpeech(speechId);
            },
            onMicLevel: (lvl) => {
              setMicLevel(isMicMutedRef.current ? 0 : lvl);
            },
            onBotLevel: (lvl) => {
              setBotLevel(lvl);
            },
          });
        } catch (pipelineErr) {
          if (!isAttemptActive()) return;
          console.error('Audio pipeline initialization failed:', pipelineErr);
          terminateSession(
            'Audio processing could not start. Check that your browser supports audio worklets, then click Retry.'
          );
          return;
        }
        if (!isAttemptActive()) {
          pipeline?.dispose?.();
          return;
        }
        audioPipelineRef.current = pipeline;
      }

      // Drain any early buffered chunks
      if (audioPipelineRef.current && earlyAudioBufferRef.current.length > 0) {
        earlyAudioBufferRef.current.forEach((chunk) => {
          audioPipelineRef.current.feedPlaybackChunk(currentSpeechIdRef.current, chunk);
        });
        earlyAudioBufferRef.current = [];
      }
    } catch (audioErr) {
      if (!isAttemptActive()) return;
      console.warn('Audio initialization warning:', audioErr);
      // In mock/test environments getUserMedia might be unmocked
    }

    if (!isAttemptActive()) return;
    if (!audioPipelineRef.current || !audioCtxRef.current) {
      setConnectionState('preparing_audio');
      setAudioActivationRequired(true);
      setErrorMessage('Audio could not be prepared. Follow the audio prompt to continue.');
      return;
    }

    // 2. Open WebSocket with short-lived ticket
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    let url = `${proto}//${host}/ws/interview/${canonicalSessionId}`;

    let ticket = mockState?.ticket || null;
    if (!ticket) {
      const tokenToUse =
        token ||
        localStorage.getItem('candidly-auth-token-candidate') ||
        localStorage.getItem('candidly-auth-token');

      if (!tokenToUse) {
        terminateSession('Authentication required: please log in to access this interview session.');
        return;
      }

      let ticketAttempts = 0;
      const maxTicketAttempts = 3;

      while (ticketAttempts < maxTicketAttempts && !ticket && !isTerminatedRef.current) {
        if (!isAttemptActive()) return;
        ticketAttempts++;
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 5000);
        try {
          const ticketRes = await fetch(`/api/interview-sessions/${canonicalSessionId}/ws-ticket`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Bearer ${tokenToUse}`,
            },
            signal: controller.signal,
          });
          clearTimeout(timeoutId);
          if (!isAttemptActive()) return;
          if (ticketRes.status === 401 || ticketRes.status === 403) {
            terminateSession('Access forbidden: you are not authorized to join this interview session.');
            return;
          }
          if (ticketRes.status === 404) {
            terminateSession('Interview session not found.');
            return;
          }
          if (ticketRes.ok) {
            const ticketData = await ticketRes.json();
            if (!isAttemptActive()) return;
            if (ticketData?.ticket) {
              ticket = ticketData.ticket;
              break;
            }
          }
        } catch (err) {
          clearTimeout(timeoutId);
          if (!isAttemptActive()) return;
          console.warn(`Ticket fetch attempt ${ticketAttempts} failed:`, err);
        }
        if (!ticket && ticketAttempts < maxTicketAttempts) {
          await new Promise((r) => setTimeout(r, 400 * Math.pow(2, ticketAttempts - 1)));
          if (!isAttemptActive()) return;
        }
      }

      if (!isAttemptActive()) return;
      if (!ticket) {
        terminateSession('Failed to obtain interview session ticket. Please refresh or try again later.');
        return;
      }
    }

    if (!isAttemptActive()) return;
    url += `?ticket=${encodeURIComponent(ticket)}`;

    try {
      const ws = new WebSocket(url);
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;

      const armStartupWatchdog = (socket) => {
        clearStartupWatchdog();
        startupWatchdogRef.current = setTimeout(() => {
          startupWatchdogRef.current = null;
          if (
            socket !== wsRef.current ||
            isHandshakeCompleteRef.current ||
            isTerminatedRef.current
          ) {
            return;
          }

          // Audio activation is intentionally user-driven. Do not turn a
          // browser autoplay prompt into an opaque terminal failure; the room
          // already displays the activation control in this case.
          if (clientReadySocketRef.current !== socket) {
            const sent = sendClientReadyIfReady(socket);
            if (!sent) {
              setAudioActivationRequired(true);
              return;
            }
          }

          terminateSession(
            'Interview startup timed out before the conductor was ready. Click Retry Connection to try again.'
          );
        }, 15000);
      };

      ws.onopen = async () => {
        if (ws !== wsRef.current || !isComponentMountedRef.current || isTerminatedRef.current) return;
        setConnectionState('connected');
        sendClientReadyIfReady(ws);
        armStartupWatchdog(ws);
      };

      ws.onmessage = (event) => {
        if (ws !== wsRef.current || !isComponentMountedRef.current || isTerminatedRef.current) return;

        // Handle Aura-2 24kHz PCM audio binary stream
        if (event.data instanceof ArrayBuffer) {
          const sid = currentSpeechIdRef.current;
          if (sid) {
            delete bufferDrainedMapRef.current[sid];
          }
          if (audioPipelineRef.current) {
            audioPipelineRef.current.feedPlaybackChunk(
              sid,
              event.data
            );
          } else {
            // Buffer early chunks up to 50 (~1.5s) to guarantee zero greeting drop
            if (earlyAudioBufferRef.current.length < 50) {
              earlyAudioBufferRef.current.push(event.data);
            }
          }
          return;
        }

        // Handle JSON control frames
        try {
          const msg = JSON.parse(event.data);

          if (msg.type === 'SessionConnected') {
            if (msg.question_count) {
              totalSectionsRef.current = msg.question_count;
              setTotalSections(msg.question_count);
            }
            sendClientReadyIfReady(ws);
          } else if (msg.type === 'SessionReady') {
            clearStartupWatchdog();
            isHandshakeCompleteRef.current = true;
            const audioContext = audioCtxRef.current;
            if (audioContext && audioContext.state !== 'running') {
              setAudioActivationRequired(true);
            } else {
              setAudioActivationRequired(false);
            }
            setConnectionState('connected');
            updateStatus('speaking');
          } else if (msg.type === 'SessionError') {
            if (msg.error === 'SessionPersistenceFailed' || msg.detail?.includes('persistence')) {
              setErrorMessage('Persistence failure: finalizing interview via fallback API...');
              if (performRestFallbackRef.current) {
                performRestFallbackRef.current();
              }
            } else if (msg.retryable) {
              setConnectionState('connected');
              setErrorMessage(msg.detail || msg.error || 'Temporary session warning. Retrying...');
            } else {
              terminateSession(msg.detail || msg.error || 'Interview session error');
            }
          } else if (msg.type === 'SessionEnding') {
            setIsEndingSession(true);
            setConnectionState('ending');
            updateStatus('closing');
            if (endTimeoutRef.current) {
              clearTimeout(endTimeoutRef.current);
              endTimeoutRef.current = setTimeout(() => {
                if (performRestFallbackRef.current) {
                  performRestFallbackRef.current();
                }
              }, 14000);
            }
          } else if (msg.type === 'SessionEnded') {
            if (completionFallbackTimerRef.current) {
              clearTimeout(completionFallbackTimerRef.current);
              completionFallbackTimerRef.current = null;
            }
            if (endTimeoutRef.current) {
              clearTimeout(endTimeoutRef.current);
              endTimeoutRef.current = null;
            }
            handleTerminalCleanup();
          } else if (msg.type === 'TTSError') {
            // TTS failure recovered: transition out of stuck speaking
            updateStatus('listening');
            setBotLevel(0);
          } else if (msg.type === 'UIStatus') {
            const newStatus = msg.status;
            if (msg.phase) setPhase(msg.phase);
            if (typeof msg.question_index === 'number') {
              // P1-13: Clamp question_index >= 1000 to totalSections
              if (msg.question_index >= 1000) {
                setCurrentSection(totalSectionsRef.current);
              } else {
                setCurrentSection(msg.question_index + 1);
              }
            }

            // Map UI status
            if (newStatus === 'waiting_for_ready') {
              updateStatus('waiting_for_ready');
            } else if (newStatus === 'completed') {
              updateStatus('completed');
              setConnectionState('completed');
              // P0-2: Do NOT call handleTerminalCleanup() immediately!
              // Arm 5s timer: if SessionEnded does not arrive within 5s, call REST fallback
              if (completionFallbackTimerRef.current) {
                clearTimeout(completionFallbackTimerRef.current);
              }
              completionFallbackTimerRef.current = setTimeout(() => {
                if (!isTerminatedRef.current && performRestFallbackRef.current) {
                  performRestFallbackRef.current();
                }
              }, 5000);
            } else if (newStatus === 'closing') {
              updateStatus('closing');
              setConnectionState('ending');
            } else if (newStatus === 'uncommitted') {
              // Interim answer from candidate
              if (msg.payload?.answer) {
                setCandidateLiveTranscript(msg.payload.answer);
              }
            } else {
              updateStatus(newStatus || 'listening');
            }

            // Update captions if question text received
            const displayQ = msg.payload?.display_question || msg.payload?.question_text;
            if (displayQ) {
              const newText = displayQ.trim();
              setCurrentBotCaption((prev) => {
                if (prev && prev !== newText) {
                  setPreviousBotCaption(prev);
                  // Add to transcript drawer
                  setTranscriptHistory((history) => [
                    ...history,
                    { role: 'bot', text: prev, time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) },
                  ]);
                }
                return newText;
              });
            }

            if (msg.payload?.transition_text || msg.payload?.transition) {
              setBotTransitionText((msg.payload.transition_text || msg.payload.transition).trim());
            } else if (msg.payload?.display_question) {
              setBotTransitionText('');
            }

            if (msg.payload?.topic_index !== undefined) {
              setTopicIndex(Number(msg.payload.topic_index));
            }
            if (msg.payload?.topic_count !== undefined) {
              setTopicCount(Number(msg.payload.topic_count));
            }

            if (msg.payload?.topic_label || msg.payload?.skill) {
              setSkillName(msg.payload.topic_label || msg.payload.skill);
            }
          } else if (msg.type === 'TTSStarted' || msg.type === 'BotSpeechStarted') {
            if (msg.speech_id) {
              currentSpeechIdRef.current = msg.speech_id;
              delete bufferDrainedMapRef.current[msg.speech_id];
              delete ttsDoneMapRef.current[msg.speech_id];
            }
            updateStatus('speaking');
            if (
              msg.text &&
              !msg.is_ack &&
              (!currentBotCaptionRef.current ||
                currentBotCaptionRef.current === 'Preparing your interview environment and audio pipeline...')
            ) {
              setCurrentBotCaption(msg.text.trim());
            }
          } else if (msg.type === 'TTSDone') {
            const sid = msg.speech_id || currentSpeechIdRef.current;
            ttsDoneMapRef.current[sid] = true;
            if (audioPipelineRef.current?.markSpeechDone) {
              audioPipelineRef.current.markSpeechDone(sid);
            }
            if (bufferDrainedMapRef.current[sid]) {
              completePlaybackForSpeech(sid);
            }
          } else if (msg.type === 'TTSCancelled') {
            const sid = currentSpeechIdRef.current;
            delete ttsDoneMapRef.current[sid];
            delete bufferDrainedMapRef.current[sid];
            if (audioPipelineRef.current) {
              audioPipelineRef.current.flushPlayback();
            }
            updateStatus('listening');
            setBotLevel(0);
          } else if (msg.type === 'InterimCaption' || msg.type === 'Update') {
            const text = msg.text || '';
            setCandidateLiveTranscript(text);
          } else if (msg.type === 'CommittedAnswer') {
            const answer = msg.text || '';
            setLastCandidateAnswer(answer);
            setCandidateLiveTranscript('');
            setTranscriptHistory((history) => [
              ...history,
              { role: 'candidate', text: answer, time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) },
            ]);
          }
        } catch (jsonErr) {
          console.warn('Failed to parse WS JSON message:', jsonErr);
        }
      };

      ws.onclose = (event) => {
        if (ws !== wsRef.current || !isComponentMountedRef.current || isTerminatedRef.current) return;
        clearStartupWatchdog();
        if (stableTimerRef.current) {
          clearTimeout(stableTimerRef.current);
          stableTimerRef.current = null;
        }
        const code = event?.code;
        if ([4000, 4003, 4004, 4008, 4401, 4403].includes(code)) {
          const msg =
            code === 4008
              ? 'Interview startup timed out while waiting for the audio handshake. Click Retry Connection to try again.'
              : code === 4401
              ? 'Authentication failed: unauthorized ticket or session token.'
              : code === 4403
              ? 'Access forbidden: you are not authorized for this interview session.'
              : code === 4004
              ? 'Interview session not found.'
              : 'Interview session terminated with terminal error.';
          terminateSession(msg);
          return;
        }

        // Enforce maximum reconnect attempts cap
        if (reconnectAttemptsRef.current >= MAX_RECONNECT_ATTEMPTS) {
          terminateSession('Connection lost. Maximum reconnection attempts exceeded.');
          return;
        }

        setConnectionState('reconnecting');
        // Automatic seamless reconnection with backoff
        const delay = Math.min(10000, 1000 * Math.pow(1.5, reconnectAttemptsRef.current));
        reconnectAttemptsRef.current += 1;
        if (reconnectTimerRef.current) {
          clearTimeout(reconnectTimerRef.current);
        }
        reconnectTimerRef.current = setTimeout(() => {
          if (isComponentMountedRef.current && !isTerminatedRef.current && wsRef.current?.readyState !== WebSocket.OPEN) {
            connectSession();
          }
        }, delay);
      };

      ws.onerror = (err) => {
        console.warn('Interview WS error:', err);
      };
    } catch (err) {
      if (!isAttemptActive()) return;
      console.error('WebSocket connection failed:', err);
      setConnectionState('error');
      setErrorMessage(err.message || 'Failed to establish WebSocket connection');
    }
  }, [
    canonicalSessionId,
    selectedMicId,
    initialAudioOutputId,
    sendClientReadyIfReady,
    attachAudioStateListener,
    clearStartupWatchdog,
    handleTerminalCleanup,
    terminateSession,
    updateStatus,
  ]);

  // Initial startup
  useEffect(() => {
    isComponentMountedRef.current = true;
    isTerminatedRef.current = false;
    refreshDevices();
    initCamera(selectedCameraId);
    connectSession();

    return () => {
      isComponentMountedRef.current = false;
      // Invalidate any async connection attempt that is still awaiting a
      // device, worklet module, ticket, or network response.
      clientConnectionRef.current += 1;
      clearStartupWatchdog();
      detachAudioStateListener();
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (endTimeoutRef.current) {
        clearTimeout(endTimeoutRef.current);
        endTimeoutRef.current = null;
      }
      if (completionFallbackTimerRef.current) {
        clearTimeout(completionFallbackTimerRef.current);
        completionFallbackTimerRef.current = null;
      }
      if (fallbackExitTimerRef.current) {
        clearTimeout(fallbackExitTimerRef.current);
        fallbackExitTimerRef.current = null;
      }
      if (audioPipelineRef.current?.dispose) {
        audioPipelineRef.current.dispose();
        audioPipelineRef.current = null;
      }
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch (e) {}
        wsRef.current = null;
      }
      if (micStreamRef.current) {
        micStreamRef.current.getTracks().forEach((t) => t.stop());
        micStreamRef.current = null;
      }
      if (cameraStreamRef.current) {
        cameraStreamRef.current.getTracks().forEach((t) => t.stop());
        cameraStreamRef.current = null;
      }
      if (audioCtxRef.current && audioCtxRef.current.state !== 'closed') {
        audioCtxRef.current.close().catch(() => {});
      }
      audioCtxRef.current = null;
      clientReadySocketRef.current = null;
    };
  }, [clearStartupWatchdog, detachAudioStateListener]);

  // Resume browser audio after an autoplay/device suspension. This handler is
  // rendered as an explicit room-level prompt so the candidate is never left
  // staring at a silent "preparing" screen while the server waits 60 seconds.
  const enableAudioAndStart = useCallback(async () => {
    const audioContext = audioCtxRef.current;
    if (audioContext?.state === 'suspended') {
      try {
        await audioContext.resume();
      } catch (err) {
        console.warn('Failed to resume AudioContext from activation prompt:', err);
      }
    }

    const contextRunning = audioCtxRef.current?.state === 'running';
    if (!contextRunning || !audioPipelineRef.current) {
      // Rebuild the context/pipeline from a real click gesture.
      setAudioActivationRequired(false);
      setErrorMessage('');
      connectSession();
      return;
    }

    setAudioActivationRequired(false);
    setErrorMessage('');
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      sendClientReadyIfReady();
    } else {
      setConnectionState('preparing_audio');
      connectSession();
    }
  }, [connectSession, sendClientReadyIfReady]);

  // Handle Mute Toggle
  const toggleMicMute = useCallback(() => {
    setIsMicMuted((prev) => {
      const next = !prev;
      isMicMutedRef.current = next;
      if (micStreamRef.current) {
        micStreamRef.current.getAudioTracks().forEach((track) => {
          track.enabled = !next;
        });
      }
      return next;
    });
  }, []);

  // Handle Ready Button
  const handleReadyClick = useCallback(async () => {
    if (audioCtxRef.current && audioCtxRef.current.state === 'suspended') {
      try {
        await audioCtxRef.current.resume();
      } catch (e) {
        console.warn('Failed to resume AudioContext on ready click:', e);
      }
    }

    if (!audioCtxRef.current || audioCtxRef.current.state !== 'running') {
      setErrorMessage('Audio device not ready. Tap again to enable audio.');
      return;
    }

    sendClientReadyIfReady();
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'ready_button' }));
    }
    updateStatus('listening');
  }, [sendClientReadyIfReady, updateStatus]);

  // Handle Test Speakers
  const playTestSpeakerChime = useCallback(() => {
    try {
      const AudioCtxClass = window.AudioContext || window.webkitAudioContext;
      const ctx = new AudioCtxClass();
      const now = ctx.currentTime;

      const osc1 = ctx.createOscillator();
      const osc2 = ctx.createOscillator();
      const gain = ctx.createGain();

      osc1.type = 'sine';
      osc1.frequency.setValueAtTime(587.33, now); // D5
      osc1.frequency.exponentialRampToValueAtTime(880, now + 0.15); // A5

      osc2.type = 'sine';
      osc2.frequency.setValueAtTime(880, now + 0.15);
      osc2.frequency.exponentialRampToValueAtTime(1174.66, now + 0.35); // D6

      gain.gain.setValueAtTime(0.2, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.45);

      osc1.connect(gain);
      osc2.connect(gain);
      gain.connect(ctx.destination);

      osc1.start(now);
      osc1.stop(now + 0.15);
      osc2.start(now + 0.15);
      osc2.stop(now + 0.45);
    } catch (e) {
      console.warn('Audio test speaker playback failed:', e);
    }
  }, []);

  // Bounded REST fallback if WS terminal ack doesn't arrive within bounded time
  const performRestFallback = useCallback(async () => {
    if (endFallbackAttemptedRef.current || isTerminatedRef.current) return;
    endFallbackAttemptedRef.current = true;
    const controller = new AbortController();
    const abortTimeout = setTimeout(() => controller.abort(), 8000);
    try {
      const tokenToUse =
        token ||
        localStorage.getItem('candidly-auth-token-candidate') ||
        localStorage.getItem('candidly-auth-token');
      const res = await fetch(`/api/interview-sessions/${canonicalSessionId}/end`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(tokenToUse ? { Authorization: `Bearer ${tokenToUse}` } : {}),
        },
        signal: controller.signal,
      });
      clearTimeout(abortTimeout);
      if (res.ok) {
        handleTerminalCleanup();
        return;
      }
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || 'Failed to end session via API');
    } catch (err) {
      clearTimeout(abortTimeout);
      console.error('REST end interview fallback failed:', err);
      setIsEndingSession(false);
      endFallbackAttemptedRef.current = false;
      setErrorMessage('Unable to persist session completion to server. Returning to your dashboard...');

      // Persist a dashboard notice before leaving. The room still offers
      // "Exit Room Anyway" during the short delay, but the user is never
      // stranded on the error screen if they do nothing.
      try {
        sessionStorage.setItem(
          INTERVIEW_EXIT_NOTICE_KEY,
          'Your interview ended, but completion could not be confirmed with the server. Please check your application status or contact support if it still shows in progress.'
        );
      } catch (storageErr) {
        console.warn('Could not persist interview exit notice:', storageErr);
      }

      if (fallbackExitTimerRef.current) {
        clearTimeout(fallbackExitTimerRef.current);
      }
      fallbackExitTimerRef.current = setTimeout(() => {
        fallbackExitTimerRef.current = null;
        handleTerminalCleanup();
      }, PERSISTENCE_FAILURE_EXIT_DELAY_MS);
    }
  }, [canonicalSessionId, token, handleTerminalCleanup]);

  useEffect(() => {
    performRestFallbackRef.current = performRestFallback;
  }, [performRestFallback]);

  // Handle End Interview with unique request ID and REST fallback
  const handleConfirmEndInterview = useCallback(async () => {
    if (isEndingSession) return;
    if (fallbackExitTimerRef.current) {
      clearTimeout(fallbackExitTimerRef.current);
      fallbackExitTimerRef.current = null;
    }
    setIsEndingSession(true);

    const requestId = `end_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
    const socketOpen = wsRef.current && wsRef.current.readyState === WebSocket.OPEN;

    if (socketOpen) {
      try {
        wsRef.current.send(JSON.stringify({ type: 'end_button', request_id: requestId }));
      } catch (err) {
        console.warn('Failed to send end_button on WebSocket:', err);
      }
    }

    if (!socketOpen) {
      await performRestFallback();
    } else {
      endTimeoutRef.current = setTimeout(performRestFallback, 3500);
    }
  }, [isEndingSession, performRestFallback]);

  // Status badge config
  const statusConfig = {
    listening: { label: 'Listening', dotColor: 'bg-emerald-400', textColor: 'text-emerald-300' },
    thinking: { label: 'Thinking', dotColor: 'bg-amber-400', textColor: 'text-amber-300' },
    speaking: { label: 'Speaking', dotColor: 'bg-teal-400', textColor: 'text-teal-300' },
    waiting_for_ready: { label: 'Ready Gate', dotColor: 'bg-teal-400', textColor: 'text-teal-300' },
    preparing_audio: { label: 'Preparing Audio', dotColor: 'bg-teal-400', textColor: 'text-teal-300' },
    closing: { label: 'Concluding...', dotColor: 'bg-amber-400', textColor: 'text-amber-300' },
    completed: { label: 'Interview Finished', dotColor: 'bg-zinc-400', textColor: 'text-zinc-300' },
    failed: { label: 'Connection Failed', dotColor: 'bg-rose-400', textColor: 'text-rose-300' },
  }[status] || { label: 'Connecting...', dotColor: 'bg-zinc-500', textColor: 'text-zinc-400' };

  if ((!canonicalSessionId || connectionState === 'error') && !mockState?.skipConnect) {
    return (
      <div
        data-testid="live-interview-room-error"
        className="fixed inset-0 z-50 flex h-full w-full flex-col items-center justify-center bg-black text-white p-6 font-sans select-none"
      >
        <div className="max-w-md w-full rounded-2xl border border-rose-900/60 bg-zinc-950 p-6 text-center space-y-4 shadow-2xl">
          <div className="w-12 h-12 rounded-full bg-rose-500/10 text-rose-400 flex items-center justify-center mx-auto">
            <AlertTriangle className="w-6 h-6" />
          </div>
          <h2 className="text-lg font-semibold text-white">Interview Session Unavailable</h2>
          <p className="text-xs text-zinc-400 leading-relaxed" data-testid="error-message">
            {errorMessage || 'The interview session identifier was missing or invalid. Please return to your dashboard and launch the interview again.'}
          </p>
          <div className="flex flex-col sm:flex-row gap-2 pt-2">
            {canonicalSessionId && (
              <button
                type="button"
                data-testid="retry-connection-button"
                onClick={() => {
                  isTerminatedRef.current = false;
                  // A manual retry gets a fresh reconnection budget. Without
                  // this, one close after the fifth automatic attempt is
                  // immediately treated as terminal again.
                  reconnectAttemptsRef.current = 0;
                  setErrorMessage('');
                  setConnectionState('preparing_audio');
                  connectSession();
                }}
                className="flex-1 py-2.5 px-4 rounded-xl bg-teal-600 hover:bg-teal-500 text-xs font-semibold text-white transition flex items-center justify-center gap-1.5"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                <span>Retry Connection</span>
              </button>
            )}
            <button
              type="button"
              data-testid="exit-to-dashboard-button"
              onClick={canonicalOnExit}
              className="flex-1 py-2.5 px-4 rounded-xl bg-zinc-800 hover:bg-zinc-700 text-xs font-semibold text-white transition"
            >
              Return to Candidate Dashboard
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      data-testid="live-interview-room"
      className="fixed inset-0 z-50 flex h-full w-full flex-col bg-black text-white select-none overflow-hidden font-sans"
    >
      {/* 1. Top Bar */}
      <header className="relative z-20 flex h-16 w-full items-center justify-between px-6 md:px-10 border-b border-zinc-900/60 bg-black/40 backdrop-blur-md">
        {/* Left: Job Title and Skill */}
        <div className="flex items-center gap-3">
          <div className="h-2 w-2 rounded-full bg-teal-400" />
          <div>
            <h1 data-testid="room-job-title" className="text-sm font-semibold tracking-wide text-zinc-100">
              {isPractice ? `Practice Interview • ${durationMins}m` : jobTitle}
            </h1>
            {skillName && (
              <p className="text-[11px] font-medium text-zinc-400 uppercase tracking-wider">
                Topic: {skillName}
              </p>
            )}
          </div>
        </div>

        {/* Center: Thin Section Progress Indicator (No countdown pressure) */}
        <div className="flex flex-col items-center gap-1.5" data-testid="progress-indicator">
          <span className="text-[11px] font-medium text-zinc-400 tracking-wider">
            {topicCount > 0 && topicIndex > 0
              ? `Topic ${topicIndex} of ${topicCount}`
              : `Section ${currentSection} of ${totalSections}`}
          </span>
          <div className="h-1 w-32 md:w-48 rounded-full bg-zinc-900 overflow-hidden">
            <div
              className="h-full bg-teal-500 transition-all duration-500 ease-out"
              style={{
                width: `${
                  topicCount > 0 && topicIndex > 0
                    ? Math.min(100, (topicIndex / topicCount) * 100)
                    : Math.min(100, (currentSection / totalSections) * 100)
                }%`,
              }}
            />
          </div>
        </div>

        {/* Right: End Interview Button with red outline */}
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setConfirmExitOpen(true)}
            data-testid="end-interview-button"
            className="flex items-center gap-1.5 rounded-full border border-rose-500/50 bg-rose-950/20 px-3.5 py-1.5 text-xs font-medium text-rose-300 transition-colors hover:border-rose-400 hover:bg-rose-900/30 active:scale-95"
          >
            <PhoneOff className="h-3.5 w-3.5 text-rose-400" />
            <span>End interview</span>
          </button>
        </div>
      </header>

      {/* Floating Reconnection Banner */}
      {connectionState === 'reconnecting' && (
        <div
          data-testid="reconnect-banner"
          className="absolute top-20 left-1/2 -translate-x-1/2 z-40 flex items-center gap-2.5 rounded-full border border-amber-500/30 bg-amber-950/70 px-4 py-2 text-xs font-medium text-amber-200 shadow-xl backdrop-blur-md animate-pulse"
        >
          <RefreshCw className="h-3.5 w-3.5 animate-spin text-amber-400" />
          <span>Reconnecting to interview session...</span>
        </div>
      )}

      {/* Browser audio activation gate (autoplay policy / suspended device) */}
      {audioActivationRequired && connectionState !== 'error' && (
        <div
          data-testid="audio-activation-overlay"
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="audio-activation-title"
          className="absolute inset-0 z-[60] flex items-center justify-center bg-black/75 p-6 backdrop-blur-sm"
        >
          <div className="w-full max-w-md rounded-2xl border border-teal-700/50 bg-zinc-950 p-6 text-center shadow-2xl">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-teal-500/10 text-teal-300">
              <Volume2 className="h-6 w-6" />
            </div>
            <h2 id="audio-activation-title" className="mt-4 text-lg font-semibold text-white">
              Enable interview audio
            </h2>
            <p className="mt-2 text-xs leading-relaxed text-zinc-400">
              Your browser paused audio playback. Tap the button below to let the interviewer
              greet you and begin the session.
            </p>
            {errorMessage && (
              <p className="mt-3 text-xs font-medium text-rose-300" data-testid="audio-activation-error">
                {errorMessage}
              </p>
            )}
            <button
              type="button"
              data-testid="enable-audio-button"
              onClick={enableAudioAndStart}
              className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-teal-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-teal-500 active:scale-[0.99]"
            >
              <Volume2 className="h-4 w-4" />
              <span>Enable Audio &amp; Start</span>
            </button>
          </div>
        </div>
      )}

      {/* Floating Mic Muted Warning Banner */}
      {isMicMuted && (
        <div
          data-testid="muted-banner"
          className="absolute top-20 left-1/2 -translate-x-1/2 z-30 flex items-center gap-2 rounded-full border border-amber-500/40 bg-zinc-950/80 px-4 py-1.5 text-xs font-medium text-amber-300 shadow-lg backdrop-blur-md"
        >
          <MicOff className="h-3.5 w-3.5 text-amber-400" />
          <span>Microphone is muted — unmute to speak</span>
        </div>
      )}

      {/* 2. Main Content Area */}
      <main className="relative z-10 flex flex-1 flex-col md:flex-row items-center justify-between px-6 md:px-14 lg:px-20 pt-6 pb-28 gap-8 overflow-hidden">
        {/* Left Side: Bot Captions, Status Line, and Candidate Bubble */}
        <div className="flex flex-1 flex-col justify-center max-w-2xl w-full z-10">
          {/* Previous Bot Caption (Dimmed Above) */}
          {previousBotCaption && (
            <p
              data-testid="previous-caption"
              className="mb-3 text-base md:text-lg font-light text-zinc-600 line-clamp-2 transition-opacity duration-700 select-text"
            >
              {previousBotCaption}
            </p>
          )}

          {/* Transition Line (Muted Above) */}
          {botTransitionText && (
            <p
              data-testid="bot-transition-line"
              className="mb-2 text-sm md:text-base font-normal text-zinc-400 leading-relaxed select-text"
            >
              {botTransitionText}
            </p>
          )}

          {/* Current Bot Caption (Core question displayed legibly) */}
          <div className="min-h-[70px] flex items-center">
            <p
              data-testid="current-bot-caption"
              className="text-base sm:text-lg lg:text-xl font-normal leading-relaxed text-zinc-100 max-w-[68ch] break-words tracking-normal transition-all duration-300 select-text"
            >
              {currentBotCaption}
            </p>
          </div>

          {/* Status Line with Small Animated Dot Grid */}
          <div className="mt-6 flex items-center gap-3" data-testid="status-line">
            {/* Animated 3x3 Dot Grid */}
            <div className="grid grid-cols-3 gap-1 w-4 h-4 p-0.5">
              {[...Array(9)].map((_, i) => (
                <span
                  key={i}
                  className={`w-1 h-1 rounded-full transition-all duration-300 ${
                    status === 'speaking'
                      ? 'bg-teal-400 animate-pulse'
                      : status === 'thinking'
                      ? 'bg-amber-400 animate-ping'
                      : status === 'listening'
                      ? 'bg-emerald-400'
                      : 'bg-zinc-600'
                  }`}
                  style={{ animationDelay: `${(i % 3) * 120}ms` }}
                />
              ))}
            </div>

            <span className={`text-xs font-medium uppercase tracking-wider ${statusConfig.textColor}`}>
              {statusConfig.label}
            </span>

            {/* Actionable Error Notice for Audio or Device warning */}
            {errorMessage && connectionState !== 'error' && (
              <span className="ml-3 text-xs text-rose-400 font-medium" data-testid="audio-device-error">
                {errorMessage}
              </span>
            )}
          </div>

          {/* Candidate Finished Answer (Right-aligned in rounded dark bubble) */}
          {(lastCandidateAnswer || candidateLiveTranscript) && (
            <div className="mt-8 flex justify-end">
              <div
                data-testid="candidate-bubble"
                className="max-w-xl rounded-2xl border border-zinc-800 bg-zinc-900/90 px-5 py-3 shadow-2xl backdrop-blur-md"
              >
                <p className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500 mb-1">
                  {candidateLiveTranscript ? 'Speaking...' : 'Your Answer'}
                </p>
                <p className="text-sm md:text-base text-zinc-200 leading-relaxed select-text">
                  {candidateLiveTranscript || lastCandidateAnswer}
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Right Side: Mirrored Local Camera Tile with Mic-Level Meter in Corner */}
        <div className="flex items-center justify-center z-10">
          <div
            data-testid="camera-tile"
            className="relative h-48 w-64 md:h-60 md:w-80 rounded-2xl border border-zinc-800 bg-zinc-950 shadow-2xl overflow-hidden flex items-center justify-center"
          >
            {isVideoOff ? (
              <div className="flex flex-col items-center gap-2 text-zinc-600">
                <VideoOff className="h-8 w-8" />
                <span className="text-xs font-medium text-zinc-500">{candidateName}</span>
              </div>
            ) : (
              <video
                ref={videoElementRef}
                autoPlay
                playsInline
                muted
                className="h-full w-full object-cover scale-x-[-1]"
              />
            )}

            {/* Corner Mic-Level Meter */}
            <div
              data-testid="corner-mic-meter"
              className="absolute bottom-2.5 left-2.5 flex items-center gap-1.5 rounded-full bg-black/60 px-2.5 py-1 backdrop-blur-md border border-zinc-800/80"
            >
              <Mic className={`h-3 w-3 ${isMicMuted ? 'text-rose-400' : 'text-teal-400'}`} />
              <div className="h-1.5 w-12 rounded-full bg-zinc-800 overflow-hidden">
                <div
                  className={`h-full transition-all duration-75 ${isMicMuted ? 'bg-rose-500' : 'bg-teal-400'}`}
                  style={{ width: `${Math.round(micLevel * 100)}%` }}
                />
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* 3. Dotted Wave / Dome Visualizer across screen bottom */}
      <AudioDomeVisualizer
        status={status}
        audioLevel={audioLevel}
        className="z-0"
      />

      {/* 4. Bottom Center Pill Control Bar */}
      <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-30 flex items-center gap-2 rounded-full border border-zinc-800/80 bg-zinc-950/80 px-3 py-2 shadow-2xl backdrop-blur-lg">
        {/* Button 1: Mic Mute */}
        <button
          type="button"
          onClick={toggleMicMute}
          data-testid="pill-mic-toggle"
          title={isMicMuted ? 'Unmute microphone' : 'Mute microphone'}
          className={`relative flex h-10 w-10 items-center justify-center rounded-full transition-all active:scale-95 ${
            isMicMuted
              ? 'bg-rose-500/20 text-rose-300 border border-rose-500/40 hover:bg-rose-500/30'
              : 'text-zinc-300 hover:bg-zinc-800/70 hover:text-white'
          }`}
        >
          {isMicMuted ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
        </button>

        {/* Button 2: Device Settings */}
        <div className="relative">
          <button
            type="button"
            onClick={() => setIsSettingsOpen((prev) => !prev)}
            data-testid="pill-settings-toggle"
            title="Audio and video settings"
            className={`flex h-10 w-10 items-center justify-center rounded-full transition-all active:scale-95 ${
              isSettingsOpen
                ? 'bg-zinc-800 text-teal-300'
                : 'text-zinc-300 hover:bg-zinc-800/70 hover:text-white'
            }`}
          >
            <Sliders className="h-4 w-4" />
          </button>

          {/* Device Settings Popover */}
          {isSettingsOpen && (
            <div
              data-testid="device-settings-popover"
              className="absolute bottom-14 left-1/2 -translate-x-1/2 w-80 rounded-2xl border border-zinc-800 bg-zinc-950 p-4 shadow-2xl backdrop-blur-xl z-50 text-xs"
            >
              <div className="flex items-center justify-between pb-3 border-b border-zinc-800">
                <span className="font-semibold text-zinc-200">Device Settings</span>
                <button
                  type="button"
                  onClick={() => setIsSettingsOpen(false)}
                  className="text-zinc-400 hover:text-zinc-200"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>

              {/* Microphone Selector + Live Level */}
              <div className="mt-3">
                <label className="text-[11px] font-medium text-zinc-400 mb-1 block">Microphone</label>
                <select
                  value={selectedMicId}
                  onChange={(e) => switchMicrophone(e.target.value)}
                  className="w-full rounded-lg border border-zinc-800 bg-zinc-900 px-2.5 py-1.5 text-zinc-200 text-xs focus:outline-none focus:border-teal-500"
                >
                  {audioInputDevices.map((d) => (
                    <option key={d.deviceId} value={d.deviceId}>
                      {d.label || `Microphone ${d.deviceId.slice(0, 5)}`}
                    </option>
                  ))}
                </select>
                {/* Live Mic Level Bar */}
                <div className="mt-1.5 flex items-center gap-2">
                  <span className="text-[10px] text-zinc-500">Level:</span>
                  <div className="flex-1 h-1.5 rounded-full bg-zinc-800 overflow-hidden">
                    <div
                      className="h-full bg-teal-400 transition-all duration-75"
                      style={{ width: `${Math.round(micLevel * 100)}%` }}
                    />
                  </div>
                </div>
              </div>

              {/* Speaker Selector + Test Speakers */}
              <div className="mt-3">
                <div className="flex items-center justify-between mb-1">
                  <label className="text-[11px] font-medium text-zinc-400">Speaker</label>
                  <button
                    type="button"
                    onClick={playTestSpeakerChime}
                    data-testid="test-speakers-btn"
                    className="text-[10px] text-teal-400 hover:underline flex items-center gap-1"
                  >
                    <Volume2 className="h-3 w-3" /> Test speakers
                  </button>
                </div>
                <select
                  value={selectedSpeakerId}
                  onChange={(e) => switchSpeaker(e.target.value)}
                  className="w-full rounded-lg border border-zinc-800 bg-zinc-900 px-2.5 py-1.5 text-zinc-200 text-xs focus:outline-none focus:border-teal-500"
                >
                  {audioOutputDevices.map((d) => (
                    <option key={d.deviceId} value={d.deviceId}>
                      {d.label || `Speaker ${d.deviceId.slice(0, 5)}`}
                    </option>
                  ))}
                </select>
              </div>

              {/* Camera Selector */}
              <div className="mt-3">
                <label className="text-[11px] font-medium text-zinc-400 mb-1 block">Camera</label>
                <select
                  value={selectedCameraId}
                  onChange={(e) => {
                    setSelectedCameraId(e.target.value);
                    initCamera(e.target.value);
                  }}
                  className="w-full rounded-lg border border-zinc-800 bg-zinc-900 px-2.5 py-1.5 text-zinc-200 text-xs focus:outline-none focus:border-teal-500"
                >
                  {videoInputDevices.map((d) => (
                    <option key={d.deviceId} value={d.deviceId}>
                      {d.label || `Camera ${d.deviceId.slice(0, 5)}`}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          )}
        </div>

        {/* Button 3: Transcript Toggle */}
        <button
          type="button"
          onClick={() => setIsTranscriptOpen((prev) => !prev)}
          data-testid="pill-transcript-toggle"
          title="Toggle transcript"
          className={`flex h-10 w-10 items-center justify-center rounded-full transition-all active:scale-95 ${
            isTranscriptOpen
              ? 'bg-zinc-800 text-teal-300'
              : 'text-zinc-300 hover:bg-zinc-800/70 hover:text-white'
          }`}
        >
          <FileText className="h-4 w-4" />
        </button>
      </div>

      {/* 5. Transcript Slide-Out Drawer */}
      {isTranscriptOpen && (
        <aside
          data-testid="transcript-drawer"
          className="fixed top-0 right-0 z-40 h-full w-full max-w-md border-l border-zinc-800 bg-zinc-950/95 p-6 shadow-2xl backdrop-blur-xl flex flex-col"
        >
          <div className="flex items-center justify-between pb-4 border-b border-zinc-800">
            <h2 className="text-sm font-semibold text-zinc-100 flex items-center gap-2">
              <FileText className="h-4 w-4 text-teal-400" />
              Interview Transcript
            </h2>
            <button
              type="button"
              onClick={() => setIsTranscriptOpen(false)}
              className="text-zinc-400 hover:text-zinc-200"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto py-4 space-y-4">
            {transcriptHistory.length === 0 ? (
              <p className="text-xs text-zinc-500 text-center py-8">
                Conversation turns will appear here as you speak.
              </p>
            ) : (
              transcriptHistory.map((item, idx) => (
                <div
                  key={idx}
                  className={`rounded-xl p-3 text-xs leading-relaxed ${
                    item.role === 'bot'
                      ? 'bg-zinc-900 border border-zinc-800 text-zinc-300'
                      : 'bg-teal-950/40 border border-teal-800/40 text-teal-200 ml-4'
                  }`}
                >
                  <div className="flex items-center justify-between text-[10px] text-zinc-500 mb-1">
                    <span className="font-semibold uppercase tracking-wider">
                      {item.role === 'bot' ? 'Interviewer' : candidateName}
                    </span>
                    <span>{item.time}</span>
                  </div>
                  <p>{item.text}</p>
                </div>
              ))
            )}
          </div>
        </aside>
      )}

      {/* 6. End Interview Confirmation Dialog */}
      {confirmExitOpen && (
        <div
          data-testid="end-confirm-modal"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-md"
        >
          <div className="w-full max-w-sm rounded-2xl border border-zinc-800 bg-zinc-950 p-6 shadow-2xl">
            <div className="flex items-center gap-3 text-rose-400 mb-3">
              <AlertTriangle className="h-5 w-5" />
              <h3 className="text-base font-semibold text-white">End Interview?</h3>
            </div>
            <p className="text-xs text-zinc-400 leading-relaxed">
              Are you sure you want to end your interview session now? Your responses recorded so far will be saved and evaluated.
            </p>
            {errorMessage && (
              <div className="mt-3 p-2.5 rounded-xl bg-rose-950/40 border border-rose-900/50 text-[11px] text-rose-300">
                {errorMessage}
              </div>
            )}
            <div className="mt-6 flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={() => setConfirmExitOpen(false)}
                className="rounded-full border border-zinc-800 bg-zinc-900 px-4 py-2 text-xs font-medium text-zinc-300 hover:bg-zinc-800 transition"
              >
                Continue Interview
              </button>
              {errorMessage && !isEndingSession ? (
                <button
                  type="button"
                  data-testid="force-exit-button"
                  onClick={handleTerminalCleanup}
                  className="rounded-full bg-zinc-800 px-4 py-2 text-xs font-medium text-white hover:bg-zinc-700 transition"
                >
                  Exit Room Anyway
                </button>
              ) : (
                <button
                  type="button"
                  onClick={handleConfirmEndInterview}
                  disabled={isEndingSession}
                  data-testid="confirm-end-button"
                  className="flex items-center gap-1.5 rounded-full bg-rose-600 px-4 py-2 text-xs font-medium text-white hover:bg-rose-500 transition shadow-lg"
                >
                  {isEndingSession ? (
                    <>
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      <span>Ending...</span>
                    </>
                  ) : (
                    <span>Confirm & End</span>
                  )}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
