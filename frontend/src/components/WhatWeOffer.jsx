import React from 'react';
import { Target, MessageSquareCode, Scale, ShieldCheck, Sparkles, Check } from 'lucide-react';

export default function WhatWeOffer() {
  const features = [
    {
      icon: Target,
      tag: 'Dynamic Personalization',
      title: 'Tailored interviews, not templates',
      description:
        'Instead of fixed generic question banks, every interview synthesizes questions directly from the candidate’s verified background and role requirements.',
      bullets: [
        'Explores actual project architecture claims',
        'Tests depth where experience is claimed',
        'Evaluates foundational problem-solving on new skills',
      ],
      badgeColor: 'bg-indigo-50 dark:bg-indigo-950/60 text-indigo-700 dark:text-indigo-300 border-indigo-200 dark:border-indigo-800',
    },
    {
      icon: MessageSquareCode,
      tag: 'True Conversational Flow',
      title: 'Real conversations, not scripts',
      description:
        'Natural, bi-directional voice dialogue with intelligent follow-up mechanics that probe into engineering decisions, trade-offs, and edge cases.',
      bullets: [
        'Probes deeper when answers skip critical constraints',
        'Never badgers candidates on unfamiliar topics',
        'Respects time limits with adaptive question pacing',
      ],
      badgeColor: 'bg-purple-50 dark:bg-purple-950/60 text-purple-700 dark:text-purple-300 border-purple-200 dark:border-purple-800',
    },
    {
      icon: Scale,
      tag: 'Objective Standards',
      title: 'Fair by design',
      description:
        'Eliminate interviewer fatigue and unconscious bias. Every candidate is evaluated against calibrated 5-level behavioral rubrics with transparent weighting.',
      bullets: [
        'Standardized 5-tier behavioral anchors (L1 to L5)',
        'Calibrated percentage weightage per competency',
        'Zero variance in interview difficulty or tone',
      ],
      badgeColor: 'bg-blue-50 dark:bg-blue-950/60 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-800',
    },
    {
      icon: ShieldCheck,
      tag: 'Continuous Assurance',
      title: 'Built-in integrity',
      description:
        'Continuous, non-invasive session verification guarantees that candidates are working independently and authentically, protecting fair hiring outcomes.',
      bullets: [
        'Seamless presence & identity continuity checks',
        'Focus and workspace engagement verification',
        'Objective audit timeline without intrusive surveillance',
      ],
      badgeColor: 'bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800',
    },
  ];

  return (
    <section id="what-we-offer" className="py-20 md:py-28 bg-slate-50/70 dark:bg-[#0B0F19]/60 border-y border-slate-200/60 dark:border-slate-800/60 scroll-mt-20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        
        {/* Section Header */}
        <div className="text-center max-w-3xl mx-auto space-y-4 mb-16">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-indigo-50 dark:bg-indigo-950/50 border border-indigo-200 dark:border-indigo-800 text-xs font-semibold text-indigo-700 dark:text-indigo-300">
            <Sparkles className="w-3.5 h-3.5" />
            <span>Autonomous Intelligence & Architecture</span>
          </div>
          <h2 className="text-3xl sm:text-4xl font-extrabold text-slate-900 dark:text-white tracking-tight">
            Designed for depth, fairness, and speed.
          </h2>
          <p className="text-base sm:text-lg text-slate-600 dark:text-slate-300">
            Replace unpredictable screening calls with calibrated, voice-driven technical dialogues that provide unequivocal clarity on engineering capability.
          </p>
        </div>

        {/* 4 Feature Panels Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
          {features.map((feature, idx) => {
            const Icon = feature.icon;
            return (
              <div
                key={idx}
                className="group relative p-8 rounded-2xl bg-white dark:bg-[#111827] border border-slate-200/90 dark:border-slate-800/90 hover:border-indigo-500/50 dark:hover:border-indigo-500/50 transition-all duration-300 shadow-sm hover:shadow-xl hover:-translate-y-1 flex flex-col justify-between"
              >
                <div className="space-y-4">
                  {/* Top bar with Icon & Tag */}
                  <div className="flex items-center justify-between">
                    <div className="w-12 h-12 rounded-xl bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400 flex items-center justify-center group-hover:scale-110 transition-transform">
                      <Icon className="w-6 h-6" />
                    </div>
                    <span className={`text-[11px] font-semibold px-3 py-1 rounded-full border ${feature.badgeColor}`}>
                      {feature.tag}
                    </span>
                  </div>

                  {/* Title & Description */}
                  <div>
                    <h3 className="text-xl font-bold text-slate-900 dark:text-white tracking-tight mb-2">
                      {feature.title}
                    </h3>
                    <p className="text-sm text-slate-600 dark:text-slate-300 leading-relaxed">
                      {feature.description}
                    </p>
                  </div>

                  {/* Bullet points */}
                  <ul className="space-y-2.5 pt-2 border-t border-slate-100 dark:border-slate-800/70">
                    {feature.bullets.map((bullet, bIdx) => (
                      <li key={bIdx} className="flex items-start gap-2.5 text-xs text-slate-700 dark:text-slate-300">
                        <div className="w-4 h-4 rounded-full bg-emerald-100 dark:bg-emerald-950/70 text-emerald-600 dark:text-emerald-400 flex items-center justify-center flex-shrink-0 mt-0.5">
                          <Check className="w-2.5 h-2.5" />
                        </div>
                        <span>{bullet}</span>
                      </li>
                    ))}
                  </ul>
                </div>

                {/* Bottom subtle accent line */}
                <div className="mt-6 h-1 w-0 group-hover:w-full bg-gradient-to-r from-indigo-500 to-purple-500 rounded-full transition-all duration-500" />
              </div>
            );
          })}
        </div>

      </div>
    </section>
  );
}

