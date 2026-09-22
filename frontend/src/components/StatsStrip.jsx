import React from 'react';
import { Clock, Scale, Zap, ShieldCheck } from 'lucide-react';

export default function StatsStrip() {
  const stats = [
    {
      icon: Clock,
      value: '20 min',
      label: 'Average Calibrated Interview',
      subtext: 'Focused, complete evaluation without screening fatigue',
    },
    {
      icon: Scale,
      value: '100%',
      label: 'Uniform Rubric Rigor',
      subtext: 'Every candidate measured by the identical competency criteria',
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
      subtext: 'Every score justified with verbatim timestamped quotes',
    },
  ];

  return (
    <section className="py-12 bg-indigo-600 text-white dark:bg-indigo-950/90 dark:border-y dark:border-indigo-900/60">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-8 lg:gap-6">
          {stats.map((stat, idx) => {
            const Icon = stat.icon;
            return (
              <div key={idx} className="space-y-2 text-center sm:text-left">
                <div className="inline-flex items-center justify-center w-8 h-8 rounded-lg bg-white/15 text-white mb-1">
                  <Icon className="w-4 h-4" />
                </div>
                <div className="text-3xl sm:text-4xl font-black tracking-tight text-white">
                  {stat.value}
                </div>
                <div className="text-sm font-bold text-indigo-100">
                  {stat.label}
                </div>
                <div className="text-xs text-indigo-200/90 leading-normal">
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

