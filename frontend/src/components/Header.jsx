import React, { useState, useEffect } from 'react';
import { Sun, Moon, Menu, X, ArrowRight, User, LogOut, Briefcase, Building, Sparkles } from 'lucide-react';
import Logo from './Logo';

export default function Header({
  theme,
  toggleTheme,
  onRequestDemo,
  authUser,
  onOpenAuth,
  onOpenDashboard,
  onSignOut
}) {
  const [isScrolled, setIsScrolled] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      setIsScrolled(window.scrollY > 15);
    };
    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  const navLinks = [
    { name: 'Product', href: '#what-we-offer' },
    { name: 'How it works', href: '#how-we-evaluate' },
    { name: 'Integrity', href: '#proctoring' },
    { name: 'For Recruiters', href: '#personas' },
    { name: 'For Candidates', href: '#personas' },
  ];

  return (
    <header
      className={`sticky top-0 z-50 transition-all duration-200 ${
        isScrolled
          ? 'bg-white/95 dark:bg-[#0B0F19]/95 backdrop-blur-md shadow-sm border-b border-slate-200/80 dark:border-slate-800/80 py-3'
          : 'bg-white/90 dark:bg-[#0B0F19]/90 backdrop-blur-sm border-b border-slate-100 dark:border-slate-800/40 py-3.5'
      }`}
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between">
          {/* Logo / Wordmark */}
          <a href="#" className="flex items-center gap-3 group">
            <Logo size={36} className="w-9 h-9" />
            <div className="flex flex-col">
              <div className="flex items-center gap-2">
                <span className="font-extrabold text-xl tracking-tight text-slate-900 dark:text-white">
                  Candidly<span className="text-indigo-600 dark:text-indigo-400">.AI</span>
                </span>
                <span className="hidden sm:inline-block text-[10px] font-bold px-2 py-0.5 rounded-full bg-indigo-50 dark:bg-indigo-950/70 text-indigo-700 dark:text-indigo-300 border border-indigo-200/70 dark:border-indigo-800/60 tracking-wide">
                  ENTERPRISE
                </span>
              </div>
            </div>
          </a>

          {/* Desktop Navigation */}
          <nav className="hidden lg:flex items-center space-x-1">
            {navLinks.map((link) => (
              <a
                key={link.name}
                href={link.href}
                className="px-3 py-1.5 text-xs sm:text-sm font-medium text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white rounded-lg hover:bg-slate-100/80 dark:hover:bg-slate-800/60 transition-colors"
              >
                {link.name}
              </a>
            ))}
          </nav>

          {/* Right actions: Auth, Theme Toggle, CTA */}
          <div className="hidden md:flex items-center gap-2.5">
            {/* Theme Toggle Button */}
            <button
              onClick={toggleTheme}
              aria-label="Toggle Color Theme"
              className="p-2 rounded-xl text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white bg-slate-100/80 dark:bg-slate-800/80 hover:bg-slate-200/80 dark:hover:bg-slate-700/80 transition-all focus:outline-none"
            >
              {theme === 'dark' ? (
                <Sun className="w-4 h-4 text-amber-400" />
              ) : (
                <Moon className="w-4 h-4 text-slate-600" />
              )}
            </button>

            {/* Authenticated user pill OR Single Clean Login Button */}
            {authUser ? (
              <div className="flex items-center gap-2">
                <button
                  onClick={onOpenDashboard}
                  className="flex items-center gap-2 px-3.5 py-2 rounded-xl bg-slate-100 hover:bg-slate-200/80 dark:bg-slate-800/90 dark:hover:bg-slate-700/80 border border-slate-200/80 dark:border-slate-700/80 text-xs font-semibold text-slate-800 dark:text-slate-200 transition-all"
                >
                  <span className={`w-2 h-2 rounded-full ${authUser.role === 'recruiter' ? 'bg-indigo-500' : 'bg-emerald-500'} animate-pulse`} />
                  <span className="font-bold">{authUser.full_name}</span>
                  <span className="text-[10px] uppercase font-extrabold px-2 py-0.5 rounded-full bg-white dark:bg-slate-900 text-indigo-600 dark:text-indigo-400 border border-slate-200 dark:border-slate-800">
                    {authUser.role}
                  </span>
                </button>

                <button
                  onClick={onSignOut}
                  title="Sign Out"
                  className="p-2 rounded-xl text-slate-400 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/50 transition-colors"
                >
                  <LogOut className="w-4 h-4" />
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                {/* Single Clean Sign In Button */}
                <button
                  onClick={() => onOpenAuth('signin')}
                  className="px-4 py-2 rounded-xl text-xs sm:text-sm font-bold text-slate-700 hover:text-slate-900 dark:text-slate-200 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                >
                  Sign In
                </button>

                {/* Request a Demo CTA */}
                <button
                  onClick={onRequestDemo}
                  className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs sm:text-sm font-bold text-white bg-indigo-600 hover:bg-indigo-700 dark:bg-indigo-600 dark:hover:bg-indigo-500 shadow-sm shadow-indigo-600/30 hover:shadow-indigo-600/40 hover:-translate-y-0.5 transition-all duration-150"
                >
                  <span>Request a Demo</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </button>
              </div>
            )}
          </div>

          {/* Mobile menu button */}
          <div className="flex items-center gap-2 md:hidden">
            <button
              onClick={toggleTheme}
              aria-label="Toggle Color Theme"
              className="p-2 rounded-lg text-slate-600 dark:text-slate-300 bg-slate-100 dark:bg-slate-800"
            >
              {theme === 'dark' ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4" />}
            </button>
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="p-2 rounded-lg text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800"
            >
              {mobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
            </button>
          </div>
        </div>

        {/* Mobile menu dropdown */}
        {mobileMenuOpen && (
          <div className="md:hidden pt-4 pb-3 border-t border-slate-200 dark:border-slate-800 mt-3 space-y-2 bg-white/95 dark:bg-[#0B0F19]/95 backdrop-blur-lg rounded-2xl p-4 shadow-xl">
            {navLinks.map((link) => (
              <a
                key={link.name}
                href={link.href}
                onClick={() => setMobileMenuOpen(false)}
                className="block px-3 py-2 text-base font-medium text-slate-700 dark:text-slate-200 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800"
              >
                {link.name}
              </a>
            ))}

            <div className="pt-3 space-y-2 border-t border-slate-100 dark:border-slate-800/80">
              {authUser ? (
                <>
                  <div className="p-3 rounded-xl bg-slate-100 dark:bg-slate-800 text-xs font-semibold">
                    Signed in as: <strong>{authUser.full_name}</strong> ({authUser.role})
                  </div>
                  <button
                    onClick={() => {
                      setMobileMenuOpen(false);
                      onOpenDashboard();
                    }}
                    className="w-full py-2.5 rounded-xl text-xs font-bold text-white bg-indigo-600 text-center block"
                  >
                    Go to {authUser.role === 'recruiter' ? 'Recruiter Console' : 'Candidate Portal'}
                  </button>
                  <button
                    onClick={() => {
                      setMobileMenuOpen(false);
                      onSignOut();
                    }}
                    className="w-full py-2 rounded-xl text-xs font-semibold text-rose-600 bg-rose-50 dark:bg-rose-950/40 text-center block"
                  >
                    Sign Out
                  </button>
                </>
              ) : (
                <div className="space-y-2">
                  <button
                    onClick={() => {
                      setMobileMenuOpen(false);
                      onOpenAuth('signin');
                    }}
                    className="w-full py-3 rounded-xl text-sm font-bold text-slate-800 dark:text-slate-100 bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-center block transition-colors"
                  >
                    Sign In
                  </button>
                  <button
                    onClick={() => {
                      setMobileMenuOpen(false);
                      onRequestDemo();
                    }}
                    className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl text-sm font-semibold text-white bg-indigo-600 hover:bg-indigo-700 shadow-md transition-all"
                  >
                    <span>Request a Demo</span>
                    <ArrowRight className="w-4 h-4" />
                  </button>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </header>
  );
}
