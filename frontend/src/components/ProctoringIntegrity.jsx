import React from 'react';
import { ShieldCheck, Eye, UserCheck, Volume2, Lock, CheckCircle2 } from 'lucide-react';

export default function ProctoringIntegrity() {
  const integrityPillars = [
    {
      icon: UserCheck,
      title: 'Continuous Identity Continuity',
      description:
        'Ensures the participant on camera remains consistent and verified from start to finish without interrupting the natural conversation flow.',
    },
    {
      icon: Eye,
      title: 'Attentive Focus Assurance',
      description:
        'Verifies active engagement with the interview dialogue, ensuring candidates have the space to concentrate and present their genuine capabilities.',
    },
    {
      icon: Volume2,
      title: 'Acoustic Environment Clarity',
      description:
        'Confirms a clean, isolated audio environment so that every spoken insight is captured clearly without disruptive ambient interference.',
    },
  ];

  return (
    <section id="proctoring" className="py-20 md:py-28 bg-slate-50/70 dark:bg-[#0B0F19]/60 border-y border-slate-200/60 dark:border-slate-800/60 scroll-mt-20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-12 lg:gap-16 items-center">
          
          {/* Left: Copy & Pillars */}
          <div className="lg:col-span-6 space-y-6 text-center lg:text-left">
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-50 dark:bg-emerald-950/50 border border-emerald-200 dark:border-emerald-800 text-xs font-semibold text-emerald-700 dark:text-emerald-300">
              <ShieldCheck className="w-3.5 h-3.5" />
              <span>Session Authenticity & Trust</span>
            </div>

            <h2 className="text-3xl sm:text-4xl font-extrabold text-slate-900 dark:text-white tracking-tight leading-tight">
              Fairness protected for every candidate.
            </h2>

            <p className="text-base sm:text-lg text-slate-600 dark:text-slate-300 leading-relaxed">
              True meritocracy requires trust. Our continuous verification runs calmly in the background, safeguarding honest candidates by ensuring that every submitted interview represents authentic, independent work.
            </p>

            <div className="space-y-4 pt-2">
              {integrityPillars.map((pillar, idx) => {
                const Icon = pillar.icon;
                return (
                  <div
                    key={idx}
                    className="p-4 rounded-xl bg-white dark:bg-[#111827] border border-slate-200/80 dark:border-slate-800 flex items-start gap-4 shadow-sm"
                  >
                    <div className="w-10 h-10 rounded-lg bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 flex items-center justify-center flex-shrink-0 mt-0.5">
                      <Icon className="w-5 h-5" />
                    </div>
                    <div className="space-y-1">
                      <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                        {pillar.title}
                      </h3>
                      <p className="text-xs text-slate-600 dark:text-slate-300 leading-normal">
                        {pillar.description}
                      </p>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Right: Calm, Trustworthy Integrity Dashboard Visual */}
          <div className="lg:col-span-6">
            <div className="relative mx-auto max-w-md rounded-2xl bg-white dark:bg-[#111827] border border-slate-200 dark:border-slate-800 shadow-xl p-6 sm:p-8 space-y-6">
              
              {/* Header */}
              <div className="flex items-center justify-between pb-4 border-b border-slate-100 dark:border-slate-800">
                <div className="flex items-center gap-2.5">
                  <div className="w-9 h-9 rounded-xl bg-emerald-100 dark:bg-emerald-950/80 text-emerald-600 dark:text-emerald-400 flex items-center justify-center">
                    <Lock className="w-4 h-4" />
                  </div>
                  <div>
                    <div className="text-xs font-bold text-slate-900 dark:text-white">
                      Integrity Audit Overview
                    </div>
                    <div className="text-[11px] text-slate-500 dark:text-slate-400">
                      Standard Session Protocol
                    </div>
                  </div>
                </div>
                <span className="px-2.5 py-1 rounded-full bg-emerald-50 dark:bg-emerald-950/70 text-emerald-700 dark:text-emerald-300 text-xs font-semibold border border-emerald-200/60 dark:border-emerald-800/60">
                  Verified · Normal
                </span>
              </div>

              {/* Integrity Score Radial/Gauge representation */}
              <div className="text-center py-3 bg-slate-50 dark:bg-slate-900/60 rounded-xl border border-slate-100 dark:border-slate-800">
                <div className="text-3xl font-black text-slate-900 dark:text-white">
                  98 <span className="text-sm font-normal text-slate-500 dark:text-slate-400">/ 100</span>
                </div>
                <div className="text-xs font-semibold text-emerald-600 dark:text-emerald-400 mt-1 flex items-center justify-center gap-1">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  <span>Optimal Session Confidence</span>
                </div>
                <p className="text-[11px] text-slate-500 dark:text-slate-400 px-4 mt-1">
                  Session meets all enterprise security and merit-protection criteria.
                </p>
              </div>

              {/* Chronological Confidence Timeline */}
              <div className="space-y-3">
                <div className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                  Continuous Verification Timeline
                </div>

                <div className="space-y-2 text-xs">
                  <div className="p-2.5 rounded-lg bg-slate-50 dark:bg-slate-900/40 border border-slate-100 dark:border-slate-800/80 flex items-center justify-between">
                    <span className="text-slate-700 dark:text-slate-300 font-medium">Pre-Flight Hardware Check</span>
                    <span className="text-emerald-600 dark:text-emerald-400 font-semibold">Passed [00:00]</span>
                  </div>
                  <div className="p-2.5 rounded-lg bg-slate-50 dark:bg-slate-900/40 border border-slate-100 dark:border-slate-800/80 flex items-center justify-between">
                    <span className="text-slate-700 dark:text-slate-300 font-medium">Participant Identity Consistency</span>
                    <span className="text-emerald-600 dark:text-emerald-400 font-semibold">Continuous [100%]</span>
                  </div>
                  <div className="p-2.5 rounded-lg bg-slate-50 dark:bg-slate-900/40 border border-slate-100 dark:border-slate-800/80 flex items-center justify-between">
                    <span className="text-slate-700 dark:text-slate-300 font-medium">Environmental Audio Clarity</span>
                    <span className="text-emerald-600 dark:text-emerald-400 font-semibold">Uninterrupted</span>
                  </div>
                </div>
              </div>

              <div className="pt-2 text-center text-[11px] text-slate-500 dark:text-slate-400 italic">
                “Candidate dignity and privacy are respected at every moment.”
              </div>

            </div>
          </div>

        </div>

      </div>
    </section>
  );
}

