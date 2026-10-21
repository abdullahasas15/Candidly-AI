import React, { useState } from 'react';
import { X, CheckCircle2, ArrowRight, ShieldCheck, Mail, Building, User, Sparkles } from 'lucide-react';

export default function DemoModal({ isOpen, onClose }) {
  const [submitted, setSubmitted] = useState(false);
  const [formData, setFormData] = useState({
    name: '',
    workEmail: '',
    company: '',
    roleVolume: '50-200 interviews/month',
  });

  if (!isOpen) return null;

  const handleSubmit = (e) => {
    e.preventDefault();
    setSubmitted(true);
  };

  const handleReset = () => {
    setSubmitted(false);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 bg-black/80 backdrop-blur-sm animate-fadeIn">
      <div className="relative w-full max-w-lg rounded-2xl bg-[#0A0A0B] border border-white/[0.08] shadow-2xl overflow-hidden p-6 sm:p-8">
        
        {/* Close button */}
        <button
          onClick={onClose}
          className="absolute top-5 right-5 p-1.5 rounded-lg text-zinc-400 hover:text-white bg-white/[0.05] border border-white/[0.06] transition-colors"
        >
          <X className="w-5 h-5" />
        </button>

        {submitted ? (
          <div className="text-center py-8 space-y-4">
            <div className="w-16 h-16 rounded-2xl bg-teal-500/10 border border-teal-500/20 text-teal-400 flex items-center justify-center mx-auto">
              <CheckCircle2 className="w-8 h-8" />
            </div>
            <h3 className="text-2xl font-display font-bold text-white">
              Walkthrough Requested
            </h3>
            <p className="text-sm text-zinc-300 max-w-sm mx-auto leading-relaxed">
              Thank you, {formData.name || 'there'}. An enterprise onboarding specialist will prepare a customized rubric demonstration for {formData.company || 'your team'} within 2 business hours.
            </p>
            <div className="pt-4">
              <button
                onClick={handleReset}
                className="px-6 py-2.5 rounded-lg font-semibold text-xs text-black bg-teal-500 hover:bg-teal-400 transition-colors"
              >
                Return to Overview
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-6">
            <div>
              <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-white/[0.05] border border-white/[0.08] text-xs font-mono text-teal-400 mb-3">
                <Sparkles className="w-3.5 h-3.5" />
                <span>Enterprise Platform Access</span>
              </div>
              <h3 className="text-2xl font-bold font-display text-white tracking-tight">
                Request an Enterprise Demo
              </h3>
              <p className="text-xs sm:text-sm text-zinc-400 mt-1">
                Experience a live autonomous voice interview calibrated to your exact engineering requirements.
              </p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-zinc-300 mb-1">
                  Full Name
                </label>
                <div className="relative">
                  <User className="w-4 h-4 text-zinc-500 absolute left-3.5 top-3" />
                  <input
                    type="text"
                    required
                    placeholder="Jane Doe"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    className="w-full pl-10 pr-4 py-2.5 rounded-lg border border-white/[0.12] bg-[#111113] text-white text-xs placeholder:text-zinc-500 focus:outline-none focus:border-teal-400"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-zinc-300 mb-1">
                  Work Email
                </label>
                <div className="relative">
                  <Mail className="w-4 h-4 text-zinc-500 absolute left-3.5 top-3" />
                  <input
                    type="email"
                    required
                    placeholder="jane@company.com"
                    value={formData.workEmail}
                    onChange={(e) => setFormData({ ...formData, workEmail: e.target.value })}
                    className="w-full pl-10 pr-4 py-2.5 rounded-lg border border-white/[0.12] bg-[#111113] text-white text-xs placeholder:text-zinc-500 focus:outline-none focus:border-teal-400"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-zinc-300 mb-1">
                  Company Name
                </label>
                <div className="relative">
                  <Building className="w-4 h-4 text-zinc-500 absolute left-3.5 top-3" />
                  <input
                    type="text"
                    required
                    placeholder="Acme Systems, Inc."
                    value={formData.company}
                    onChange={(e) => setFormData({ ...formData, company: e.target.value })}
                    className="w-full pl-10 pr-4 py-2.5 rounded-lg border border-white/[0.12] bg-[#111113] text-white text-xs placeholder:text-zinc-500 focus:outline-none focus:border-teal-400"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-zinc-300 mb-1">
                  Estimated Monthly Technical Interview Volume
                </label>
                <select
                  value={formData.roleVolume}
                  onChange={(e) => setFormData({ ...formData, roleVolume: e.target.value })}
                  className="w-full px-3.5 py-2.5 rounded-lg border border-white/[0.12] bg-[#111113] text-white text-xs focus:outline-none focus:border-teal-400"
                >
                  <option value="10-50">10 – 50 interviews / month</option>
                  <option value="50-200">50 – 200 interviews / month</option>
                  <option value="200-500">200 – 500 interviews / month</option>
                  <option value="500+">500+ interviews / month (High Scale)</option>
                </select>
              </div>

              <div className="pt-2">
                <button
                  type="submit"
                  className="w-full py-3 rounded-lg font-semibold text-xs text-black bg-teal-500 hover:bg-teal-400 transition-colors flex items-center justify-center gap-2 cursor-pointer shadow-lg shadow-teal-500/20"
                >
                  <span>Submit Demo Request</span>
                  <ArrowRight className="w-4 h-4" />
                </button>
              </div>

              <p className="text-[11px] text-center text-zinc-500">
                Zero spam. An engineer will tailor a demo blueprint to your stack.
              </p>
            </form>
          </div>
        )}

      </div>
    </div>
  );
}
