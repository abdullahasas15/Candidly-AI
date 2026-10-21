import React from 'react';

export default function Card({
  children,
  className = '',
  hoverable = false,
  onClick,
  as: Component = 'div',
  ...props
}) {
  return (
    <Component
      onClick={onClick}
      className={`rounded-2xl border border-white/[0.08] bg-[#0A0A0B] p-6 text-white shadow-sm transition-all duration-200 ${
        hoverable ? 'hover:border-white/[0.16] hover:bg-[#111113] cursor-pointer' : ''
      } ${className}`}
      {...props}
    >
      {children}
    </Component>
  );
}
