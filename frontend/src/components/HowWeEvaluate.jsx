import React, { useState } from 'react';
import { Layers, Quote, CheckCircle2, ChevronRight, BarChart3, Award, FileText, ChevronDown } from 'lucide-react';

export default function HowWeEvaluate() {
  const [activeCompetency, setActiveCompetency] = useState(0);

  const steps = [
    {
      num: '01',
      title: 'Contextual Calibration',
      desc: 'Competencies, role seniority, and behavioral anchors (L1 to L5) are defined before any candidate call begins.',
    },
    {
      num: '02',
      title: 'Adaptive Voice Dialogue',
      desc: 'Live conversational probing tests depth, explores trade-offs, and validates hands-on execution claims.',
    },
    {
      num: '03',
      title: 'Verbatim Evidence Audit',
      desc: 'Every score is linked to exact timestamped quotes, creating a completely transparent, auditable report.',
    },
  ];

  const scorecardData = [
    {
      skill: 'System Design & Scalability',
      weight: '35%',
      score: 4.2,
      tier: 'L4 · Advanced',
      evidenceQuote:
        '“We used Redis with LRU cache eviction and set TTL to 3600 seconds with mutex locking on cache misses to prevent thundering herd under 50k RPS.”',
      timestamp: 'Turn 4 · 06:12',
      strengths: ['Identified read scalability constraints', 'Proactively mitigated cache stampedes'],
      areasForGrowth: ['Could have elaborated on automated failover mechanics for the primary storage cluster'],
    },
    {
      skill: 'Data Consistency & Storage',
      weight: '30%',
      score: 4.0,
      tier: 'L4 · Advanced',
      evidenceQuote:
        '“We opted for an append-only event ledger with idempotent consumers to guarantee eventual consistency across microservice boundaries.”',
      timestamp: 'Turn 6 · 11:45',
      strengths: ['Clear grasp of idempotent design', 'Understood distributed transaction trade-offs'],
      areasForGrowth: ['Could have discussed dead-letter queue retry policies'],
    },
    {
      skill: 'Architectural Trade-Offs',
      weight: '20%',
      score: 3.5,
      tier: 'L3 · Proficient',
      evidenceQuote:
        '“We balanced immediate developer velocity against long-term maintenance by isolating shared libraries into versioned packages.”',
      timestamp: 'Turn 8 · 16:20',
      strengths: ['Realistic assessment of engineering overhead', 'Solid justification of modular boundaries'],
      areasForGrowth: ['Deeper analysis of backward-compatibility deprecation windows'],
    },
    {
      skill: 'Structured Communication',
      weight: '15%',
      score: 4.5,
      tier: 'L5 · Expert',
      evidenceQuote:
        '“Let me break this down into three parts: data ingestion, persistence, and client fan-out to ensure clarity.”',
      timestamp: 'Turn 2 · 02:40',
      strengths: ['Top-down structured thinking', 'Clear, concise technical cadence without rambling'],
      areasForGrowth: ['Maintained consistent pacing throughout'],
    },
  ];

  return (
    <section id="how-we-evaluate" className="py-20 md:py-28 relative scroll-mt-20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        
        {/* Section Header */}
        <div className="text-center max-w-3xl mx-auto space-y-4 mb-16">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-indigo-50 dark:bg-indigo-950/50 border border-indigo-200 dark:border-indigo-800 text-xs font-semibold text-indigo-700 dark:text-indigo-300">
            <Award className="w-3.5 h-3.5" />
            <span>The Evaluation Standard</span>
          </div>
          <h2 className="text-3xl sm:text-4xl font-extrabold text-slate-900 dark:text-white tracking-tight">
            Transparent scorecards, not black-box scores.
          </h2>
          <p className="text-base sm:text-lg text-slate-600 dark:text-slate-300">
            Every grade is defended by verbatim evidence from the interview. Hiring managers get actionable clarity without having to re-watch hours of video.
          </p>
        </div>

        {/* 3-Step Flow Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-16">
          {steps.map((step, sIdx) => (
            <div
              key={sIdx}
              className="p-6 rounded-2xl bg-white dark:bg-[#111827] border border-slate-200 dark:border-slate-800 relative shadow-sm hover:border-indigo-400 dark:hover:border-indigo-500/60 transition-all"
            >
              <div className="text-3xl font-black text-indigo-600/20 dark:text-indigo-400/20 mb-3 font-mono">
                {step.num}
              </div>
              <h3 className="text-lg font-bold text-slate-900 dark:text-white mb-2">
                {step.title}
              </h3>
              <p className="text-sm text-slate-600 dark:text-slate-300 leading-relaxed">
                {step.desc}
              </p>
            </div>
          ))}
        </div>

        {/* Interactive Scorecard Showcase */}
        <div className="rounded-2xl bg-white dark:bg-[#111827] border border-slate-200 dark:border-slate-800 shadow-xl overflow-hidden">
          
          {/* Scorecard Header Bar */}
          <div className="px-6 py-4 bg-slate-50 dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-xl bg-indigo-50 dark:bg-indigo-950 text-indigo-600 dark:text-indigo-400">
                <FileText className="w-5 h-5" />
              </div>
              <div>
                <div className="text-sm font-bold text-slate-900 dark:text-white flex items-center gap-2">
                  <span>Candidate Evaluation Record</span>
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-950/80 text-emerald-700 dark:text-emerald-300 font-semibold">
                    Verdict: Strong Hire (84/100)
                  </span>
                </div>
                <div className="text-xs text-slate-500 dark:text-slate-400">
                  Role: Senior Distributed Systems Engineer · Duration: 21m 15s
                </div>
              </div>
            </div>

            <div className="flex items-center gap-4 text-xs">
              <div className="text-right">
                <div className="text-slate-500 dark:text-slate-400">Overall Fit Score</div>
                <div className="text-lg font-bold text-indigo-600 dark:text-indigo-400">84.0 / 100</div>
              </div>
            </div>
          </div>

          {/* Interactive Skill Selector Tabs */}
          <div className="grid grid-cols-2 lg:grid-cols-4 border-b border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/30">
            {scorecardData.map((item, idx) => (
              <button
                key={idx}
                onClick={() => setActiveCompetency(idx)}
                className={`p-4 text-left transition-all border-r last:border-r-0 border-slate-200 dark:border-slate-800 ${
                  activeCompetency === idx
                    ? 'bg-white dark:bg-[#111827] border-b-2 border-b-indigo-600 dark:border-b-indigo-400'
                    : 'hover:bg-slate-100/60 dark:hover:bg-slate-800/40 opacity-70'
                }`}
              >
                <div className="text-xs font-semibold text-slate-500 dark:text-slate-400 flex items-center justify-between mb-1">
                  <span>Weight: {item.weight}</span>
                  <span className="font-bold text-indigo-600 dark:text-indigo-400">{item.score}/5.0</span>
                </div>
                <div className="text-xs sm:text-sm font-bold text-slate-900 dark:text-white truncate">
                  {item.skill}
                </div>
                <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-1">
                  {item.tier}
                </div>
              </button>
            ))}
          </div>

          {/* Active Competency Evidence Breakdown */}
          <div className="p-6 md:p-8 space-y-6">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-slate-100 dark:border-slate-800">
              <div>
                <h4 className="text-xl font-bold text-slate-900 dark:text-white">
                  {scorecardData[activeCompetency].skill}
                </h4>
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                  Assigned Rubric Tier: <strong className="text-indigo-600 dark:text-indigo-400">{scorecardData[activeCompetency].tier}</strong> · Weight Contribution: {scorecardData[activeCompetency].weight}
                </p>
              </div>

              {/* Score Bar visual */}
              <div className="w-full md:w-56 space-y-1.5">
                <div className="flex justify-between text-xs font-semibold">
                  <span className="text-slate-600 dark:text-slate-400">Calibrated Grade</span>
                  <span className="text-slate-900 dark:text-white">{scorecardData[activeCompetency].score} / 5.0</span>
                </div>
                <div className="h-2.5 w-full bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-indigo-600 to-indigo-400 rounded-full transition-all duration-500"
                    style={{ width: `${(scorecardData[activeCompetency].score / 5.0) * 100}%` }}
                  />
                </div>
              </div>
            </div>

            {/* Verbatim Evidence Quote Callout */}
            <div className="p-5 rounded-xl bg-indigo-50/60 dark:bg-indigo-950/30 border border-indigo-100 dark:border-indigo-900/60 space-y-2">
              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-1.5 font-bold text-indigo-700 dark:text-indigo-300">
                  <Quote className="w-3.5 h-3.5" />
                  <span>Verbatim Spoken Evidence</span>
                </div>
                <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-300 border border-indigo-100 dark:border-indigo-900">
                  {scorecardData[activeCompetency].timestamp}
                </span>
              </div>
              <p className="text-sm md:text-base italic text-slate-800 dark:text-slate-200 font-normal leading-relaxed">
                {scorecardData[activeCompetency].evidenceQuote}
              </p>
            </div>

            {/* Strengths & Observations */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-2">
              <div>
                <h5 className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-3 flex items-center gap-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
                  <span>Demonstrated Strengths</span>
                </h5>
                <ul className="space-y-2">
                  {scorecardData[activeCompetency].strengths.map((str, idx) => (
                    <li key={idx} className="text-xs text-slate-700 dark:text-slate-300 flex items-start gap-2">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 mt-1.5 flex-shrink-0" />
                      <span>{str}</span>
                    </li>
                  ))}
                </ul>
              </div>

              <div>
                <h5 className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-3 flex items-center gap-1.5">
                  <ChevronRight className="w-3.5 h-3.5 text-indigo-500" />
                  <span>Target Growth & Next Steps</span>
                </h5>
                <ul className="space-y-2">
                  {scorecardData[activeCompetency].areasForGrowth.map((area, idx) => (
                    <li key={idx} className="text-xs text-slate-700 dark:text-slate-300 flex items-start gap-2">
                      <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 mt-1.5 flex-shrink-0" />
                      <span>{area}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>

          </div>

        </div>

      </div>
    </section>
  );
}

