import React from 'react';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import LiveInterviewRoom from '../LiveInterviewRoom';
import AudioDomeVisualizer from '../AudioDomeVisualizer';

let capturedOnPcmChunk = null;
let capturedAudioOptions = null;
let mockAudioPipeline = null;
vi.mock('../audioWorklet', () => ({
  initAudioPipeline: vi.fn(async (options) => {
    capturedAudioOptions = options;
    capturedOnPcmChunk = options?.onPcmChunk;
    mockAudioPipeline = {
      captureNode: { port: { postMessage: vi.fn() }, connect: vi.fn() },
      playbackNode: { port: { postMessage: vi.fn() }, connect: vi.fn() },
      micSource: { connect: vi.fn() },
      feedPlaybackChunk: vi.fn(),
      markSpeechDone: vi.fn(),
      flushPlayback: vi.fn(),
    };
    return mockAudioPipeline;
  }),
}));

// Mock WebSocket
class MockWebSocket {
  static instances = [];
  constructor(url) {
    this.url = url;
    this.readyState = MockWebSocket.OPEN;
    this.send = vi.fn();
    this.close = vi.fn();
    MockWebSocket.instances.push(this);
    setTimeout(() => {
      if (this.onopen) this.onopen();
    }, 10);
  }
}
MockWebSocket.CONNECTING = 0;
MockWebSocket.OPEN = 1;
MockWebSocket.CLOSING = 2;
MockWebSocket.CLOSED = 3;

const socketSentClientReady = (ws) =>
  ws.send.mock.calls.some((args) => {
    try {
      return JSON.parse(args[0]).type === 'client_ready';
    } catch (e) {
      return false;
    }
  });

describe('AudioDomeVisualizer Component', () => {
  it('renders canvas element with container', () => {
    const { container } = render(
      <AudioDomeVisualizer status="listening" audioLevel={0.4} />
    );
    const visualizer = screen.getByTestId('audio-dome-visualizer');
    expect(visualizer).toBeInTheDocument();
    const canvas = container.querySelector('canvas');
    expect(canvas).toBeInTheDocument();
  });

  it('handles idle, thinking, and speaking states without errors', () => {
    const { rerender } = render(<AudioDomeVisualizer status="idle" audioLevel={0} />);
    expect(screen.getByTestId('audio-dome-visualizer')).toBeInTheDocument();

    rerender(<AudioDomeVisualizer status="thinking" audioLevel={0.1} />);
    expect(screen.getByTestId('audio-dome-visualizer')).toBeInTheDocument();

    rerender(<AudioDomeVisualizer status="speaking" audioLevel={0.8} />);
    expect(screen.getByTestId('audio-dome-visualizer')).toBeInTheDocument();
  });
});

describe('LiveInterviewRoom Component', () => {
  let originalWebSocket;
  let originalFetch;

  beforeEach(() => {
    MockWebSocket.instances = [];
    originalWebSocket = global.WebSocket;
    global.WebSocket = MockWebSocket;
    originalFetch = global.fetch;
    localStorage.setItem('candidly-auth-token', 'mock-valid-jwt-token');
    global.fetch = vi.fn(async (url) => {
      if (typeof url === 'string' && url.includes('/ws-ticket')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ ticket: 'mock-ws-ticket-abc', session_id: 'test-session-123' }),
        };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    global.WebSocket = originalWebSocket;
    global.fetch = originalFetch;
    localStorage.clear();
    sessionStorage.clear();
    vi.clearAllMocks();
  });

  it('opens exactly one WebSocket and handshakes it under React StrictMode', async () => {
    render(
      <React.StrictMode>
        <LiveInterviewRoom
          sessionId="sess-strict-mode-startup"
          jobTitle="Backend Engineer"
          candidateName="Test User"
        />
      </React.StrictMode>
    );

    // StrictMode invokes mount effects twice. A stale async startup must not
    // open a second socket after the cleanup/re-mount cycle.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 100));
    });

    expect(MockWebSocket.instances).toHaveLength(1);
    expect(socketSentClientReady(MockWebSocket.instances[0])).toBe(true);
  });

  it('sends client_ready on the replacement socket after a reconnect', async () => {
    render(
      <LiveInterviewRoom
        sessionId="sess-ready-per-socket"
        jobTitle="Backend Engineer"
        candidateName="Test User"
      />
    );

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });

    const firstSocket = MockWebSocket.instances[0];
    expect(socketSentClientReady(firstSocket)).toBe(true);

    act(() => {
      firstSocket.onmessage({
        data: JSON.stringify({ type: 'SessionConnected', question_count: 5 }),
      });
      firstSocket.readyState = MockWebSocket.CLOSED;
      firstSocket.onclose({ code: 1006, reason: 'Network blip' });
    });

    await waitFor(
      () => expect(MockWebSocket.instances.length).toBe(2),
      { timeout: 3000 }
    );

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });

    const replacementSocket = MockWebSocket.instances[1];
    expect(socketSentClientReady(replacementSocket)).toBe(true);
  });

  it('renders initial setup with header, progress, captions, camera tile, and pill controls', async () => {
    render(
      <LiveInterviewRoom
        sessionId="test-session-123"
        jobTitle="Senior Backend Engineer"
        candidateName="Alex Smith"
        durationMins={20}
      />
    );

    // Header and progress
    expect(screen.getByText('Senior Backend Engineer')).toBeInTheDocument();
    expect(screen.getByTestId('progress-indicator')).toBeInTheDocument();
    expect(screen.getByText(/Section 1 of 5/i)).toBeInTheDocument();

    // End Interview button
    expect(screen.getByTestId('end-interview-button')).toBeInTheDocument();

    // Captions and Status
    expect(screen.getByTestId('current-bot-caption')).toBeInTheDocument();
    expect(screen.getByTestId('status-line')).toBeInTheDocument();

    // Camera Tile and Meter
    expect(screen.getByTestId('camera-tile')).toBeInTheDocument();
    expect(screen.getByTestId('corner-mic-meter')).toBeInTheDocument();

    // Pill controls
    expect(screen.getByTestId('pill-mic-toggle')).toBeInTheDocument();
    expect(screen.getByTestId('pill-settings-toggle')).toBeInTheDocument();
    expect(screen.getByTestId('pill-transcript-toggle')).toBeInTheDocument();
  });

  it('renders the practice header with the planned duration', async () => {
    render(
      <LiveInterviewRoom
        sessionId="sess-practice-header"
        jobTitle="Practice Interview (General Warm-Up)"
        candidateName="Test User"
        durationMins={5}
        isPractice={true}
      />
    );

    expect(screen.getByTestId('room-job-title')).toHaveTextContent('Practice Interview • 5m');
  });

  it('renders "speaking" status correctly when bot is talking', async () => {
    render(
      <LiveInterviewRoom
        sessionId="test-session-123"
        jobTitle="Technical Interview"
      />
    );

    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const ws = MockWebSocket.instances[0];
    expect(ws).toBeDefined();

    // Simulate incoming UIStatus for speaking
    act(() => {
      if (ws.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            type: 'UIStatus',
            status: 'speaking',
            phase: 'skill_anchor',
            question_index: 0,
            payload: {
              question_text: 'How do you design a high-throughput event streaming pipeline?',
              skill: 'System Design',
            },
          }),
        });
      }
    });

    expect(screen.getByText(/SPEAKING/i)).toBeInTheDocument();
    expect(
      screen.getByText('How do you design a high-throughput event streaming pipeline?')
    ).toBeInTheDocument();
    expect(screen.getByText(/Topic: System Design/i)).toBeInTheDocument();
  });

  it('renders "listening" status when candidate turn begins', async () => {
    render(
      <LiveInterviewRoom
        sessionId="test-session-123"
      />
    );

    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const ws = MockWebSocket.instances[0];

    act(() => {
      if (ws.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            type: 'UIStatus',
            status: 'listening',
            phase: 'skill_anchor',
            question_index: 1,
            payload: {},
          }),
        });
      }
    });

    expect(screen.getByText(/LISTENING/i)).toBeInTheDocument();
  });

  it('renders "thinking" status during speculation / inference', async () => {
    render(
      <LiveInterviewRoom
        sessionId="test-session-123"
      />
    );

    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const ws = MockWebSocket.instances[0];

    act(() => {
      if (ws.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            type: 'UIStatus',
            status: 'thinking',
            phase: 'skill_anchor',
            payload: {},
          }),
        });
      }
    });

    expect(screen.getByText(/THINKING/i)).toBeInTheDocument();
  });

  it('does not display redundant ready gate button under direct opening contract', async () => {
    render(
      <LiveInterviewRoom
        sessionId="test-session-123"
      />
    );

    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const ws = MockWebSocket.instances[0];

    act(() => {
      if (ws.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            type: 'UIStatus',
            status: 'greeting',
            phase: 'greeting',
            payload: {
              display_question: 'Hi, I’m your interviewer. Thanks for making the time today. How are you?',
              question_text: 'Hi, I’m your interviewer. Thanks for making the time today. How are you?',
            },
          }),
        });
      }
    });

    expect(screen.queryByTestId('ready-gate-button')).not.toBeInTheDocument();
    expect(screen.getByTestId('current-bot-caption')).toHaveTextContent(/Hi, I’m your interviewer/i);
  });

  it('displays candidate finished answer bubble when committed', async () => {
    render(
      <LiveInterviewRoom
        sessionId="test-session-123"
      />
    );

    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const ws = MockWebSocket.instances[0];

    act(() => {
      if (ws.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            type: 'CommittedAnswer',
            text: 'I use Kafka partitioned by user ID to guarantee strict in-order processing.',
          }),
        });
      }
    });

    expect(screen.getByTestId('candidate-bubble')).toBeInTheDocument();
    expect(
      screen.getByText('I use Kafka partitioned by user ID to guarantee strict in-order processing.')
    ).toBeInTheDocument();
  });

  it('shows reconnect banner when connection closes unexpectedly', async () => {
    render(
      <LiveInterviewRoom
        sessionId="test-session-123"
      />
    );

    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const ws = MockWebSocket.instances[0];

    act(() => {
      if (ws.onclose) {
        ws.onclose({ code: 1006, reason: 'Abnormal network closure' });
      }
    });

    expect(screen.getByTestId('reconnect-banner')).toBeInTheDocument();
    expect(screen.getByText(/Reconnecting to interview session.../i)).toBeInTheDocument();
  });

  it('toggles microphone mute and displays muted banner', async () => {
    render(
      <LiveInterviewRoom
        sessionId="test-session-123"
      />
    );

    const muteBtn = screen.getByTestId('pill-mic-toggle');
    expect(screen.queryByTestId('muted-banner')).not.toBeInTheDocument();

    // Toggle Mute On
    fireEvent.click(muteBtn);
    expect(screen.getByTestId('muted-banner')).toBeInTheDocument();
    expect(screen.getByText(/Microphone is muted — unmute to speak/i)).toBeInTheDocument();

    // Toggle Mute Off
    fireEvent.click(muteBtn);
    expect(screen.queryByTestId('muted-banner')).not.toBeInTheDocument();
  });

  it('opens and closes Device Settings popover and triggers speaker test chime', async () => {
    render(
      <LiveInterviewRoom
        sessionId="test-session-123"
      />
    );

    const settingsBtn = screen.getByTestId('pill-settings-toggle');
    expect(screen.queryByTestId('device-settings-popover')).not.toBeInTheDocument();

    // Open popover
    fireEvent.click(settingsBtn);
    expect(screen.getByTestId('device-settings-popover')).toBeInTheDocument();
    expect(screen.getByText('Device Settings')).toBeInTheDocument();
    expect(screen.getByText('Microphone')).toBeInTheDocument();
    expect(screen.getByText('Speaker')).toBeInTheDocument();
    expect(screen.getByText('Camera')).toBeInTheDocument();

    // Click test speakers
    const testSpeakersBtn = screen.getByTestId('test-speakers-btn');
    fireEvent.click(testSpeakersBtn);

    // Close popover
    fireEvent.click(settingsBtn);
    expect(screen.queryByTestId('device-settings-popover')).not.toBeInTheDocument();
  });

  it('opens and closes Transcript drawer', async () => {
    render(
      <LiveInterviewRoom
        sessionId="test-session-123"
      />
    );

    const transcriptBtn = screen.getByTestId('pill-transcript-toggle');
    expect(screen.queryByTestId('transcript-drawer')).not.toBeInTheDocument();

    // Open Drawer
    fireEvent.click(transcriptBtn);
    expect(screen.getByTestId('transcript-drawer')).toBeInTheDocument();
    expect(screen.getByText('Interview Transcript')).toBeInTheDocument();

    // Close Drawer
    fireEvent.click(transcriptBtn);
    expect(screen.queryByTestId('transcript-drawer')).not.toBeInTheDocument();
  });

  it('opens End Interview confirmation dialog and sends end_button when confirmed', async () => {
    const onExitMock = vi.fn();
    render(
      <LiveInterviewRoom
        sessionId="test-session-123"
        onExit={onExitMock}
      />
    );

    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const ws = MockWebSocket.instances[0];

    // Click End interview button
    const endBtn = screen.getByTestId('end-interview-button');
    fireEvent.click(endBtn);

    // Modal appears
    expect(screen.getByTestId('end-confirm-modal')).toBeInTheDocument();
    expect(screen.getByText('End Interview?')).toBeInTheDocument();

    // Click Continue Interview to dismiss
    fireEvent.click(screen.getByText('Continue Interview'));
    expect(screen.queryByTestId('end-confirm-modal')).not.toBeInTheDocument();

    // Click End again and Confirm
    fireEvent.click(endBtn);
    const confirmBtn = screen.getByTestId('confirm-end-button');
    fireEvent.click(confirmBtn);

    const endCall = ws.send.mock.calls.find((call) => call[0].includes('"type":"end_button"'));
    expect(endCall).toBeDefined();
    const parsedEnd = JSON.parse(endCall[0]);
    expect(parsedEnd.type).toBe('end_button');
    expect(parsedEnd.request_id).toBeDefined();

    await act(async () => {
      ws.onmessage({ data: JSON.stringify({ type: 'SessionEnded', request_id: parsedEnd.request_id }) });
    });

    expect(onExitMock).toHaveBeenCalled();
  });

  it('transmits PCM chunk only after ready gate is open, blocks while speaking or muted (P0-1 regression)', async () => {
    render(
      <LiveInterviewRoom
        sessionId="test-session-pcm"
        jobTitle="Technical Interview"
      />
    );

    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];
    expect(ws).toBeDefined();
    expect(capturedOnPcmChunk).toBeTypeOf('function');

    // Startup: server sends SessionConnected then SessionReady
    act(() => {
      ws.onmessage({ data: JSON.stringify({ type: 'SessionConnected', question_count: 5 }) });
      ws.onmessage({ data: JSON.stringify({ type: 'SessionReady' }) });
    });

    // Helper to get all transmitted binary audio buffers
    const getSentBuffers = () => ws.send.mock.calls.filter((c) => c[0] instanceof ArrayBuffer).map((c) => c[0]);

    // 1. When status is speaking or handshake not complete, PCM should NOT transmit
    const testChunk1 = new Uint8Array([10, 11, 12]).buffer;
    act(() => {
      capturedOnPcmChunk(testChunk1);
    });
    expect(getSentBuffers()).toHaveLength(0);

    // 2. Status transitions to listening -> gate opens
    act(() => {
      ws.onmessage({ data: JSON.stringify({ type: 'UIStatus', status: 'listening' }) });
    });

    // Now PCM transmits through open gate
    const testChunk2 = new Uint8Array([20, 21, 22]).buffer;
    act(() => {
      capturedOnPcmChunk(testChunk2);
    });
    expect(getSentBuffers()).toHaveLength(1);
    expect(getSentBuffers()[0]).toBe(testChunk2);

    // 3. Bot starts speaking -> status becomes speaking -> gate must close
    act(() => {
      ws.onmessage({ data: JSON.stringify({ type: 'UIStatus', status: 'speaking', phase: 'skill_anchor' }) });
    });

    const testChunk3 = new Uint8Array([30, 31, 32]).buffer;
    act(() => {
      capturedOnPcmChunk(testChunk3);
    });
    expect(getSentBuffers()).toHaveLength(1); // Still 1, testChunk3 dropped

    // 4. Bot finishes speaking -> back to listening -> gate re-opens
    act(() => {
      ws.onmessage({ data: JSON.stringify({ type: 'UIStatus', status: 'listening' }) });
    });

    const testChunk4 = new Uint8Array([40, 41, 42]).buffer;
    act(() => {
      capturedOnPcmChunk(testChunk4);
    });
    expect(getSentBuffers()).toHaveLength(2);
    expect(getSentBuffers()[1]).toBe(testChunk4);

    // 5. Mute microphone -> gate must close even if listening
    const muteBtn = screen.getByTestId('pill-mic-toggle');
    act(() => {
      fireEvent.click(muteBtn);
    });

    const testChunk5 = new Uint8Array([50, 51, 52]).buffer;
    act(() => {
      capturedOnPcmChunk(testChunk5);
    });
    expect(getSentBuffers()).toHaveLength(2); // Still 2, testChunk5 dropped
  });

  it('handles SessionEnding event gracefully without immediate teardown and tears down on SessionEnded', async () => {
    const handleExit = vi.fn();
    render(
      <LiveInterviewRoom
        sessionId="sess-test-session-ending"
        jobTitle="Backend Engineer"
        candidateName="Test User"
        onExit={handleExit}
      />
    );

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBeGreaterThan(0);
    });
    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];

    // Session connects and completes ready gate
    act(() => {
      ws.onmessage({ data: JSON.stringify({ type: 'SessionConnected', question_count: 5 }) });
      ws.onmessage({ data: JSON.stringify({ type: 'SessionReady' }) });
    });

    // Receive SessionEnding (conductor entered closing speech)
    act(() => {
      ws.onmessage({ data: JSON.stringify({ type: 'SessionEnding', session_id: 'sess-test-session-ending', status: 'ending' }) });
    });

    // Room must not have exited or closed WebSocket yet so closing audio can play
    expect(handleExit).not.toHaveBeenCalled();
    expect(ws.close).not.toHaveBeenCalled();

    // Now SessionEnded arrives after audio playback finishes
    act(() => {
      ws.onmessage({ data: JSON.stringify({ type: 'SessionEnded', session_id: 'sess-test-session-ending', status: 'completed' }) });
    });

    // Terminal cleanup triggers exit callback and closes socket
    expect(handleExit).toHaveBeenCalledTimes(1);
    expect(ws.close).toHaveBeenCalled();
  });

  it('handles ws-ticket 401/403 failure: no WebSocket created, displays terminal error (Phase 3)', async () => {
    global.fetch = vi.fn(async (url) => {
      if (typeof url === 'string' && url.includes('/ws-ticket')) {
        return { ok: false, status: 403, json: async () => ({ detail: 'Forbidden' }) };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    });

    render(
      <LiveInterviewRoom
        sessionId="sess-auth-forbidden"
        jobTitle="Backend Engineer"
        candidateName="Test User"
      />
    );

    await waitFor(() => {
      expect(screen.getByTestId('live-interview-room-error')).toBeInTheDocument();
      expect(screen.getByText(/Access forbidden/i)).toBeInTheDocument();
    });

    // WebSocket MUST NEVER be opened
    expect(MockWebSocket.instances.length).toBe(0);
  });

  it('uses short-lived ws-ticket in URL and raw JWT never appears (Phase 3)', async () => {
    const rawJwt = 'my-super-secret-long-lived-jwt-token';
    localStorage.setItem('candidly-auth-token', rawJwt);

    global.fetch = vi.fn(async (url) => {
      if (typeof url === 'string' && url.includes('/ws-ticket')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ ticket: 'short-lived-signed-ws-ticket-999', session_id: 'sess-ticket-test' }),
        };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    });

    render(
      <LiveInterviewRoom
        sessionId="sess-ticket-test"
        jobTitle="Backend Engineer"
        candidateName="Test User"
      />
    );

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBeGreaterThan(0);
    });

    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];
    expect(ws.url).toContain('ticket=short-lived-signed-ws-ticket-999');
    expect(ws.url).not.toContain(rawJwt);
  });

  it('caps non-terminal 1006 reconnection attempts at MAX_RECONNECT_ATTEMPTS=5 (Phase 3)', async () => {
    render(
      <LiveInterviewRoom
        sessionId="sess-reconnect-cap"
        jobTitle="Backend Engineer"
        candidateName="Test User"
      />
    );

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBe(1);
    });

    const ws = MockWebSocket.instances[0];

    // Simulate close events until max reconnect attempts cap (5) is exceeded
    for (let i = 0; i <= 5; i++) {
      act(() => {
        if (ws.onclose) ws.onclose({ code: 1006, reason: 'Abnormal Closure' });
      });
    }

    // After cap is exceeded -> terminal error screen displayed
    await waitFor(() => {
      expect(screen.getByTestId('live-interview-room-error')).toBeInTheDocument();
      expect(screen.getByText(/Maximum reconnection attempts exceeded/i)).toBeInTheDocument();
    });

    // A manual retry must receive a fresh attempt budget.
    act(() => {
      fireEvent.click(screen.getByTestId('retry-connection-button'));
    });

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBeGreaterThan(1);
    });
    const retryWs = MockWebSocket.instances[MockWebSocket.instances.length - 1];

    act(() => {
      retryWs.onclose({ code: 1006, reason: 'Retry close' });
    });

    await waitFor(() => {
      expect(screen.queryByTestId('live-interview-room-error')).not.toBeInTheDocument();
    });
    expect(screen.getByTestId('reconnect-banner')).toBeInTheDocument();
  });

  it('treats 4403 as immediate terminal close without reconnecting (Phase 3)', async () => {
    render(
      <LiveInterviewRoom
        sessionId="sess-4403-terminal"
        jobTitle="Backend Engineer"
        candidateName="Test User"
      />
    );

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBe(1);
    });
    const ws = MockWebSocket.instances[0];

    act(() => {
      if (ws.onclose) ws.onclose({ code: 4403, reason: 'Forbidden' });
    });

    await waitFor(() => {
      expect(screen.getByTestId('live-interview-room-error')).toBeInTheDocument();
      expect(screen.getByText(/Access forbidden/i)).toBeInTheDocument();
    });
  });

  it('guards AudioContext readiness: suspended context prevents client_ready and listening status (Phase 4)', async () => {
    const origAudioContext = window.AudioContext;
    class SuspendedAudioContext extends origAudioContext {
      constructor() {
        super();
        this.state = 'suspended';
      }
      resume() {
        return Promise.reject(new Error('Audio gesture required'));
      }
    }
    window.AudioContext = SuspendedAudioContext;

    render(
      <LiveInterviewRoom
        sessionId="sess-audiocontext-guard"
        jobTitle="Backend Engineer"
        candidateName="Test User"
      />
    );

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBeGreaterThan(0);
    });
    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];

    act(() => {
      ws.onmessage({ data: JSON.stringify({ type: 'SessionConnected', question_count: 5 }) });
      ws.onmessage({ data: JSON.stringify({ type: 'SessionReady' }) });
    });

    await waitFor(() => {
      expect(screen.getByTestId('audio-activation-overlay')).toBeInTheDocument();
    });

    const clientReadySent = ws.send.mock.calls.some((args) => {
      try {
        const payload = JSON.parse(args[0]);
        return payload.type === 'client_ready';
      } catch (e) {
        return false;
      }
    });
    expect(clientReadySent).toBe(false);

    window.AudioContext = origAudioContext;
  });

  it('shows an activation prompt for a suspended AudioContext and handshakes after the user enables audio', async () => {
    const origAudioContext = window.AudioContext;
    class RecoverableSuspendedAudioContext extends origAudioContext {
      constructor() {
        super();
        this.state = 'suspended';
        this.resumeAttempts = 0;
      }
      resume() {
        this.resumeAttempts += 1;
        if (this.resumeAttempts === 1) {
          return Promise.reject(new Error('Autoplay gesture required'));
        }
        this.state = 'running';
        return Promise.resolve();
      }
    }
    window.AudioContext = RecoverableSuspendedAudioContext;

    try {
      render(
        <LiveInterviewRoom
          sessionId="sess-audio-activation"
          jobTitle="Backend Engineer"
          candidateName="Test User"
        />
      );

      await waitFor(() => {
        expect(MockWebSocket.instances.length).toBeGreaterThan(0);
      });
      const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];

      await waitFor(() => {
        expect(screen.getByTestId('audio-activation-overlay')).toBeInTheDocument();
      });
      expect(socketSentClientReady(ws)).toBe(false);

      await act(async () => {
        fireEvent.click(screen.getByTestId('enable-audio-button'));
      });

      await waitFor(() => {
        expect(socketSentClientReady(ws)).toBe(true);
      });
      expect(screen.queryByTestId('audio-activation-overlay')).not.toBeInTheDocument();
    } finally {
      window.AudioContext = origAudioContext;
    }
  });

  it('UIStatus completed shows thank-you screen; SessionEnded defers exit to click or grace', async () => {
    const onExitMock = vi.fn();
    render(
      <LiveInterviewRoom
        sessionId="sess-completed-decoupled"
        jobTitle="Backend Engineer"
        candidateName="Test User"
        onExit={onExitMock}
      />
    );

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBeGreaterThan(0);
    });
    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];

    act(() => {
      ws.onmessage({ data: JSON.stringify({ type: 'SessionConnected', question_count: 5 }) });
      ws.onmessage({ data: JSON.stringify({ type: 'SessionReady' }) });
      ws.onmessage({ data: JSON.stringify({ type: 'UIStatus', status: 'completed' }) });
    });

    // onExit MUST NOT have been called yet because SessionEnded has not arrived,
    // and the completion / thank-you screen is visible.
    expect(onExitMock).not.toHaveBeenCalled();
    expect(screen.getByTestId('completion-overlay')).toBeInTheDocument();

    // Now emit SessionEnded: exit is deferred briefly so the candidate can read
    // the thank-you screen instead of being torn down instantly.
    act(() => {
      ws.onmessage({ data: JSON.stringify({ type: 'SessionEnded' }) });
    });

    expect(onExitMock).not.toHaveBeenCalled();
    expect(screen.getByTestId('completion-overlay')).toBeInTheDocument();

    // The candidate clicks "Return to Dashboard" to leave immediately.
    fireEvent.click(screen.getByTestId('completion-exit-button'));
    expect(onExitMock).toHaveBeenCalledTimes(1);
  });

  it('arms 5s fallback to REST /end if SessionEnded does not arrive after UIStatus completed', async () => {
    const onExitMock = vi.fn();
    render(
      <LiveInterviewRoom
        sessionId="sess-fallback-timeout"
        jobTitle="Backend Engineer"
        candidateName="Test User"
        onExit={onExitMock}
      />
    );

    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];
    expect(ws).toBeDefined();

    vi.useFakeTimers();

    act(() => {
      ws.onmessage({ data: JSON.stringify({ type: 'SessionConnected', question_count: 5 }) });
      ws.onmessage({ data: JSON.stringify({ type: 'SessionReady' }) });
      ws.onmessage({ data: JSON.stringify({ type: 'UIStatus', status: 'completed' }) });
    });

    expect(onExitMock).not.toHaveBeenCalled();

    // Advance fake timers by 5100ms to trigger REST fallback
    await act(async () => {
      vi.advanceTimersByTime(5100);
    });

    const restCall = global.fetch.mock.calls.some(
      (call) => typeof call[0] === 'string' && call[0].includes('/end')
    );
    expect(restCall).toBe(true);

    vi.useRealTimers();
  });

  it('auto-navigates with a dashboard notice when REST /end persistence fails', async () => {
    const onExitMock = vi.fn();
    sessionStorage.clear();

    render(
      <LiveInterviewRoom
        sessionId="sess-fallback-failure"
        jobTitle="Backend Engineer"
        candidateName="Test User"
        onExit={onExitMock}
      />
    );

    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];
    expect(ws).toBeDefined();

    global.fetch = vi.fn((url) => {
      if (typeof url === 'string' && url.includes('/end')) {
        return Promise.resolve({
          ok: false,
          status: 500,
          json: async () => ({ detail: 'database unavailable' }),
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({}) });
    });

    vi.useFakeTimers();

    act(() => {
      ws.onmessage({ data: JSON.stringify({ type: 'SessionConnected', question_count: 5 }) });
      ws.onmessage({ data: JSON.stringify({ type: 'SessionReady' }) });
      ws.onmessage({ data: JSON.stringify({ type: 'UIStatus', status: 'completed' }) });
    });

    await act(async () => {
      vi.advanceTimersByTime(5100);
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText(/unable to persist session completion/i)).toBeInTheDocument();
    expect(sessionStorage.getItem('candidly-interview-exit-notice')).toMatch(
      /completion could not be confirmed/i
    );
    expect(onExitMock).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(2500);
    });

    expect(onExitMock).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it('does not call onExit twice when SessionEnded races the REST fallback', async () => {
    const onExitMock = vi.fn();
    render(
      <LiveInterviewRoom
        sessionId="sess-fallback-idempotent"
        jobTitle="Backend Engineer"
        candidateName="Test User"
        onExit={onExitMock}
      />
    );

    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];
    expect(ws).toBeDefined();

    let resolveEnd;
    const pendingEnd = new Promise((resolve) => {
      resolveEnd = resolve;
    });
    global.fetch = vi.fn((url) => {
      if (typeof url === 'string' && url.includes('/end')) {
        return pendingEnd;
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({}) });
    });

    vi.useFakeTimers();

    act(() => {
      ws.onmessage({ data: JSON.stringify({ type: 'SessionConnected', question_count: 5 }) });
      ws.onmessage({ data: JSON.stringify({ type: 'SessionReady' }) });
      ws.onmessage({ data: JSON.stringify({ type: 'UIStatus', status: 'completed' }) });
    });

    await act(async () => {
      vi.advanceTimersByTime(5100);
    });
    expect(
      global.fetch.mock.calls.some((call) => typeof call[0] === 'string' && call[0].includes('/end'))
    ).toBe(true);

    // SessionEnded arrives while the REST request is still in flight. Exit is
    // deferred for the completion screen grace period; fire it here.
    act(() => {
      ws.onmessage({ data: JSON.stringify({ type: 'SessionEnded' }) });
    });
    await act(async () => {
      vi.advanceTimersByTime(8200);
    });
    expect(onExitMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveEnd({ ok: true, status: 200, json: async () => ({}) });
      await Promise.resolve();
    });

    // The late REST success must not invoke onExit a second time.
    expect(onExitMock).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it('clamps question_index >= 1000 to totalSections', async () => {
    render(
      <LiveInterviewRoom
        sessionId="sess-section-clamp"
        jobTitle="Backend Engineer"
        candidateName="Test User"
      />
    );

    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];

    act(() => {
      ws.onmessage({ data: JSON.stringify({ type: 'SessionConnected', question_count: 6 }) });
      ws.onmessage({ data: JSON.stringify({ type: 'UIStatus', status: 'listening', question_index: 1001 }) });
    });

    await waitFor(() => {
      expect(screen.getByTestId('progress-indicator')).toHaveTextContent('Section 6 of 6');
    });
  });

  it('ticket fetch 404 triggers terminal error screen', async () => {
    global.fetch = vi.fn(async (url) => {
      if (typeof url === 'string' && url.includes('/ws-ticket')) {
        return {
          ok: false,
          status: 404,
          json: async () => ({ detail: 'Interview session not found.' }),
        };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    });

    render(
      <LiveInterviewRoom
        sessionId="sess-not-found"
        jobTitle="Backend Engineer"
        candidateName="Test User"
      />
    );

    await waitFor(() => {
      expect(screen.getByTestId('live-interview-room-error')).toBeInTheDocument();
      expect(screen.getByTestId('error-message')).toHaveTextContent('Interview session not found');
    });
  });

  it('switchMicrophone invokes initAudioPipeline with new deviceId', async () => {
    const { initAudioPipeline } = await import('../audioWorklet');
    const origEnumerate = navigator.mediaDevices.enumerateDevices;
    navigator.mediaDevices.enumerateDevices = vi.fn(async () => [
      { kind: 'audioinput', deviceId: 'mic-1', label: 'Internal Mic' },
      { kind: 'audioinput', deviceId: 'mic-2', label: 'USB Mic' },
    ]);

    render(
      <LiveInterviewRoom
        sessionId="sess-mic-switch"
        jobTitle="Backend Engineer"
        candidateName="Test User"
      />
    );

    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    // Open settings popover
    act(() => {
      fireEvent.click(screen.getByTestId('pill-settings-toggle'));
    });

    const popover = screen.getByTestId('device-settings-popover');
    expect(popover).toBeInTheDocument();

    const selects = popover.querySelectorAll('select');
    const micSelect = selects[0];

    await act(async () => {
      fireEvent.change(micSelect, { target: { value: 'mic-2' } });
    });

    expect(initAudioPipeline).toHaveBeenCalled();
    navigator.mediaDevices.enumerateDevices = origEnumerate;
  });

  it('shows a terminal error instead of opening the socket when audio worklets fail', async () => {
    const { initAudioPipeline } = await import('../audioWorklet');
    initAudioPipeline.mockRejectedValueOnce(new Error('AudioWorklet unavailable'));

    render(
      <LiveInterviewRoom
        sessionId="sess-worklet-failure"
        jobTitle="Backend Engineer"
        candidateName="Test User"
      />
    );

    await waitFor(() => {
      expect(screen.getByTestId('live-interview-room-error')).toBeInTheDocument();
      expect(screen.getByTestId('error-message')).toHaveTextContent(/Audio processing could not start/i);
    });
    expect(MockWebSocket.instances.length).toBe(0);
  });

  it('applies the preflight speaker selection to the playback AudioContext', async () => {
    const origAudioContext = window.AudioContext;
    let createdContext = null;
    class SinkAudioContext extends origAudioContext {
      constructor() {
        super();
        this.setSinkId = vi.fn(async () => {});
        createdContext = this;
      }
    }
    window.AudioContext = SinkAudioContext;

    render(
      <LiveInterviewRoom
        sessionId="sess-speaker-routing"
        jobTitle="Backend Engineer"
        candidateName="Test User"
        initialAudioOutputId="speaker-usb-2"
      />
    );

    await waitFor(() => {
      expect(createdContext).not.toBeNull();
    });
    await waitFor(() => {
      expect(createdContext.setSinkId).toHaveBeenCalledWith('speaker-usb-2');
    });

    window.AudioContext = origAudioContext;
  });

  describe('TTS and Playback Handshake Scenarios', () => {
    it('sends playback_ended when TTSDone arrives before audio buffer drain', async () => {
      render(
        <LiveInterviewRoom
          sessionId="sess-tts-before-drain"
          jobTitle="Backend Engineer"
          candidateName="Test User"
        />
      );
      await act(async () => {
        await new Promise((r) => setTimeout(r, 20));
      });
      const ws = MockWebSocket.instances[0];

      // 1. Server starts TTS
      act(() => {
        ws.onmessage({
          data: JSON.stringify({ type: 'TTSStarted', speech_id: 'speech_101', text: 'First question' }),
        });
      });

      // 2. Server finishes sending TTS chunks
      act(() => {
        ws.onmessage({
          data: JSON.stringify({ type: 'TTSDone', speech_id: 'speech_101' }),
        });
      });

      expect(mockAudioPipeline.markSpeechDone).toHaveBeenCalledWith('speech_101');
      // playback_ended MUST NOT be sent yet because audio has not drained
      const endedCallsBefore = ws.send.mock.calls.filter(([arg]) => {
        try { return JSON.parse(arg).type === 'playback_ended'; } catch (e) { return false; }
      });
      expect(endedCallsBefore.length).toBe(0);

      // 3. AudioWorklet finishes playback drain
      act(() => {
        capturedAudioOptions.onPlaybackDrained('speech_101');
      });

      // Now playback_ended MUST be sent
      const endedCallsAfter = ws.send.mock.calls.filter(([arg]) => {
        try {
          const parsed = JSON.parse(arg);
          return parsed.type === 'playback_ended' && parsed.speech_id === 'speech_101';
        } catch (e) { return false; }
      });
      expect(endedCallsAfter.length).toBe(1);
    });

    it('sends playback_ended when audio buffer drains before TTSDone arrives', async () => {
      render(
        <LiveInterviewRoom
          sessionId="sess-drain-before-tts"
          jobTitle="Backend Engineer"
          candidateName="Test User"
        />
      );
      await act(async () => {
        await new Promise((r) => setTimeout(r, 20));
      });
      const ws = MockWebSocket.instances[0];

      // 1. Server starts TTS
      act(() => {
        ws.onmessage({
          data: JSON.stringify({ type: 'TTSStarted', speech_id: 'speech_102', text: 'Second question' }),
        });
      });

      // 2. Worklet drains buffer early
      act(() => {
        capturedAudioOptions.onPlaybackDrained('speech_102');
      });

      // playback_ended MUST NOT be sent yet because TTSDone hasn't arrived
      const endedCallsBefore = ws.send.mock.calls.filter(([arg]) => {
        try { return JSON.parse(arg).type === 'playback_ended'; } catch (e) { return false; }
      });
      expect(endedCallsBefore.length).toBe(0);

      // 3. TTSDone arrives
      act(() => {
        ws.onmessage({
          data: JSON.stringify({ type: 'TTSDone', speech_id: 'speech_102' }),
        });
      });

      // Now playback_ended MUST be sent
      const endedCallsAfter = ws.send.mock.calls.filter(([arg]) => {
        try {
          const parsed = JSON.parse(arg);
          return parsed.type === 'playback_ended' && parsed.speech_id === 'speech_102';
        } catch (e) { return false; }
      });
      expect(endedCallsAfter.length).toBe(1);
    });

    it('does not send playback_ended on transient drain until TTSDone arrives', async () => {
      render(
        <LiveInterviewRoom
          sessionId="sess-transient-drain"
          jobTitle="Backend Engineer"
          candidateName="Test User"
        />
      );
      await act(async () => {
        await new Promise((r) => setTimeout(r, 20));
      });
      const ws = MockWebSocket.instances[0];

      act(() => {
        ws.onmessage({
          data: JSON.stringify({ type: 'TTSStarted', speech_id: 'speech_103', text: 'Third question' }),
        });
      });

      // Mid-sentence transient drain
      act(() => {
        capturedAudioOptions.onPlaybackStarted('speech_103');
      });

      const endedCalls = ws.send.mock.calls.filter(([arg]) => {
        try { return JSON.parse(arg).type === 'playback_ended'; } catch (e) { return false; }
      });
      expect(endedCalls.length).toBe(0);
    });

    it('correctly handles ack speech without overwriting active caption and completes handshake', async () => {
      render(
        <LiveInterviewRoom
          sessionId="sess-ack-speech"
          jobTitle="Backend Engineer"
          candidateName="Test User"
        />
      );
      await act(async () => {
        await new Promise((r) => setTimeout(r, 20));
      });
      const ws = MockWebSocket.instances[0];

      // Set existing question text first
      act(() => {
        ws.onmessage({
          data: JSON.stringify({ type: 'UIStatus', payload: { question_text: 'Explain indexing' } }),
        });
      });

      // Now incoming fast ack speech
      act(() => {
        ws.onmessage({
          data: JSON.stringify({ type: 'TTSStarted', speech_id: 'ack_104', is_ack: true, text: 'Understood.' }),
        });
      });

      // Caption should remain the main question, not overwritten by ack
      expect(screen.getByTestId('current-bot-caption')).toHaveTextContent('Explain indexing');

      // Complete ack playback
      act(() => {
        ws.onmessage({
          data: JSON.stringify({ type: 'TTSDone', speech_id: 'ack_104' }),
        });
        capturedAudioOptions.onPlaybackDrained('ack_104');
      });

      const endedCalls = ws.send.mock.calls.filter(([arg]) => {
        try {
          const parsed = JSON.parse(arg);
          return parsed.type === 'playback_ended' && parsed.speech_id === 'ack_104';
        } catch (e) { return false; }
      });
      expect(endedCalls.length).toBe(1);
    });

    it('normal speech updates caption and returns status to listening on complete drain', async () => {
      render(
        <LiveInterviewRoom
          sessionId="sess-normal-speech"
          jobTitle="Backend Engineer"
          candidateName="Test User"
        />
      );
      await act(async () => {
        await new Promise((r) => setTimeout(r, 20));
      });
      const ws = MockWebSocket.instances[0];

      act(() => {
        ws.onmessage({
          data: JSON.stringify({ type: 'TTSStarted', speech_id: 'normal_105', text: 'What is idempotency?' }),
        });
      });

      expect(screen.getByTestId('current-bot-caption')).toHaveTextContent('What is idempotency?');

      act(() => {
        ws.onmessage({
          data: JSON.stringify({ type: 'TTSDone', speech_id: 'normal_105' }),
        });
        capturedAudioOptions.onPlaybackDrained('normal_105');
      });

      const endedCalls = ws.send.mock.calls.filter(([arg]) => {
        try {
          const parsed = JSON.parse(arg);
          return parsed.type === 'playback_ended' && parsed.speech_id === 'normal_105';
        } catch (e) { return false; }
      });
      expect(endedCalls.length).toBe(1);
    });
  });
});
