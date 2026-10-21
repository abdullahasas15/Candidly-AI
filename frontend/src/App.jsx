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

const InterviewPreviewGallery = React.lazy(() => import('./components/candidate/interview/InterviewPreviewGallery'));

export default function App() {
  // Check for developer/preview gallery mode in URL
  const isPreviewMode =
    typeof window !== 'undefined' &&
    new URLSearchParams(window.location.search).get('preview') === 'interview';

  if (isPreviewMode) {
    return (
      <React.Suspense fallback={<div className="min-h-screen bg-black flex items-center justify-center text-teal-400">Loading Preview...</div>}>
        <InterviewPreviewGallery />
      </React.Suspense>
    );
  }

  const [authUser, setAuthUser] = useState(() => {
    if (typeof window !== 'undefined') {
      try {
        const saved = localStorage.getItem('candidly-auth-user') || localStorage.getItem('candidly_user');
        return saved ? JSON.parse(saved) : null;
      } catch (e) {
        return null;
      }
    }
    return null;
  });

  const [viewMode, setViewMode] = useState(() => {
    if (typeof window !== 'undefined') {
      const paramView = new URLSearchParams(window.location.search).get('view');
      if (paramView === 'recruiter' || paramView === 'candidate' || paramView === 'landing') {
        return paramView;
      }
      try {
        const saved = localStorage.getItem('candidly-auth-user') || localStorage.getItem('candidly_user');
        if (saved) {
          const parsed = JSON.parse(saved);
          if (parsed?.role === 'candidate') return 'candidate';
          if (parsed?.role === 'recruiter') return 'recruiter';
        }
      } catch (e) {
        // ignore
      }
    }
    return 'landing';
  }); // 'landing' | 'recruiter' | 'candidate'

  const [authModal, setAuthModal] = useState({
    isOpen: false,
    mode: 'signin', // 'signin' | 'signup'
    role: 'recruiter' // 'recruiter' | 'candidate'
  });

  const [demoModalOpen, setDemoModalOpen] = useState(false);

  useEffect(() => {
    document.documentElement.classList.add('dark');
  }, []);

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
    // Immediately navigate to their role-specific dashboard and sync URL
    if (user.role === 'candidate') {
      setViewMode('candidate');
      if (typeof window !== 'undefined') {
        window.history.replaceState(null, '', '?view=candidate');
      }
    } else {
      setViewMode('recruiter');
      if (typeof window !== 'undefined') {
        window.history.replaceState(null, '', '?view=recruiter');
      }
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleSignOut = () => {
    setAuthUser(null);
    localStorage.removeItem('candidly-auth-user');
    localStorage.removeItem('candidly-auth-token');
    localStorage.removeItem('candidly-auth-token-candidate');
    localStorage.removeItem('candidly-auth-token-recruiter');
    localStorage.removeItem('candidly_user');
    localStorage.removeItem('candidly_token');
    setViewMode('landing');
    if (typeof window !== 'undefined') {
      window.history.replaceState(null, '', '/');
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleOpenDashboard = () => {
    if (!authUser) {
      handleOpenAuth('signin', 'recruiter');
      return;
    }
    if (authUser.role === 'candidate') {
      setViewMode('candidate');
      if (typeof window !== 'undefined') {
        window.history.replaceState(null, '', '?view=candidate');
      }
    } else {
      setViewMode('recruiter');
      if (typeof window !== 'undefined') {
        window.history.replaceState(null, '', '?view=recruiter');
      }
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleBackToLanding = () => {
    setViewMode('landing');
    if (typeof window !== 'undefined') {
      window.history.replaceState(null, '', '?view=landing');
    }
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
    <div className="min-h-screen flex flex-col bg-black text-slate-100 selection:bg-teal-500 selection:text-white transition-colors duration-300">
      {/* Sticky Header with Recruiter, Candidate & Account Buttons */}
      <Header
        onRequestDemo={handleOpenDemo}
        authUser={authUser}
        onOpenAuth={handleOpenAuth}
        onOpenDashboard={handleOpenDashboard}
        onSignOut={handleSignOut}
        currentView={viewMode}
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
