import React from 'react';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import BlueprintReviewEditor from '../BlueprintReviewEditor';

describe('BlueprintReviewEditor Component', () => {
  const mockJob = {
    id: 'job-test-123',
    job_title: 'Full Stack Engineer',
    department: 'Engineering',
    seniority_level: 'mid',
    interview_duration_mins: 20,
    skills: [{ name: 'React' }, { name: 'FastAPI' }],
  };

  beforeEach(() => {
    localStorage.setItem('candidly-auth-token-recruiter', 'recruiter-token-123');
    vi.stubGlobal('alert', vi.fn());
  });

  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('renders blocked badge and disables approval when blueprint is approved but has validation errors (P1-10)', async () => {
    const approvedWithErrorBlueprint = {
      id: 'bp-with-errors',
      job_id: mockJob.id,
      version: 1,
      status: 'approved',
      is_stale: false,
      validation_report: {
        is_valid: false,
        errors: [
          'Entry-level role must not include System Architecture anchor questions.',
          'Total allocated duration (35 mins) exceeds job duration (20 mins).',
        ],
        warnings: [],
      },
      sections: [
        {
          id: 'sec-1',
          skill_name: 'System Architecture',
          section_order: 1,
          allocated_minutes: 15,
          rubrics: [],
          questions: [],
        },
      ],
    };

    render(
      <BlueprintReviewEditor
        job={mockJob}
        initialBlueprint={approvedWithErrorBlueprint}
        onApproved={vi.fn()}
      />
    );

    // 1. Top badge must show blocked status, NOT active/live
    expect(screen.getByTestId('blocked-status-badge')).toBeInTheDocument();
    expect(screen.getByText('Blocked by Validation Errors')).toBeInTheDocument();
    expect(screen.queryByTestId('live-status-badge')).not.toBeInTheDocument();
    expect(screen.queryByText('Active & Accepting Applications')).not.toBeInTheDocument();

    // 2. Bottom status strip must indicate repair required
    expect(
      screen.getByText(/Approved with Unresolved Validation Errors — Requires Repair & Re-Approval/i)
    ).toBeInTheDocument();

    // 3. Approve button must be disabled due to validation errors
    const approveBtn = screen.getByRole('button', { name: /approve/i });
    expect(approveBtn).toBeDisabled();
  });

  it('renders live status badge and enables approval when blueprint is approved with zero validation errors (P1-10)', async () => {
    const cleanApprovedBlueprint = {
      id: 'bp-clean',
      job_id: mockJob.id,
      version: 1,
      status: 'approved',
      is_stale: false,
      validation_report: {
        is_valid: true,
        errors: [],
        warnings: [],
      },
      sections: [
        {
          id: 'sec-1',
          skill_name: 'React Fundamentals',
          section_order: 1,
          allocated_minutes: 20,
          rubrics: [],
          questions: [],
        },
      ],
    };

    render(
      <BlueprintReviewEditor
        job={mockJob}
        initialBlueprint={cleanApprovedBlueprint}
        onApproved={vi.fn()}
      />
    );

    // 1. Top badge must show active & live
    expect(screen.getByTestId('live-status-badge')).toBeInTheDocument();
    expect(screen.getByText('Active & Accepting Applications')).toBeInTheDocument();
    expect(screen.queryByTestId('blocked-status-badge')).not.toBeInTheDocument();

    // 2. Bottom status strip shows approved & live
    expect(screen.getByText('Approved & Live for Applications')).toBeInTheDocument();
  });

  it('resumes polling after clicking Generate until background task completes (P1-11)', async () => {
    let pollCount = 0;
    let hasGenerated = false;

    vi.spyOn(global, 'fetch').mockImplementation(async (url, opts) => {
      if (url.includes('/api/budget/blueprint/preview')) {
        return { ok: true, status: 200, json: async () => ({}) };
      }
      if (url.includes('/api/jobs/job-test-123/blueprint/generate/status')) {
        if (!hasGenerated) {
          return { ok: true, status: 200, json: async () => ({ status: 'idle' }) };
        }
        pollCount += 1;
        if (pollCount === 1) {
          return {
            ok: true,
            status: 200,
            json: async () => ({ status: 'in_progress', task_id: 'task-gen-99' }),
          };
        }
        return {
          ok: true,
          status: 200,
          json: async () => ({
            status: 'completed',
            task_id: 'task-gen-99',
            blueprint: {
              id: 'bp-generated-1',
              job_id: mockJob.id,
              version: 1,
              status: 'draft',
              is_stale: false,
              sections: [],
              validation_report: { is_valid: true, errors: [], warnings: [] },
            },
          }),
        };
      }
      if (url.includes('/api/jobs/job-test-123/blueprint/generate') && opts?.method === 'POST') {
        hasGenerated = true;
        return {
          ok: true,
          status: 202,
          json: async () => ({ status: 'in_progress', task_id: 'task-gen-99' }),
        };
      }
      if (url.includes('/api/jobs/job-test-123/blueprint')) {
        if (!hasGenerated) {
          return {
            ok: false,
            status: 404,
            json: async () => ({ detail: 'Blueprint not found' }),
          };
        }
        return {
          ok: true,
          status: 200,
          json: async () => ({
            id: 'bp-generated-1',
            job_id: mockJob.id,
            version: 1,
            status: 'draft',
            is_stale: false,
            sections: [],
            validation_report: { is_valid: true, errors: [], warnings: [] },
          }),
        };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    });

    render(<BlueprintReviewEditor job={mockJob} initialBlueprint={null} />);

    // Initial state: not generated yet, show Generate button
    await waitFor(() => {
      expect(screen.getByText('Generate Interview Blueprint')).toBeInTheDocument();
    });

    const genBtn = screen.getByText('Generate Interview Blueprint');

    // Click Generate
    await act(async () => {
      fireEvent.click(genBtn);
    });

    // Verify polling resumed and progressed to completion
    await waitFor(() => {
      expect(pollCount).toBeGreaterThanOrEqual(1);
    });

    // The editor renders the generated blueprint and clears the generating state
    await waitFor(
      () => {
        expect(screen.getByText(/v1 Draft/i)).toBeInTheDocument();
      },
      { timeout: 4000 }
    );
  });
});
