/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    // Templates
    '../../templates/**/*.html',
    '../../**/templates/**/*.html',
    // Theme
    './src/**/*.css',
  ],
  theme: {
    extend: {
      colors: {
        // White-label overridable via CSS custom properties. Reference the
        // real theme tokens (styles.css :root) — the old --brand-primary vars
        // were never defined, so these fell back to off-brand indigo.
        brand: {
          primary: 'var(--primary, #C2410C)',
          'primary-hover': 'var(--primary-hover, #9A3412)',
          secondary: 'var(--brand-green-500, #94A43F)',
        },
      },
    },
  },
  plugins: [],
}
