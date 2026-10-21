import React from 'react';

const VARIANT_MAP = {
  teal: 'bg-teal-950/60 text-teal-300 border-teal-800/60',
  brand: 'bg-teal-950/60 text-teal-300 border-teal-800/60',
  success: 'bg-emerald-950/60 text-emerald-300 border-emerald-800/60',
  warning: 'bg-amber-950/60 text-amber-300 border-amber-800/60',
  error: 'bg-rose-950/60 text-rose-300 border-rose-800/60',
  neutral: 'bg-[#18181B] text-zinc-300 border-white/[0.08]',
  outline: 'bg-transparent text-zinc-400 border-white/[0.12]',
  subtle: 'bg-white/[0.04] text-zinc-300 border-white/[0.06]',
};

const SIZE_MAP = {
  sm: 'px-2 py-0.5 text-[10px]',
  md: 'px-2.5 py-1 text-xs',
  lg: 'px-3 py-1.5 text-xs',
};

export default function Badge({
  children,
  variant = 'neutral',
  size = 'md',
  dot = false,
  dotColor = '',
  className = '',
  ...props
}) {
  const variantClasses = VARIANT_MAP[variant] || VARIANT_MAP.neutral;
  const sizeClasses = SIZE_MAP[size] || SIZE_MAP.md;

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border font-semibold tracking-wide transition-colors ${variantClasses} ${sizeClasses} ${className}`}
      {...props}
    >
      {dot && (
        <span
          className={`h-1.5 w-1.5 rounded-full ${
            dotColor ||
            (variant === 'success'
              ? 'bg-emerald-400'
              : variant === 'warning'
              ? 'bg-amber-400'
              : variant === 'error'
              ? 'bg-rose-400'
              : variant === 'teal' || variant === 'brand'
              ? 'bg-teal-400'
              : 'bg-zinc-400')
          }`}
        />
      )}
      {children}
    </span>
  );
}
