import React from 'react';

export default function Stat({
  label,
  value,
  subtext,
  icon: Icon,
  trend,
  className = '',
  serifValue = false,
}) {
  return (
    <div
      className={`relative overflow-hidden rounded-2xl border border-white/[0.08] bg-[#0A0A0B] p-5 text-white transition-all duration-200 hover:border-white/[0.14] ${className}`}
    >
      <div className="flex items-center justify-between gap-3">
        <span className="text-[11px] font-bold uppercase tracking-wider text-zinc-400">
          {label}
        </span>
        {Icon && (
          <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-white/[0.06] bg-white/[0.03] text-teal-400">
            <Icon className="h-4 w-4" />
          </div>
        )}
      </div>

      <div className="mt-3 flex items-baseline gap-2">
        <span
          className={`font-bold tracking-tight text-white ${
            serifValue
              ? 'font-display text-3xl sm:text-4xl font-normal'
              : 'text-2xl sm:text-3xl'
          }`}
        >
          {value}
        </span>
        {trend && (
          <span
            className={`text-xs font-semibold ${
              trend.positive ? 'text-emerald-400' : 'text-rose-400'
            }`}
          >
            {trend.value}
          </span>
        )}
      </div>

      {subtext && (
        <p className="mt-1 text-xs text-zinc-500 leading-relaxed truncate">{subtext}</p>
      )}
    </div>
  );
}
