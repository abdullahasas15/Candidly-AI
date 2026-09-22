import React, { useState, useEffect } from 'react';
import { ArrowRight, CheckCircle2, Shield, Activity, Clock, FileCheck, Sparkles } from 'lucide-react';

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
    <section className="relative pt-12 sm:pt-16 lg:pt-20 pb-16 sm:pb-24 lg:pb-28 overflow-hidden">
      {/* Background Decorative Gradient Glow */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-full max-w-7xl h-[560px] pointer-events-none opacity-50 dark:opacity-25 -z-10">
        <div className="absolute inset-0 bg-gradient-to-b from-indigo-500/20 via-purple-500/10 to-transparent blur-3xl" />
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-12 lg:gap-10 items-center">
          
          {/* Left Column: Value Proposition & Copy */}
          <div className="lg:col-span-6 space-y-6 text-center lg:text-left">
            {/* Trust Pill */}
            <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-indigo-50 dark:bg-indigo-950/60 border border-indigo-200/80 dark:border-indigo-800/70 text-xs font-semibold text-indigo-700 dark:text-indigo-300">
              <span className="flex h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
              <span>Next-Generation Autonomous Technical Hiring</span>
            </div>

            {/* Headline */}
            <h1 className="text-3xl sm:text-4xl lg:text-5xl xl:text-6xl font-extrabold tracking-tight text-slate-900 dark:text-white leading-[1.16]">
              Autonomous voice interviews with{' '}
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-600 via-indigo-500 to-purple-600 dark:from-indigo-400 dark:via-purple-300 dark:to-indigo-300">
                human-grade precision.
              </span>
            </h1>

            {/* Subheadline */}
            <p className="text-base sm:text-lg lg:text-xl text-slate-600 dark:text-slate-300 font-normal leading-relaxed max-w-2xl mx-auto lg:mx-0">
              An AI-led interview experience that evaluates candidates the way a great human interviewer would — fair, consistent, and evidence-backed — while quietly ensuring the person on the other side of the camera is who they say they are, doing their own work, in real time.
            </p>

            {/* Action Buttons */}
            <div className="flex flex-col sm:flex-row items-center justify-center lg:justify-start gap-4 pt-2">
              <button
                onClick={onRequestDemo}
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2.5 px-6 py-3.5 rounded-xl font-semibold text-base text-white bg-indigo-600 hover:bg-indigo-700 dark:bg-indigo-600 dark:hover:bg-indigo-500 shadow-lg shadow-indigo-600/25 hover:shadow-indigo-600/35 hover:-translate-y-0.5 transition-all duration-150"
              >
                <span>Request Enterprise Demo</span>
                <ArrowRight className="w-4 h-4" />
              </button>

              <button
                onClick={onExploreEvaluation}
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-6 py-3.5 rounded-xl font-medium text-base text-slate-700 dark:text-slate-200 bg-white dark:bg-slate-800/90 hover:bg-slate-50 dark:hover:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-sm transition-all"
              >
                <FileCheck className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                <span>Explore Evaluation Report</span>
              </button>
            </div>

            {/* Micro value badges */}
            <div className="pt-2 flex flex-wrap items-center justify-center lg:justify-start gap-y-2 gap-x-5 text-xs text-slate-500 dark:text-slate-400">
              <div className="flex items-center gap-1.5">
                <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                <span>Zero scheduling bottlenecks</span>
              </div>
              <div className="flex items-center gap-1.5">
                <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                <span>Calibrated 5-level rubrics</span>
              </div>
              <div className="flex items-center gap-1.5">
                <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                <span>Non-invasive session integrity</span>
              </div>
            </div>
          </div>

          {/* Right Column: Live Interview UI Mockup Graphic */}
          <div className="lg:col-span-6 relative">
            <div className="relative mx-auto max-w-lg rounded-2xl bg-white dark:bg-[#111827] border border-slate-200 dark:border-slate-800 shadow-2xl overflow-hidden">
              
              {/* Header Bar of Mockup */}
              <div className="px-5 py-3.5 bg-slate-50/90 dark:bg-slate-900/90 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <div className="w-3 h-3 rounded-full bg-red-400/80" />
                  <div className="w-3 h-3 rounded-full bg-amber-400/80" />
                  <div className="w-3 h-3 rounded-full bg-emerald-400/80" />
                  <span className="ml-2 text-xs font-semibold text-slate-700 dark:text-slate-300">
                    Live Session: Senior Backend Engineer
                  </span>
                </div>
                {/* Calm Integrity Status Pill */}
                <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-50 dark:bg-emerald-950/50 border border-emerald-200 dark:border-emerald-800/60 text-[11px] font-medium text-emerald-700 dark:text-emerald-300">
                  <Shield className="w-3 h-3 text-emerald-500" />
                  <span>Integrity: Optimal</span>
                </div>
              </div>

              {/* Mockup Body */}
              <div className="p-5 sm:p-6 space-y-4">
                
                {/* Visual Audio Wave & Active Turn */}
                <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-900/60 border border-slate-100 dark:border-slate-800/80">
                  <div className="flex items-center justify-between mb-2.5">
                    <div className="flex items-center gap-2">
                      <div className="w-2 h-2 rounded-full bg-indigo-500 animate-ping" />
                      <span className="text-xs font-semibold text-slate-800 dark:text-slate-200">
                        Active Turn Dialogue
                      </span>
                    </div>
                    {/* Synchronized Pacing Indicator */}
                    <div className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400 font-mono">
                      <Clock className="w-3.5 h-3.5 text-slate-400" />
                      <span>08:42 / 20:00</span>
                    </div>
                  </div>

                  {/* Audio Frequency Simulation Bar */}
                  <div className="h-10 flex items-center justify-center gap-1 px-4 py-2 bg-white dark:bg-slate-950/70 rounded-lg border border-slate-200/60 dark:border-slate-800/60">
                    {[35, 65, 85, 55, 30, 80, 95, 70, 45, 80, 100, 65, 40, 80, 50, 90, 70, 35, 60, 40].map((h, idx) => (
                      <div
                        key={idx}
                        className={`w-1 rounded-full transition-all duration-300 ${
                          idx % 2 === 0
                            ? 'bg-indigo-500 dark:bg-indigo-400'
                            : 'bg-indigo-300 dark:bg-indigo-600'
                        }`}
                        style={{
                          height: `${Math.max(15, (h * (activeVoiceStep === 1 ? 1 : 0.45)))}%`,
                        }}
                      />
                    ))}
                  </div>
                </div>

                {/* Simulated Real-Time Turn Bubble */}
                <div className="transition-all duration-300">
                  <div className="flex items-center justify-between text-xs mb-1.5">
                    <span className="font-semibold text-indigo-600 dark:text-indigo-400">
                      {conversationSteps[activeVoiceStep].speaker}
                    </span>
                    <span className="text-[10px] px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400">
                      {conversationSteps[activeVoiceStep].tag}
                    </span>
                  </div>
                  <p className="text-xs sm:text-sm text-slate-700 dark:text-slate-300 leading-relaxed italic bg-slate-50 dark:bg-slate-800/40 p-3.5 rounded-xl border border-slate-100 dark:border-slate-800">
                    {conversationSteps[activeVoiceStep].text}
                  </p>
                  <div className="mt-2 flex items-center justify-between text-[11px] text-slate-500 dark:text-slate-400">
                    <span className="flex items-center gap-1 text-indigo-600 dark:text-indigo-400 font-medium">
                      <Activity className="w-3 h-3" />
                      {conversationSteps[activeVoiceStep].status}
                    </span>
                    <span className="font-mono">Follow-Up Depth: 1/2</span>
                  </div>
                </div>

                {/* Real-time Competency Progress Checklist */}
                <div className="pt-2 border-t border-slate-100 dark:border-slate-800/80 space-y-2">
                  <div className="flex items-center justify-between text-xs text-slate-600 dark:text-slate-400 font-medium">
                    <span>Target Competency Evaluation</span>
                    <span className="text-indigo-600 dark:text-indigo-400 font-semibold">Weight: 35%</span>
                  </div>
                  <div className="flex items-center justify-between bg-slate-50 dark:bg-slate-900/50 p-2.5 rounded-lg border border-slate-100 dark:border-slate-800">
                    <span className="text-xs font-medium text-slate-800 dark:text-slate-200">
                      System Design & Scalability
                    </span>
                    <span className="px-2 py-0.5 rounded bg-indigo-50 dark:bg-indigo-950/70 text-indigo-700 dark:text-indigo-300 text-[11px] font-semibold">
                      L4 Anchor Identified
                    </span>
                  </div>
                </div>

              </div>

              {/* Bottom Clean Status Bar (No overlapping badges) */}
              <div className="px-5 py-3 bg-slate-50 dark:bg-slate-900/80 border-t border-slate-200/70 dark:border-slate-800/70 flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-emerald-500" />
                  <span className="text-slate-700 dark:text-slate-300 font-medium">Real-Time Evidence Citations Active</span>
                </div>
                <div className="flex items-center gap-1 text-emerald-600 dark:text-emerald-400 font-semibold">
                  <span>100% Calibrated</span>
                </div>
              </div>

            </div>

            {/* Neatly Integrated Evidence Callout Pill Underneath (Non-overlapping) */}
            <div className="mt-4 flex items-center justify-center sm:justify-end gap-3 text-xs text-slate-500 dark:text-slate-400">
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-sm font-medium">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
                <span>Every score substantiated with timestamped transcripts</span>
              </span>
            </div>

          </div>

        </div>
      </div>
    </section>
  );
}
