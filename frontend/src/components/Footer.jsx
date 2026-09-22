import React from 'react';
import { ShieldCheck, Heart } from 'lucide-react';
import Logo from './Logo';

export default function Footer({ onRequestDemo }) {
  return (
    <footer className="bg-white dark:bg-[#070A12] border-t border-slate-200 dark:border-slate-800/80 pt-16 pb-12 transition-colors">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 space-y-12">
        
        {/* Top bar: Brand + Links */}
        <div className="grid grid-cols-1 md:grid-cols-12 gap-8 items-start">
          
          {/* Brand Info */}
          <div className="md:col-span-5 space-y-4">
            <div className="flex items-center gap-3">
              <Logo size={32} className="w-8 h-8" />
              <span className="font-extrabold text-lg text-slate-900 dark:text-white">
                Candidly<span className="text-indigo-600 dark:text-indigo-400">.AI</span>
              </span>
            </div>

            <p className="text-sm text-slate-600 dark:text-slate-400 max-w-sm leading-relaxed">
              An AI-led interview experience that evaluates candidates the way a great human interviewer would — fair, consistent, and evidence-backed — with continuous integrity verification built in.
            </p>

            <div className="flex items-center gap-2 text-xs text-emerald-600 dark:text-emerald-400 font-medium">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              <span>All Evaluation Engines Operational</span>
            </div>
          </div>

          {/* Navigation Links */}
          <div className="md:col-span-7 grid grid-cols-2 sm:grid-cols-3 gap-6 text-xs">
            <div>
              <div className="font-bold uppercase tracking-wider text-slate-900 dark:text-white mb-3">
                Platform
              </div>
              <ul className="space-y-2 text-slate-600 dark:text-slate-400">
                <li><a href="#what-we-offer" className="hover:text-indigo-600 dark:hover:text-indigo-400">Adaptive Voice Dialogue</a></li>
                <li><a href="#how-we-evaluate" className="hover:text-indigo-600 dark:hover:text-indigo-400">Calibrated Rubrics</a></li>
                <li><a href="#proctoring" className="hover:text-indigo-600 dark:hover:text-indigo-400">Session Integrity</a></li>
                <li><a href="#how-we-evaluate" className="hover:text-indigo-600 dark:hover:text-indigo-400">Evidence Citations</a></li>
              </ul>
            </div>

            <div>
              <div className="font-bold uppercase tracking-wider text-slate-900 dark:text-white mb-3">
                Solutions
              </div>
              <ul className="space-y-2 text-slate-600 dark:text-slate-400">
                <li><a href="#personas" className="hover:text-indigo-600 dark:hover:text-indigo-400">For Talent Leaders</a></li>
                <li><a href="#personas" className="hover:text-indigo-600 dark:hover:text-indigo-400">For Engineering Leads</a></li>
                <li><a href="#personas" className="hover:text-indigo-600 dark:hover:text-indigo-400">For Candidates</a></li>
                <li><button onClick={onRequestDemo} className="hover:text-indigo-600 dark:hover:text-indigo-400">Request Sandbox</button></li>
              </ul>
            </div>

            <div>
              <div className="font-bold uppercase tracking-wider text-slate-900 dark:text-white mb-3">
                Compliance & Trust
              </div>
              <ul className="space-y-2 text-slate-600 dark:text-slate-400">
                <li><a href="#" className="hover:text-indigo-600 dark:hover:text-indigo-400">Merit & Privacy Standards</a></li>
                <li><a href="#" className="hover:text-indigo-600 dark:hover:text-indigo-400">Security Practices</a></li>
                <li><a href="#" className="hover:text-indigo-600 dark:hover:text-indigo-400">Candidate Dignity Charter</a></li>
                <li><a href="#" className="hover:text-indigo-600 dark:hover:text-indigo-400">Terms & Conditions</a></li>
              </ul>
            </div>
          </div>

        </div>

        {/* Bottom bar: Copyright */}
        <div className="pt-8 border-t border-slate-100 dark:border-slate-800/80 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-slate-500 dark:text-slate-500">
          <div>
            &copy; {new Date().getFullYear()} Candidly AI, Inc. All rights reserved.
          </div>
          <div className="flex items-center gap-1">
            <span>Built for fair, evidence-backed hiring</span>
            <ShieldCheck className="w-3.5 h-3.5 text-indigo-500" />
          </div>
        </div>

      </div>
    </footer>
  );
}

