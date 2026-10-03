import React, { useState, useEffect } from 'react';
import Header from './components/Header';
import Hero from './components/Hero';
import StatsStrip from './components/StatsStrip';
import WhatWeOffer from './components/WhatWeOffer';
import HowWeEvaluate from './components/HowWeEvaluate';
import ProctoringIntegrity from './components/ProctoringIntegrity';
import PersonaTabs from './components/PersonaTabs';
import Footer from './components/Footer';
import DemoModal from './components/DemoModal';
import AuthModal from './components/auth/AuthModal';
import RecruiterDashboard from './components/recruiter/RecruiterDashboard';
import CandidateDashboard from './components/candidate/CandidateDashboard';

export default function App() {
  const [viewMode, setViewMode] = useState('landing'); // 'landing' | 'recruiter' | 'candidate'

  const [authUser, setAuthUser] = useState(() => {
    if (typeof window !== 'undefined') {
      try {
        const saved = localStorage.getItem('candidly-auth-user');
        return saved ? JSON.parse(saved) : null;
      } catch (e) {
        return null;
      }
    }
    return null;
  });

  const [authModal, setAuthModal] = useState({
    isOpen: false,
    mode: 'signin', // 'signin' | 'signup'
    role: 'recruiter' // 'recruiter' | 'candidate'
  });

  const [theme, setTheme] = useState(() => {
    if (typeof window !== 'undefined') {
      const savedTheme = localStorage.getItem('candidly-theme');
      if (savedTheme) return savedTheme;
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    return 'dark';
  });

  const [demoModalOpen, setDemoModalOpen] = useState(false);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'dark') {
      root.classList.add('dark');
    } else {
      root.classList.remove('dark');
    }
    localStorage.setItem('candidly-theme', theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme((prevTheme) => (prevTheme === 'dark' ? 'light' : 'dark'));
  };

  const handleOpenDemo = () => {
    setDemoModalOpen(true);
  };

  const handleCloseDemo = () => {
    setDemoModalOpen(false);
  };

  const handleOpenAuth = (mode = 'signin', role = 'recruiter') => {
    setAuthModal({
      isOpen: true,
      mode,
      role
    });
  };

  const handleCloseAuth = () => {
    setAuthModal((prev) => ({ ...prev, isOpen: false }));
  };

  const handleAuthSuccess = (user) => {
    setAuthUser(user);
    localStorage.setItem('candidly-auth-user', JSON.stringify(user));
    setAuthModal((prev) => ({ ...prev, isOpen: false }));
    // Immediately navigate to their role-specific dashboard
    if (user.role === 'candidate') {
      setViewMode('candidate');
    } else {
      setViewMode('recruiter');
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleSignOut = () => {
    setAuthUser(null);
    localStorage.removeItem('candidly-auth-user');
    localStorage.removeItem('candidly-auth-token');
    localStorage.removeItem('candidly_user');
    localStorage.removeItem('candidly_token');
    setViewMode('landing');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleOpenDashboard = () => {
    if (!authUser) {
      handleOpenAuth('signin', 'recruiter');
      return;
    }
    if (authUser.role === 'candidate') {
      setViewMode('candidate');
    } else {
      setViewMode('recruiter');
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleBackToLanding = () => {
    setViewMode('landing');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleExploreEvaluation = () => {
    const section = document.getElementById('how-we-evaluate');
    if (section) {
      section.scrollIntoView({ behavior: 'smooth' });
    }
  };

  // View Routing: Recruiter Dashboard
  if (viewMode === 'recruiter') {
    return (
      <RecruiterDashboard
        authUser={authUser}
        onBackToLanding={handleBackToLanding}
        onSignOut={handleSignOut}
      />
    );
  }

  // View Routing: Candidate Dashboard
  if (viewMode === 'candidate') {
    return (
      <CandidateDashboard
        authUser={authUser}
        onBackToLanding={handleBackToLanding}
        onSignOut={handleSignOut}
      />
    );
  }

  // Default: Landing Page
  return (
    <div className="min-h-screen flex flex-col bg-[#F8FAFC] dark:bg-[#0B0F19] text-slate-900 dark:text-slate-100 selection:bg-indigo-500 selection:text-white transition-colors duration-300">
      {/* Sticky Header with Recruiter, Candidate & Account Buttons */}
      <Header
        theme={theme}
        toggleTheme={toggleTheme}
        onRequestDemo={handleOpenDemo}
        authUser={authUser}
        onOpenAuth={handleOpenAuth}
        onOpenDashboard={handleOpenDashboard}
        onSignOut={handleSignOut}
      />

      {/* Main Single-Page Content */}
      <main className="flex-1">
        <Hero
          onRequestDemo={handleOpenDemo}
          onExploreEvaluation={handleExploreEvaluation}
        />

        <StatsStrip />

        <WhatWeOffer />

        <HowWeEvaluate />

        <ProctoringIntegrity />

        <PersonaTabs
          onRequestDemo={handleOpenDemo}
          onOpenAuth={handleOpenAuth}
        />
      </main>

      {/* Footer */}
      <Footer onRequestDemo={handleOpenDemo} />

      {/* Interactive Request Demo Modal */}
      <DemoModal
        isOpen={demoModalOpen}
        onClose={handleCloseDemo}
      />

      {/* Unified Authentication Modal (Sign In & Create Account for Recruiters & Candidates) */}
      <AuthModal
        isOpen={authModal.isOpen}
        onClose={handleCloseAuth}
        initialMode={authModal.mode}
        initialRole={authModal.role}
        onSuccess={handleAuthSuccess}
      />
    </div>
  );
}
