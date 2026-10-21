import React from 'react';

export default function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className = '',
}) {
  return (
    <div
      className={`relative overflow-hidden rounded-3xl border border-white/[0.08] bg-[#0A0A0B] p-10 sm:p-14 text-center ${className}`}
    >
      {/* Dotted-wave background, low opacity */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.07]"
        style={{
          backgroundImage:
            'radial-gradient(circle at 50% 50%, rgba(20, 184, 166, 0.4) 0%, transparent 60%), radial-gradient(rgba(255, 255, 255, 0.6) 1px, transparent 1px)',
          backgroundSize: '100% 100%, 20px 20px',
        }}
      />

      <div className="relative z-10 mx-auto max-w-md space-y-4">
        {Icon && (
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl border border-white/[0.08] bg-white/[0.03] text-teal-400 shadow-inner">
            <Icon className="h-6 w-6" />
          </div>
        )}

        <div className="space-y-1.5">
          <h3 className="font-display text-2xl font-normal text-white tracking-tight">
            {title}
          </h3>
          {description && (
            <p className="text-xs sm:text-sm text-zinc-400 leading-relaxed max-w-sm mx-auto">
              {description}
            </p>
          )}
        </div>

        {action && <div className="pt-2">{action}</div>}
      </div>
    </div>
  );
}
