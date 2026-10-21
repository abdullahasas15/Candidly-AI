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
