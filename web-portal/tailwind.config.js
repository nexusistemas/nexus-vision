/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        nexus: {
          bg: '#070D19',
          surface: '#0F172A',
          card: '#111C31',
          border: '#1E2D47',
          cyan: '#22D3EE',
          emerald: '#10B981',
        },
      },
    },
  },
  plugins: [],
};
