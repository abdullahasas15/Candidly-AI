import React, { useState } from 'react';
import { Users, Briefcase, Check, ArrowRight, Video, FileText, Clock, Sparkles } from 'lucide-react';

export default function PersonaTabs({ onRequestDemo, onOpenAuth }) {
  const [activeTab, setActiveTab] = useState('recruiters');

  return (
    <section id="personas" className="py-20 md:py-28 scroll-mt-20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        
        {/* Section Header */}
        <div className="text-center max-w-3xl mx-auto space-y-4 mb-12">
          <h2 className="text-3xl sm:text-4xl font-extrabold text-slate-900 dark:text-white tracking-tight">
            Built for both sides of the hiring table.
          </h2>
          <p className="text-base sm:text-lg text-slate-600 dark:text-slate-300">
            A frictionless experience that empowers talent teams with rigorous hiring data while treating candidates with dignity, speed, and fairness.
          </p>

          {/* Tab Selector */}
          <div className="inline-flex p-1.5 rounded-2xl bg-slate-100 dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700/80 mt-4">
            <button
              onClick={() => setActiveTab('recruiters')}
              className={`flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm font-bold transition-all ${
                activeTab === 'recruiters'
                  ? 'bg-white dark:bg-slate-900 text-indigo-600 dark:text-indigo-400 shadow-sm'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
              }`}
            >
              <Briefcase className="w-4 h-4" />
              <span>For Talent Teams & Recruiters</span>
            </button>
            <button
              onClick={() => setActiveTab('candidates')}
              className={`flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm font-bold transition-all ${
                activeTab === 'candidates'
                  ? 'bg-white dark:bg-slate-900 text-indigo-600 dark:text-indigo-400 shadow-sm'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
              }`}
            >
              <Users className="w-4 h-4" />
              <span>For Candidates & Engineers</span>
            </button>
          </div>
        </div>

        {/* Tab Content Display */}
        <div className="rounded-3xl bg-slate-50/70 dark:bg-[#111827] border border-slate-200 dark:border-slate-800 p-8 sm:p-12 transition-all">
          {activeTab === 'recruiters' ? (
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-10 items-center">
              <div className="lg:col-span-7 space-y-6">
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-50 dark:bg-indigo-950/60 border border-indigo-200 dark:border-indigo-800 text-xs font-semibold text-indigo-700 dark:text-indigo-300">
                  <Briefcase className="w-3.5 h-3.5" />
                  <span>Calibrated Pipeline Velocity</span>
                </div>
                <h3 className="text-2xl sm:text-3xl font-bold text-slate-900 dark:text-white tracking-tight">
                  Screen top engineering talent in hours, not weeks.
                </h3>
                <p className="text-sm sm:text-base text-slate-600 dark:text-slate-300 leading-relaxed">
                  Eliminate the scheduling dance and inconsistent interviewer notes. Talent acquisition and engineering leaders define their role rubrics once, and Candidly autonomously conducts high-signal voice dialogues, delivering structured scorecards directly into your workflow.
                </p>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
                  <div className="flex items-start gap-2.5 text-xs text-slate-700 dark:text-slate-300">
                    <Check className="w-4 h-4 text-emerald-500 mt-0.5 flex-shrink-0" />
                    <span>Calibrated 5-tier rubrics per competency</span>
                  </div>
                  <div className="flex items-start gap-2.5 text-xs text-slate-700 dark:text-slate-300">
                    <Check className="w-4 h-4 text-emerald-500 mt-0.5 flex-shrink-0" />
                    <span>Side-by-side video & transcript replay</span>
                  </div>
                  <div className="flex items-start gap-2.5 text-xs text-slate-700 dark:text-slate-300">
                    <Check className="w-4 h-4 text-emerald-500 mt-0.5 flex-shrink-0" />
                    <span>100% auditable evidence citations</span>
                  </div>
                  <div className="flex items-start gap-2.5 text-xs text-slate-700 dark:text-slate-300">
                    <Check className="w-4 h-4 text-emerald-500 mt-0.5 flex-shrink-0" />
                    <span>One-click executive PDF report export</span>
                  </div>
                </div>

                <div className="pt-2">
                  <button
                    onClick={onRequestDemo}
                    className="inline-flex items-center gap-2 px-5 py-3 rounded-xl text-sm font-semibold text-white bg-indigo-600 hover:bg-indigo-700 dark:bg-indigo-600 shadow-md transition-all"
                  >
                    <span>Schedule Talent Team Walkthrough</span>
                    <ArrowRight className="w-4 h-4" />
                  </button>
                </div>
              </div>

              <div className="lg:col-span-5 bg-white dark:bg-slate-900 rounded-2xl p-6 border border-slate-200 dark:border-slate-800 shadow-lg space-y-4">
                <div className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                  Recruiter Dashboard Highlights
                </div>
                <div className="space-y-3">
                  <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-100 dark:border-slate-700 flex items-center justify-between text-xs">
                    <div>
                      <div className="font-bold text-slate-900 dark:text-white">Active Applicants</div>
                      <div className="text-slate-500 dark:text-slate-400">32 interviews completed today</div>
                    </div>
                    <span className="text-emerald-600 dark:text-emerald-400 font-bold bg-emerald-50 dark:bg-emerald-950/70 px-2 py-1 rounded-lg">
                      10x Velocity
                    </span>
                  </div>
                  <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-100 dark:border-slate-700 flex items-center justify-between text-xs">
                    <div>
                      <div className="font-bold text-slate-900 dark:text-white">Lead Time Reduction</div>
                      <div className="text-slate-500 dark:text-slate-400">From 9 days to 45 minutes</div>
                    </div>
                    <span className="text-indigo-600 dark:text-indigo-400 font-bold bg-indigo-50 dark:bg-indigo-950/70 px-2 py-1 rounded-lg">
                      -92% Wait
                    </span>
                  </div>
                  <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-100 dark:border-slate-700 flex items-center justify-between text-xs">
                    <div>
                      <div className="font-bold text-slate-900 dark:text-white">Hiring Manager Approval</div>
                      <div className="text-slate-500 dark:text-slate-400">Clear rationale backed by quotes</div>
                    </div>
                    <span className="text-purple-600 dark:text-purple-400 font-bold bg-purple-50 dark:bg-purple-950/70 px-2 py-1 rounded-lg">
                      98% Consensus
                    </span>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-10 items-center">
              <div className="lg:col-span-7 space-y-6">
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-50 dark:bg-emerald-950/60 border border-emerald-200 dark:border-emerald-800 text-xs font-semibold text-emerald-700 dark:text-emerald-300">
                  <Users className="w-3.5 h-3.5" />
                  <span>Fair & Respectful Candidate Experience</span>
                </div>
                <h3 className="text-2xl sm:text-3xl font-bold text-slate-900 dark:text-white tracking-tight">
                  Interview on your terms with zero human bias.
                </h3>
                <p className="text-sm sm:text-base text-slate-600 dark:text-slate-300 leading-relaxed">
                  No more waiting two weeks for a recruiter screen or hoping you get an interviewer on a good day. Candidly allows you to complete your technical dialogue at the time you are sharpest, with questions tailored to your experience and a standardized rubric protecting your merit.
                </p>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
                  <div className="flex items-start gap-2.5 text-xs text-slate-700 dark:text-slate-300">
                    <Check className="w-4 h-4 text-emerald-500 mt-0.5 flex-shrink-0" />
                    <span>24/7 on-demand interview availability</span>
                  </div>
                  <div className="flex items-start gap-2.5 text-xs text-slate-700 dark:text-slate-300">
                    <Check className="w-4 h-4 text-emerald-500 mt-0.5 flex-shrink-0" />
                    <span>Stress-free pre-flight hardware check</span>
                  </div>
                  <div className="flex items-start gap-2.5 text-xs text-slate-700 dark:text-slate-300">
                    <Check className="w-4 h-4 text-emerald-500 mt-0.5 flex-shrink-0" />
                    <span>Adaptive pacing with optional grace extension</span>
                  </div>
                  <div className="flex items-start gap-2.5 text-xs text-slate-700 dark:text-slate-300">
                    <Check className="w-4 h-4 text-emerald-500 mt-0.5 flex-shrink-0" />
                    <span>Actionable strengths & skill feedback report</span>
                  </div>
                </div>

                <div className="pt-2">
                  <button
                    onClick={() => onOpenAuth ? onOpenAuth('signin', 'candidate') : onRequestDemo()}
                    className="inline-flex items-center gap-2 px-5 py-3 rounded-xl text-sm font-semibold text-white bg-emerald-600 hover:bg-emerald-700 dark:bg-emerald-600 shadow-md transition-all"
                  >
                    <span>Explore Candidate Interface</span>
                    <ArrowRight className="w-4 h-4" />
                  </button>
                </div>
              </div>

              <div className="lg:col-span-5 bg-white dark:bg-slate-900 rounded-2xl p-6 border border-slate-200 dark:border-slate-800 shadow-lg space-y-4">
                <div className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                  Candidate Journey Summary
                </div>
                <div className="space-y-3">
                  <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-100 dark:border-slate-700 flex items-center justify-between text-xs">
                    <div>
                      <div className="font-bold text-slate-900 dark:text-white">Pre-Flight Test</div>
                      <div className="text-slate-500 dark:text-slate-400">Mic & camera verified in 30s</div>
                    </div>
                    <span className="text-emerald-600 dark:text-emerald-400 font-bold bg-emerald-50 dark:bg-emerald-950/70 px-2 py-1 rounded-lg">
                      Ready
                    </span>
                  </div>
                  <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-100 dark:border-slate-700 flex items-center justify-between text-xs">
                    <div>
                      <div className="font-bold text-slate-900 dark:text-white">Natural Cadence</div>
                      <div className="text-slate-500 dark:text-slate-400">Fluid voice interaction</div>
                    </div>
                    <span className="text-indigo-600 dark:text-indigo-400 font-bold bg-indigo-50 dark:bg-indigo-950/70 px-2 py-1 rounded-lg">
                      Conversational
                    </span>
                  </div>
                  <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-100 dark:border-slate-700 flex items-center justify-between text-xs">
                    <div>
                      <div className="font-bold text-slate-900 dark:text-white">Constructive Feedback</div>
                      <div className="text-slate-500 dark:text-slate-400">Objective score breakdown</div>
                    </div>
                    <span className="text-blue-600 dark:text-blue-400 font-bold bg-blue-50 dark:bg-blue-950/70 px-2 py-1 rounded-lg">
                      Transparent
                    </span>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

      </div>
    </section>
  );
}

