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
    <section id="proctoring" className="py-20 md:py-28 bg-black border-b border-white/[0.08] scroll-mt-20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-12 lg:gap-16 items-center">
          
          {/* Left: Copy & Pillars */}
          <div className="lg:col-span-6 space-y-6 text-center lg:text-left">
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-xs font-mono text-emerald-400">
              <ShieldCheck className="w-3.5 h-3.5" />
              <span>Session Authenticity & Trust</span>
            </div>

            <h2 className="font-display text-4xl sm:text-5xl font-normal text-white tracking-tight leading-tight">
              Fairness protected for every candidate.
            </h2>

            <p className="text-base sm:text-lg text-zinc-300 leading-relaxed">
              True meritocracy requires trust. Our continuous verification runs calmly in the background, safeguarding honest candidates by ensuring that every submitted interview represents authentic, independent work.
            </p>

            <div className="space-y-3 pt-2">
              {integrityPillars.map((pillar, idx) => {
                const Icon = pillar.icon;
                return (
                  <div
                    key={idx}
                    className="p-4 rounded-xl bg-[#0A0A0B] border border-white/[0.08] flex items-start gap-4 shadow-sm"
                  >
                    <div className="w-10 h-10 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center justify-center shrink-0 mt-0.5">
                      <Icon className="w-5 h-5" />
                    </div>
                    <div className="space-y-1">
                      <h3 className="text-sm font-semibold text-white">
                        {pillar.title}
                      </h3>
                      <p className="text-xs text-zinc-400 leading-normal">
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
            <div className="relative mx-auto max-w-md rounded-2xl bg-[#0A0A0B] border border-white/[0.08] shadow-2xl p-6 sm:p-8 space-y-6">
              
              {/* Header */}
              <div className="flex items-center justify-between pb-4 border-b border-white/[0.06]">
                <div className="flex items-center gap-2.5">
                  <div className="w-9 h-9 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 flex items-center justify-center">
                    <Lock className="w-4 h-4" />
                  </div>
                  <div>
                    <div className="text-xs font-semibold text-white">
                      Integrity Audit Overview
                    </div>
                    <div className="text-[11px] font-mono text-zinc-500">
                      Standard Session Protocol
                    </div>
                  </div>
                </div>
                <span className="px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-300 text-xs font-mono border border-emerald-500/20">
                  Verified · Optimal
                </span>
              </div>

              {/* Integrity Score Radial/Gauge representation */}
              <div className="text-center py-4 bg-[#111113] rounded-xl border border-white/[0.06]">
                <div className="font-display text-4xl font-normal text-white">
                  98 <span className="text-sm font-mono text-zinc-500">/ 100</span>
                </div>
                <div className="text-[11px] font-mono uppercase tracking-wider text-emerald-400 mt-1">
                  Confidence Score: High
                </div>
              </div>

              {/* Verification Checklist */}
              <div className="space-y-2.5 text-xs">
                <div className="flex items-center justify-between text-zinc-300 p-2 rounded-lg bg-black/40 border border-white/[0.04]">
                  <span className="flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                    <span>Single Face In-Frame</span>
                  </span>
                  <span className="text-[11px] font-mono text-zinc-500">Continuous</span>
                </div>

                <div className="flex items-center justify-between text-zinc-300 p-2 rounded-lg bg-black/40 border border-white/[0.04]">
                  <span className="flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                    <span>Focus Continuity</span>
                  </span>
                  <span className="text-[11px] font-mono text-zinc-500">No Tab Deviations</span>
                </div>

                <div className="flex items-center justify-between text-zinc-300 p-2 rounded-lg bg-black/40 border border-white/[0.04]">
                  <span className="flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                    <span>Acoustic Isolation</span>
                  </span>
                  <span className="text-[11px] font-mono text-zinc-500">Clean Audio Feed</span>
                </div>
              </div>

            </div>
          </div>

        </div>

      </div>
    </section>
  );
}
