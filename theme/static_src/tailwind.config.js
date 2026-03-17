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
          // Primitive_Main (used by catalog only)
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
      // Standardized spacing scale following design system
      spacing: {
        '18': '4.5rem',   // 72px
        '88': '22rem',    // 352px
        '92': '23rem',    // 368px
        '104': '26rem',   // 416px
        '128': '32rem',   // 512px
      },
      // Standardized border radius
      borderRadius: {
        'sm': '0.25rem',   // 4px
        DEFAULT: '0.5rem', // 8px
        'md': '0.75rem',   // 12px
        'lg': '1rem',      // 16px
        'xl': '1.5rem',    // 24px
        '2xl': '2rem',     // 32px
      },
      // Standardized transitions
      transitionDuration: {
        DEFAULT: '200ms',
        'fast': '150ms',
        'slow': '300ms',
      },
      // Standardized shadows for components
      boxShadow: {
        'card': '0 2px 8px rgba(0, 0, 0, 0.1)',
        'card-hover': '0 4px 12px rgba(0, 0, 0, 0.15)',
        'dropdown': '0 4px 16px rgba(0, 0, 0, 0.12)',
      },
    },
  },
  plugins: [
    require("daisyui"),
    function({ addBase, theme }) {
      addBase({
        'body.app-backend': {
          fontFamily: 'Inter, system-ui, sans-serif',
        },
        'body.app-backend h1, body.app-backend h2, body.app-backend h3, body.app-backend h4, body.app-backend h5, body.app-backend h6': {
          fontFamily: '"DM Serif Display", Georgia, serif',
        },
        'body.app-backend .prose h1, body.app-backend .prose h2, body.app-backend .prose h3, body.app-backend .prose h4, body.app-backend .prose h5, body.app-backend .prose h6': {
          fontFamily: '"DM Serif Display", Georgia, serif',
        },
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
    themes: [
      {
        // Custom "arkumu-backend" theme - use this for all backend development
        light: {
          "primary": "#2B7EF2",           // arkumu-blue
          "primary-content": "#ffffff",
          "secondary": "#666666",
          "secondary-content": "#ffffff",
          "accent": "#5498F7",
          "accent-content": "#ffffff",
          "neutral": "#1E1E1E",           // arkumu-dark
          "neutral-content": "#ffffff",
          "base-100": "#FAF9F6",          // arkumu-light (warm off-white)
          "base-200": "#EBEBEB",          // arkumu-light-soft
          "base-300": "#D9D9D9",          // arkumu-light-hover
          "base-content": "#1E1E1E",      // arkumu-dark
          "info": "#3ABFF8",
          "success": "#36D399",
          "warning": "#FBBD23",
          "error": "#F87272",
        },
      },
      {
        // Dark theme for backend
        dark: {
          "primary": "#2B7EF2",           // arkumu-blue
          "primary-content": "#ffffff",
          "secondary": "#AFAFAF",         // arkumu-light-passive
          "secondary-content": "#1E1E1E",
          "accent": "#74ADFC",            // arkumu-blue-passive
          "accent-content": "#1E1E1E",
          "neutral": "#FAF9F6",           // arkumu-light
          "neutral-content": "#1E1E1E",
          "base-100": "#1E1E1E",          // arkumu-dark
          "base-200": "#393939",          // arkumu-dark-hover
          "base-300": "#434343",          // arkumu-dark-soft
          "base-content": "#FAF9F6",      // arkumu-light
          "info": "#3ABFF8",
          "success": "#36D399",
          "warning": "#FBBD23",
          "error": "#F87272",
        },
      },
    ],
  },
}