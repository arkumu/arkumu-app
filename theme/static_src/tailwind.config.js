module.exports = {
  content: [
    // Templates in your Django project
    '../../**/templates/**/*.html',
    '../../**/templates/**/*.py',  
    // JavaScript files that might contain Tailwind classes
    './js/**/*.js',
  ],
  theme: {
    extend: {
      colors: {
        arkumu: {
          // Primitive_Main
          dark: '#1E1E1E',
          light: '#FAF9F6',
          blue: '#2B7EF2',
          
          // Primitive_Hover
          'dark-hover': '#393939',
          'light-hover': '#D9D9D9',
          'blue-hover': '#5498F7',
          
          // Primitive_Soft
          'dark-soft': '#434343',
          'light-soft': '#EBEBEB',
          'blue-soft': '#E4EFFF',
          
          // Primitive_Passive
          'dark-passive': '#666666',
          'light-passive': '#AFAFAF',
          'blue-passive': '#74ADFC',
          
          // Keep existing color schemes
          'blau': '#4285F4',
          'hell': '#F8F7F4',
          'dunkel': '#1D1D1D',
        },
      },
      fontFamily: {
        sans: ['Roboto Mono', 'monospace'],
        mono: ['Roboto Mono', 'monospace'],
      },
    },
  },
  plugins: [
    require("daisyui"),
    function({ addBase, theme }) {
      addBase({
        ':root': {
          '--primary-bg': theme('colors.arkumu.light'),
          '--primary-hover': theme('colors.arkumu.light-hover'),
          '--primary-text': theme('colors.arkumu.dark'),
          '--primary-soft': theme('colors.arkumu.light-soft'),
          '--primary-passive': theme('colors.arkumu.light-passive'),
          
          '--accent-bg': theme('colors.arkumu.blue'),
          '--accent-hover': theme('colors.arkumu.blue-hover'),
          '--accent-text': theme('colors.arkumu.light'),
          '--accent-soft': theme('colors.arkumu.blue-soft'),
          '--accent-passive': theme('colors.arkumu.blue-passive'),
        },
        '.theme-dark': {
          '--primary-bg': theme('colors.arkumu.dark'),
          '--primary-hover': theme('colors.arkumu.dark-hover'),
          '--primary-text': theme('colors.arkumu.light'),
          '--primary-soft': theme('colors.arkumu.dark-soft'),
          '--primary-passive': theme('colors.arkumu.dark-passive'),
        },
        '.theme-blue': {
          '--primary-bg': theme('colors.arkumu.blue'),
          '--primary-hover': theme('colors.arkumu.blue-hover'),
          '--primary-text': theme('colors.arkumu.light'),
          '--primary-soft': theme('colors.arkumu.blue-soft'),
          '--primary-passive': theme('colors.arkumu.blue-passive'),
        }
      });
    },
    function({ addVariant }) {
      // Add theme variants
      addVariant('theme-dark', '.theme-dark &');
      addVariant('theme-light', '.theme-light &');
      addVariant('theme-blue', '.theme-blue &');
    }
  ],
  daisyui: {
    themes: ["light", "dark"], // Enable built-in themes
  },
}