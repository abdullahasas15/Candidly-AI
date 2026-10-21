import React, { useState } from 'react';
import { Users, Briefcase, Check, ArrowRight, Video, FileText, Clock, Sparkles } from 'lucide-react';

export default function PersonaTabs({ onRequestDemo, onOpenAuth }) {
  const [activeTab, setActiveTab] = useState('recruiters');

  return (
    <section id="personas" className="py-20 md:py-28 bg-black border-b border-white/[0.08] scroll-mt-20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        
        {/* Section Header */}
        <div className="text-center max-w-3xl mx-auto space-y-4 mb-12">
          <h2 className="font-display text-4xl sm:text-5xl font-normal text-white tracking-tight">
            Built for both sides of the hiring table.
          </h2>
          <p className="text-base sm:text-lg text-zinc-300">
            A frictionless experience that empowers talent teams with rigorous hiring data while treating candidates with dignity, speed, and fairness.
          </p>

          {/* Tab Selector */}
          <div className="inline-flex p-1 rounded-xl bg-[#111113] border border-white/[0.08] mt-4">
            <button
              onClick={() => setActiveTab('recruiters')}
              className={`flex items-center gap-2 px-5 py-2 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                activeTab === 'recruiters'
                  ? 'bg-teal-500 text-black shadow-sm font-semibold'
                  : 'text-zinc-400 hover:text-white'
              }`}
            >
              <Briefcase className="w-3.5 h-3.5" />
              <span>For Talent Teams & Recruiters</span>
            </button>
            <button
              onClick={() => setActiveTab('candidates')}
              className={`flex items-center gap-2 px-5 py-2 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                activeTab === 'candidates'
                  ? 'bg-teal-500 text-black shadow-sm font-semibold'
                  : 'text-zinc-400 hover:text-white'
              }`}
            >
              <Users className="w-3.5 h-3.5" />
              <span>For Candidates & Engineers</span>
            </button>
          </div>
        </div>

        {/* Tab Content Display */}
        <div className="rounded-2xl bg-[#0A0A0B] border border-white/[0.08] p-8 sm:p-12 transition-all">
          {activeTab === 'recruiters' ? (
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-10 items-center">
              <div className="lg:col-span-7 space-y-6">
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-teal-500/10 border border-teal-500/20 text-xs font-mono text-teal-300">
                  <Briefcase className="w-3.5 h-3.5" />
                  <span>Pipeline Velocity</span>
                </div>
                <h3 className="text-2xl sm:text-3xl font-display font-bold text-white tracking-tight">
                  Screen top engineering talent in hours, not weeks.
                </h3>
                <p className="text-sm sm:text-base text-zinc-300 leading-relaxed">
                  Eliminate scheduling bottlenecks and inconsistent interview notes. Talent acquisition and engineering leaders define their role rubrics once, and Candidly autonomously conducts high-signal voice dialogues, delivering structured scorecards directly into your workflow.
                </p>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
                  <div className="flex items-start gap-2.5 text-xs text-zinc-300">
                    <Check className="w-4 h-4 text-teal-400 mt-0.5 shrink-0" />
                    <span>Calibrated 5-tier rubrics per competency</span>
                  </div>
                  <div className="flex items-start gap-2.5 text-xs text-zinc-300">
                    <Check className="w-4 h-4 text-teal-400 mt-0.5 shrink-0" />
                    <span>Audio & transcript evidence replay</span>
                  </div>
                  <div className="flex items-start gap-2.5 text-xs text-zinc-300">
                    <Check className="w-4 h-4 text-teal-400 mt-0.5 shrink-0" />
                    <span>100% auditable evidence citations</span>
                  </div>
                  <div className="flex items-start gap-2.5 text-xs text-zinc-300">
                    <Check className="w-4 h-4 text-teal-400 mt-0.5 shrink-0" />
                    <span>Direct candidate dossier & decisions</span>
                  </div>
                </div>

                <div className="pt-2">
                  <button
                    onClick={onRequestDemo}
                    className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-xs font-semibold text-black bg-teal-500 hover:bg-teal-400 transition-all cursor-pointer"
                  >
                    <span>Schedule Talent Team Walkthrough</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              <div className="lg:col-span-5 bg-[#111113] rounded-xl p-6 border border-white/[0.08] shadow-lg space-y-4">
                <div className="text-xs font-mono uppercase tracking-wider text-zinc-400">
                  Recruiter Highlights
                </div>
                <div className="space-y-3">
                  <div className="p-3 rounded-lg bg-black/40 border border-white/[0.06] flex items-center justify-between text-xs">
                    <div>
                      <div className="font-semibold text-white">Active Requisitions</div>
                      <div className="text-[11px] text-zinc-500">Autonomous interviewing live</div>
                    </div>
                    <span className="font-mono text-teal-400 font-bold">12 Roles</span>
                  </div>

                  <div className="p-3 rounded-lg bg-black/40 border border-white/[0.06] flex items-center justify-between text-xs">
                    <div>
                      <div className="font-semibold text-white">Completed Scorecards</div>
                      <div className="text-[11px] text-zinc-500">Average evaluation turnaround</div>
                    </div>
                    <span className="font-mono text-teal-400 font-bold">&lt; 3 mins</span>
                  </div>

                  <div className="p-3 rounded-lg bg-black/40 border border-white/[0.06] flex items-center justify-between text-xs">
                    <div>
                      <div className="font-semibold text-white">Engineering Hours Saved</div>
                      <div className="text-[11px] text-zinc-500">Screening load reclaimed</div>
                    </div>
                    <span className="font-mono text-teal-400 font-bold">140+ hrs/mo</span>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-10 items-center">
              <div className="lg:col-span-7 space-y-6">
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-teal-500/10 border border-teal-500/20 text-xs font-mono text-teal-300">
                  <Users className="w-3.5 h-3.5" />
                  <span>Candidate-First Experience</span>
                </div>
                <h3 className="text-2xl sm:text-3xl font-display font-bold text-white tracking-tight">
                  Interview on your schedule, judged solely on merit.
                </h3>
                <p className="text-sm sm:text-base text-zinc-300 leading-relaxed">
                  No scheduling delays or recruiter ghosting. Test your real-world systems thinking and problem-solving depth in a voice-first conversation tailored to your background. Receive constructive reflections upon completion.
                </p>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
                  <div className="flex items-start gap-2.5 text-xs text-zinc-300">
                    <Check className="w-4 h-4 text-teal-400 mt-0.5 shrink-0" />
                    <span>24/7 on-demand interview availability</span>
                  </div>
                  <div className="flex items-start gap-2.5 text-xs text-zinc-300">
                    <Check className="w-4 h-4 text-teal-400 mt-0.5 shrink-0" />
                    <span>Zero trick algorithmic leetcode questions</span>
                  </div>
                  <div className="flex items-start gap-2.5 text-xs text-zinc-300">
                    <Check className="w-4 h-4 text-teal-400 mt-0.5 shrink-0" />
                    <span>Fast-track response to hiring team</span>
                  </div>
                  <div className="flex items-start gap-2.5 text-xs text-zinc-300">
                    <Check className="w-4 h-4 text-teal-400 mt-0.5 shrink-0" />
                    <span>Practice warm-up sandbox included</span>
                  </div>
                </div>

                <div className="pt-2">
                  <button
                    onClick={() => onOpenAuth('signup', 'candidate')}
                    className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-xs font-semibold text-black bg-teal-500 hover:bg-teal-400 transition-all cursor-pointer"
                  >
                    <span>Create Candidate Account</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              <div className="lg:col-span-5 bg-[#111113] rounded-xl p-6 border border-white/[0.08] shadow-lg space-y-4">
                <div className="text-xs font-mono uppercase tracking-wider text-zinc-400">
                  Candidate Experience Pillars
                </div>
                <div className="space-y-3">
                  <div className="p-3 rounded-lg bg-black/40 border border-white/[0.06] flex items-center justify-between text-xs">
                    <div>
                      <div className="font-semibold text-white">Voice-First Conversation</div>
                      <div className="text-[11px] text-zinc-500">Natural conversational pacing</div>
                    </div>
                    <span className="font-mono text-teal-400 font-bold">&lt; 300ms</span>
                  </div>

                  <div className="p-3 rounded-lg bg-black/40 border border-white/[0.06] flex items-center justify-between text-xs">
                    <div>
                      <div className="font-semibold text-white">Objective Grading</div>
                      <div className="text-[11px] text-zinc-500">Uniform criteria across all candidates</div>
                    </div>
                    <span className="font-mono text-teal-400 font-bold">100% Fair</span>
                  </div>

                  <div className="p-3 rounded-lg bg-black/40 border border-white/[0.06] flex items-center justify-between text-xs">
                    <div>
                      <div className="font-semibold text-white">Constructive Feedback</div>
                      <div className="text-[11px] text-zinc-500">Key competency reflection report</div>
                    </div>
                    <span className="font-mono text-teal-400 font-bold">Guaranteed</span>
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
