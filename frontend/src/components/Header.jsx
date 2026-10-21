import React, { useState, useEffect, useRef } from 'react';
import {
  Menu,
  X,
  ArrowRight,
  User,
  LogOut,
  Briefcase,
  Building,
  Settings,
  Sparkles,
  Plus,
  ChevronDown,
  Layers,
  FileText,
} from 'lucide-react';
import Logo from './Logo';

export default function Header({
  onRequestDemo,
  authUser,
  onOpenAuth,
  onOpenDashboard,
  onSignOut,
  onBackToLanding,
  currentView = 'landing', // 'landing' | 'recruiter' | 'candidate'
  activeNav = 'jobs',
  onNavChange,
  primaryAction,
}) {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [avatarMenuOpen, setAvatarMenuOpen] = useState(false);
  const avatarMenuRef = useRef(null);

  // Close avatar dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(e) {
      if (avatarMenuRef.current && !avatarMenuRef.current.contains(e.target)) {
        setAvatarMenuOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Landing page section links
  const landingNavLinks = [
    { name: 'Product', href: '#what-we-offer' },
    { name: 'How it works', href: '#how-we-evaluate' },
    { name: 'Integrity', href: '#proctoring' },
    { name: 'For Recruiters', href: '#personas' },
    { name: 'For Candidates', href: '#personas' },
  ];

  // Recruiter role nav: Jobs / Candidates / Settings
  const recruiterNavLinks = [
    { id: 'jobs', name: 'Jobs', icon: Briefcase },
    { id: 'candidates', name: 'Candidates', icon: User },
    { id: 'settings', name: 'Settings', icon: Settings },
  ];

  // Candidate role nav: Jobs / Applications / Profile
  const candidateNavLinks = [
    { id: 'jobs', name: 'Jobs', icon: Sparkles },
    { id: 'applications', name: 'Applications', icon: Layers },
    { id: 'profile', name: 'Profile', icon: User },
  ];

  const isRecruiter = currentView === 'recruiter' || authUser?.role === 'recruiter';
  const isCandidate = currentView === 'candidate' || authUser?.role === 'candidate';
  const isDashboard = currentView === 'recruiter' || currentView === 'candidate';

  const roleNavLinks = isRecruiter
    ? recruiterNavLinks
    : isCandidate
    ? candidateNavLinks
    : null;

  const getInitials = (name) => {
    if (!name) return 'U';
    return name
      .split(' ')
      .map((part) => part[0])
      .slice(0, 2)
      .join('')
      .toUpperCase();
  };

  return (
    <header className="sticky top-0 z-50 h-14 bg-black/90 backdrop-blur-md border-b border-white/[0.08] transition-all">
      <div className="max-w-7xl mx-auto h-full px-4 sm:px-6 lg:px-8 flex items-center justify-between gap-4">
        
        {/* Left: Logo & Wordmark */}
        <div className="flex items-center gap-3 shrink-0">
          <button
            type="button"
            onClick={() => {
              if (onBackToLanding) onBackToLanding();
              else if (typeof window !== 'undefined') window.location.href = '/';
            }}
            className="flex items-center gap-2.5 group focus:outline-none"
            aria-label="Candidly AI Home"
          >
            <Logo size={28} className="w-7 h-7" />
            <div className="flex items-center gap-1.5">
              <span className="font-extrabold text-base tracking-tight text-white group-hover:text-zinc-200 transition-colors">
                Candidly<span className="text-teal-400">.AI</span>
              </span>
              {isRecruiter && (
                <span className="hidden sm:inline-block text-[9px] font-bold px-2 py-0.5 rounded-full bg-teal-950/70 text-teal-300 border border-teal-800/60 uppercase tracking-wider">
                  Recruiter
                </span>
              )}
              {isCandidate && (
                <span className="hidden sm:inline-block text-[9px] font-bold px-2 py-0.5 rounded-full bg-teal-950/70 text-teal-300 border border-teal-800/60 uppercase tracking-wider">
                  Candidate
                </span>
              )}
            </div>
          </button>
        </div>

        {/* Center: Section Nav (Landing) OR Role Nav (Dashboards) */}
        <nav className="hidden md:flex items-center space-x-1">
          {isDashboard && roleNavLinks ? (
            <div className="flex items-center gap-1 rounded-xl border border-white/[0.06] bg-white/[0.02] p-1">
              {roleNavLinks.map((tab) => {
                const Icon = tab.icon;
                const isActive = activeNav === tab.id;
                return (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => onNavChange && onNavChange(tab.id)}
                    className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold transition-all ${
                      isActive
                        ? 'bg-[#18181B] text-teal-300 border border-white/[0.08] shadow-sm'
                        : 'text-zinc-400 hover:text-white hover:bg-white/[0.04]'
                    }`}
                  >
                    <Icon className="w-3.5 h-3.5" />
                    <span>{tab.name}</span>
                  </button>
                );
              })}
            </div>
          ) : (
            landingNavLinks.map((link) => (
              <a
                key={link.name}
                href={link.href}
                className="px-3 py-1.5 text-xs font-medium text-zinc-400 hover:text-white rounded-lg hover:bg-white/[0.04] transition-colors"
              >
                {link.name}
              </a>
            ))
          )}
        </nav>

        {/* Right side: Avatar Menu & One Teal Primary Button */}
        <div className="flex items-center gap-3">
          
          {/* Avatar Menu (if user is authenticated) */}
          {authUser ? (
            <div className="relative" ref={avatarMenuRef}>
              <button
                type="button"
                onClick={() => setAvatarMenuOpen((prev) => !prev)}
                className="flex items-center gap-2 rounded-xl border border-white/[0.08] bg-[#0A0A0B] p-1 pl-1.5 pr-2 hover:border-white/[0.16] hover:bg-[#111113] transition-all focus:outline-none"
                aria-label="User Profile Menu"
              >
                <div className="relative flex h-7 w-7 items-center justify-center rounded-lg bg-teal-500 text-black text-xs font-bold shadow-sm">
                  {getInitials(authUser.full_name)}
                  <span className="absolute -bottom-0.5 -right-0.5 h-2 w-2 rounded-full border border-black bg-emerald-400" />
                </div>
                <span className="hidden sm:inline-block max-w-[100px] truncate text-xs font-semibold text-zinc-200">
                  {authUser.full_name?.split(' ')[0] || 'Account'}
                </span>
                <ChevronDown className="h-3 w-3 text-zinc-400" />
              </button>

              {/* Avatar Dropdown Popover */}
              {avatarMenuOpen && (
                <div className="absolute right-0 mt-2 w-56 rounded-2xl border border-white/[0.08] bg-[#0A0A0B] p-2 shadow-2xl backdrop-blur-xl z-50">
                  <div className="border-b border-white/[0.06] px-3 py-2.5 mb-1">
                    <p className="text-xs font-bold text-white truncate">
                      {authUser.full_name}
                    </p>
                    <p className="text-[10px] text-zinc-400 truncate mt-0.5">
                      {authUser.email || `${authUser.role}@candidly.ai`}
                    </p>
                    <span className="mt-1.5 inline-block text-[9px] font-bold uppercase tracking-wider px-2 py-0.2 rounded-full bg-teal-950/70 text-teal-300 border border-teal-800/60">
                      {authUser.role || 'Member'}
                    </span>
                  </div>

                  {onOpenDashboard && (
                    <button
                      type="button"
                      onClick={() => {
                        setAvatarMenuOpen(false);
                        onOpenDashboard();
                      }}
                      className="w-full flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-semibold text-zinc-300 hover:text-white hover:bg-white/[0.04] transition-colors"
                    >
                      <Briefcase className="w-3.5 h-3.5 text-teal-400" />
                      <span>Workspace Console</span>
                    </button>
                  )}

                  <button
                    type="button"
                    onClick={() => {
                      setAvatarMenuOpen(false);
                      if (onNavChange) onNavChange('settings');
                    }}
                    className="w-full flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-semibold text-zinc-300 hover:text-white hover:bg-white/[0.04] transition-colors"
                  >
                    <Settings className="w-3.5 h-3.5 text-zinc-400" />
                    <span>Profile & Settings</span>
                  </button>

                  <div className="my-1 border-t border-white/[0.06]" />

                  <button
                    type="button"
                    onClick={() => {
                      setAvatarMenuOpen(false);
                      if (onSignOut) onSignOut();
                    }}
                    className="w-full flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-semibold text-rose-400 hover:bg-rose-950/30 transition-colors"
                  >
                    <LogOut className="w-3.5 h-3.5" />
                    <span>Sign Out</span>
                  </button>
                </div>
              )}
            </div>
          ) : (
            <button
              type="button"
              onClick={() => onOpenAuth && onOpenAuth('signin')}
              className="text-xs font-semibold text-zinc-300 hover:text-white px-2 py-1 transition-colors"
            >
              Sign In
            </button>
          )}

          {/* One Teal Primary Button */}
          {primaryAction ? (
            <button
              type="button"
              onClick={primaryAction.onClick}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-bold text-black bg-teal-400 hover:bg-teal-300 shadow-sm shadow-teal-500/20 hover:shadow-teal-500/30 transition-all"
            >
              {primaryAction.icon && <primaryAction.icon className="w-3.5 h-3.5" />}
              <span>{primaryAction.label}</span>
            </button>
          ) : isRecruiter ? (
            <button
              type="button"
              onClick={() => onNavChange && onNavChange('create_job')}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-bold text-black bg-teal-400 hover:bg-teal-300 shadow-sm shadow-teal-500/20 hover:shadow-teal-500/30 transition-all"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>Create Job</span>
            </button>
          ) : isCandidate ? (
            <button
              type="button"
              onClick={() => onNavChange && onNavChange('browse')}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-bold text-black bg-teal-400 hover:bg-teal-300 shadow-sm shadow-teal-500/20 hover:shadow-teal-500/30 transition-all"
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>Explore Jobs</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={onRequestDemo}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-bold text-black bg-teal-400 hover:bg-teal-300 shadow-sm shadow-teal-500/20 hover:shadow-teal-500/30 hover:-translate-y-0.5 transition-all"
            >
              <span>Request a Demo</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          )}

          {/* Mobile Sheet Toggle */}
          <button
            type="button"
            onClick={() => setMobileMenuOpen((prev) => !prev)}
            className="md:hidden p-1.5 rounded-lg text-zinc-400 hover:text-white hover:bg-white/[0.04] transition-colors"
            aria-label="Toggle Mobile Menu"
          >
            {mobileMenuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </div>
      </div>

      {/* Mobile Collapsible Sheet */}
      {mobileMenuOpen && (
        <div className="md:hidden fixed inset-x-0 top-14 bg-[#0A0A0B]/98 border-b border-white/[0.08] p-5 shadow-2xl backdrop-blur-2xl z-40 space-y-4">
          <nav className="space-y-1">
            {isDashboard && roleNavLinks ? (
              <div className="space-y-1 mb-4">
                <span className="text-[10px] font-bold uppercase tracking-wider text-zinc-500 px-3">
                  Workspace Navigation
                </span>
                {roleNavLinks.map((tab) => {
                  const Icon = tab.icon;
                  const isActive = activeNav === tab.id;
                  return (
                    <button
                      key={tab.id}
                      type="button"
                      onClick={() => {
                        setMobileMenuOpen(false);
                        if (onNavChange) onNavChange(tab.id);
                      }}
                      className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-semibold transition-all ${
                        isActive
                          ? 'bg-[#18181B] text-teal-300 border border-white/[0.08]'
                          : 'text-zinc-300 hover:text-white hover:bg-white/[0.04]'
                      }`}
                    >
                      <Icon className="w-4 h-4" />
                      <span>{tab.name}</span>
                    </button>
                  );
                })}
              </div>
            ) : (
              landingNavLinks.map((link) => (
                <a
                  key={link.name}
                  href={link.href}
                  onClick={() => setMobileMenuOpen(false)}
                  className="block px-3 py-2 text-sm font-medium text-zinc-300 hover:text-white rounded-xl hover:bg-white/[0.04] transition-colors"
                >
                  {link.name}
                </a>
              ))
            )}
          </nav>

          <div className="border-t border-white/[0.08] pt-4 space-y-2">
            {authUser ? (
              <>
                <div className="flex items-center gap-3 px-3 py-2 rounded-xl bg-[#111113] border border-white/[0.06]">
                  <div className="h-8 w-8 rounded-lg bg-teal-500 text-black flex items-center justify-center font-bold text-xs">
                    {getInitials(authUser.full_name)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-bold text-white truncate">
                      {authUser.full_name}
                    </p>
                    <p className="text-[10px] text-zinc-400 truncate">
                      {authUser.role}
                    </p>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => {
                    setMobileMenuOpen(false);
                    if (onSignOut) onSignOut();
                  }}
                  className="w-full flex items-center justify-center gap-2 py-2 rounded-xl text-xs font-semibold text-rose-400 bg-rose-950/30 hover:bg-rose-950/50 transition-colors"
                >
                  <LogOut className="w-4 h-4" />
                  <span>Sign Out</span>
                </button>
              </>
            ) : (
              <div className="space-y-2">
                <button
                  type="button"
                  onClick={() => {
                    setMobileMenuOpen(false);
                    if (onOpenAuth) onOpenAuth('signin');
                  }}
                  className="w-full py-2.5 rounded-xl text-xs font-bold text-white bg-[#18181B] hover:bg-[#27272A] border border-white/[0.08] transition-colors"
                >
                  Sign In
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setMobileMenuOpen(false);
                    if (onRequestDemo) onRequestDemo();
                  }}
                  className="w-full flex items-center justify-center gap-1.5 py-2.5 rounded-xl text-xs font-bold text-black bg-teal-400 hover:bg-teal-300 transition-colors"
                >
                  <span>Request a Demo</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </header>
  );
}
