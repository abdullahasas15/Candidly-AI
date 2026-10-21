import React from 'react';
import { ShieldCheck } from 'lucide-react';
import Logo from './Logo';

export default function Footer({ onRequestDemo }) {
  return (
    <footer className="bg-black border-t border-white/[0.08] pt-16 pb-12 transition-colors">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 space-y-12">
        
        {/* Top bar: Brand + Links */}
        <div className="grid grid-cols-1 md:grid-cols-12 gap-8 items-start">
          
          {/* Brand Info */}
          <div className="md:col-span-5 space-y-4">
            <div className="flex items-center gap-2.5">
              <Logo size={28} className="w-7 h-7" />
              <span className="font-bold text-lg text-white">
                Candidly<span className="text-teal-400">.AI</span>
              </span>
            </div>

            <p className="text-xs text-zinc-400 max-w-sm leading-relaxed">
              An AI-led interview experience that evaluates candidates the way a great human interviewer would — fair, consistent, and evidence-backed — with continuous integrity verification built in.
            </p>

            <div className="flex items-center gap-2 text-xs text-teal-400 font-mono">
              <span className="w-2 h-2 rounded-full bg-teal-400 animate-pulse" />
              <span>All Evaluation Engines Operational</span>
            </div>
          </div>

          {/* Navigation Links */}
          <div className="md:col-span-7 grid grid-cols-2 sm:grid-cols-3 gap-6 text-xs">
            <div>
              <div className="font-mono uppercase tracking-wider text-zinc-300 text-[11px] mb-3">
                Platform
              </div>
              <ul className="space-y-2 text-zinc-400">
                <li><a href="#what-we-offer" className="hover:text-teal-400 transition-colors">Adaptive Voice Dialogue</a></li>
                <li><a href="#how-we-evaluate" className="hover:text-teal-400 transition-colors">Calibrated Rubrics</a></li>
                <li><a href="#proctoring" className="hover:text-teal-400 transition-colors">Session Integrity</a></li>
                <li><a href="#how-we-evaluate" className="hover:text-teal-400 transition-colors">Evidence Citations</a></li>
              </ul>
            </div>

            <div>
              <div className="font-mono uppercase tracking-wider text-zinc-300 text-[11px] mb-3">
                Solutions
              </div>
              <ul className="space-y-2 text-zinc-400">
                <li><a href="#personas" className="hover:text-teal-400 transition-colors">For Talent Leaders</a></li>
                <li><a href="#personas" className="hover:text-teal-400 transition-colors">For Engineering Leads</a></li>
                <li><a href="#personas" className="hover:text-teal-400 transition-colors">For Candidates</a></li>
                <li><button onClick={onRequestDemo} className="hover:text-teal-400 transition-colors cursor-pointer">Request Sandbox</button></li>
              </ul>
            </div>

            <div>
              <div className="font-mono uppercase tracking-wider text-zinc-300 text-[11px] mb-3">
                Compliance & Trust
              </div>
              <ul className="space-y-2 text-zinc-400">
                <li><a href="#" className="hover:text-teal-400 transition-colors">Merit & Privacy Standards</a></li>
                <li><a href="#" className="hover:text-teal-400 transition-colors">Security Practices</a></li>
                <li><a href="#" className="hover:text-teal-400 transition-colors">Candidate Dignity Charter</a></li>
                <li><a href="#" className="hover:text-teal-400 transition-colors">Terms & Conditions</a></li>
              </ul>
            </div>
          </div>

        </div>

        {/* Bottom bar: Copyright */}
        <div className="pt-8 border-t border-white/[0.06] flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-zinc-500">
          <div>
            &copy; {new Date().getFullYear()} Candidly AI, Inc. All rights reserved.
          </div>
          <div className="flex items-center gap-1.5 font-mono text-[11px]">
            <span>Evidence-anchored hiring platform</span>
            <ShieldCheck className="w-3.5 h-3.5 text-teal-400" />
          </div>
        </div>

      </div>
    </footer>
  );
}
