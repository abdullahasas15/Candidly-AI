import React, { useState } from 'react';

const LiveInterviewRoom = React.lazy(() => import('./LiveInterviewRoom'));

const PREVIEW_STATES = {
  speaking: {
    status: 'speaking',
    connectionState: 'connected',
    currentBotCaption: 'Could you describe a distributed systems challenge where you had to balance consistency and partition tolerance?',
    previousBotCaption: 'Welcome to your technical session. Let us begin with your systems experience.',
    skillName: 'System Architecture',
    currentSection: 2,
    totalSections: 5,
    botLevel: 0.72,
    audioLevel: 0.72,
    skipConnect: true,
  },
  listening: {
    status: 'listening',
    connectionState: 'connected',
    currentBotCaption: 'How did you ensure exactly-once semantics in your payment processing worker?',
    previousBotCaption: 'Could you describe a distributed systems challenge where you had to balance consistency and partition tolerance?',
    candidateLiveTranscript: 'We implemented an idempotency key stored in Redis with an atomic Lua script before writing to Postgres...',
    skillName: 'System Architecture',
    currentSection: 2,
    totalSections: 5,
    micLevel: 0.65,
    audioLevel: 0.65,
    skipConnect: true,
  },
  thinking: {
    status: 'thinking',
    connectionState: 'connected',
    currentBotCaption: 'How did you ensure exactly-once semantics in your payment processing worker?',
    previousBotCaption: 'Could you describe a distributed systems challenge where you had to balance consistency and partition tolerance?',
    lastCandidateAnswer: 'We implemented an idempotency key stored in Redis with an atomic Lua script before writing to Postgres.',
    skillName: 'System Architecture',
    currentSection: 2,
    totalSections: 5,
    micLevel: 0,
    botLevel: 0,
    audioLevel: 0.15,
    skipConnect: true,
  },
  reconnecting: {
    status: 'listening',
    connectionState: 'reconnecting',
    currentBotCaption: 'How did you ensure exactly-once semantics in your payment processing worker?',
    previousBotCaption: 'Could you describe a distributed systems challenge where you had to balance consistency and partition tolerance?',
    skillName: 'System Architecture',
    currentSection: 2,
    totalSections: 5,
    skipConnect: true,
  },
  end_confirm: {
    status: 'listening',
    connectionState: 'connected',
    currentBotCaption: 'How did you ensure exactly-once semantics in your payment processing worker?',
    previousBotCaption: 'Could you describe a distributed systems challenge where you had to balance consistency and partition tolerance?',
    confirmExitOpen: true,
    skillName: 'System Architecture',
    currentSection: 2,
    totalSections: 5,
    skipConnect: true,
  },
};

export default function InterviewPreviewGallery() {
  const urlParams = new URLSearchParams(window.location.search);
  const initialKey = urlParams.get('state') || 'speaking';
  const [activeKey, setActiveKey] = useState(initialKey in PREVIEW_STATES ? initialKey : 'speaking');

  const activeState = PREVIEW_STATES[activeKey] || PREVIEW_STATES.speaking;

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-black">
      {/* State Switcher Top-Pill Bar for Testing and Screenshots */}
      <div className="fixed top-3 left-1/2 -translate-x-1/2 z-[60] flex items-center gap-1.5 rounded-full border border-zinc-800 bg-zinc-950/90 px-3 py-1.5 shadow-2xl backdrop-blur-md">
        <span className="text-[10px] font-bold uppercase tracking-wider text-zinc-500 mr-1.5">
          Preview State:
        </span>
        {Object.keys(PREVIEW_STATES).map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => {
              setActiveKey(key);
              const url = new URL(window.location);
              url.searchParams.set('state', key);
              window.history.replaceState({}, '', url);
            }}
            data-testid={`preview-tab-${key}`}
            className={`rounded-full px-2.5 py-1 text-[11px] font-semibold transition-all ${
              activeKey === key
                ? 'bg-teal-500 text-black shadow-md'
                : 'text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200'
            }`}
          >
            {key}
          </button>
        ))}
      </div>

      <React.Suspense fallback={<div className="p-12 text-center text-teal-400 font-semibold">Loading Live Room Preview...</div>}>
        <LiveInterviewRoom
          key={activeKey}
          sessionId="preview-session-id"
          jobTitle="Staff Distributed Systems Engineer"
          candidateName="Alex Morgan"
          durationMins={20}
          mockState={activeState}
        />
      </React.Suspense>
    </div>
  );
}
