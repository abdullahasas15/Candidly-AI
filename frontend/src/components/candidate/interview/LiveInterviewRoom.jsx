import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Mic,
  MicOff,
  Video,
  VideoOff,
  PhoneOff,
  Sparkles,
  CheckCircle2,
  AlertCircle,
  AlertTriangle,
  Clock,
  User,
  Bot,
  VolumeX,
  Play,
  RotateCcw,
  Loader2,
  Wifi,
  Star,
  Settings,
  MessageSquare,
  ChevronRight,
} from 'lucide-react';

import { PipecatClient } from '@pipecat-ai/client-js';
import { SmallWebRTCTransport } from '@pipecat-ai/small-webrtc-transport';

// Compact AI interviewer orb for the two-pane layout (left pane, ~140px area).
const ORB_THEMES = {
  speaking: { glow: 'bg-violet-500', ring: 'border-violet-400/80', fill: 'from-violet-500/30 to-violet-900/50', icon: 'text-violet-300' },
  listening: { glow: 'bg-emerald-500', ring: 'border-emerald-400/80', fill: 'from-emerald-500/25 to-emerald-900/50', icon: 'text-emerald-300' },
  ai_speaking_wait: { glow: 'bg-rose-500', ring: 'border-rose-400/90', fill: 'from-rose-500/25 to-rose-900/50', icon: 'text-rose-300' },
  finishing: { glow: 'bg-amber-400', ring: 'border-amber-400/90', fill: 'from-amber-500/25 to-amber-900/50', icon: 'text-amber-300' },
  finished: { glow: 'bg-slate-600', ring: 'border-slate-600', fill: 'from-slate-700/40 to-slate-900/70', icon: 'text-slate-400' },
  thinking: { glow: 'bg-amber-500', ring: 'border-amber-400/80', fill: 'from-amber-500/25 to-amber-900/50', icon: 'text-amber-300' },
  interrupted: { glow: 'bg-rose-500', ring: 'border-rose-400/70', fill: 'from-rose-500/25 to-rose-900/50', icon: 'text-rose-300' },
  idle: { glow: 'bg-indigo-600', ring: 'border-slate-700', fill: 'from-indigo-500/20 to-slate-900/50', icon: 'text-indigo-400' },
};

function InterviewerOrb({ aiState }) {
  const theme = ORB_THEMES[aiState] || ORB_THEMES.idle;
  const spinningRing = aiState === 'finishing' || aiState === 'thinking';
  const pingRing = aiState === 'speaking' || aiState === 'ai_speaking_wait';
  return (
    <div className="relative flex h-[140px] w-full items-center justify-center overflow-hidden">
      {/* Ambient radial glow */}
      <div
        className={`absolute h-40 w-40 rounded-full blur-3xl opacity-30 transition-all duration-700 ${theme.glow} ${
          aiState === 'speaking' ? 'scale-125' : 'scale-100'
        }`}
      />
      <div className={`relative flex h-24 w-24 items-center justify-center rounded-full border-2 ${theme.ring} bg-gradient-to-b ${theme.fill} ${theme.icon} transition-colors duration-300`}>
        {pingRing && <span className="absolute inset-0 rounded-full border border-current opacity-40 animate-ping [animation-duration:1.6s]" />}
        {spinningRing && <span className="absolute -inset-1.5 rounded-full border-2 border-transparent border-t-current animate-spin" />}
        <Bot className="h-9 w-9 text-current" />
      </div>
    </div>
  );
}

// State pill copy — the five simple-mode states must render EXACTLY as below.
// Extra entries (thinking / interrupted / idle) are graceful fallbacks kept for adaptive sessions.
const STATE_PILLS = {
  speaking: { label: 'Speaking', cls: 'bg-violet-950/70 text-violet-300 border-violet-700/60', dot: 'bg-violet-400 animate-ping' },
  listening: { label: 'Listening', cls: 'bg-emerald-950/70 text-emerald-300 border-emerald-700/60', dot: 'bg-emerald-400 animate-pulse' },
  ai_speaking_wait: { label: 'AI is speaking, please wait', cls: 'bg-rose-950/80 text-rose-200 border-rose-600/70', dot: 'bg-rose-400 animate-pulse' },
  finishing: { label: 'Finishing your answer...', cls: 'bg-amber-950/70 text-amber-300 border-amber-700/60', dot: 'bg-amber-400 animate-pulse', spin: true },
  finished: { label: 'Finished', cls: 'bg-slate-800/90 text-slate-300 border-slate-700', dot: 'bg-slate-500' },
  thinking: { label: 'Processing response...', cls: 'bg-amber-950/70 text-amber-300 border-amber-700/60', spin: true },
  interrupted: { label: 'Listening (interrupted)', cls: 'bg-rose-950/70 text-rose-300 border-rose-700/60', dot: 'bg-rose-400' },
  idle: { label: 'Ready', cls: 'bg-slate-900/80 text-slate-400 border-slate-700/60', dot: 'bg-slate-500' },
};

export default function LiveInterviewRoom({
  sessionId,
  jobTitle,
  candidateName,
  durationMins = 20,
  token,
  onExit,
}) {
  // Connection states
  const [client, setClient] = useState(null);
  const [transport, setTransport] = useState(null);
  const [connectionState, setConnectionState] = useState('connecting'); // connecting, connected, busy, error
  const [connectionError, setConnectionError] = useState(null);
  const [retryCount, setRetryCount] = useState(0);

  // Live session states
  const [interviewBegun, setInterviewBegun] = useState(false);
  const [currentPhase, setCurrentPhase] = useState('greeting'); // greeting, ready_check, self_intro, deep_dive, candidate_questions, closing, completed
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
  const [totalQuestions, setTotalQuestions] = useState(5);
  const [currentQuestionText, setCurrentQuestionText] = useState('');
  const [skillName, setSkillName] = useState('');
  const [isFollowup, setIsFollowup] = useState(false);
  const [remainingSeconds, setRemainingSeconds] = useState(durationMins * 60);
  const [graceExtended, setGraceExtended] = useState(false);

  // R3.5 simple-mode awareness (topic progress vs adaptive question progress)
  const [interviewMode, setInterviewMode] = useState(null); // 'simple' | 'adaptive' | null (until first coordinator message)
  const [topicIndex, setTopicIndex] = useState(0);
  const [topicTotal, setTopicTotal] = useState(0);

  // Audio / Visual states
  const [aiState, setAiState] = useState('idle'); // idle, listening, speaking, thinking, ai_speaking_wait, finishing, finished, interrupted
  const [candidateState, setCandidateState] = useState('listening'); // listening, speaking, muted
  const [isMicMuted, setIsMicMuted] = useState(false);
  const [isVideoOff, setIsVideoOff] = useState(false);
  const [confirmExitOpen, setConfirmExitOpen] = useState(false);
  const [isEndingSession, setIsEndingSession] = useState(false);
  const [audioAutoplayBlocked, setAudioAutoplayBlocked] = useState(false);

  // Candidate Experience controls
  const [speechSpeed, setSpeechSpeed] = useState(1.0);
  const [repeatingQuestion, setRepeatingQuestion] = useState(false);
  const [feedbackRating, setFeedbackRating] = useState(0);
  const [feedbackComment, setFeedbackComment] = useState('');
  const [feedbackSubmitted, setFeedbackSubmitted] = useState(false);
  const [submittingFeedback, setSubmittingFeedback] = useState(false);

  // Resilience: Device switcher & Network quality (Part C3)
  const [deviceWarning, setDeviceWarning] = useState(null);
  const [deviceMenuOpen, setDeviceMenuOpen] = useState(false);
  const [audioInputs, setAudioInputs] = useState([]);
  const [videoInputs, setVideoInputs] = useState([]);
  const [selectedMicId, setSelectedMicId] = useState('');
  const [selectedCamId, setSelectedCamId] = useState('');
  const [networkQuality, setNetworkQuality] = useState({ status: 'Good', rttMs: 24 });

  // Real-time subtitles: interviewer question (left pane) + candidate live caption (right pane)
  const [aiSubtitle, setAiSubtitle] = useState('');
  const [candidateSubtitle, setCandidateSubtitle] = useState('');
  const [candidateIsInterim, setCandidateIsInterim] = useState(false);
  const [showHeadphoneNotice, setShowHeadphoneNotice] = useState(true);

  // R3.5 "I'm done answering" commit flow
  const [commitPending, setCommitPending] = useState(false);
  const [inlineNotice, setInlineNotice] = useState(null); // {tone: 'ok'|'warn', text}

  // Collapsed transcript drawer
  const [transcriptOpen, setTranscriptOpen] = useState(false);
  const [transcriptEntries, setTranscriptEntries] = useState([]); // {at, kind: 'ai'|'answer', text}

  const audioCtxRef = useRef(null);
  const lastQuestionIdRef = useRef(null);
  // Last bot state announced by the server coordinator (guards local RTVI overrides in simple mode)
  const serverBotStateRef = useRef('idle');
  const interviewModeRef = useRef(null);

  // Media references
  const candidateVideoRef = useRef(null);
  const remoteAudioRef = useRef(null);
  const localStreamRef = useRef(null);
  const peerConnRef = useRef(null);
  const transcriptScrollRef = useRef(null);

  const getAuthHeaders = useCallback(() => {
    const authToken =
      token ||
      localStorage.getItem('candidly-auth-token-candidate') ||
      localStorage.getItem('candidly-auth-token');
    return {
      ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
      'Content-Type': 'application/json',
    };
  }, [token]);

  // Helper to log integrity events (Part F1 & F2)
  const logIntegrityEvent = useCallback(
    async (eventType, details = null) => {
      if (!sessionId || !interviewBegun || currentPhase === 'completed') return;
      try {
        await fetch(`/api/interview-sessions/${sessionId}/integrity-events`, {
          method: 'POST',
          headers: getAuthHeaders(),
          body: JSON.stringify({ event_type: eventType, details }),
        });
      } catch (e) {
        // Ignore telemetry network errors
      }
    },
    [sessionId, interviewBegun, currentPhase, getAuthHeaders]
  );

  // Transcript drawer entries: interviewer speech + committed answers, capped at 50.
  const pushTranscriptEntry = useCallback((entry) => {
    setTranscriptEntries((prev) => {
      const next = [...prev, { at: Date.now(), ...entry }];
      return next.length > 50 ? next.slice(next.length - 50) : next;
    });
  }, []);

  const showInlineNotice = useCallback((tone, text) => {
    setInlineNotice({ tone, text });
  }, []);

  // Auto-dismiss the subtle commit/notice toast
  useEffect(() => {
    if (!inlineNotice) return undefined;
    const t = setTimeout(() => setInlineNotice(null), 3000);
    return () => clearTimeout(t);
  }, [inlineNotice]);

  // Auto-scroll the transcript drawer while it is open
  useEffect(() => {
    if (transcriptOpen && transcriptScrollRef.current) {
      transcriptScrollRef.current.scrollTop = transcriptScrollRef.current.scrollHeight;
    }
  }, [transcriptOpen, transcriptEntries]);

  // 1. Initialize local candidate media stream (Webcam + Mic) & Device loss listeners (Part C3)
  const startLocalMedia = useCallback(
    async (micDeviceId = selectedMicId, camDeviceId = selectedCamId) => {
      try {
        if (localStreamRef.current) {
          localStreamRef.current.getTracks().forEach((t) => t.stop());
        }
        const stream = await navigator.mediaDevices.getUserMedia({
          video: camDeviceId
            ? { deviceId: { exact: camDeviceId }, width: { ideal: 1280 }, height: { ideal: 720 } }
            : { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'user' },
          audio: micDeviceId
            ? {
                deviceId: { exact: micDeviceId },
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
        localStreamRef.current = stream;
        if (candidateVideoRef.current) {
          candidateVideoRef.current.srcObject = stream;
        }
        setDeviceWarning(null);

        // Enumerate devices for mid-call switcher
        const devices = await navigator.mediaDevices.enumerateDevices();
        setAudioInputs(devices.filter((d) => d.kind === 'audioinput'));
        setVideoInputs(devices.filter((d) => d.kind === 'videoinput'));

        // Track loss detection
        stream.getAudioTracks().forEach((track) => {
          track.onended = () => {
            setDeviceWarning('Microphone disconnected! Select another audio input below.');
            logIntegrityEvent('mic_muted', { reason: 'hardware_track_ended' });
          };
        });
        stream.getVideoTracks().forEach((track) => {
          track.onended = () => {
            setDeviceWarning('Camera disconnected! Select another camera below.');
            logIntegrityEvent('camera_blocked', { reason: 'hardware_track_ended' });
          };
        });
      } catch (err) {
        console.error('Error starting local candidate media:', err);
        setDeviceWarning('Could not access camera or microphone. Check device permissions.');
      }
    },
    [selectedMicId, selectedCamId, logIntegrityEvent]
  );

  useEffect(() => {
    startLocalMedia();
    const handleDeviceChange = async () => {
      try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        setAudioInputs(devices.filter((d) => d.kind === 'audioinput'));
        setVideoInputs(devices.filter((d) => d.kind === 'videoinput'));
      } catch (e) {}
    };
    navigator.mediaDevices?.addEventListener?.('devicechange', handleDeviceChange);
    return () => {
      navigator.mediaDevices?.removeEventListener?.('devicechange', handleDeviceChange);
      if (localStreamRef.current) {
        localStreamRef.current.getTracks().forEach((t) => t.stop());
      }
    };
  }, []);

  // 2. Single initial hydration of session state on mount/reconnect (NO polling loop — Part C2)
  useEffect(() => {
    let active = true;
    async function hydrateInitialSession() {
      try {
        const res = await fetch(`/api/interview-sessions/${sessionId}/live-status`, {
          headers: getAuthHeaders(),
        });
        if (!res.ok || !active) return;
        const data = await res.json();
        if (data.current_phase) setCurrentPhase(data.current_phase);
        if (data.live_status) {
          if (data.live_status.has_begun) setInterviewBegun(true);
          if (data.live_status.phase) setCurrentPhase(data.live_status.phase);
          if (typeof data.live_status.current_question_index === 'number') {
            setCurrentQuestionIndex(data.live_status.current_question_index);
          }
          if (typeof data.live_status.total_questions === 'number') {
            setTotalQuestions(data.live_status.total_questions);
          }
          if (typeof data.live_status.remaining_seconds === 'number') {
            setRemainingSeconds(Math.max(0, Math.ceil(data.live_status.remaining_seconds)));
          }
          if (data.live_status.grace_extended) {
            setGraceExtended(true);
          }
          if (data.live_status.is_completed) {
            setCurrentPhase('completed');
          }
          if (data.live_status.last_ai_speech) {
            setAiSubtitle(data.live_status.last_ai_speech);
          }
          if (data.live_status.last_candidate_speech) {
            setCandidateSubtitle(data.live_status.last_candidate_speech);
          }
        }
      } catch (e) {
        // Initial hydration optional
      }
    }
    hydrateInitialSession();
    return () => {
      active = false;
    };
  }, [sessionId, getAuthHeaders]);

  // 3. Initialize Pipecat WebRTC client (RTVI single channel for transcripts & state)
  useEffect(() => {
    let pipecatClient = null;
    let swTransport = null;
    let active = true;

    async function initPipecat() {
      try {
        setConnectionState('connecting');
        setConnectionError(null);

        const localHour = new Date().getHours();
        const headersObj = getAuthHeaders();
        const webrtcEndpoint = `/api/interview-sessions/${sessionId}/webrtc`;

        const webrtcRequest = new Request(webrtcEndpoint, {
          method: 'POST',
          headers: headersObj,
        });

        swTransport = new SmallWebRTCTransport({
          webrtcRequestParams: {
            endpoint: webrtcRequest,
            headers: headersObj,
            requestData: {
              candidate_local_hour: localHour,
            },
          },
          iceServers: [
            { urls: 'stun:stun.l.google.com:19302' },
            { urls: 'stun:stun1.l.google.com:19302' },
            { urls: 'stun:stun2.l.google.com:19302' },
          ],
        });

        pipecatClient = new PipecatClient({
          transport: swTransport,
          enableMic: true,
          enableCam: true,
          callbacks: {
            onUserTranscript: (data) => {
              if (data?.text) {
                setCandidateSubtitle(data.text);
              }
            },
            onBotTranscript: (data) => {
              if (data?.text) {
                setAiSubtitle(data.text);
              }
            },
            onBotOutput: (data) => {
              if (data?.text) {
                setAiSubtitle(data.text);
              }
            },
            onBotTtsText: (data) => {
              if (data?.text) {
                setAiSubtitle(data.text);
              }
            },
          },
        });

        // Helper to route incoming bot WebRTC audio track to local speaker
        const attachRemoteAudio = (track) => {
          if (!track) return;
          const stream = new MediaStream([track]);
          if (remoteAudioRef.current) {
            remoteAudioRef.current.srcObject = stream;
            remoteAudioRef.current.muted = false;
            remoteAudioRef.current.volume = 1.0;
            remoteAudioRef.current
              .play()
              .then(() => {
                setAudioAutoplayBlocked(false);
              })
              .catch(() => {
                setAudioAutoplayBlocked(true);
              });
          }
        };

        // Native RTVI transcript event listeners
        pipecatClient.on('userTranscript', (data) => {
          if (data?.text) setCandidateSubtitle(data.text);
        });
        pipecatClient.on('botTranscript', (data) => {
          if (data?.text) setAiSubtitle(data.text);
        });
        pipecatClient.on('botOutput', (data) => {
          if (data?.text) setAiSubtitle(data.text);
        });
        pipecatClient.on('botTtsText', (data) => {
          if (data?.text) setAiSubtitle(data.text);
        });

        // Track lifecycle subscriptions
        pipecatClient.on('trackStarted', (track, participant) => {
          if (participant?.local) return;
          if (track.kind === 'audio') {
            attachRemoteAudio(track);
          }
        });

        // Pipeline event subscriptions
        pipecatClient.on('botStartedSpeaking', () => {
          setAiState('speaking');
          setCandidateState(isMicMuted ? 'muted' : 'listening');
          if (remoteAudioRef.current && remoteAudioRef.current.paused) {
            remoteAudioRef.current
              .play()
              .then(() => setAudioAutoplayBlocked(false))
              .catch(() => setAudioAutoplayBlocked(true));
          }
        });

        pipecatClient.on('botStoppedSpeaking', () => {
          setAiState('listening');
        });

        pipecatClient.on('userStartedSpeaking', () => {
          if (!isMicMuted) {
            setCandidateState('speaking');
            // Simple mode: never visually "grant the floor" while the scripted
            // interviewer holds it (speaking / ai_speaking_wait / finishing).
            const srvState = serverBotStateRef.current;
            const simpleHold =
              interviewModeRef.current === 'simple' &&
              (srvState === 'speaking' || srvState === 'ai_speaking_wait' || srvState === 'finishing');
            if (!simpleHold) {
              setAiState('listening');
            }
          }
        });

        pipecatClient.on('userStoppedSpeaking', () => {
          setCandidateState(isMicMuted ? 'muted' : 'listening');
        });

        // Custom RTVI messages emitted by the simple-mode coordinator (and legacy adaptive mode)
        pipecatClient.on('serverMessage', (payload) => {
          if (!payload) return;
          const msg = payload.data || payload;

          // Freshest time budget from every coordinator message in both modes.
          if (typeof msg.remaining_seconds === 'number') {
            setRemainingSeconds(Math.max(0, Math.ceil(msg.remaining_seconds)));
          }

          if (msg.type === 'interview-phase-change') {
            if (msg.phase) setCurrentPhase(msg.phase);
            if (msg.phase === 'completed') {
              setAiState('idle');
            }
          } else if (msg.type === 'interview-progress') {
            if (typeof msg.question_index === 'number') {
              setCurrentQuestionIndex(msg.question_index);
            }
            if (typeof msg.total_questions === 'number') {
              setTotalQuestions(msg.total_questions);
            }
            if (msg.question_text) {
              setCurrentQuestionText(msg.question_text);
              setAiSubtitle(msg.question_text);
            }
            if (msg.text) {
              // Simple mode: the current scripted utterance/question, verbatim — replace, never append.
              setCurrentQuestionText(msg.text);
              setAiSubtitle(msg.text);
            }
            if (msg.skill_name) {
              setSkillName(msg.skill_name);
            }
            if (typeof msg.topic_index === 'number') {
              setTopicIndex(msg.topic_index);
            }
            if (typeof msg.topic_total === 'number') {
              setTopicTotal(msg.topic_total);
            }
            if (msg.mode) {
              setInterviewMode(msg.mode);
              interviewModeRef.current = msg.mode;
            }
            if (msg.grace_extended) {
              setGraceExtended(true);
            }
            setIsFollowup(Boolean(msg.is_followup));
            // New question (by id) → start a fresh live caption for the candidate's next answer.
            if (msg.question_id && msg.question_id !== lastQuestionIdRef.current) {
              lastQuestionIdRef.current = msg.question_id;
              setCandidateSubtitle('');
            }
          } else if (msg.type === 'interview-bot-state') {
            if (msg.state) {
              serverBotStateRef.current = msg.state;
              setAiState(msg.state);
              if (msg.state === 'listening') {
                setCommitPending(false);
              }
            }
          } else if (msg.type === 'ai-speech-transcript' && msg.text) {
            setAiSubtitle(msg.text);
            if (msg.question_id && msg.question_id !== lastQuestionIdRef.current) {
              lastQuestionIdRef.current = msg.question_id;
              setCandidateSubtitle('');
            }
            if (msg.question_text) {
              setCurrentQuestionText(msg.question_text);
            } else if (msg.text.includes('?') || msg.phase === 'deep_dive') {
              setCurrentQuestionText(msg.text);
            }
            pushTranscriptEntry({ kind: 'ai', text: msg.text });
          } else if (msg.type === 'candidate-speech-transcript' && msg.text) {
            setCandidateSubtitle(msg.text);
            setCandidateIsInterim(
              typeof msg.is_final === 'boolean' ? !msg.is_final : Boolean(msg.is_interim)
            );
          } else if (msg.type === 'interview-committed') {
            // Answer captured: clear the live caption and drop a drawer row.
            setCandidateSubtitle('');
            setCandidateIsInterim(false);
            const words = typeof msg.words === 'number' ? msg.words : 0;
            const label = words > 0 ? `Answer captured — ${words} words` : 'Answer captured';
            showInlineNotice('ok', label);
            pushTranscriptEntry({ kind: 'answer', text: label });
          }
        });

        const bindPeerConnection = (pc) => {
          if (!pc) return;
          peerConnRef.current = pc;
          pc.addEventListener('track', (evt) => {
            if (evt.track.kind === 'audio') {
              attachRemoteAudio(evt.track);
            }
          });
          pc.addEventListener('connectionstatechange', () => {
            if (pc.connectionState === 'connected') {
              if (active) setConnectionState('connected');
            } else if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') {
              if (active) {
                setConnectionState('error');
                setConnectionError('Connection interrupted. Your session is paused — click Reconnect to resume.');
              }
            }
          });
          pc.addEventListener('iceconnectionstatechange', () => {
            if (pc.iceConnectionState === 'connected' || pc.iceConnectionState === 'completed') {
              if (active) setConnectionState('connected');
            }
          });
        };

        const connectPromise = pipecatClient.connect();
        const timeoutPromise = new Promise((resolve) => setTimeout(() => resolve('timeout'), 6000));
        await Promise.race([connectPromise, timeoutPromise]);

        if (!active) return;

        if (swTransport.pc) {
          bindPeerConnection(swTransport.pc);
          swTransport.pc.getReceivers?.().forEach((r) => {
            if (r.track && r.track.kind === 'audio') {
              attachRemoteAudio(r.track);
            }
          });
        }

        try {
          const currentTracks = pipecatClient.tracks?.();
          if (currentTracks?.bot?.audio) {
            attachRemoteAudio(currentTracks.bot.audio);
          }
        } catch (e) {}

        setClient(pipecatClient);
        setTransport(swTransport);
        setConnectionState('connected');
      } catch (err) {
        console.error('WebRTC Pipecat connection error:', err);
        if (active) {
          const msg = err?.message || '';
          if (msg.includes('429') || msg.toLowerCase().includes('busy') || msg.toLowerCase().includes('another live')) {
            setConnectionState('busy');
            setConnectionError('The AI Interviewer is currently in another live session on this machine. Please retry in a moment.');
          } else {
            setConnectionState('error');
            setConnectionError(msg || 'Unable to establish WebRTC connection with the interview room.');
          }
        }
      }
    }

    initPipecat();

    return () => {
      active = false;
      if (pipecatClient) {
        pipecatClient.disconnect().catch(() => {});
      }
    };
  }, [sessionId, token, retryCount, getAuthHeaders, pushTranscriptEntry, showInlineNotice]);

  // 4. Local 1-second countdown between server remaining_seconds syncs (Part B8)
  useEffect(() => {
    if (!interviewBegun || currentPhase === 'completed') return;
    const timer = setInterval(() => {
      setRemainingSeconds((prev) => Math.max(0, prev - 1));
    }, 1000);
    return () => clearInterval(timer);
  }, [interviewBegun, currentPhase]);

  useEffect(() => {
    const statsInterval = setInterval(async () => {
      const pc = peerConnRef.current;
      if (!pc || pc.connectionState !== 'connected') return;
      try {
        const stats = await pc.getStats();
        let currentRtt = null;
        stats.forEach((report) => {
          if (report.type === 'candidate-pair' && report.state === 'succeeded' && typeof report.currentRoundTripTime === 'number') {
            currentRtt = Math.round(report.currentRoundTripTime * 1000);
          }
        });
        if (currentRtt !== null) {
          const status = currentRtt < 120 ? 'Good' : currentRtt < 280 ? 'Fair' : 'Poor';
          setNetworkQuality({ status, rttMs: currentRtt });
        }
      } catch (e) {}
    }, 5000);
    return () => clearInterval(statsInterval);
  }, []);

  // 5. Client-Side Integrity Signal Listeners & Periodic Face/Camera Check (Part F1 & F2)
  useEffect(() => {
    if (!interviewBegun || currentPhase === 'completed') return;

    const onVisibilityChange = () => {
      if (document.hidden) {
        logIntegrityEvent('tab_hidden', { timestamp: new Date().toISOString() });
      }
    };
    const onWindowBlur = () => {
      logIntegrityEvent('window_blur', { timestamp: new Date().toISOString() });
    };
    const onFullscreenChange = () => {
      if (!document.fullscreenElement) {
        logIntegrityEvent('fullscreen_exit', { timestamp: new Date().toISOString() });
      }
    };
    const onPaste = (e) => {
      const pastedLen = e.clipboardData?.getData('text')?.length || 0;
      logIntegrityEvent('paste', { length: pastedLen });
    };

    document.addEventListener('visibilitychange', onVisibilityChange);
    window.addEventListener('blur', onWindowBlur);
    document.addEventListener('fullscreenchange', onFullscreenChange);
    window.addEventListener('paste', onPaste);

    // Periodic lightweight face-count / camera-occlusion check every 12s
    const faceInterval = setInterval(async () => {
      const videoEl = candidateVideoRef.current;
      if (!videoEl || isVideoOff || videoEl.readyState < 2) return;
      try {
        if ('FaceDetector' in window) {
          const detector = new window.FaceDetector({ fastMode: true, maxDetectedFaces: 3 });
          const faces = await detector.detect(videoEl);
          if (faces.length === 0) {
            logIntegrityEvent('no_face_detected', { faces: 0 });
          } else if (faces.length > 1) {
            logIntegrityEvent('multiple_faces_detected', { faces: faces.length });
          }
        } else {
          // Fallback luminance check for covered/blocked camera lens
          const canvas = document.createElement('canvas');
          canvas.width = 32;
          canvas.height = 32;
          const ctx = canvas.getContext('2d');
          if (ctx) {
            ctx.drawImage(videoEl, 0, 0, 32, 32);
            const data = ctx.getImageData(0, 0, 32, 32).data;
            let sum = 0;
            for (let i = 0; i < data.length; i += 4) {
              sum += (data[i] + data[i + 1] + data[i + 2]) / 3;
            }
            const avgBrightness = sum / (32 * 32);
            if (avgBrightness < 6) {
              logIntegrityEvent('camera_blocked', { avg_brightness: Math.round(avgBrightness) });
            }
          }
        }
      } catch (e) {}
    }, 12000);

    return () => {
      document.removeEventListener('visibilitychange', onVisibilityChange);
      window.removeEventListener('blur', onWindowBlur);
      document.removeEventListener('fullscreenchange', onFullscreenChange);
      window.removeEventListener('paste', onPaste);
      clearInterval(faceInterval);
    };
  }, [interviewBegun, currentPhase, isVideoOff, logIntegrityEvent]);

  // 6. Deliberate "Begin Interview" (or Resume) CTA
  const handleBeginInterview = async () => {
    try {
      if (remoteAudioRef.current) {
        remoteAudioRef.current.muted = false;
        remoteAudioRef.current.volume = 1.0;
        remoteAudioRef.current
          .play()
          .then(() => setAudioAutoplayBlocked(false))
          .catch(() => setAudioAutoplayBlocked(true));
      }
      if (audioCtxRef.current && audioCtxRef.current.state === 'suspended') {
        audioCtxRef.current.resume().catch(() => {});
      }

      setInterviewBegun(true);
      setAiState('speaking');

      // The POST can race this room's own WebRTC assembly: /begin answers 409
      // ("still establishing") while the server registers the runner a second
      // later. Retry briefly so a deliberate Begin click is never silently lost.
      for (let attempt = 0; attempt < 8; attempt += 1) {
        let res = null;
        try {
          res = await fetch(`/api/interview-sessions/${sessionId}/begin`, {
            method: 'POST',
            headers: getAuthHeaders(),
          });
        } catch (err) {
          res = null;
        }
        if (res && res.ok) return;
        if (res && res.status === 404) break; // session gone — don't spin
        await new Promise((resolve) => setTimeout(resolve, attempt < 4 ? 700 : 1500));
      }
      showInlineNotice('warn', 'The interviewer is still connecting — the greeting may arrive late. Use Reconnect or Begin again if it never starts.');
      setAiState('listening');
    } catch (err) {
      console.error('Error starting interview:', err);
    }
  };

  // 6a. R3.5: "I'm done answering" — commit the current turn explicitly (simple mode).
  const handleCommitTurn = async () => {
    if (!interviewBegun || commitPending || currentPhase === 'completed') return;
    setCommitPending(true);
    // Optimistic finishing ring; the server emits the same state right after.
    setAiState('finishing');
    try {
      const res = await fetch(`/api/interview-sessions/${sessionId}/commit-turn`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ reason: 'button' }),
      });
      if (res.ok) {
        const data = await res.json().catch(() => ({}));
        if (data && data.status === 'ignored') {
          setCommitPending(false);
          setAiState('listening');
          showInlineNotice('warn', 'That turn was not captured — wait for the interviewer to finish, then try again.');
        } else {
          const words = data && typeof data.words === 'number' ? data.words : null;
          showInlineNotice('ok', words !== null ? `Answer captured — ${words} words` : 'Answer captured');
        }
      } else {
        setCommitPending(false);
        setAiState('listening');
        showInlineNotice(
          'warn',
          res.status === 409
            ? 'Session is not connected yet — try again in a moment.'
            : `Could not submit the answer (${res.status}). Try again.`
        );
      }
    } catch (e) {
      setCommitPending(false);
      setAiState('listening');
      showInlineNotice('warn', 'Network hiccup — could not submit the answer. Try again.');
    }
  };

  // 6b. Repeat Question Button (Part G2)
  const handleRepeatQuestion = async () => {
    if (repeatingQuestion || !interviewBegun) return;
    setRepeatingQuestion(true);
    try {
      const res = await fetch(`/api/interview-sessions/${sessionId}/repeat-question`, {
        method: 'POST',
        headers: getAuthHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.text) setAiSubtitle(data.text);
      }
    } catch (e) {
      console.warn('Repeat question failed:', e);
    } finally {
      setRepeatingQuestion(false);
    }
  };

  // 6c. Speech Speed Control (Part G3)
  const handleSpeedChange = async (newSpeed) => {
    setSpeechSpeed(newSpeed);
    try {
      await fetch(`/api/interview-sessions/${sessionId}/settings`, {
        method: 'PATCH',
        headers: getAuthHeaders(),
        body: JSON.stringify({ tts_speed: newSpeed }),
      });
    } catch (e) {}
  };

  // 6d. Submit Post-Interview Candidate Feedback (Part G5)
  const handleSubmitFeedback = async () => {
    if (!feedbackRating || submittingFeedback || feedbackSubmitted) return;
    setSubmittingFeedback(true);
    try {
      const res = await fetch(`/api/interview-sessions/${sessionId}/feedback`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ rating: feedbackRating, comment: feedbackComment }),
      });
      if (res.ok) {
        setFeedbackSubmitted(true);
      }
    } catch (e) {
      console.warn('Feedback submit error:', e);
    } finally {
      setSubmittingFeedback(false);
    }
  };

  // 6e. End live interview session & notify backend
  const handleEndSessionAndExit = async () => {
    setIsEndingSession(true);
    try {
      if (client) {
        await client.disconnect().catch(() => {});
      }
      await fetch(`/api/interview-sessions/${sessionId}/end`, {
        method: 'POST',
        headers: getAuthHeaders(),
      });
    } catch (err) {
      console.warn('Error completing session on server:', err);
    } finally {
      setIsEndingSession(false);
      setConfirmExitOpen(false);
      onExit();
    }
  };

  // 7. Media Controls
  const toggleMic = () => {
    if (localStreamRef.current) {
      const audioTracks = localStreamRef.current.getAudioTracks();
      audioTracks.forEach((t) => {
        t.enabled = !t.enabled;
      });
      const newMuted = !isMicMuted;
      setIsMicMuted(newMuted);
      setCandidateState(newMuted ? 'muted' : 'listening');
      if (transport) {
        transport.enableMic(!newMuted);
      }
      if (newMuted) {
        logIntegrityEvent('mic_muted', { manual: true });
      }
    }
  };

  const toggleVideo = () => {
    if (localStreamRef.current) {
      const videoTracks = localStreamRef.current.getVideoTracks();
      videoTracks.forEach((t) => {
        t.enabled = !t.enabled;
      });
      const nextVideoOff = !isVideoOff;
      setIsVideoOff(nextVideoOff);
      if (transport) {
        transport.enableCam(!nextVideoOff);
      }
      if (nextVideoOff) {
        logIntegrityEvent('camera_blocked', { manual_video_off: true });
      }
    }
  };

  const handleSwitchDevice = async (kind, deviceId) => {
    if (kind === 'audio') {
      setSelectedMicId(deviceId);
      await startLocalMedia(deviceId, selectedCamId);
    } else {
      setSelectedCamId(deviceId);
      await startLocalMedia(selectedMicId, deviceId);
    }
    setDeviceMenuOpen(false);
  };

  const formatTimer = (totalSec) => {
    const mins = Math.floor(totalSec / 60);
    const secs = totalSec % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  // Top-bar focus label: simple mode shows topic progress; adaptive mode falls back to question progress.
  const progressLabel =
    topicTotal > 0 || (interviewMode === 'simple' && topicTotal === 0)
      ? `Topic ${Math.max(1, topicIndex)} of ${topicTotal || topicIndex || 1}`
      : totalQuestions > 0
      ? `Question ${currentQuestionIndex + 1} of ${totalQuestions}`
      : 'Live interview';

  const statePill = STATE_PILLS[aiState] || null;

  // "I'm done answering" enablement (R3.5):
  // simple → listening AND the candidate has live words; adaptive → listening.
  const canCommit =
    interviewBegun &&
    currentPhase !== 'completed' &&
    !commitPending &&
    aiState === 'listening' &&
    (interviewMode === 'simple' ? candidateSubtitle.trim().length > 0 : true);

  // Show the gateway overlay while connecting pre-begin, when the interviewer is busy,
  // when a begun session lost its connection (paused → Reconnect), or while a reconnect is in progress.
  const showGatewayOverlay =
    currentPhase !== 'completed' &&
    (!interviewBegun || connectionState !== 'connected');

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-slate-950 text-white select-none">
      {/* Top bar — single row: identity, topic progress + time left, network */}
      <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-slate-800 bg-slate-900/85 px-3 sm:px-5 backdrop-blur-md">
        <div className="flex min-w-0 items-center gap-2.5">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-indigo-600/20 text-indigo-400 border border-indigo-500/30">
            <Sparkles className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <div className="flex min-w-0 items-center gap-2">
              <span className="truncate text-xs sm:text-sm font-bold text-slate-100">
                {jobTitle || 'Technical Interview'}
              </span>
              <span className="hidden shrink-0 rounded-full bg-slate-800 px-2 py-0.5 text-[10px] font-semibold text-slate-400 md:inline-flex">
                Live Room
              </span>
            </div>
            <div className="truncate text-[10px] text-slate-500">{candidateName || 'Candidate'}</div>
          </div>
        </div>

        {/* Topic X of Y — mm:ss left (falls back to Question X of Y in adaptive mode) */}
        <div className="flex min-w-0 items-center justify-center gap-2">
          <Clock className="h-3.5 w-3.5 shrink-0 text-indigo-400" />
          <span className="truncate text-xs sm:text-sm font-bold text-slate-200">{progressLabel}</span>
          <span className="shrink-0 text-slate-600">—</span>
          <span className="shrink-0 font-mono text-xs sm:text-sm font-bold tabular-nums text-emerald-400">
            {formatTimer(remainingSeconds)} left
          </span>
          {graceExtended && (
            <span className="hidden shrink-0 rounded bg-amber-500/20 px-1.5 py-0.5 text-[9px] font-bold text-amber-300 border border-amber-500/40 sm:inline">
              +5m Grace
            </span>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2.5">
          {/* Network Quality Badge (Part C3) */}
          <div
            className={`hidden items-center gap-1.5 rounded-xl px-2.5 py-1.5 text-[11px] font-semibold border sm:flex ${
              networkQuality.status === 'Good'
                ? 'bg-emerald-950/40 text-emerald-400 border-emerald-800/60'
                : networkQuality.status === 'Fair'
                ? 'bg-amber-950/40 text-amber-400 border-amber-800/60'
                : 'bg-rose-950/40 text-rose-400 border-rose-800/60'
            }`}
            title={`WebRTC RTT: ${networkQuality.rttMs}ms`}
          >
            <Wifi className="h-3.5 w-3.5" />
            <span>{networkQuality.status}</span>
            <span className="text-[10px] opacity-75">({networkQuality.rttMs}ms)</span>
          </div>
        </div>
      </header>

      {/* Headphone Recommended Notice */}
      {showHeadphoneNotice && (
        <div className="z-30 shrink-0 border-b border-indigo-800/40 bg-indigo-950/70 px-4 py-1.5 text-xs text-indigo-200 flex items-center justify-between">
          <div className="flex items-center gap-2 mx-auto">
            <span>🎧</span>
            <span><strong>Headphone Recommended:</strong> Please wear headphones to prevent acoustic echo and ensure high speech accuracy.</span>
          </div>
          <button
            onClick={() => setShowHeadphoneNotice(false)}
            className="text-indigo-400 hover:text-indigo-200 text-xs px-2 cursor-pointer"
            title="Dismiss notice"
          >
            ✕
          </button>
        </div>
      )}

      {/* Hardware Disconnect Warning Banner (Part C3) */}
      {deviceWarning && (
        <div className="z-40 shrink-0 bg-amber-500/95 text-slate-950 px-4 py-2 text-xs font-bold flex items-center justify-center gap-3">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>{deviceWarning}</span>
          <button
            type="button"
            onClick={() => setDeviceMenuOpen(true)}
            className="rounded-lg bg-slate-950 px-2.5 py-1 text-[11px] font-bold text-white hover:bg-slate-800"
          >
            Switch Device
          </button>
        </div>
      )}

      {/* Main two-pane layout: interviewer (left, fixed width) + candidate camera (right) */}
      <main className="relative z-10 flex-1 overflow-y-auto p-3 sm:p-5 md:overflow-hidden">
        <div className="grid h-full grid-cols-1 gap-4 md:grid-cols-[minmax(0,340px)_minmax(0,1fr)] sm:gap-5">
          {/* LEFT pane: interviewer orb, state pill, current scripted utterance */}
          <div className="flex min-h-[290px] flex-col overflow-hidden rounded-3xl border border-indigo-500/20 bg-slate-900 shadow-2xl md:min-h-0">
            <InterviewerOrb aiState={aiState} />

            <div className="flex justify-center px-4">
              {statePill && (
                <div
                  className={`inline-flex items-center gap-2 rounded-full border px-4 py-1.5 text-xs font-bold backdrop-blur-md transition-colors duration-300 ${statePill.cls}`}
                  data-state={aiState}
                >
                  {statePill.spin ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <span className={`h-2 w-2 rounded-full ${statePill.dot || 'bg-slate-500'}`} />
                  )}
                  <span>{statePill.label}</span>
                </div>
              )}
            </div>

            {/* Current scripted utterance / question — replaced on every update, never appended */}
            <div className="flex-1 overflow-y-auto px-5 pb-4 pt-3">
              <div className="flex flex-wrap items-center gap-2 text-[10px] font-bold uppercase tracking-wider text-slate-500">
                <Bot className="h-3.5 w-3.5 text-indigo-400" />
                <span>Interviewer</span>
                {skillName && (
                  <span className="rounded-md border border-indigo-800/60 bg-indigo-950/80 px-2 py-0.5 text-[10px] font-bold text-indigo-300">
                    {skillName}
                  </span>
                )}
                {isFollowup && (
                  <span className="rounded-md border border-amber-800/60 bg-amber-950/70 px-2 py-0.5 text-[10px] font-bold text-amber-300">
                    Follow-up
                  </span>
                )}
              </div>
              <p className="mt-2 whitespace-pre-wrap text-sm font-semibold leading-relaxed text-slate-100">
                {aiSubtitle || currentQuestionText || 'The interviewer is preparing…'}
              </p>
            </div>
          </div>

          {/* RIGHT pane: candidate camera preview + live caption of their own words */}
          <div
            className={`relative flex min-h-[290px] flex-col overflow-hidden rounded-3xl border bg-slate-900 shadow-2xl transition-all duration-300 md:min-h-0 ${
              candidateState === 'speaking'
                ? 'border-emerald-500 ring-4 ring-emerald-500/20'
                : candidateState === 'muted'
                ? 'border-rose-500/60 ring-2 ring-rose-500/10'
                : 'border-slate-800'
            }`}
          >
            {/* Top overlay badges */}
            <div className="absolute top-3 left-3 z-10 flex items-center gap-2">
              <div className="flex items-center gap-2 rounded-full bg-slate-950/70 px-3 py-1 text-xs font-semibold backdrop-blur-md border border-slate-700/50">
                <User className="h-3.5 w-3.5 text-slate-400" />
                <span>{candidateName || 'You (Candidate)'}</span>
              </div>
              {isMicMuted && (
                <span className="flex items-center gap-1.5 rounded-full bg-rose-500/20 px-2.5 py-1 text-[11px] font-bold text-rose-400 backdrop-blur-md border border-rose-500/40">
                  <MicOff className="h-3 w-3" /> Muted
                </span>
              )}
            </div>

            {/* Small inline camera/device controls (kept features, kept out of the primary control bar) */}
            <div className="absolute top-3 right-3 z-10 flex items-center gap-2">
              <button
                onClick={toggleVideo}
                className={`rounded-xl p-2 backdrop-blur-md transition-colors ${
                  isVideoOff ? 'bg-rose-600 text-white' : 'bg-slate-950/70 text-slate-300 hover:bg-slate-800'
                }`}
                title={isVideoOff ? 'Enable Camera' : 'Turn Off Camera'}
              >
                {isVideoOff ? <VideoOff className="h-4 w-4" /> : <Video className="h-4 w-4" />}
              </button>
              <button
                onClick={() => setDeviceMenuOpen((prev) => !prev)}
                className="rounded-xl bg-slate-950/70 p-2 text-slate-300 backdrop-blur-md hover:bg-slate-800 transition-colors"
                title="Switch Microphone or Camera Device"
              >
                <Settings className="h-4 w-4" />
              </button>
            </div>

            {/* Camera feed */}
            <div className="relative min-h-0 flex-1 bg-slate-950">
              {isVideoOff ? (
                <div className="flex h-full items-center justify-center">
                  <div className="flex flex-col items-center gap-2 text-slate-600">
                    <VideoOff className="h-12 w-12" />
                    <span className="text-xs font-medium">Camera is turned off</span>
                  </div>
                </div>
              ) : (
                <video
                  ref={candidateVideoRef}
                  autoPlay
                  playsInline
                  muted
                  className="h-full w-full object-cover transform -scale-x-100"
                />
              )}
            </div>

            {/* Live caption: candidate's own words (cleared when the answer is committed / a question starts) */}
            <div className="shrink-0 border-t border-slate-800/80 bg-slate-950/80 px-4 py-3">
              <div className="flex items-center gap-2 text-[10px] font-semibold font-mono uppercase tracking-wide text-emerald-400">
                <span
                  className={`h-1.5 w-1.5 rounded-full bg-emerald-400 ${
                    candidateState === 'speaking' || candidateIsInterim ? 'animate-ping' : ''
                  }`}
                />
                <span>{candidateIsInterim ? 'Your words (live)' : 'Your words'}</span>
              </div>
              <p className="mt-1 min-h-[2.5rem] line-clamp-3 text-xs sm:text-sm font-medium text-slate-100">
                {candidateSubtitle || 'Your answer will appear here as you speak…'}
              </p>
            </div>

            {/* Device Switcher Popover (Part C3) */}
            {deviceMenuOpen && (
              <div className="absolute right-3 top-16 z-30 w-72 space-y-3 rounded-2xl bg-slate-900 p-4 border border-slate-700 shadow-2xl text-xs">
                <div className="flex items-center justify-between font-bold text-white">
                  <span>Switch Input Devices</span>
                  <button onClick={() => setDeviceMenuOpen(false)} className="text-slate-400 hover:text-white">
                    ✕
                  </button>
                </div>
                <div>
                  <label className="mb-1 block text-[10px] font-bold uppercase text-slate-400">Microphone</label>
                  <select
                    value={selectedMicId}
                    onChange={(e) => handleSwitchDevice('audio', e.target.value)}
                    className="w-full rounded-xl bg-slate-800 px-2.5 py-1.5 text-xs text-white border border-slate-700"
                  >
                    {audioInputs.map((d, i) => (
                      <option key={d.deviceId || i} value={d.deviceId}>
                        {d.label || `Microphone ${i + 1}`}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-[10px] font-bold uppercase text-slate-400">Camera</label>
                  <select
                    value={selectedCamId}
                    onChange={(e) => handleSwitchDevice('video', e.target.value)}
                    className="w-full rounded-xl bg-slate-800 px-2.5 py-1.5 text-xs text-white border border-slate-700"
                  >
                    {videoInputs.map((d, i) => (
                      <option key={d.deviceId || i} value={d.deviceId}>
                        {d.label || `Camera ${i + 1}`}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-[10px] font-bold uppercase text-slate-400">Interviewer Voice Speed</label>
                  <select
                    value={speechSpeed}
                    onChange={(e) => handleSpeedChange(parseFloat(e.target.value))}
                    aria-label="Interviewer speech speed"
                    className="w-full rounded-xl bg-slate-800 px-2.5 py-1.5 text-xs text-white border border-slate-700"
                  >
                    <option value={0.85}>0.85x</option>
                    <option value={1.0}>1.0x</option>
                    <option value={1.15}>1.15x</option>
                  </select>
                </div>
              </div>
            )}
          </div>
        </div>
      </main>

      {/* Subtle inline notice ("toast") */}
      {inlineNotice && (
        <div className="pointer-events-none absolute bottom-32 left-1/2 z-40 -translate-x-1/2">
          <div
            className={`flex items-center gap-2 rounded-full border px-4 py-2 text-xs font-semibold shadow-xl backdrop-blur-md ${
              inlineNotice.tone === 'ok'
                ? 'bg-emerald-950/90 text-emerald-300 border-emerald-700/60'
                : 'bg-amber-950/90 text-amber-300 border-amber-700/60'
            }`}
          >
            {inlineNotice.tone === 'ok' ? (
              <CheckCircle2 className="h-3.5 w-3.5" />
            ) : (
              <AlertCircle className="h-3.5 w-3.5" />
            )}
            <span>{inlineNotice.text}</span>
          </div>
        </div>
      )}

      {/* Footer: collapsible transcript drawer + control bar */}
      <footer className="relative z-20 shrink-0 border-t border-slate-800 bg-slate-900/95 backdrop-blur-md">
        {transcriptOpen && (
          <div>
            <div ref={transcriptScrollRef} className="max-h-56 overflow-y-auto border-b border-slate-800 px-4 py-3">
              {transcriptEntries.length === 0 ? (
                <p className="text-xs text-slate-500">
                  Transcribed interviewer lines and your captured answers will collect here.
                </p>
              ) : (
                <div className="space-y-2.5 text-xs">
                  {transcriptEntries.map((entry, idx) => (
                    <div
                      key={idx}
                      className={`pl-2.5 border-l-2 ${
                        entry.kind === 'ai' ? 'border-indigo-500/60' : 'border-emerald-500/60'
                      }`}
                    >
                      <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                        {entry.kind === 'ai' ? 'Interviewer' : 'Candidate answer'} ·{' '}
                        {new Date(entry.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                      </div>
                      <p className="line-clamp-3 text-slate-300">{entry.text}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Transcript drawer tab */}
        <button
          type="button"
          onClick={() => setTranscriptOpen((prev) => !prev)}
          className="flex w-full items-center justify-center gap-1.5 py-1 text-[11px] font-bold text-slate-400 transition-colors hover:text-slate-200"
        >
          <MessageSquare className="h-3 w-3" />
          <span>
            Transcript{transcriptEntries.length > 0 ? ` (${transcriptEntries.length})` : ''}
          </span>
          <span>{transcriptOpen ? '▾ Hide' : '▴ Show'}</span>
        </button>

        {/* Primary controls bar */}
        <div className="flex flex-wrap items-center justify-center gap-2.5 px-4 pb-3 pt-1">
          <button
            onClick={toggleMic}
            className={`flex items-center gap-1.5 rounded-xl px-3.5 py-2 text-xs font-bold transition-colors ${
              isMicMuted ? 'bg-rose-600 text-white' : 'bg-slate-800 text-slate-200 hover:bg-slate-700'
            }`}
            title={isMicMuted ? 'Unmute Microphone' : 'Mute Microphone'}
          >
            {isMicMuted ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
            <span>{isMicMuted ? 'Unmute mic' : 'Mute mic'}</span>
          </button>

          <button
            onClick={handleCommitTurn}
            disabled={!canCommit}
            className={`flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-bold transition-all ${
              canCommit
                ? 'bg-gradient-to-r from-indigo-600 to-violet-600 text-white shadow-lg shadow-indigo-600/25 hover:from-indigo-500 hover:to-violet-500'
                : 'cursor-not-allowed border border-slate-700/60 bg-slate-800 text-slate-500'
            }`}
            title={
              interviewMode === 'simple'
                ? 'Commit your answer and move to the next question'
                : 'N/A in this session mode'
            }
          >
            {commitPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                <span>Saving your answer…</span>
              </>
            ) : (
              <span>I&apos;m done answering</span>
            )}
          </button>

          <button
            onClick={handleRepeatQuestion}
            disabled={!interviewBegun || repeatingQuestion}
            className="flex items-center gap-1.5 rounded-xl bg-slate-800 px-3.5 py-2 text-xs font-bold text-slate-200 hover:bg-slate-700 disabled:opacity-40 transition-colors"
            title="Ask the AI Interviewer to repeat the current question"
          >
            <RotateCcw className={`h-3.5 w-3.5 ${repeatingQuestion ? 'animate-spin' : ''}`} />
            <span>Repeat question</span>
          </button>

          <button
            onClick={() => setConfirmExitOpen(true)}
            className="flex items-center gap-1.5 rounded-xl border border-rose-500/30 bg-rose-600/20 px-3.5 py-2 text-xs font-bold text-rose-400 transition-colors hover:bg-rose-600 hover:text-white"
            title="End this live interview session"
          >
            <PhoneOff className="h-4 w-4" />
            <span>End interview</span>
          </button>
        </div>
      </footer>

      {/* Initial Begin Interview / Reconnect / Busy Overlay */}
      {showGatewayOverlay && (
        <div className="absolute inset-0 z-30 flex items-center justify-center bg-slate-950/75 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-3xl border border-slate-700/80 bg-slate-900 p-6 sm:p-8 text-center shadow-2xl">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-indigo-600/20 text-indigo-400 border border-indigo-500/30">
              <Sparkles className="h-7 w-7" />
            </div>
            <h3 className="mt-4 text-xl font-black text-white">
              {interviewBegun && connectionState === 'connecting'
                ? 'Reconnecting…'
                : interviewBegun && connectionState === 'error'
                ? 'Connection Interrupted'
                : connectionState === 'busy'
                ? 'Interviewer Busy'
                : 'Live Room Connected'}
            </h3>
            <p className="mt-2 text-xs text-slate-400 leading-relaxed">
              {connectionState === 'busy'
                ? connectionError
                : interviewBegun && (connectionState === 'error' || connectionState === 'connecting')
                ? connectionError || 'Re-establishing the real-time audio channel…'
                : "Your webcam and microphone are live and continuous audio streaming is primed. Click Begin Interview when you are ready to receive the interviewer's greeting."}
            </p>

            {/* Status Indicator */}
            <div className="mt-4 flex items-center justify-center gap-2">
              {connectionState === 'connected' ? (
                <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                  <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
                  Real-Time Audio Channel Primed
                </span>
              ) : connectionState === 'busy' || connectionState === 'error' ? (
                <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/30">
                  <AlertCircle className="h-3.5 w-3.5" />
                  {connectionError || 'Network handshake warning'}
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-indigo-500/10 text-indigo-400 border border-indigo-500/30">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Establishing Real-Time Audio Pipeline...
                </span>
              )}
            </div>

            {/* Headphone Recommendation */}
            <div className="mt-4 flex items-center justify-center gap-2 rounded-xl bg-slate-950/80 px-3.5 py-2.5 border border-slate-800 text-[11px] text-slate-300">
              <span className="text-base">🎧</span>
              <span><strong>Headphone Recommended:</strong> Please wear headphones to prevent acoustic echo and ensure high audio accuracy.</span>
            </div>

            {/* Action Buttons */}
            <div className="mt-6 space-y-3">
              {!interviewBegun && connectionState !== 'busy' && (
                <button
                  type="button"
                  onClick={handleBeginInterview}
                  className="w-full inline-flex items-center justify-center gap-2 rounded-xl px-6 py-3.5 text-sm font-bold text-white shadow-lg transition-all bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 shadow-indigo-600/30 cursor-pointer"
                >
                  <Play className="h-4 w-4 fill-white" />
                  <span>Begin Interview</span>
                </button>
              )}

              {(connectionState === 'error' || connectionState === 'busy') && (
                <button
                  type="button"
                  onClick={() => setRetryCount((prev) => prev + 1)}
                  className="w-full inline-flex items-center justify-center gap-2 rounded-xl border border-slate-700 bg-slate-800/80 px-4 py-2.5 text-xs font-bold text-slate-200 hover:bg-slate-700/80 transition-all cursor-pointer"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  <span>{interviewBegun ? 'Reconnect Session' : 'Retry Connection'}</span>
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Phase 5: Session Completed Celebration + Candidate Feedback Rating (Part G5) */}
      {currentPhase === 'completed' && (
        <div className="absolute inset-0 z-40 flex items-center justify-center bg-slate-950/90 p-4 backdrop-blur-md overflow-y-auto">
          <div className="w-full max-w-lg rounded-3xl border border-slate-700/80 bg-slate-900 p-6 sm:p-8 text-center shadow-2xl my-auto">
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/40">
              <CheckCircle2 className="h-8 w-8" />
            </div>
            <h3 className="mt-4 text-2xl font-black text-white">Interview Complete!</h3>
            <p className="mt-2 text-xs text-slate-300 leading-relaxed">
              Thank you for completing your interview for{' '}
              <strong className="text-indigo-400">{jobTitle}</strong>. Your responses have been saved for review.
            </p>

            {/* Post-Interview Rating & Feedback (Part G5) */}
            <div className="mt-5 rounded-2xl bg-slate-950/70 p-4 border border-slate-800 text-left space-y-3">
              <div className="text-xs font-bold text-slate-200 flex items-center justify-between">
                <span>How was your interview experience?</span>
                {feedbackSubmitted && (
                  <span className="text-emerald-400 text-[11px]">Thank you for your feedback! ✓</span>
                )}
              </div>
              <div className="flex items-center gap-2">
                {[1, 2, 3, 4, 5].map((star) => (
                  <button
                    key={star}
                    type="button"
                    disabled={feedbackSubmitted}
                    onClick={() => setFeedbackRating(star)}
                    className={`p-2 rounded-xl border transition-all ${
                      feedbackRating >= star
                        ? 'bg-amber-500/20 border-amber-500/50 text-amber-400'
                        : 'bg-slate-900 border-slate-800 text-slate-600 hover:text-slate-400'
                    }`}
                  >
                    <Star className={`h-5 w-5 ${feedbackRating >= star ? 'fill-amber-400' : ''}`} />
                  </button>
                ))}
              </div>
              {!feedbackSubmitted && feedbackRating > 0 && (
                <div className="space-y-2 pt-1">
                  <textarea
                    rows={2}
                    value={feedbackComment}
                    onChange={(e) => setFeedbackComment(e.target.value)}
                    placeholder="Optional comments on audio quality, question clarity, or pacing..."
                    className="w-full rounded-xl bg-slate-900 border border-slate-800 p-2.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
                  />
                  <button
                    type="button"
                    disabled={submittingFeedback}
                    onClick={handleSubmitFeedback}
                    className="rounded-xl bg-indigo-600/80 hover:bg-indigo-600 px-4 py-1.5 text-xs font-bold text-white transition-colors"
                  >
                    {submittingFeedback ? 'Saving...' : 'Submit Feedback'}
                  </button>
                </div>
              )}
            </div>

            <button
              type="button"
              disabled={isEndingSession}
              onClick={handleEndSessionAndExit}
              className="mt-6 w-full inline-flex items-center justify-center gap-2 rounded-xl bg-indigo-600 px-6 py-3 text-sm font-bold text-white hover:bg-indigo-500 disabled:opacity-60 transition-all cursor-pointer"
            >
              <span>{isEndingSession ? 'Finalizing Session...' : 'Return to Candidate Portal'}</span>
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      {/* Confirmation Modal for Ending Call Early */}
      {confirmExitOpen && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-2xl text-center">
            <h4 className="text-base font-bold text-white">Leave Interview Room?</h4>
            <p className="mt-2 text-xs text-slate-400">
              Are you sure you want to end this live session? Your turns up to this point are durably saved.
            </p>
            <div className="mt-6 flex items-center justify-end gap-3">
              <button
                type="button"
                disabled={isEndingSession}
                onClick={() => setConfirmExitOpen(false)}
                className="rounded-xl border border-slate-700 px-4 py-2 text-xs font-semibold text-slate-300 hover:bg-slate-800 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={isEndingSession}
                onClick={handleEndSessionAndExit}
                className="rounded-xl bg-rose-600 px-4 py-2 text-xs font-bold text-white hover:bg-rose-500 disabled:opacity-50"
              >
                {isEndingSession ? 'Leaving...' : 'Leave Room'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Audio Autoplay Unblock Banner */}
      {audioAutoplayBlocked && (
        <div className="absolute top-20 left-1/2 z-50 -translate-x-1/2 flex items-center gap-3 rounded-2xl bg-amber-500/95 text-slate-950 px-5 py-2.5 shadow-2xl backdrop-blur-md animate-bounce">
          <VolumeX className="h-5 w-5 shrink-0 text-slate-950" />
          <span className="text-xs font-bold">Browser blocked audio playback. Click Unmute to hear the AI interviewer:</span>
          <button
            type="button"
            onClick={() => {
              if (remoteAudioRef.current) {
                remoteAudioRef.current.play().then(() => setAudioAutoplayBlocked(false)).catch(() => {});
              }
            }}
            className="rounded-lg bg-slate-950 px-3 py-1 text-xs font-bold text-white hover:bg-slate-800 cursor-pointer"
          >
            Unmute
          </button>
        </div>
      )}

      {/* Remote audio element to route incoming WebRTC bot audio to speakers */}
      <audio
        ref={remoteAudioRef}
        autoPlay
        playsInline
        muted={false}
        style={{ position: 'fixed', top: -1000, left: -1000, opacity: 0, pointerEvents: 'none' }}
      />
    </div>
  );
}
