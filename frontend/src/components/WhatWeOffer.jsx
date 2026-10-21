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
    },
    {
      icon: MessageSquareCode,
      tag: 'Conversational Flow',
      title: 'Real conversations, not scripts',
      description:
        'Natural, bi-directional voice dialogue with intelligent follow-up mechanics that probe into engineering decisions, trade-offs, and edge cases.',
      bullets: [
        'Probes deeper when answers skip critical constraints',
        'Never badgers candidates on unfamiliar topics',
        'Respects time limits with adaptive question pacing',
      ],
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
    },
  ];

  return (
    <section id="what-we-offer" className="py-20 md:py-28 bg-black border-b border-white/[0.08] scroll-mt-20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        
        {/* Section Header */}
        <div className="text-center max-w-3xl mx-auto space-y-4 mb-16">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-white/[0.05] border border-white/[0.08] text-xs font-mono text-teal-400">
            <Sparkles className="w-3.5 h-3.5" />
            <span>Autonomous Intelligence & Architecture</span>
          </div>
          <h2 className="font-display text-4xl sm:text-5xl font-normal text-white tracking-tight">
            Designed for depth, fairness, and speed.
          </h2>
          <p className="text-base sm:text-lg text-zinc-300">
            Replace unpredictable screening calls with calibrated, voice-driven technical dialogues that provide unequivocal clarity on engineering capability.
          </p>
        </div>

        {/* 4 Feature Panels Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {features.map((feature, idx) => {
            const Icon = feature.icon;
            return (
              <div
                key={idx}
                className="group relative p-8 rounded-2xl bg-[#0A0A0B] border border-white/[0.08] hover:border-white/[0.16] transition-all duration-300 shadow-sm hover:-translate-y-0.5 flex flex-col justify-between"
              >
                <div className="space-y-4">
                  {/* Top bar with Icon & Tag */}
                  <div className="flex items-center justify-between">
                    <div className="w-11 h-11 rounded-xl bg-teal-500/10 text-teal-400 border border-teal-500/20 flex items-center justify-center transition-transform">
                      <Icon className="w-5 h-5" />
                    </div>
                    <span className="text-[10px] font-mono px-2.5 py-0.5 rounded-full border border-white/[0.08] bg-white/[0.03] text-zinc-400">
                      {feature.tag}
                    </span>
                  </div>

                  {/* Title & Description */}
                  <div>
                    <h3 className="text-xl font-bold text-white tracking-tight mb-2">
                      {feature.title}
                    </h3>
                    <p className="text-xs sm:text-sm text-zinc-400 leading-relaxed">
                      {feature.description}
                    </p>
                  </div>

                  {/* Bullet Points */}
                  <ul className="space-y-2 pt-2 border-t border-white/[0.06]">
                    {feature.bullets.map((bullet, bIdx) => (
                      <li key={bIdx} className="flex items-center gap-2 text-xs text-zinc-300">
                        <Check className="w-3.5 h-3.5 text-teal-400 shrink-0" />
                        <span>{bullet}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            );
          })}
        </div>

      </div>
    </section>
  );
}
