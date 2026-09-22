import React from 'react';

export default function Logo({ className = "w-10 h-10", size = 40 }) {
  return (
    <div className={`relative flex items-center justify-center flex-shrink-0 ${className}`}>
      <svg
        width={size}
        height={size}
        viewBox="0 0 48 48"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="w-full h-full transform hover:scale-105 transition-transform duration-200"
      >
        <defs>
          {/* Main Gradient */}
          <linearGradient id="candidlyGrad" x1="4" y1="4" x2="44" y2="44" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#6366F1" />
            <stop offset="50%" stopColor="#4F46E5" />
            <stop offset="100%" stopColor="#7C3AED" />
          </linearGradient>

          {/* Core Spark Gradient */}
          <linearGradient id="sparkGrad" x1="20" y1="18" x2="28" y2="30" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#38BDF8" />
            <stop offset="100%" stopColor="#818CF8" />
          </linearGradient>

          {/* Subtle Glow Filter */}
          <filter id="glowFilter" x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow dx="0" dy="2" stdDeviation="3" floodColor="#6366F1" floodOpacity="0.3" />
          </filter>
        </defs>

        {/* Squircle Container */}
        <rect
          x="3"
          y="3"
          width="42"
          height="42"
          rx="12"
          fill="url(#candidlyGrad)"
          filter="url(#glowFilter)"
        />

        {/* Dynamic Stylized "C" Arc symbolizing Speech Resonance & Integrity */}
        <path
          d="M 33 16 C 29 12 21 12 16 16 C 11 20.5 11 27.5 16 32 C 21 36 29 36 33 32"
          stroke="white"
          strokeWidth="3.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* Inner Voice Soundwave Bars radiating from the C */}
        <line x1="23" y1="20" x2="23" y2="28" stroke="white" strokeWidth="2.8" strokeLinecap="round" />
        <line x1="28" y1="18" x2="28" y2="30" stroke="white" strokeWidth="2.8" strokeLinecap="round" opacity="0.9" />
        <line x1="33" y1="22" x2="33" y2="26" stroke="white" strokeWidth="2.8" strokeLinecap="round" opacity="0.8" />

        {/* Intelligence Diamond / Spark at the top right of the curve */}
        <circle cx="33" cy="16" r="2.2" fill="url(#sparkGrad)" />
      </svg>
    </div>
  );
}

