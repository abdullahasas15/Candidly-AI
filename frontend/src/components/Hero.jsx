import React, { useState, useEffect } from 'react';
import { ArrowRight, CheckCircle2, Shield, Activity, Clock, Sparkles } from 'lucide-react';

export default function Hero({ onRequestDemo, onExploreEvaluation }) {
  const [activeVoiceStep, setActiveVoiceStep] = useState(0);

  // Simulated live conversational cadence
  useEffect(() => {
    const interval = setInterval(() => {
      setActiveVoiceStep((prev) => (prev + 1) % 3);
    }, 4200);
    return () => clearInterval(interval);
  }, []);

  const conversationSteps = [
    {
      speaker: 'Candidly Interviewer',
      tag: 'Adaptive Question',
      text: '“You noted using distributed secondary caching for read performance. How does your design handle cache stampedes when hot keys expire under sudden traffic spikes?”',
      status: 'Probing Depth · L4 Target',
    },
    {
      speaker: 'Candidate',
      tag: 'Spoken Response',
      text: '“We implemented probabilistic early expiration combined with mutex locking on cache misses, allowing one background worker to regenerate data while stale reads are temporarily served.”',
      status: 'Analyzing Key Criteria (<300ms)',
    },
    {
      speaker: 'Candidly Interviewer',
      tag: 'Adaptive Follow-Up',
      text: '“Excellent. And how did you calibrate the mutex lock TTL to prevent cascading delays across downstream database connections?”',
      status: 'Targeted Trade-Off Follow-Up',
    },
  ];

  return (
    <section className="relative pt-16 sm:pt-20 lg:pt-24 pb-16 sm:pb-24 lg:pb-28 overflow-hidden bg-black bg-dots">
      {/* Background Decorative Gradient Glow */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-full max-w-7xl h-[560px] pointer-events-none opacity-20 -z-10">
        <div className="absolute inset-0 bg-gradient-to-b from-teal-500/20 via-teal-900/10 to-transparent blur-3xl" />
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-12 lg:gap-10 items-center">
          
          {/* Left Column: Value Proposition & Copy */}
          <div className="lg:col-span-6 space-y-6 text-center lg:text-left">
            {/* Trust Pill */}
            <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-white/[0.05] border border-white/[0.08] text-xs font-mono text-teal-400">
              <span className="flex h-2 w-2 rounded-full bg-teal-400 animate-pulse" />
              <span>Next-Generation Autonomous Technical Hiring</span>
            </div>

            {/* Headline with Serif Font */}
            <h1 className="font-display text-4xl sm:text-5xl lg:text-6xl xl:text-7xl font-normal tracking-tight text-white leading-[1.12]">
              Autonomous voice interviews with{' '}
              <span className="italic text-transparent bg-clip-text bg-gradient-to-r from-teal-300 via-teal-200 to-white">
                human-grade precision.
              </span>
            </h1>

            {/* Subheadline */}
            <p className="text-base sm:text-lg text-zinc-300 font-normal leading-relaxed max-w-2xl mx-auto lg:mx-0">
              An AI-led interview experience that evaluates candidates the way a great human interviewer would — fair, consistent, and evidence-backed — while quietly ensuring the person on camera is who they say they are, in real time.
            </p>

            {/* Single Prominent Teal Call to Action */}
            <div className="pt-2 flex justify-center lg:justify-start">
              <button
                type="button"
                onClick={onRequestDemo}
                className="inline-flex items-center justify-center gap-2.5 px-8 py-4 rounded-xl font-semibold text-base text-black bg-teal-500 hover:bg-teal-400 shadow-xl shadow-teal-500/20 hover:-translate-y-0.5 transition-all duration-150 cursor-pointer"
              >
                <span>Request Enterprise Demo</span>
                <ArrowRight className="w-4 h-4 stroke-[2.5]" />
              </button>
            </div>

            {/* Micro value badges */}
            <div className="pt-2 flex flex-wrap items-center justify-center lg:justify-start gap-y-2 gap-x-5 text-xs text-zinc-400">
              <div className="flex items-center gap-1.5">
                <CheckCircle2 className="w-3.5 h-3.5 text-teal-400" />
                <span>Zero scheduling bottlenecks</span>
              </div>
              <div className="flex items-center gap-1.5">
                <CheckCircle2 className="w-3.5 h-3.5 text-teal-400" />
                <span>Calibrated 5-level rubrics</span>
              </div>
              <div className="flex items-center gap-1.5">
                <CheckCircle2 className="w-3.5 h-3.5 text-teal-400" />
                <span>Verbatim quote evidence</span>
              </div>
            </div>
          </div>

          {/* Right Column: Live Interview UI Mockup Graphic */}
          <div className="lg:col-span-6 relative">
            <div className="relative mx-auto max-w-lg rounded-2xl bg-[#0A0A0B] border border-white/[0.08] shadow-2xl overflow-hidden">
              
              {/* Header Bar of Mockup */}
              <div className="px-5 py-3.5 bg-[#0A0A0B] border-b border-white/[0.08] flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <div className="w-2.5 h-2.5 rounded-full bg-rose-500/80" />
                  <div className="w-2.5 h-2.5 rounded-full bg-amber-500/80" />
                  <div className="w-2.5 h-2.5 rounded-full bg-teal-400/80" />
                  <span className="ml-2 text-xs font-medium text-zinc-300">
                    Live Session: Senior Backend Engineer
                  </span>
                </div>
                {/* Integrity Status Pill */}
                <div className="flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-teal-500/10 border border-teal-500/20 text-[11px] font-mono text-teal-300">
                  <Shield className="w-3 h-3 text-teal-400" />
                  <span>Integrity: Optimal</span>
                </div>
              </div>

              {/* Mockup Body */}
              <div className="p-5 sm:p-6 space-y-4">
                
                {/* Visual Audio Wave & Active Turn */}
                <div className="p-4 rounded-xl bg-[#111113] border border-white/[0.06]">
                  <div className="flex items-center justify-between mb-2.5">
                    <div className="flex items-center gap-2">
                      <div className="w-2 h-2 rounded-full bg-teal-400 animate-ping" />
                      <span className="text-xs font-semibold text-zinc-200">
                        Active Turn Dialogue
                      </span>
                    </div>
                    {/* Synchronized Pacing Indicator */}
                    <div className="flex items-center gap-1.5 text-xs text-zinc-500 font-mono">
                      <Clock className="w-3.5 h-3.5 text-zinc-500" />
                      <span>08:42 / 20:00</span>
                    </div>
                  </div>

                  {/* Audio Frequency Simulation Bar */}
                  <div className="h-10 flex items-center justify-center gap-1 px-4 py-2 bg-black/60 rounded-lg border border-white/[0.06]">
                    {[35, 65, 85, 55, 30, 80, 95, 70, 45, 80, 100, 65, 40, 80, 50, 90, 70, 35, 60, 40].map((h, idx) => (
                      <div
                        key={idx}
                        className={`w-1 rounded-full transition-all duration-300 ${
                          idx % 2 === 0
                            ? 'bg-teal-400'
                            : 'bg-teal-500/50'
                        }`}
                        style={{ height: `${h}%` }}
                      />
                    ))}
                  </div>
                </div>

                {/* Animated Conversational Stream */}
                <div className="space-y-2.5">
                  {conversationSteps.map((step, idx) => {
                    const isActive = idx === activeVoiceStep;
                    const isInterviewer = step.speaker.includes('Interviewer');

                    return (
                      <div
                        key={idx}
                        className={`p-3.5 rounded-xl border transition-all duration-300 ${
                          isActive
                            ? 'bg-[#18181B] border-teal-400/40 shadow-sm'
                            : 'bg-[#111113] border-white/[0.04] opacity-50'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-1.5">
                          <div className="flex items-center gap-2">
                            <span
                              className={`text-xs font-semibold ${
                                isInterviewer ? 'text-teal-400' : 'text-zinc-200'
                              }`}
                            >
                              {step.speaker}
                            </span>
                            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-white/[0.05] text-zinc-400 border border-white/[0.06]">
                              {step.tag}
                            </span>
                          </div>
                          <span className="text-[10px] font-mono text-zinc-500">
                            {step.status}
                          </span>
                        </div>
                        <p className="text-xs text-zinc-300 leading-relaxed font-sans">
                          {step.text}
                        </p>
                      </div>
                    );
                  })}
                </div>

                {/* Bottom Live Diagnostic Row */}
                <div className="pt-2 border-t border-white/[0.06] flex items-center justify-between text-xs text-zinc-400">
                  <div className="flex items-center gap-1.5">
                    <Activity className="w-3.5 h-3.5 text-teal-400" />
                    <span>Response Latency: 280ms</span>
                  </div>
                  <div className="font-mono text-[11px] text-zinc-500">
                    Confidence: 94.2%
                  </div>
                </div>

              </div>
            </div>
          </div>

        </div>
      </div>
    </section>
  );
}
