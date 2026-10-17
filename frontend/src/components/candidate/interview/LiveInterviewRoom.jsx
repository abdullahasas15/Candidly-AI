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
  Volume2,
  VolumeX,
  Play,
  RotateCcw,
  ShieldCheck,
  ChevronRight,
  Loader2,
  Radio,
  Activity,
  Cpu,
  Zap,
  Wifi,
  Star,
  Settings,
  MessageSquare,
} from 'lucide-react';

import { PipecatClient } from '@pipecat-ai/client-js';
import { SmallWebRTCTransport } from '@pipecat-ai/small-webrtc-transport';

// Enterprise-Grade Cybernetic AI Interviewer Avatar
function CyberBotAvatar({ aiState }) {
  const isSpeaking = aiState === 'speaking';
  const isThinking = aiState === 'thinking';
  const isListening = aiState === 'listening';

  return (
    <div className="relative flex-1 flex flex-col items-center justify-center bg-gradient-to-b from-slate-900 via-[#070b14] to-slate-950 p-4 sm:p-6 overflow-hidden select-none">
      {/* Tactical Corner Brackets */}
          <div className="absolute top-4 left-4 w-5 h-5 border-t-2 border-l-2 border-cyan-500/40 pointer-events-none" />
          <div className="absolute top-4 right-4 w-5 h-5 border-t-2 border-r-2 border-cyan-500/40 pointer-events-none" />
          <div className="absolute bottom-4 left-4 w-5 h-5 border-b-2 border-l-2 border-cyan-500/40 pointer-events-none" />
          <div className="absolute bottom-4 right-4 w-5 h-5 border-b-2 border-r-2 border-cyan-500/40 pointer-events-none" />

          {/* Ambient Radial Backlight Glow */}
          <div
            className={`absolute h-72 w-72 rounded-full blur-3xl opacity-25 transition-all duration-700 pointer-events-none ${
              isSpeaking
                ? 'bg-violet-600 scale-125'
                : isThinking
                ? 'bg-amber-500 scale-110'
                : isListening
                ? 'bg-emerald-500 scale-115'
                : 'bg-indigo-600/70 scale-95'
            }`}
          />

          <div className="relative z-10 flex flex-col items-center">
            {/* Holographic Overhead Ring */}
            <div className="relative mb-3 flex items-center justify-center">
              <div
                className={`h-2 rounded-full transition-all duration-500 ${
                  isSpeaking
                    ? 'w-32 bg-gradient-to-r from-violet-500 via-fuchsia-400 to-indigo-500 shadow-lg shadow-violet-500/50 animate-pulse'
                    : isThinking
                    ? 'w-24 bg-gradient-to-r from-amber-400 via-orange-400 to-amber-500 shadow-lg shadow-amber-500/50 animate-pulse'
                    : isListening
                    ? 'w-28 bg-gradient-to-r from-emerald-400 via-teal-300 to-cyan-400 shadow-lg shadow-emerald-500/50 animate-pulse'
                    : 'w-20 bg-gradient-to-r from-slate-600 via-indigo-500 to-slate-600 shadow-sm'
                }`}
              />
            </div>

            {/* High-Tech Vector Robot Face */}
            <div className="relative w-44 h-44 sm:w-52 sm:h-52 flex items-center justify-center">
              {/* Concentric Sonic Aura Rings */}
              {isSpeaking && (
                <>
                  <div className="absolute inset-0 rounded-full border border-violet-500/30 animate-ping [animation-duration:2s]" />
                  <div className="absolute -inset-4 rounded-full border border-indigo-500/20 animate-pulse [animation-duration:1.2s]" />
                </>
              )}
              {isListening && (
                <div className="absolute -inset-3 rounded-full border border-emerald-400/30 animate-pulse [animation-duration:1.5s]" />
              )}

              <svg
                viewBox="0 0 200 200"
                className="w-full h-full drop-shadow-[0_12px_28px_rgba(0,0,0,0.65)]"
              >
                <defs>
                  <linearGradient id="chassisGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stopColor="#1E293B" />
                    <stop offset="50%" stopColor="#0F172A" />
                    <stop offset="100%" stopColor="#020617" />
                  </linearGradient>
                  <linearGradient id="plateBorder" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" stopColor="#38BDF8" stopOpacity="0.8" />
                    <stop offset="50%" stopColor="#818CF8" stopOpacity="0.4" />
                    <stop offset="100%" stopColor="#A855F7" stopOpacity="0.8" />
                  </linearGradient>
                  <linearGradient id="visorGlass" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" stopColor="#050B14" />
                    <stop offset="100%" stopColor="#0A1526" />
                  </linearGradient>
                  <linearGradient id="visorGlowSpeaking" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" stopColor="#8B5CF6" />
                    <stop offset="50%" stopColor="#EC4899" />
                    <stop offset="100%" stopColor="#6366F1" />
                  </linearGradient>
                  <linearGradient id="visorGlowListening" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" stopColor="#10B981" />
                    <stop offset="50%" stopColor="#06B6D4" />
                    <stop offset="100%" stopColor="#3B82F6" />
                  </linearGradient>
                  <linearGradient id="visorGlowThinking" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" stopColor="#F59E0B" />
                    <stop offset="50%" stopColor="#F97316" />
                    <stop offset="100%" stopColor="#EAB308" />
                  </linearGradient>
                </defs>

                {/* Ear Antennas / Audio Receptor Pods */}
                <path d="M 28 85 L 38 78 L 38 122 L 28 115 Z" fill="#1E293B" stroke="#475569" strokeWidth="1.5" />
                <circle cx="33" cy="100" r="3.5" fill={isSpeaking ? '#A855F7' : isListening ? '#10B981' : isThinking ? '#F59E0B' : '#38BDF8'} />

                <path d="M 172 85 L 162 78 L 162 122 L 172 115 Z" fill="#1E293B" stroke="#475569" strokeWidth="1.5" />
                <circle cx="167" cy="100" r="3.5" fill={isSpeaking ? '#A855F7' : isListening ? '#10B981' : isThinking ? '#F59E0B' : '#38BDF8'} />

                {/* Neck Mechanical Structure */}
                <rect x="88" y="152" width="24" height="24" rx="4" fill="#0F172A" stroke="#334155" strokeWidth="1.5" />
                <line x1="94" y1="156" x2="94" y2="172" stroke="#475569" strokeWidth="2" />
                <line x1="100" y1="156" x2="100" y2="172" stroke="#475569" strokeWidth="2" />
                <line x1="106" y1="156" x2="106" y2="172" stroke="#475569" strokeWidth="2" />

                {/* Torso Collar Plates */}
                <path d="M 50 176 L 150 176 L 165 198 L 35 198 Z" fill="#090E17" stroke="#1E293B" strokeWidth="2" />
                <circle cx="100" cy="186" r="4" fill={isSpeaking ? '#8B5CF6' : isListening ? '#10B981' : isThinking ? '#F59E0B' : '#0EA5E9'} />

                {/* Main Cranium Helmet */}
                <path
                  d="M 44 80 C 44 45, 70 30, 100 30 C 130 30, 156 45, 156 80 L 156 120 C 156 142, 134 156, 100 156 C 66 156, 44 142, 44 120 Z"
                  fill="url(#chassisGrad)"
                  stroke="url(#plateBorder)"
                  strokeWidth="2.5"
                />

                {/* Forehead Micro-Seams */}
                <path d="M 75 42 L 100 48 L 125 42" fill="none" stroke="#334155" strokeWidth="1.5" />
                <circle cx="100" cy="48" r="2" fill="#38BDF8" />

                {/* Curved Cyber Visor */}
                <rect
                  x="52"
                  y="72"
                  width="96"
                  height="48"
                  rx="18"
                  fill="url(#visorGlass)"
                  stroke={
                    isSpeaking
                      ? 'url(#visorGlowSpeaking)'
                      : isListening
                      ? 'url(#visorGlowListening)'
                      : isThinking
                      ? 'url(#visorGlowThinking)'
                      : '#1E293B'
                  }
                  strokeWidth="2.5"
                />

                {/* Gloss Reflection Highlight */}
                <path
                  d="M 58 78 Q 100 70 142 78"
                  fill="none"
                  stroke="white"
                  strokeOpacity="0.25"
                  strokeWidth="1.5"
                />

                {/* Visor Animated HUD Content */}
                {isSpeaking && (
                  <g className="animate-pulse">
                    <rect x="68" y="86" width="4" height="20" rx="2" fill="#C084FC" />
                    <rect x="78" y="80" width="4" height="32" rx="2" fill="#E879F9" />
                    <rect x="88" y="84" width="4" height="24" rx="2" fill="#818CF8" />
                    <rect x="98" y="77" width="4" height="38" rx="2" fill="#F472B6" />
                    <rect x="108" y="83" width="4" height="26" rx="2" fill="#818CF8" />
                    <rect x="118" y="80" width="4" height="32" rx="2" fill="#E879F9" />
                    <rect x="128" y="87" width="4" height="18" rx="2" fill="#C084FC" />
                  </g>
                )}

                {isThinking && (
                  <g>
                    <circle cx="100" cy="96" r="14" fill="none" stroke="#F59E0B" strokeWidth="1.5" strokeDasharray="3 3" />
                    <circle cx="100" cy="96" r="6" fill="#F59E0B" className="animate-ping" />
                    <circle cx="100" cy="96" r="3" fill="#FFFBEB" />
                    <line x1="86" y1="96" x2="114" y2="96" stroke="#F59E0B" strokeWidth="1" strokeOpacity="0.6" />
                    <line x1="100" y1="82" x2="100" y2="110" stroke="#F59E0B" strokeWidth="1" strokeOpacity="0.6" />
                  </g>
                )}

                {isListening && (
                  <g>
                    <circle cx="100" cy="96" r="18" fill="none" stroke="#10B981" strokeWidth="1" strokeOpacity="0.4" />
                    <circle cx="100" cy="96" r="11" fill="none" stroke="#06B6D4" strokeWidth="1.5" strokeOpacity="0.8" />
                    <circle cx="100" cy="96" r="4" fill="#34D399" />
                    <circle cx="78" cy="96" r="2" fill="#06B6D4" />
                    <circle cx="122" cy="96" r="2" fill="#06B6D4" />
                  </g>
                )}

                {!isSpeaking && !isThinking && !isListening && (
                  <g>
                    <rect x="74" y="94" width="52" height="4" rx="2" fill="#38BDF8" />
                    <circle cx="100" cy="96" r="3.5" fill="#FFFFFF" />
                  </g>
                )}

                {/* Acoustic Lower Speaker Vents */}
                <g opacity="0.8">
                  <line x1="84" y1="134" x2="116" y2="134" stroke="#334155" strokeWidth="2" strokeLinecap="round" />
                  <line x1="88" y1="139" x2="112" y2="139" stroke="#334155" strokeWidth="1.5" strokeLinecap="round" />
                  <line x1="92" y1="144" x2="108" y2="144" stroke="#334155" strokeWidth="1.5" strokeLinecap="round" />
                </g>
              </svg>
            </div>

            {/* State Telemetry Badge */}
            <div className="mt-4 flex flex-col items-center gap-2">
              <div
                className={`inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-xs font-bold tracking-wide backdrop-blur-md border shadow-lg transition-colors duration-300 ${
                  isSpeaking
                    ? 'bg-violet-950/70 text-violet-300 border-violet-700/60 shadow-violet-900/30'
                    : isThinking
                    ? 'bg-amber-950/70 text-amber-300 border-amber-700/60 shadow-amber-900/30'
                    : isListening
                    ? 'bg-emerald-950/70 text-emerald-300 border-emerald-700/60 shadow-emerald-900/30'
                    : 'bg-slate-900/80 text-slate-300 border-slate-700/60'
                }`}
              >
                <span
                  className={`h-2.5 w-2.5 rounded-full ${
                    isSpeaking
                      ? 'bg-violet-400 animate-ping'
                      : isThinking
                      ? 'bg-amber-400 animate-pulse'
                      : isListening
                      ? 'bg-emerald-400 animate-pulse'
                      : 'bg-slate-500'
                  }`}
                />
                <span>
                  {isSpeaking
                    ? 'VOICE ENGINE STREAMING'
                    : isThinking
                    ? 'NEURAL EVALUATION & PLANNING'
                    : isListening
                    ? 'LISTENING TO CANDIDATE'
                    : 'AI INTERVIEWER STANDBY'}
                </span>
              </div>

              {/* Symmetrical Real-Time Voice Equalizer Display (16 bars) */}
              <div className="flex items-center gap-1 h-8 px-4 py-1 rounded-xl bg-slate-950/60 border border-slate-800/80">
                {[4, 8, 14, 20, 26, 18, 12, 6, 6, 12, 18, 26, 20, 14, 8, 4].map((baseH, idx) => {
                  const activeH = isSpeaking
                    ? Math.min(28, Math.max(5, (baseH * (0.6 + Math.sin(idx * 0.9) * 0.4)) * 1.2))
                    : isThinking
                    ? 5 + (idx % 3) * 3
                    : isListening
                    ? 4 + (idx % 2) * 4
                    : 3;
                  return (
                    <span
                      key={idx}
                      style={{ height: `${activeH}px` }}
                      className={`w-1 rounded-full transition-all duration-150 ${
                        isSpeaking
                          ? 'bg-gradient-to-t from-indigo-500 to-violet-300'
                          : isThinking
                          ? 'bg-amber-500/60'
                          : isListening
                          ? 'bg-emerald-500/60'
                          : 'bg-slate-700'
                      }`}
                    />
                  );
                })}
              </div>

              {/* Subtitle Telemetry Metadata */}
              <div className="flex items-center gap-2 text-[10px] text-slate-500 font-mono tracking-wider">
                <span>KOKORO-82M TTS</span>
                <span>•</span>
                <span>24KHZ LOSSLESS</span>
                <span>•</span>
                <span>SMART TURN V3</span>
              </div>
            </div>
          </div>
    </div>
  );
}

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

  // Audio / Visual states
  const [aiState, setAiState] = useState('idle'); // idle, listening, speaking, thinking, interrupted
  const [candidateState, setCandidateState] = useState('listening'); // listening, speaking, muted
  const [isMicMuted, setIsMicMuted] = useState(false);
  const [isVideoOff, setIsVideoOff] = useState(false);
  const [confirmExitOpen, setConfirmExitOpen] = useState(false);
  const [isEndingSession, setIsEndingSession] = useState(false);
  const [audioAutoplayBlocked, setAudioAutoplayBlocked] = useState(false);

  // Candidate Experience controls (Part G1, G2, G3, G5)
  const [captionsEnabled, setCaptionsEnabled] = useState(true);
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

  // Real-time Subtitles for AI Interviewer and Candidate
  const [aiSubtitle, setAiSubtitle] = useState('');
  const [candidateSubtitle, setCandidateSubtitle] = useState('');
  const [candidateIsInterim, setCandidateIsInterim] = useState(false);
  const [showQuestionCard, setShowQuestionCard] = useState(true);
  const [showHeadphoneNotice, setShowHeadphoneNotice] = useState(true);
  const audioCtxRef = useRef(null);

  // Timer
  const [secondsElapsed, setSecondsElapsed] = useState(0);

  // Media references
  const candidateVideoRef = useRef(null);
  const remoteAudioRef = useRef(null);
  const localStreamRef = useRef(null);
  const peerConnRef = useRef(null);

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
            setRemainingSeconds(data.live_status.remaining_seconds);
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
            setAiState('listening');
          }
        });

        pipecatClient.on('userStoppedSpeaking', () => {
          setCandidateState(isMicMuted ? 'muted' : 'listening');
        });

        // Custom RTVI messages emitted by InterviewCoordinatorProcessor
        pipecatClient.on('serverMessage', (payload) => {
          if (!payload) return;
          const msg = payload.data || payload;

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
            if (msg.skill_name) {
              setSkillName(msg.skill_name);
            }
            if (typeof msg.remaining_seconds === 'number') {
              setRemainingSeconds(msg.remaining_seconds);
            }
            if (msg.grace_extended) {
              setGraceExtended(true);
            }
            setIsFollowup(Boolean(msg.is_followup));
          } else if (msg.type === 'interview-bot-state') {
            if (msg.state) setAiState(msg.state);
          } else if (msg.type === 'ai-speech-transcript' && msg.text) {
            setAiSubtitle(msg.text);
            if (msg.question_text) {
              setCurrentQuestionText(msg.question_text);
            } else if (msg.text.includes('?') || msg.phase === 'deep_dive') {
              setCurrentQuestionText(msg.text);
            }
          } else if (msg.type === 'candidate-speech-transcript' && msg.text) {
            setCandidateSubtitle(msg.text);
            setCandidateIsInterim(Boolean(msg.is_interim));
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
  }, [sessionId, token, retryCount, getAuthHeaders]);

  // 4. Timer & Network Stats Sampling (Part B8 & C3)
  useEffect(() => {
    if (!interviewBegun || currentPhase === 'completed') return;
    const timer = setInterval(() => {
      setSecondsElapsed((prev) => prev + 1);
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

      await fetch(`/api/interview-sessions/${sessionId}/begin`, {
        method: 'POST',
        headers: getAuthHeaders(),
      });
    } catch (err) {
      console.error('Error starting interview:', err);
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
        method: 'POST',
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

  const getPhaseDisplay = () => {
    switch (currentPhase) {
      case 'greeting':
      case 'ready_check':
        return 'Phase 1: Welcome & Readiness Check';
      case 'self_intro':
        return 'Phase 2: Self-Introduction';
      case 'deep_dive':
        return isFollowup
          ? `Deep Dive: Follow-up (${currentQuestionIndex + 1}/${totalQuestions})`
          : `Deep Dive: Question ${currentQuestionIndex + 1} of ${totalQuestions}`;
      case 'candidate_questions':
        return 'Phase 4: Candidate Q&A';
      case 'closing':
        return 'Phase 5: Closing & Next Steps';
      case 'completed':
        return 'Interview Session Completed';
      default:
        return 'AI Voice Interview Room';
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-slate-950 text-white select-none">
      {/* Top Header Bar */}
      <header className="flex h-16 items-center justify-between border-b border-slate-800 bg-slate-900/80 px-4 sm:px-6 backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-600/20 text-indigo-400 border border-indigo-500/30">
            <Sparkles className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-bold text-slate-100">{jobTitle || 'Technical Interview'}</span>
              <span className="rounded-full bg-slate-800 px-2 py-0.5 text-[10px] font-semibold text-slate-400">
                Live Room
              </span>
            </div>
            <div className="text-xs text-slate-400">Candidate: {candidateName || 'Candidate'}</div>
          </div>
        </div>

        {/* Session Progress Indicator */}
        <div className="hidden md:flex items-center gap-3 rounded-full bg-slate-800/80 px-4 py-1.5 border border-slate-700/60">
          <span className="h-2 w-2 rounded-full bg-indigo-400 animate-pulse" />
          <span className="text-xs font-semibold text-slate-200">{getPhaseDisplay()}</span>
          {skillName && currentPhase === 'deep_dive' && (
            <span className="rounded-md bg-indigo-950 px-2 py-0.5 text-[10px] font-bold text-indigo-300 border border-indigo-800/60">
              {skillName}
            </span>
          )}
        </div>

        {/* Network Quality, Remaining Time & Exit */}
        <div className="flex items-center gap-2.5 sm:gap-3">
          {/* Network Quality Badge (Part C3) */}
          <div
            className={`hidden sm:flex items-center gap-1.5 rounded-xl px-2.5 py-1.5 text-[11px] font-semibold border ${
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

          {/* Remaining Time & Grace Extension Badge (Part B8) */}
          <div className="flex items-center gap-1.5 rounded-xl bg-slate-800/60 px-3 py-1.5 text-xs font-mono font-bold text-slate-300 border border-slate-800">
            <Clock className="h-3.5 w-3.5 text-indigo-400" />
            <span title="Elapsed">{formatTimer(secondsElapsed)}</span>
            <span className="text-slate-500">·</span>
            <span className="text-emerald-400" title="Remaining Budget">
              -{formatTimer(remainingSeconds)}
            </span>
            {graceExtended && (
              <span className="ml-1 rounded bg-amber-500/20 px-1.5 py-0.5 text-[9px] font-sans font-bold text-amber-300 border border-amber-500/40">
                +5m Grace
              </span>
            )}
          </div>

          <button
            onClick={() => setConfirmExitOpen(true)}
            className="flex items-center gap-1.5 rounded-xl bg-rose-600/20 px-3.5 py-1.5 text-xs font-bold text-rose-400 hover:bg-rose-600 hover:text-white transition-colors border border-rose-500/30"
          >
            <PhoneOff className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">End Call</span>
          </button>
        </div>
      </header>

      {/* Headphone Recommended Notice */}
      {showHeadphoneNotice && (
        <div className="bg-indigo-950/70 border-b border-indigo-800/40 px-4 py-1.5 text-xs text-indigo-200 flex items-center justify-between z-30">
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
        <div className="bg-amber-500/95 text-slate-950 px-4 py-2 text-xs font-bold flex items-center justify-center gap-3 z-40">
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

      {/* Main Two-Pane Real-Time Layout */}
      <main className="relative flex-1 p-4 sm:p-6 grid grid-cols-1 md:grid-cols-2 gap-4 sm:gap-6 overflow-hidden">
        {/* Left Pane: Candidate's Live Webcam Video Feed */}
        <div
          className={`relative flex flex-col justify-between overflow-hidden rounded-3xl bg-slate-900 border transition-all duration-300 shadow-2xl ${
            candidateState === 'speaking'
              ? 'border-emerald-500 ring-4 ring-emerald-500/20'
              : candidateState === 'muted'
              ? 'border-rose-500/60 ring-2 ring-rose-500/10'
              : 'border-slate-800'
          }`}
        >
          {/* Top Overlay Badge */}
          <div className="absolute top-4 left-4 z-10 flex items-center gap-2">
            <div className="flex items-center gap-2 rounded-full bg-slate-950/70 px-3 py-1 text-xs font-semibold backdrop-blur-md border border-slate-700/50">
              <User className="h-3.5 w-3.5 text-slate-400" />
              <span>{candidateName || 'You (Candidate)'}</span>
            </div>

            {candidateState === 'speaking' && (
              <span className="flex items-center gap-1.5 rounded-full bg-emerald-500/20 px-2.5 py-1 text-[11px] font-bold text-emerald-400 backdrop-blur-md border border-emerald-500/40 animate-pulse">
                <span className="h-2 w-2 rounded-full bg-emerald-400" /> Speaking
              </span>
            )}
            {candidateState === 'listening' && (
              <span className="flex items-center gap-1.5 rounded-full bg-indigo-500/20 px-2.5 py-1 text-[11px] font-semibold text-indigo-300 backdrop-blur-md border border-indigo-500/30">
                Listening
              </span>
            )}
            {candidateState === 'muted' && (
              <span className="flex items-center gap-1.5 rounded-full bg-rose-500/20 px-2.5 py-1 text-[11px] font-bold text-rose-400 backdrop-blur-md border border-rose-500/40">
                <MicOff className="h-3 w-3" /> Muted
              </span>
            )}
          </div>

          {/* Video Feed */}
          <div className="relative flex-1 flex items-center justify-center bg-slate-950">
            {isVideoOff ? (
              <div className="flex flex-col items-center gap-2 text-slate-600">
                <VideoOff className="h-12 w-12" />
                <span className="text-xs font-medium">Camera is turned off</span>
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

          {/* Candidate Live Subtitle Transcript Banner (Dual-Lane STT: Lane 1 Interim + Lane 2 Accuracy) */}
          {captionsEnabled && (
            <div className="absolute bottom-20 left-4 right-4 z-10 rounded-2xl bg-slate-950/90 p-3.5 backdrop-blur-md border border-emerald-500/30 shadow-xl transition-all">
              <div className="flex items-center justify-between text-[11px] font-semibold text-slate-400 mb-1">
                <span className="flex items-center gap-1.5 text-emerald-400 font-mono tracking-wide">
                  <span className={`h-2 w-2 rounded-full bg-emerald-400 ${candidateState === 'speaking' || candidateIsInterim ? 'animate-ping' : ''}`} />
                  {candidateIsInterim ? 'CANDIDATE LIVE SPEECH (STREAMING)' : 'CANDIDATE SPEECH (ACCURACY)'}
                </span>
                <span className="text-[10px] text-slate-500 font-mono">PARAKEET TDT STT</span>
              </div>
              <p className={`text-xs sm:text-sm font-medium line-clamp-3 transition-colors ${candidateIsInterim ? 'text-slate-300 italic' : 'text-slate-100 not-italic'}`}>
                {candidateSubtitle ? (
                  <>
                    <span>{candidateSubtitle}</span>
                    {candidateIsInterim && (
                      <span className="inline-block w-1.5 h-1.5 ml-1.5 rounded-full bg-emerald-400 animate-pulse align-middle" />
                    )}
                  </>
                ) : (
                  candidateState === 'speaking' ? 'Listening and transcribing response...' : 'Microphone active — speak anytime to respond...'
                )}
              </p>
            </div>
          )}

          {/* Bottom Floating Control Bar (Mic, Video, Captions, Repeat Question, Speed, Device Switcher) */}
          <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-20 flex items-center gap-2 rounded-2xl bg-slate-950/90 p-2 backdrop-blur-md border border-slate-700/60 shadow-lg">
            <button
              onClick={toggleMic}
              className={`rounded-xl p-2.5 transition-colors ${
                isMicMuted ? 'bg-rose-600 text-white' : 'bg-slate-800 text-slate-200 hover:bg-slate-700'
              }`}
              title={isMicMuted ? 'Unmute Microphone' : 'Mute Microphone'}
            >
              {isMicMuted ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
            </button>

            <button
              onClick={toggleVideo}
              className={`rounded-xl p-2.5 transition-colors ${
                isVideoOff ? 'bg-rose-600 text-white' : 'bg-slate-800 text-slate-200 hover:bg-slate-700'
              }`}
              title={isVideoOff ? 'Enable Camera' : 'Turn Off Camera'}
            >
              {isVideoOff ? <VideoOff className="h-4 w-4" /> : <Video className="h-4 w-4" />}
            </button>

            {/* Captions Toggle (Part G1) */}
            <button
              onClick={() => setCaptionsEnabled((prev) => !prev)}
              className={`rounded-xl px-2.5 py-2 text-xs font-bold transition-colors ${
                captionsEnabled
                  ? 'bg-indigo-600 text-white'
                  : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
              }`}
              title={captionsEnabled ? 'Hide Live Captions' : 'Show Live Captions'}
            >
              CC
            </button>

            {/* Repeat Question Button (Part G2) */}
            <button
              onClick={handleRepeatQuestion}
              disabled={!interviewBegun || repeatingQuestion}
              className="flex items-center gap-1 rounded-xl bg-slate-800 px-3 py-2 text-xs font-bold text-slate-200 hover:bg-slate-700 disabled:opacity-40 transition-colors"
              title="Ask the AI Interviewer to repeat the current question"
            >
              <RotateCcw className={`h-3.5 w-3.5 ${repeatingQuestion ? 'animate-spin' : ''}`} />
              <span className="hidden sm:inline">Repeat</span>
            </button>

            {/* Speech Speed Selector (Part G3) */}
            <select
              value={speechSpeed}
              onChange={(e) => handleSpeedChange(parseFloat(e.target.value))}
              aria-label="Interviewer speech speed"
              title="Interviewer Voice Speed"
              className="rounded-xl bg-slate-800 px-2.5 py-2 text-xs font-bold text-slate-200 border border-slate-700 focus:outline-none"
            >
              <option value={0.85}>0.85x</option>
              <option value={1.0}>1.0x</option>
              <option value={1.15}>1.15x</option>
            </select>

            {/* Device Switcher Button (Part C3) */}
            <button
              onClick={() => setDeviceMenuOpen((prev) => !prev)}
              className="rounded-xl bg-slate-800 p-2.5 text-slate-300 hover:bg-slate-700 transition-colors"
              title="Switch Microphone or Camera Device"
            >
              <Settings className="h-4 w-4" />
            </button>
          </div>

          {/* Device Switcher Popover (Part C3) */}
          {deviceMenuOpen && (
            <div className="absolute bottom-20 left-4 right-4 sm:left-auto sm:right-4 sm:w-72 z-30 rounded-2xl bg-slate-900 p-4 border border-slate-700 shadow-2xl space-y-3 text-xs">
              <div className="flex items-center justify-between font-bold text-white">
                <span>Switch Input Devices</span>
                <button onClick={() => setDeviceMenuOpen(false)} className="text-slate-400 hover:text-white">
                  ✕
                </button>
              </div>
              <div>
                <label className="block text-[10px] font-bold uppercase text-slate-400 mb-1">Microphone</label>
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
                <label className="block text-[10px] font-bold uppercase text-slate-400 mb-1">Camera</label>
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
            </div>
          )}
        </div>

        {/* Right Pane: AI Interviewer High-Tech CyberBot & Live Speech Subtitles */}
        <div
          className={`relative flex flex-col justify-between overflow-hidden rounded-3xl bg-slate-900 border transition-all duration-300 shadow-2xl ${
            aiState === 'speaking'
              ? 'border-indigo-500 ring-4 ring-indigo-500/20'
              : aiState === 'thinking'
              ? 'border-amber-500 ring-2 ring-amber-500/20'
              : 'border-slate-800'
          }`}
        >
          {/* Top Overlay Badge & Prominent Bot State Indicator Pill */}
          <div className="absolute top-4 left-4 z-10 flex items-center gap-2">
            <div className="flex items-center gap-2 rounded-full bg-slate-950/70 px-3 py-1 text-xs font-semibold backdrop-blur-md border border-slate-700/50">
              <Bot className="h-3.5 w-3.5 text-indigo-400" />
              <span>AI Interviewer</span>
            </div>

            {aiState === 'speaking' && (
              <span className="flex items-center gap-1.5 rounded-full bg-violet-500/20 px-3 py-1 text-xs font-bold text-violet-300 backdrop-blur-md border border-violet-500/40 shadow-sm animate-pulse">
                <Volume2 className="h-3.5 w-3.5 text-violet-400" />
                <span>Speaking...</span>
              </span>
            )}
            {aiState === 'thinking' && (
              <span className="flex items-center gap-1.5 rounded-full bg-amber-500/20 px-3 py-1 text-xs font-bold text-amber-300 backdrop-blur-md border border-amber-500/40 shadow-sm">
                <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-400" />
                <span>Processing response...</span>
              </span>
            )}
            {aiState === 'listening' && (
              <span className="flex items-center gap-1.5 rounded-full bg-emerald-500/20 px-3 py-1 text-xs font-semibold text-emerald-300 backdrop-blur-md border border-emerald-500/40 shadow-sm">
                <span className="relative flex h-2.5 w-2.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500"></span>
                </span>
                <span>Listening to you...</span>
              </span>
            )}
            {aiState === 'interrupted' && (
              <span className="flex items-center gap-1.5 rounded-full bg-rose-500/20 px-3 py-1 text-xs font-semibold text-rose-300 backdrop-blur-md border border-rose-500/40 shadow-sm">
                <span>Listening (interrupted)</span>
              </span>
            )}
            {aiState === 'idle' && (
              <span className="rounded-full bg-slate-800/80 px-3 py-1 text-xs font-medium text-slate-400 border border-slate-700/40">
                Ready
              </span>
            )}
          </div>

          {/* Dedicated Question Card (Pinned & Toggleable) */}
          {showQuestionCard && (currentQuestionText || aiSubtitle) && (
            <div className="absolute top-16 left-4 right-4 z-20 rounded-2xl bg-slate-950/95 border border-indigo-500/40 p-4 shadow-2xl backdrop-blur-md transition-all">
              <div className="flex items-center justify-between gap-3 mb-2 border-b border-slate-800/80 pb-2">
                <div className="flex items-center gap-2">
                  <span className="flex h-2 w-2 rounded-full bg-indigo-400 animate-pulse" />
                  <span className="text-[11px] font-bold uppercase tracking-wider text-indigo-400 font-mono">
                    Current Question
                  </span>
                  {skillName && (
                    <span className="rounded-md bg-indigo-950/80 px-2 py-0.5 text-[10px] font-bold text-indigo-300 border border-indigo-700/50">
                      {skillName}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={handleRepeatQuestion}
                    disabled={!interviewBegun || repeatingQuestion}
                    className="flex items-center gap-1.5 rounded-lg bg-indigo-600/30 hover:bg-indigo-600/50 text-indigo-200 border border-indigo-500/40 px-2.5 py-1 text-xs font-semibold transition-all disabled:opacity-40 cursor-pointer"
                    title="Ask AI to repeat the question"
                  >
                    <RotateCcw className={`h-3 w-3 ${repeatingQuestion ? 'animate-spin' : ''}`} />
                    <span>{repeatingQuestion ? 'Repeating...' : 'Repeat'}</span>
                  </button>
                  <button
                    onClick={() => setShowQuestionCard(false)}
                    className="text-slate-400 hover:text-slate-200 p-1 rounded-md text-xs cursor-pointer"
                    title="Minimize question card"
                  >
                    ✕
                  </button>
                </div>
              </div>
              <p className="text-xs sm:text-sm font-semibold text-slate-100 leading-relaxed max-h-24 overflow-y-auto">
                {currentQuestionText || aiSubtitle}
              </p>
            </div>
          )}
          {!showQuestionCard && (currentQuestionText || aiSubtitle) && (
            <button
              onClick={() => setShowQuestionCard(true)}
              className="absolute top-4 right-4 z-20 flex items-center gap-1.5 rounded-full bg-slate-900/90 border border-indigo-500/40 px-3 py-1.5 text-xs font-semibold text-indigo-300 shadow-lg backdrop-blur-md hover:bg-slate-800 transition-all cursor-pointer"
            >
              <MessageSquare className="h-3.5 w-3.5 text-indigo-400" />
              <span>Show Question</span>
            </button>
          )}

          {/* Talking Head Avatar Container */}
          <CyberBotAvatar aiState={aiState} />

          {/* AI Interviewer Live Speech & Question Subtitle Card */}
          {captionsEnabled && !showQuestionCard && (
            <div className="absolute bottom-4 left-4 right-4 z-10 rounded-2xl bg-slate-950/90 p-4 backdrop-blur-md border border-indigo-500/40 shadow-2xl transition-all">
              <div className="flex items-center justify-between text-[11px] font-semibold text-slate-400 mb-1.5">
                <span className="flex items-center gap-1.5 text-indigo-400 font-mono tracking-wide">
                  <Bot className="h-3.5 w-3.5 text-indigo-400" />
                  AI INTERVIEWER SPEECH & PROMPT
                </span>
                {skillName && (
                  <span className="text-[10px] font-bold text-violet-300 bg-violet-950/70 px-2 py-0.5 rounded-md border border-violet-700/50">
                    {skillName}
                  </span>
                )}
              </div>
              <p className="text-xs sm:text-sm font-medium text-slate-100 leading-relaxed max-h-24 overflow-y-auto">
                {aiSubtitle || currentQuestionText || 'Preparing next technical question...'}
              </p>
            </div>
          )}
        </div>

        {/* Initial Begin Interview / Reconnect / Busy Overlay */}
        {(!interviewBegun || connectionState === 'busy') && currentPhase !== 'completed' && (
          <div className="absolute inset-0 z-30 flex items-center justify-center bg-slate-950/75 p-4 backdrop-blur-sm">
            <div className="w-full max-w-md rounded-3xl border border-slate-700/80 bg-slate-900 p-6 sm:p-8 text-center shadow-2xl">
              <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-indigo-600/20 text-indigo-400 border border-indigo-500/30">
                <Sparkles className="h-7 w-7" />
              </div>
              <h3 className="mt-4 text-xl font-black text-white">
                {connectionState === 'busy' ? 'Interviewer Busy' : 'Live Room Connected'}
              </h3>
              <p className="mt-2 text-xs text-slate-400 leading-relaxed">
                {connectionState === 'busy'
                  ? connectionError
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
                {connectionState !== 'busy' && (
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
                    <span>Retry Connection</span>
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
      </main>

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
        <div className="absolute top-20 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 rounded-2xl bg-amber-500/95 text-slate-950 px-5 py-2.5 shadow-2xl backdrop-blur-md animate-bounce">
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
