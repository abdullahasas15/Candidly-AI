import React from 'react';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import LiveInterviewRoom from '../LiveInterviewRoom';
import AudioDomeVisualizer from '../AudioDomeVisualizer';

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

  beforeEach(() => {
    MockWebSocket.instances = [];
    originalWebSocket = global.WebSocket;
    global.WebSocket = MockWebSocket;
  });

  afterEach(() => {
    global.WebSocket = originalWebSocket;
    vi.clearAllMocks();
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

  it('renders ready gate with optional "I\'m ready" button', async () => {
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
            status: 'waiting_for_ready',
            phase: 'ready_gate',
            payload: {
              question_text: 'Are you ready to begin your interview?',
            },
          }),
        });
      }
    });

    expect(screen.getByTestId('ready-gate-button')).toBeInTheDocument();
    expect(screen.getByText("I'm ready")).toBeInTheDocument();

    // Click optional ready button
    fireEvent.click(screen.getByTestId('ready-gate-button'));
    expect(ws.send).toHaveBeenCalledWith(JSON.stringify({ type: 'ready_button' }));
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
});
