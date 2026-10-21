import React from 'react';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import CandidateDashboard from '../CandidateDashboard';

// Mock LiveInterviewRoom to capture rendered props
const mockLiveRoomProps = [];
vi.mock('../interview/LiveInterviewRoom', () => {
  return {
    default: (props) => {
      mockLiveRoomProps.push(props);
      return (
        <div data-testid="mock-live-interview-room">
          <span data-testid="room-session-id">{props.sessionId}</span>
          <span data-testid="room-job-title">{props.jobTitle}</span>
          <span data-testid="room-candidate-name">{props.candidateName}</span>
          <span data-testid="room-practice-flag">{props.isPractice ? 'practice' : 'normal'}</span>
          <button data-testid="room-exit-btn" onClick={props.onExit}>
            Exit
          </button>
        </div>
      );
    },
  };
});

// Mock PreFlightCheckModal to allow direct starting
vi.mock('../interview/PreFlightCheckModal', () => {
  return {
    default: ({ isOpen, onProceedToInterview, onClose }) => {
      if (!isOpen) return null;
      return (
        <div data-testid="mock-preflight-modal">
          <button data-testid="preflight-proceed-btn" onClick={onProceedToInterview}>
            Proceed to Interview
          </button>
          <button data-testid="preflight-close-btn" onClick={onClose}>
            Cancel
          </button>
        </div>
      );
    },
  };
});

describe('CandidateDashboard Integration & Room Contract', () => {
  const mockUser = {
    id: 'cand-user-123',
    full_name: 'Alex Developer',
    email: 'alex@example.com',
    role: 'candidate',
    access_token: 'valid-test-token-candidate',
  };

  const mockApplication = {
    id: 'app-999',
    job_id: 'job-888',
    status: 'interview_ready',
    interview_ready: true,
    job: {
      id: 'job-888',
      job_title: 'Full Stack Engineer',
      company_name: 'Candidly Inc',
      interview_duration_mins: 25,
      department: 'Engineering',
    },
  };

  beforeEach(() => {
    mockLiveRoomProps.length = 0;
    vi.stubGlobal('alert', vi.fn());
    localStorage.setItem('candidly-auth-token-candidate', 'valid-test-token-candidate');
  });

  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('passes canonical session contract to LiveInterviewRoom on successful interview launch', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(async (url, opts) => {
      if (url.includes('/api/candidate/applications')) {
        return {
          ok: true,
          status: 200,
          json: async () => [mockApplication],
        };
      }
      if (url.includes('/api/applications/app-999/interview-session')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            id: 'real-session-uuid-777',
            status: 'scheduled',
            duration_planned_mins: 25,
          }),
        };
      }
      if (url.includes('/api/interview-sessions/real-session-uuid-777/start')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            id: 'real-session-uuid-777',
            status: 'in_progress',
          }),
        };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    });

    render(<CandidateDashboard authUser={mockUser} />);

    // Wait for applications to load and find Start Interview button
    await waitFor(() => {
      expect(screen.getByText('Start Interview')).toBeInTheDocument();
    });

    // Click Start Interview -> opens PreFlightCheckModal
    const startBtn = screen.getByText('Start Interview');
    await act(async () => {
      fireEvent.click(startBtn);
    });

    // In Preflight modal, click Proceed
    const proceedBtn = await screen.findByTestId('preflight-proceed-btn');
    await act(async () => {
      fireEvent.click(proceedBtn);
    });

    // Verify LiveInterviewRoom is mounted with canonical props
    await waitFor(() => {
      expect(screen.getByTestId('mock-live-interview-room')).toBeInTheDocument();
    });

    expect(screen.getByTestId('room-session-id').textContent).toBe('real-session-uuid-777');
    expect(screen.getByTestId('room-job-title').textContent).toBe('Full Stack Engineer');
    expect(screen.getByTestId('room-candidate-name').textContent).toBe('Alex Developer');
    expect(screen.getByTestId('room-practice-flag').textContent).toBe('normal');

    // Verify prop details received by the room
    const receivedProps = mockLiveRoomProps[mockLiveRoomProps.length - 1];
    expect(receivedProps.sessionId).toBe('real-session-uuid-777');
    expect(typeof receivedProps.onExit).toBe('function');
    expect(typeof receivedProps.onEndInterview).toBe('function');
    expect(receivedProps.token).toBe('valid-test-token-candidate');
  });

  it('successfully starts and configures practice interview session', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(async (url, opts) => {
      if (url.includes('/api/candidate/applications')) {
        return { ok: true, status: 200, json: async () => [mockApplication] };
      }
      if (url.includes('/api/candidate/practice-interview')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            id: 'practice-session-uuid-111',
            job_title: 'Practice Warm-Up',
            duration_mins: 5,
          }),
        };
      }
      if (url.includes('/api/interview-sessions/practice-session-uuid-111/start')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            id: 'practice-session-uuid-111',
            status: 'in_progress',
          }),
        };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    });

    render(<CandidateDashboard authUser={mockUser} />);

    // Click Warm-Up (5m) button
    await waitFor(() => {
      expect(screen.getByText('Warm-Up (5m)')).toBeInTheDocument();
    });

    const practiceBtn = screen.getByText('Warm-Up (5m)');
    await act(async () => {
      fireEvent.click(practiceBtn);
    });

    // Verify LiveInterviewRoom mounted with practice props
    await waitFor(() => {
      expect(screen.getByTestId('mock-live-interview-room')).toBeInTheDocument();
    });

    expect(screen.getByTestId('room-session-id').textContent).toBe('practice-session-uuid-111');
    expect(screen.getByTestId('room-practice-flag').textContent).toBe('practice');
  });

  it('does not enter live room when session ID is missing from API response', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(async (url, opts) => {
      if (url.includes('/api/candidate/applications')) {
        return { ok: true, status: 200, json: async () => [mockApplication] };
      }
      if (url.includes('/api/applications/app-999/interview-session')) {
        // Response without session id
        return {
          ok: true,
          status: 200,
          json: async () => ({ status: 'scheduled' }),
        };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    });

    render(<CandidateDashboard authUser={mockUser} />);

    await waitFor(() => {
      expect(screen.getByText('Start Interview')).toBeInTheDocument();
    });

    const startBtn = screen.getByText('Start Interview');
    await act(async () => {
      fireEvent.click(startBtn);
    });

    const proceedBtn = await screen.findByTestId('preflight-proceed-btn');
    await act(async () => {
      fireEvent.click(proceedBtn);
    });

    // Live interview room must NOT be rendered
    expect(screen.queryByTestId('mock-live-interview-room')).not.toBeInTheDocument();
  });

  it('guards against duplicate clicks while start request is pending', async () => {
    let practiceFetchCount = 0;
    let resolvePracticeCall;
    const practicePromise = new Promise((resolve) => {
      resolvePracticeCall = resolve;
    });

    vi.spyOn(global, 'fetch').mockImplementation(async (url, opts) => {
      if (url.includes('/api/candidate/applications')) {
        return { ok: true, status: 200, json: async () => [mockApplication] };
      }
      if (url.includes('/api/candidate/practice-interview')) {
        practiceFetchCount += 1;
        await practicePromise;
        return {
          ok: true,
          status: 200,
          json: async () => ({ id: 'practice-uuid-333' }),
        };
      }
      if (url.includes('/start')) {
        return { ok: true, status: 200, json: async () => ({ id: 'practice-uuid-333' }) };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    });

    render(<CandidateDashboard authUser={mockUser} />);

    await waitFor(() => {
      expect(screen.getByText('Warm-Up (5m)')).toBeInTheDocument();
    });

    const practiceBtn = screen.getByText('Warm-Up (5m)');

    // First click triggers pending start
    await act(async () => {
      fireEvent.click(practiceBtn);
    });
    expect(practiceFetchCount).toBe(1);

    // Second immediate click while pending
    await act(async () => {
      fireEvent.click(practiceBtn);
    });
    // Count remains 1 (duplicate click ignored)
    expect(practiceFetchCount).toBe(1);

    // Resolve the promise and complete
    await act(async () => {
      resolvePracticeCall();
    });
  });
});
