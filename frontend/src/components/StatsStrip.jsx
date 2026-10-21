import React from 'react';
import { Clock, Scale, Zap, ShieldCheck } from 'lucide-react';

export default function StatsStrip() {
  const stats = [
    {
      icon: Clock,
      value: '20 min',
      label: 'Calibrated Duration',
      subtext: 'Focused, complete evaluation without screening fatigue',
    },
    {
      icon: Scale,
      value: '100%',
      label: 'Uniform Rubric Rigor',
      subtext: 'Every candidate measured by identical competency criteria',
    },
    {
      icon: Zap,
      value: '<300ms',
      label: 'Conversational Cadence',
      subtext: 'Fluid, natural voice exchange with zero awkward pauses',
    },
    {
      icon: ShieldCheck,
      value: 'Zero',
      label: 'Black-Box Ratings',
      subtext: 'Every score anchored to verbatim timestamped quotes',
    },
  ];

  return (
    <section className="py-12 bg-[#0A0A0B] text-white border-y border-white/[0.08]">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-8 lg:gap-6">
          {stats.map((stat, idx) => {
            const Icon = stat.icon;
            return (
              <div key={idx} className="space-y-2 text-center sm:text-left">
                <div className="inline-flex items-center justify-center w-8 h-8 rounded-lg bg-teal-500/10 text-teal-400 border border-teal-500/20 mb-1">
                  <Icon className="w-4 h-4" />
                </div>
                <div className="font-display text-3xl sm:text-4xl font-normal tracking-tight text-white">
                  {stat.value}
                </div>
                <div className="text-xs font-semibold text-zinc-200 uppercase font-mono tracking-wider">
                  {stat.label}
                </div>
                <div className="text-xs text-zinc-400 leading-normal">
                  {stat.subtext}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
