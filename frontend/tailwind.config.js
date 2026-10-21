import colors from 'tailwindcss/colors';

/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Global palette override: slate/gray/zinc 950..800 -> near-black neutrals
        // (#000, #0A0A0B, #111113, #18181B, #27272A)
        slate: {
          ...colors.slate,
          950: '#000000',
          900: '#0A0A0B',
          850: '#111113',
          800: '#18181B',
          750: '#18181B',
          700: '#27272A',
        },
        gray: {
          ...colors.gray,
          950: '#000000',
          900: '#0A0A0B',
          850: '#111113',
          800: '#18181B',
          750: '#18181B',
          700: '#27272A',
        },
        zinc: {
          ...colors.zinc,
          950: '#000000',
          900: '#0A0A0B',
          850: '#111113',
          800: '#18181B',
          750: '#18181B',
          700: '#27272A',
        },
        // indigo and brand -> teal (400 #2DD4BF, 500 #14B8A6, 600 #0D9488 ...)
        indigo: {
          50: '#F0FDFA',
          100: '#CCFBF1',
          200: '#99F6E4',
          300: '#5EEAD4',
          400: '#2DD4BF',
          500: '#14B8A6',
          600: '#0D9488',
          700: '#0F766E',
          800: '#115E59',
          900: '#134E4A',
          950: '#042F2E',
        },
        brand: {
          50: '#F0FDFA',
          100: '#CCFBF1',
          200: '#99F6E4',
          300: '#5EEAD4',
          400: '#2DD4BF',
          500: '#14B8A6',
          600: '#0D9488',
          700: '#0F766E',
          800: '#115E59',
          900: '#134E4A',
          950: '#042F2E',
        },
        // Preserve status colors explicitly
        emerald: colors.emerald,
        amber: colors.amber,
        rose: colors.rose,
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        display: ['"Instrument Serif"', 'Georgia', 'serif'],
      },
      backgroundImage: {
        'dots': 'radial-gradient(rgba(255, 255, 255, 0.08) 1px, transparent 1px)',
      },
      backgroundSize: {
        'dots': '24px 24px',
      },
      animation: {
        'pulse-subtle': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'wave-1': 'wave 1.2s ease-in-out infinite',
        'wave-2': 'wave 1.5s ease-in-out infinite 0.2s',
        'wave-3': 'wave 1.1s ease-in-out infinite 0.4s',
      },
      keyframes: {
        wave: {
          '0%, 100%': { transform: 'scaleY(0.3)' },
          '50%': { transform: 'scaleY(1)' },
        },
      },
    },
  },
  plugins: [],
};
