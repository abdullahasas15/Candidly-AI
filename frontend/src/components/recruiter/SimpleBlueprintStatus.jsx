import React, { useEffect, useState } from 'react';
import { CheckCircle2, RefreshCw, Sparkles, Settings2, Volume2, Clock, Layers } from 'lucide-react';

const BlueprintReviewEditor = React.lazy(() => import('./BlueprintReviewEditor'));

const getAuthHeaders = (token, contentType) => {
  const headers = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (contentType) headers['Content-Type'] = contentType;
  return headers;
};

const STAGE_COPY = {
  budgeting: 'Planning the interview time budget…',
  generating_sections: 'Writing calibrated questions for each competency…',
  repair_passes: 'Polishing question quality…',
  batched_llm_review: 'Running a final quality review…',
  saving: 'Saving the interview blueprint…',
  completed: 'Done',
};

/**
 * Zero-touch blueprint step for job creation.
 *
 * The blueprint engine stays (it powers the live interview), but the recruiter
 * never has to understand or approve it: generation shows friendly progress,
 * and a blueprint with no validation errors is already approved by the backend.
 * The full review editor only appears when something needs attention
 * (validation errors) or when the recruiter explicitly chooses to customize.
 */
export default function SimpleBlueprintStatus({ job, onReady, onCustomized }) {
  const [phase, setPhase] = useState('checking'); // checking | generating | ready | needs_attention | failed
  const [blueprint, setBlueprint] = useState(null);
  const [error, setError] = useState(null);
  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState('budgeting');
  const [showEditor, setShowEditor] = useState(false);

  useEffect(() => {
    if (!job?.id) return;
    let cancelled = false;
    let timer = null;

    const poll = async () => {
      try {
        const token = localStorage.getItem('candidly-auth-token');
        const res = await fetch(`/api/jobs/${job.id}/blueprint/generate/status`, {
          headers: getAuthHeaders(token),
        });
        if (!res.ok) {
          if (!cancelled) timer = setTimeout(poll, 3000);
          return;
        }
        const data = await res.json();
        if (cancelled) return;

        setProgress(data.progress || 0);
        setStage(data.current_stage || 'budgeting');

        if (data.status === 'in_progress') {
          setPhase('generating');
          timer = setTimeout(poll, 1500);
          return;
        }
        if (data.status === 'failed') {
          setPhase('failed');
          setError(data.error || 'Blueprint generation failed');
          return;
        }

        // completed (or idle with a blueprint already saved & auto-approved)
        const bp = data.blueprint;
        if (bp && bp.status === 'approved') {
          setBlueprint(bp);
          setPhase('ready');
          if (onReady) onReady(bp);
        } else if (bp) {
          // Draft with validation errors: needs human attention.
          setBlueprint(bp);
          setPhase('needs_attention');
        } else {
          // No task and no blueprint yet: kick off generation.
          const token2 = localStorage.getItem('candidly-auth-token');
          const start = await fetch(`/api/jobs/${job.id}/blueprint/generate`, {
            method: 'POST',
            headers: getAuthHeaders(token2),
          });
          if (!start.ok && !cancelled) {
            setPhase('failed');
            setError('Could not start blueprint generation.');
            return;
          }
          if (!cancelled) {
            setPhase('generating');
            timer = setTimeout(poll, 1500);
          }
        }
      } catch (err) {
        if (!cancelled) timer = setTimeout(poll, 3000);
      }
    };

    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id]);

  const handleEditorApproved = (approvedBp) => {
    setBlueprint(approvedBp);
    setPhase('ready');
    setShowEditor(false);
    if (onCustomized) onCustomized(approvedBp);
  };

  // Errors and explicit customization use the full editor
  if (showEditor || phase === 'needs_attention' || phase === 'failed') {
    return (
      <div className="space-y-3">
        {phase === 'failed' && (
          <div className="rounded-2xl border border-rose-500/30 bg-rose-950/30 p-4 text-xs text-rose-200">
            {error}
          </div>
        )}
        {phase === 'needs_attention' && (
          <div className="rounded-2xl border border-amber-500/30 bg-amber-950/20 p-4 text-xs text-amber-200">
            The generated interview needs a fix before it can go live. Review the highlighted
            issues below, tweak or regenerate the affected sections, then approve.
          </div>
        )}
        <React.Suspense
          fallback={
            <div className="p-12 text-center space-y-2">
              <RefreshCw className="w-6 h-6 animate-spin mx-auto text-teal-400" />
              <p className="text-xs text-zinc-400">Loading editor…</p>
            </div>
          }
        >
          <BlueprintReviewEditor job={job} onApproved={handleEditorApproved} />
        </React.Suspense>
      </div>
    );
  }

  if (phase === 'ready') {
    const skillCount = (job?.skills || blueprint?.sections || []).length;
    return (
      <div className="py-8 text-center space-y-6" data-testid="blueprint-ready">
        <div className="w-16 h-16 rounded-2xl bg-emerald-500/10 text-emerald-400 flex items-center justify-center mx-auto shadow-sm">
          <CheckCircle2 className="w-8 h-8" />
        </div>
        <div className="max-w-lg mx-auto space-y-2">
          <h3 className="text-lg font-extrabold text-white">Your interview is ready and live</h3>
          <p className="text-xs text-zinc-400 leading-relaxed">
            Questions, rubrics, and time budget were generated for{' '}
            <span className="text-zinc-200 font-semibold">{job?.job_title}</span> and the job is now
            accepting candidate applications. No further action needed.
          </p>
        </div>
        <div className="flex items-center justify-center gap-2 flex-wrap">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-[#18181B] border border-white/[0.06] px-3 py-1.5 text-[11px] font-semibold text-zinc-300">
            <Clock className="w-3.5 h-3.5 text-teal-400" />
            {job?.interview_duration_mins || 20} min voice interview
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-[#18181B] border border-white/[0.06] px-3 py-1.5 text-[11px] font-semibold text-zinc-300">
            <Layers className="w-3.5 h-3.5 text-teal-400" />
            {skillCount || 'Multiple'} competencies assessed
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-[#18181B] border border-white/[0.06] px-3 py-1.5 text-[11px] font-semibold text-zinc-300">
            <Volume2 className="w-3.5 h-3.5 text-teal-400" />
            Fully agentic AI interviewer
          </span>
        </div>
        <button
          type="button"
          onClick={() => setShowEditor(true)}
          className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-zinc-400 hover:text-teal-300 underline underline-offset-4"
        >
          <Settings2 className="w-3.5 h-3.5" />
          Customize questions &amp; rubrics (advanced)
        </button>
      </div>
    );
  }

  // checking / generating
  const copy = STAGE_COPY[stage] || 'Preparing…';
  return (
    <div className="py-10 text-center space-y-6" data-testid="blueprint-generating">
      <div className="w-14 h-14 rounded-2xl bg-teal-500/10 text-teal-400 flex items-center justify-center mx-auto shadow-sm">
        <Sparkles className="w-7 h-7" />
      </div>
      <div className="max-w-md mx-auto space-y-1">
        <h3 className="text-base font-extrabold text-white">Setting up your interview</h3>
        <p className="text-xs text-zinc-400">{copy}</p>
      </div>
      <div className="max-w-sm mx-auto">
        <div className="h-2 w-full rounded-full bg-[#18181B] overflow-hidden">
          <div
            className="h-full rounded-full bg-gradient-to-r from-teal-500 to-emerald-400 transition-all duration-500"
            style={{ width: `${Math.max(5, Math.round((progress || 0.05) * 100))}%` }}
          />
        </div>
        <p className="mt-2 text-[11px] text-zinc-500">
          {Math.max(5, Math.round((progress || 0.05) * 100))}% — usually under a minute
        </p>
      </div>
    </div>
  );
}
