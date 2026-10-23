import React from 'react';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import PreFlightCheckModal from '../PreFlightCheckModal';

describe('PreFlightCheckModal Component', () => {
  let originalWebSocket;

  beforeEach(() => {
    originalWebSocket = global.WebSocket;
    global.WebSocket = class MockWS {
      constructor() {
        this.readyState = 1;
        setTimeout(() => {
          if (this.onopen) this.onopen();
          if (this.onmessage) this.onmessage({ data: JSON.stringify({ type: 'pong' }) });
        }, 10);
      }
      send() {}
      close() {}
    };
  });

  afterEach(() => {
    global.WebSocket = originalWebSocket;
    vi.clearAllMocks();
  });

  it('renders the modal when isOpen=true with Headphones Recommendation and WebSocket Step 3', async () => {
    render(
      <PreFlightCheckModal
        isOpen={true}
        onClose={vi.fn()}
        onProceedToInterview={vi.fn()}
        jobTitle="Full Stack Engineer"
        candidateName="Test User"
      />
    );

    // Modal title & subtitle
    expect(screen.getByText('System Readiness Check')).toBeInTheDocument();
    expect(
      screen.getByText(/WebSocket audio streaming connectivity/i)
    ).toBeInTheDocument();

    // Headphones Recommendation Notice
    expect(screen.getByText(/Headphones Recommended/i)).toBeInTheDocument();
    expect(
      screen.getByText(/For optimal acoustic clarity, natural voice turn-taking/i)
    ).toBeInTheDocument();

    // Step 3: WebSocket Audio Channel & Pipeline Probe
    expect(
      screen.getByText('WebSocket Audio Channel & Pipeline Probe')
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Probing WebSocket bidirectional audio stream/i)
    ).toBeInTheDocument();
  });

  it('lists output speakers and lets the candidate choose one', async () => {
    const origEnumerate = navigator.mediaDevices.enumerateDevices;
    navigator.mediaDevices.enumerateDevices = vi.fn(async () => [
      { deviceId: 'mic-1', kind: 'audioinput', label: 'Test Microphone' },
      { deviceId: 'cam-1', kind: 'videoinput', label: 'Test Camera' },
      { deviceId: 'speaker-1', kind: 'audiooutput', label: 'Built-in Speakers' },
      { deviceId: 'speaker-2', kind: 'audiooutput', label: 'USB Headphones' },
    ]);

    render(
      <PreFlightCheckModal
        isOpen={true}
        onClose={vi.fn()}
        onProceedToInterview={vi.fn()}
        jobTitle="Full Stack Engineer"
        candidateName="Test User"
      />
    );

    const speakerSelect = await screen.findByTestId('preflight-speaker-select');
    expect(speakerSelect).toHaveValue('speaker-1');

    fireEvent.change(speakerSelect, { target: { value: 'speaker-2' } });
    expect(speakerSelect).toHaveValue('speaker-2');

    navigator.mediaDevices.enumerateDevices = origEnumerate;
  });

  it('displays "Setting up the interview environment..." when entering', () => {
    render(
      <PreFlightCheckModal
        isOpen={true}
        onClose={vi.fn()}
        onProceedToInterview={vi.fn()}
        isEntering={true}
      />
    );

    expect(
      screen.getByText(/Setting up the interview environment.../i)
    ).toBeInTheDocument();
  });
});
