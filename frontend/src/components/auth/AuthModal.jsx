import React, { useState, useEffect } from 'react';
import {
  X, Mail, Lock, User, Building, Briefcase, ArrowRight, CheckCircle2,
  AlertCircle, Eye, EyeOff, Loader2
} from 'lucide-react';
import Logo from '../Logo';

export default function AuthModal({
  isOpen,
  onClose,
  initialMode = 'signin', // 'signin' | 'signup'
  initialRole = 'candidate', // 'candidate' | 'recruiter'
  onSuccess
}) {
  const [mode, setMode] = useState(initialMode);
  const [role, setRole] = useState(initialRole);

  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [companyName, setCompanyName] = useState('');
  const [headline, setHeadline] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (isOpen) {
      setMode(initialMode);
      setRole(initialRole);
      setError(null);
      setFullName('');
      setEmail('');
      setPassword('');
      setCompanyName('');
      setHeadline('');
    }
  }, [isOpen, initialMode, initialRole]);

  if (!isOpen) return null;

  const handleRoleChange = (newRole) => {
    setRole(newRole);
    setError(null);
  };

  const handleAuthComplete = (authResponse) => {
    if (authResponse.access_token) {
      localStorage.setItem('candidly-auth-token', authResponse.access_token);
    }
    if (authResponse.user) {
      localStorage.setItem('candidly-auth-user', JSON.stringify(authResponse.user));
      onSuccess(authResponse.user);
    } else {
      localStorage.setItem('candidly-auth-user', JSON.stringify(authResponse));
      onSuccess(authResponse);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      if (mode === 'signin') {
        const res = await fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            email: email.trim(),
            password,
            role
          })
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || 'Sign in failed. Please check your credentials.');
        }
        handleAuthComplete(data);
      } else {
        // Sign Up Validation
        if (!fullName.trim()) {
          throw new Error('Please enter your full name.');
        }
        if (password.length < 8) {
          throw new Error('Password must be at least 8 characters long.');
        }
        if (role === 'recruiter' && !companyName.trim()) {
          throw new Error('Company name is required for recruiter registration.');
        }

        const payload = {
          email: email.trim(),
          password,
          full_name: fullName.trim(),
          role,
          company_name: role === 'recruiter' ? companyName.trim() : null,
          headline: role === 'candidate' ? headline.trim() : null
        };

        const res = await fetch('/api/auth/signup', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || 'Registration failed. Please check your details and try again.');
        }
        handleAuthComplete(data);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-950/80 backdrop-blur-md flex items-center justify-center p-4 sm:p-6 animate-in fade-in duration-200">
      <div
        className="relative w-full max-w-md bg-white dark:bg-[#0E1322] rounded-3xl shadow-2xl border border-slate-200/80 dark:border-slate-800 overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header Bar */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 dark:border-slate-800/80 bg-slate-50/50 dark:bg-slate-900/40">
          <div className="flex items-center gap-2.5">
            <Logo size={28} className="w-7 h-7" />
            <span className="font-extrabold text-base tracking-tight text-slate-900 dark:text-white">
              Candidly<span className="text-indigo-600 dark:text-indigo-400">.AI</span>
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-xl text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 sm:p-8 space-y-5">
          {/* Header Title & Switcher */}
          <div className="space-y-3 text-center">
            <div>
              <h2 className="text-2xl font-black text-slate-900 dark:text-white tracking-tight">
                {mode === 'signin' ? 'Welcome Back' : 'Create an Account'}
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                {mode === 'signin'
                  ? 'Sign in to access your jobs, evaluations, and interview sessions.'
                  : 'Get started with autonomous evidence-based voice interviews.'}
              </p>
            </div>

            {/* Mode Switcher Tabs (Sign In vs Create Account) */}
            <div className="inline-flex p-1 bg-slate-100 dark:bg-slate-800/90 rounded-2xl w-full max-w-xs mx-auto">
              <button
                type="button"
                onClick={() => { setMode('signin'); setError(null); }}
                className={`flex-1 py-1.5 text-xs font-bold rounded-xl transition-all ${
                  mode === 'signin'
                    ? 'bg-white dark:bg-slate-900 text-indigo-600 dark:text-indigo-400 shadow-sm'
                    : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
                }`}
              >
                Sign In
              </button>
              <button
                type="button"
                onClick={() => { setMode('signup'); setError(null); }}
                className={`flex-1 py-1.5 text-xs font-bold rounded-xl transition-all ${
                  mode === 'signup'
                    ? 'bg-white dark:bg-slate-900 text-indigo-600 dark:text-indigo-400 shadow-sm'
                    : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
                }`}
              >
                Create Account
              </button>
            </div>
          </div>

          {/* Choosable Role Selector (Candidate vs Recruiter) */}
          <div className="space-y-1.5">
            <label className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
              Account Role
            </label>
            <div className="grid grid-cols-2 gap-2.5">
              {/* Candidate Option */}
              <button
                type="button"
                onClick={() => handleRoleChange('candidate')}
                className={`p-3 rounded-2xl border text-left transition-all relative flex flex-col justify-between ${
                  role === 'candidate'
                    ? 'border-indigo-600 bg-indigo-50/70 dark:bg-indigo-950/40 text-indigo-950 dark:text-indigo-100 ring-2 ring-indigo-500/30 shadow-sm'
                    : 'border-slate-200 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700 bg-white dark:bg-slate-900/60 text-slate-600 dark:text-slate-300'
                }`}
              >
                <div className="flex items-center justify-between w-full">
                  <div className={`p-2 rounded-xl ${role === 'candidate' ? 'bg-indigo-600 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-500'}`}>
                    <Briefcase className="w-4 h-4" />
                  </div>
                  {role === 'candidate' && (
                    <span className="w-4 h-4 rounded-full bg-indigo-600 text-white flex items-center justify-center">
                      <CheckCircle2 className="w-3 h-3" />
                    </span>
                  )}
                </div>
                <div className="mt-2">
                  <div className="font-extrabold text-xs">Candidate</div>
                  <div className="text-[10px] text-slate-500 dark:text-slate-400">Interview & Apply</div>
                </div>
              </button>

              {/* Recruiter Option */}
              <button
                type="button"
                onClick={() => handleRoleChange('recruiter')}
                className={`p-3 rounded-2xl border text-left transition-all relative flex flex-col justify-between ${
                  role === 'recruiter'
                    ? 'border-indigo-600 bg-indigo-50/70 dark:bg-indigo-950/40 text-indigo-950 dark:text-indigo-100 ring-2 ring-indigo-500/30 shadow-sm'
                    : 'border-slate-200 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700 bg-white dark:bg-slate-900/60 text-slate-600 dark:text-slate-300'
                }`}
              >
                <div className="flex items-center justify-between w-full">
                  <div className={`p-2 rounded-xl ${role === 'recruiter' ? 'bg-indigo-600 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-500'}`}>
                    <Building className="w-4 h-4" />
                  </div>
                  {role === 'recruiter' && (
                    <span className="w-4 h-4 rounded-full bg-indigo-600 text-white flex items-center justify-center">
                      <CheckCircle2 className="w-3 h-3" />
                    </span>
                  )}
                </div>
                <div className="mt-2">
                  <div className="font-extrabold text-xs">Recruiter / Team</div>
                  <div className="text-[10px] text-slate-500 dark:text-slate-400">Post Jobs & Evaluate</div>
                </div>
              </button>
            </div>
          </div>

          {/* Error Message */}
          {error && (
            <div className="p-3 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900 text-rose-700 dark:text-rose-300 text-xs flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span className="flex-1">{error}</span>
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-3.5">
            {mode === 'signup' && (
              <div className="space-y-1">
                <label className="text-[11px] font-bold text-slate-700 dark:text-slate-300">
                  Full Name <span className="text-rose-500">*</span>
                </label>
                <div className="relative">
                  <User className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
                  <input
                    type="text"
                    required
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    placeholder="e.g. Alex Mercer"
                    className="w-full pl-9 pr-3 py-2 bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl text-xs sm:text-sm text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
              </div>
            )}

            {mode === 'signup' && role === 'recruiter' && (
              <div className="space-y-1">
                <label className="text-[11px] font-bold text-slate-700 dark:text-slate-300">
                  Company / Organization <span className="text-rose-500">*</span>
                </label>
                <div className="relative">
                  <Building className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
                  <input
                    type="text"
                    required
                    value={companyName}
                    onChange={(e) => setCompanyName(e.target.value)}
                    placeholder="e.g. Stripe, OpenAI, Nexus Labs"
                    className="w-full pl-9 pr-3 py-2 bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl text-xs sm:text-sm text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
              </div>
            )}

            {mode === 'signup' && role === 'candidate' && (
              <div className="space-y-1">
                <label className="text-[11px] font-bold text-slate-700 dark:text-slate-300">
                  Headline / Professional Role (Optional)
                </label>
                <div className="relative">
                  <Briefcase className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
                  <input
                    type="text"
                    value={headline}
                    onChange={(e) => setHeadline(e.target.value)}
                    placeholder="e.g. Senior Distributed Systems Engineer"
                    className="w-full pl-9 pr-3 py-2 bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl text-xs sm:text-sm text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
              </div>
            )}

            <div className="space-y-1">
              <label className="text-[11px] font-bold text-slate-700 dark:text-slate-300">
                Email Address <span className="text-rose-500">*</span>
              </label>
              <div className="relative">
                <Mail className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="your.email@domain.com"
                  className="w-full pl-9 pr-3 py-2 bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl text-xs sm:text-sm text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>
            </div>

            <div className="space-y-1">
              <label className="text-[11px] font-bold text-slate-700 dark:text-slate-300">
                Password <span className="text-rose-500">*</span> {mode === 'signup' && <span className="text-[10px] text-slate-400">(min. 8 characters)</span>}
              </label>
              <div className="relative">
                <Lock className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
                <input
                  type={showPassword ? 'text' : 'password'}
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full pl-9 pr-9 py-2 bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl text-xs sm:text-sm text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-2.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full mt-3 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-xs sm:text-sm shadow-md shadow-indigo-600/30 hover:shadow-indigo-600/40 hover:-translate-y-0.5 transition-all flex items-center justify-center gap-2 disabled:opacity-50"
            >
              {loading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <>
                  <span>
                    {mode === 'signin'
                      ? `Sign In as ${role === 'recruiter' ? 'Recruiter' : 'Candidate'}`
                      : `Create ${role === 'recruiter' ? 'Recruiter' : 'Candidate'} Account`}
                  </span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </form>

          {/* Footer toggle */}
          <div className="text-center pt-2 border-t border-slate-100 dark:border-slate-800/80">
            {mode === 'signin' ? (
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Don't have an account yet?{' '}
                <button
                  type="button"
                  onClick={() => { setMode('signup'); setError(null); }}
                  className="font-bold text-indigo-600 dark:text-indigo-400 hover:underline"
                >
                  Create one now
                </button>
              </p>
            ) : (
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Already have an account?{' '}
                <button
                  type="button"
                  onClick={() => { setMode('signin'); setError(null); }}
                  className="font-bold text-indigo-600 dark:text-indigo-400 hover:underline"
                >
                  Sign in
                </button>
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
