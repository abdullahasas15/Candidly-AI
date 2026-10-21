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
export default function LiveInterviewRoom({
  sessionId,
  session,
  jobTitle = 'Technical Interview',
  candidateName = 'Candidate',
  durationMins = 20,
  token,
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
  const [phase, setPhase] = useState(mockState?.phase || 'welcome');
  const [status, setStatus] = useState(mockState?.status || 'waiting_for_ready'); // 'listening' | 'thinking' | 'speaking' | 'waiting_for_ready' | 'preparing_audio' | 'completed' | 'failed'
  const statusRef = useRef(status);
  const [currentSection, setCurrentSection] = useState(mockState?.currentSection || 1);
  const [totalSections, setTotalSections] = useState(mockState?.totalSections || 5);
  const [skillName, setSkillName] = useState(mockState?.skillName || '');

  // Captions
  const [currentBotCaption, setCurrentBotCaption] = useState(
    mockState?.currentBotCaption || 'Preparing your interview environment and audio pipeline...'
  );
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

  const updateStatus = useCallback((newStatus) => {
    statusRef.current = newStatus;
    setStatus(newStatus);
  }, []);

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
  const [selectedMicId, setSelectedMicId] = useState('');
  const [selectedSpeakerId, setSelectedSpeakerId] = useState('');
  const [selectedCameraId, setSelectedCameraId] = useState('');

  // Modals & Popovers
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isTranscriptOpen, setIsTranscriptOpen] = useState(false);
  const [confirmExitOpen, setConfirmExitOpen] = useState(mockState?.confirmExitOpen || false);
  const [isEndingSession, setIsEndingSession] = useState(false);

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
  const clientReadySentRef = useRef(false);
  const isHandshakeCompleteRef = useRef(false);
  const isTerminatedRef = useRef(false);
  const reconnectTimerRef = useRef(null);
  const endTimeoutRef = useRef(null);
  const endFallbackAttemptedRef = useRef(false);

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

  // Send client_ready event once WebSocket is OPEN and Audio Pipeline is running
  const sendClientReadyIfReady = useCallback(() => {
    if (
      wsRef.current &&
      wsRef.current.readyState === WebSocket.OPEN &&
      audioPipelineRef.current &&
      !clientReadySentRef.current
    ) {
      clientReadySentRef.current = true;
      wsRef.current.send(
        JSON.stringify({
          type: 'client_ready',
          sample_rate: audioCtxRef.current?.sampleRate || 24000,
        })
      );
    }
  }, []);

  // Terminal cleanup stops all hardware and invokes exit
  const handleTerminalCleanup = useCallback(() => {
    isTerminatedRef.current = true;
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (endTimeoutRef.current) {
      clearTimeout(endTimeoutRef.current);
      endTimeoutRef.current = null;
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
    if (wsRef.current) {
      try {
        wsRef.current.close();
      } catch (e) {}
      wsRef.current = null;
    }
    canonicalOnExit();
  }, [canonicalOnExit]);

  // Connect WebSocket & audio pipeline
  const connectSession = useCallback(async () => {
    if (!canonicalSessionId || mockState?.skipConnect) return;

    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }

    // Reset or close existing WS
    if (wsRef.current) {
      try {
        wsRef.current.close();
      } catch (e) {}
      wsRef.current = null;
    }

    clientReadySentRef.current = false;
    isHandshakeCompleteRef.current = false;
    setConnectionState('preparing_audio');

    // 1. Initialize Audio Pipeline first
    try {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!audioCtxRef.current || audioCtxRef.current.state === 'closed') {
        audioCtxRef.current = new AudioContextClass({ sampleRate: 24000 });
      }
      if (audioCtxRef.current.state === 'suspended') {
        await audioCtxRef.current.resume();
      }

      // Microphone stream
      if (!micStreamRef.current && navigator.mediaDevices?.getUserMedia) {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
            channelCount: 1,
            deviceId: selectedMicId ? { exact: selectedMicId } : undefined,
          },
        });
        micStreamRef.current = stream;
      }

      // Initialize Audio Worklets
      if (audioCtxRef.current && micStreamRef.current) {
        const pipeline = await initAudioPipeline({
          audioCtx: audioCtxRef.current,
          micStream: micStreamRef.current,
          onPcmChunk: (buffer) => {
            // Microphone gate: never transmit candidate PCM until startup handshake completes and bot is listening
            const currentStatus = statusRef.current;
            const isGateOpen = currentStatus === 'listening' || currentStatus === 'talking';
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
          onPlaybackEnded: (speechId) => {
            updateStatus('listening');
            setBotLevel(0);
            if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
              wsRef.current.send(JSON.stringify({ type: 'playback_ended', speech_id: speechId }));
            }
          },
          onMicLevel: (lvl) => {
            setMicLevel(isMicMutedRef.current ? 0 : lvl);
          },
          onBotLevel: (lvl) => {
            setBotLevel(lvl);
          },
        });
        audioPipelineRef.current = pipeline;

        // Drain any early buffered chunks
        if (earlyAudioBufferRef.current.length > 0) {
          earlyAudioBufferRef.current.forEach((chunk) => {
            pipeline.feedPlaybackChunk(currentSpeechIdRef.current, chunk);
          });
          earlyAudioBufferRef.current = [];
        }
      }
    } catch (audioErr) {
      console.warn('Audio initialization warning:', audioErr);
      // In mock/test environments getUserMedia might be unmocked
    }

    // 2. Open WebSocket
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const url = `${proto}//${host}/ws/interview/${canonicalSessionId}`;

    try {
      const ws = new WebSocket(url);
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;

      ws.onopen = async () => {
        if (!isComponentMountedRef.current) return;
        reconnectAttemptsRef.current = 0;
        setConnectionState('connected');
        sendClientReadyIfReady();
      };

      ws.onmessage = (event) => {
        // Handle Aura-2 24kHz PCM audio binary stream
        if (event.data instanceof ArrayBuffer) {
          if (audioPipelineRef.current) {
            audioPipelineRef.current.feedPlaybackChunk(
              currentSpeechIdRef.current,
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
              setTotalSections(msg.question_count);
            }
            sendClientReadyIfReady();
          } else if (msg.type === 'SessionReady') {
            isHandshakeCompleteRef.current = true;
            setConnectionState('connected');
            updateStatus('waiting_for_ready');
          } else if (msg.type === 'SessionError') {
            setConnectionState('error');
            setErrorMessage(msg.detail || msg.error || 'Interview session error');
            updateStatus('failed');
          } else if (msg.type === 'SessionEnded') {
            handleTerminalCleanup();
          } else if (msg.type === 'TTSError') {
            // TTS failure recovered: transition out of stuck speaking
            updateStatus('listening');
            setBotLevel(0);
          } else if (msg.type === 'UIStatus') {
            const newStatus = msg.status;
            if (msg.phase) setPhase(msg.phase);
            if (typeof msg.question_index === 'number') {
              setCurrentSection(msg.question_index + 1);
            }

            // Map UI status
            if (newStatus === 'waiting_for_ready') {
              updateStatus('waiting_for_ready');
            } else if (newStatus === 'completed') {
              updateStatus('completed');
              setConnectionState('completed');
              handleTerminalCleanup();
            } else if (newStatus === 'uncommitted') {
              // Interim answer from candidate
              if (msg.payload?.answer) {
                setCandidateLiveTranscript(msg.payload.answer);
              }
            } else {
              updateStatus(newStatus || 'listening');
            }

            // Update captions if question text received
            if (msg.payload?.question_text) {
              const newText = msg.payload.question_text.trim();
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

            if (msg.payload?.skill) {
              setSkillName(msg.payload.skill);
            }
          } else if (msg.type === 'TTSStarted') {
            currentSpeechIdRef.current = msg.speech_id;
            updateStatus('speaking');
            if (msg.text) {
              const newText = msg.text.trim();
              setCurrentBotCaption((prev) => {
                if (prev && prev !== newText) {
                  setPreviousBotCaption(prev);
                }
                return newText;
              });
            }
          } else if (msg.type === 'TTSDone') {
            // Buffer will drain and playback_ended will trigger onPlaybackEnded
          } else if (msg.type === 'TTSCancelled') {
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

      ws.onclose = () => {
        if (!isComponentMountedRef.current || isTerminatedRef.current) return;
        setConnectionState('reconnecting');
        // Automatic seamless reconnection with backoff
        const delay = Math.min(10000, 1000 * Math.pow(1.5, reconnectAttemptsRef.current));
        reconnectAttemptsRef.current += 1;
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
      console.error('WebSocket connection failed:', err);
      setConnectionState('error');
      setErrorMessage(err.message || 'Failed to establish WebSocket connection');
    }
  }, [canonicalSessionId, selectedMicId, sendClientReadyIfReady, handleTerminalCleanup, updateStatus]);

  // Initial startup
  useEffect(() => {
    isComponentMountedRef.current = true;
    isTerminatedRef.current = false;
    refreshDevices();
    initCamera(selectedCameraId);
    connectSession();

    return () => {
      isComponentMountedRef.current = false;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
      if (endTimeoutRef.current) {
        clearTimeout(endTimeoutRef.current);
      }
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch (e) {}
      }
      if (micStreamRef.current) {
        micStreamRef.current.getTracks().forEach((t) => t.stop());
      }
      if (cameraStreamRef.current) {
        cameraStreamRef.current.getTracks().forEach((t) => t.stop());
      }
      if (audioCtxRef.current && audioCtxRef.current.state !== 'closed') {
        audioCtxRef.current.close().catch(() => {});
      }
    };
  }, []);

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
  const handleReadyClick = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'ready_button' }));
    }
    updateStatus('listening');
  }, [updateStatus]);

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

  // Handle End Interview with unique request ID and REST fallback
  const handleConfirmEndInterview = useCallback(async () => {
    if (isEndingSession) return;
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

    // Bounded REST fallback if WS terminal ack doesn't arrive within 3.5s
    const performRestFallback = async () => {
      if (endFallbackAttemptedRef.current || isTerminatedRef.current) return;
      endFallbackAttemptedRef.current = true;
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
        });
        if (res.ok) {
          handleTerminalCleanup();
          return;
        }
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to end session via API');
      } catch (err) {
        console.error('REST end interview fallback failed:', err);
        setIsEndingSession(false);
        setErrorMessage('Unable to persist session completion to server. You can exit anyway.');
      }
    };

    if (!socketOpen) {
      await performRestFallback();
    } else {
      endTimeoutRef.current = setTimeout(performRestFallback, 3500);
    }
  }, [isEndingSession, canonicalSessionId, token, handleTerminalCleanup]);

  // Status badge config
  const statusConfig = {
    listening: { label: 'Listening', dotColor: 'bg-emerald-400', textColor: 'text-emerald-300' },
    thinking: { label: 'Thinking', dotColor: 'bg-amber-400', textColor: 'text-amber-300' },
    speaking: { label: 'Speaking', dotColor: 'bg-teal-400', textColor: 'text-teal-300' },
    waiting_for_ready: { label: 'Ready Gate', dotColor: 'bg-teal-400', textColor: 'text-teal-300' },
    preparing_audio: { label: 'Preparing Audio', dotColor: 'bg-teal-400', textColor: 'text-teal-300' },
    completed: { label: 'Interview Finished', dotColor: 'bg-zinc-400', textColor: 'text-zinc-300' },
    failed: { label: 'Connection Failed', dotColor: 'bg-rose-400', textColor: 'text-rose-300' },
  }[status] || { label: 'Connecting...', dotColor: 'bg-zinc-500', textColor: 'text-zinc-400' };

  if (!canonicalSessionId && !mockState?.skipConnect) {
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
          <p className="text-xs text-zinc-400 leading-relaxed">
            {errorMessage || 'The interview session identifier was missing or invalid. Please return to your dashboard and launch the interview again.'}
          </p>
          <button
            type="button"
            data-testid="exit-to-dashboard-button"
            onClick={canonicalOnExit}
            className="w-full py-2.5 px-4 rounded-xl bg-zinc-800 hover:bg-zinc-700 text-xs font-semibold text-white transition"
          >
            Return to Candidate Dashboard
          </button>
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
            <h1 className="text-sm font-semibold tracking-wide text-zinc-100">{jobTitle}</h1>
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
            Section {currentSection} of {totalSections}
          </span>
          <div className="h-1 w-32 md:w-48 rounded-full bg-zinc-900 overflow-hidden">
            <div
              className="h-full bg-teal-500 transition-all duration-500 ease-out"
              style={{ width: `${Math.min(100, (currentSection / totalSections) * 100)}%` }}
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

          {/* Current Bot Caption (Large Light Text Fading In) */}
          <div className="min-h-[100px] flex items-center">
            <p
              data-testid="current-bot-caption"
              className="text-2xl md:text-3xl lg:text-4xl font-light text-zinc-100 tracking-tight leading-snug transition-all duration-500 select-text"
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

            {/* Ready Gate Optional Button */}
            {status === 'waiting_for_ready' && (
              <button
                type="button"
                onClick={handleReadyClick}
                data-testid="ready-gate-button"
                className="ml-3 inline-flex items-center gap-1.5 rounded-full border border-teal-500/40 bg-teal-500/10 px-3.5 py-1 text-xs font-semibold text-teal-300 shadow-sm transition hover:bg-teal-500/20 active:scale-95"
              >
                <CheckCircle2 className="h-3.5 w-3.5 text-teal-400" />
                <span>I'm ready</span>
                <span className="text-[10px] text-zinc-500 font-normal">(or just say "yes")</span>
              </button>
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
                  onChange={(e) => setSelectedMicId(e.target.value)}
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
                  onChange={(e) => setSelectedSpeakerId(e.target.value)}
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
