let colors = {
  black: 'var(--black)',
  transparent: 'var(--transparent)',
  white: 'var(--white)',
  'white-50%': 'var(--white-50)',
  primary: 'var(--primary)',
  'primary-dark': 'var(--primary-dark)',
  'primary-70%': 'var(--primary-70)',
  'primary-50%': 'var(--primary-50)',
  'primary-30%': 'var(--primary-30)',
  'primary-10%': 'var(--primary-10)',
  'sidebar-icon': 'var(--sidebar-icon)',
  logo: 'var(--logo)',
  info: 'var(--info)',
  danger: 'var(--danger)',
  warning: 'var(--warning)',
  success: 'var(--success)',
  '90-half': 'var(--90-half)',
  90: 'var(--90)',
  80: 'var(--80)',
  70: 'var(--70)',
  60: 'var(--60)',
  50: 'var(--50)',
  40: 'var(--40)',
  30: 'var(--30)',
  20: 'var(--20)',
  'warning-light': 'var(--warning-light)',
  'warning-dark': 'var(--warning-dark)',
  'success-light': 'var(--success-light)',
  'success-dark': 'var(--success-dark)',
  'danger-light': 'var(--danger-light)',
  'danger-dark': 'var(--danger-dark)',
  'info-light': 'var(--info-light)',
  'info-dark': 'var(--info-dark)',
}

let svgFillColors = global.Object.assign({ current: 'currentColor' }, colors)

module.exports = {
  colors: colors,

  screens: {
    // sm: '576px',
    // md: '768px',
    // lg: '992px',
    // xl: '1200px',
  },

  fonts: {
    sans: [
      'Nunito',
      'system-ui',
      'BlinkMacSystemFont',
      '-apple-system',
      'sans-serif',
    ],
    mono: [
      'Menlo',
      'Monaco',
      'Consolas',
      'Liberation Mono',
      'Courier New',
      'monospace',
    ],
  },

  textSizes: {
    xs: '.75rem', // 12px
    sm: '.875rem', // 14px
    base: '1rem', // 16px
    lg: '1.125rem', // 18px
    xl: '1.25rem', // 20px
    '2xl': '1.5rem', // 24px
    '3xl': '1.875rem', // 30px
    '4xl': '2.25rem', // 36px
    '5xl': '3rem', // 48px
  },

  fontWeights: {
    hairline: 200,
    thin: 200,
    light: 300,
    normal: 400,
    medium: 400,
    semibold: 600,
    bold: 800,
    extrabold: 800,
    black: 800,
  },

  leading: {
    none: 1,
    tight: 1.25,
    normal: 1.5,
    loose: 2,
    '9': '2.25rem',
    '12': '3rem',
  },

  tracking: {
    tight: '-0.05em',
    normal: '0',
    wide: '0.05em',
  },

  textColors: colors,

  backgroundColors: colors,

  backgroundSize: {
    auto: 'auto',
    cover: 'cover',
    contain: 'contain',
  },

  borderWidths: {
    default: '1px',
    '0': '0',
    '2': '2px',
    '4': '4px',
    '8': '8px',
  },

  borderColors: global.Object.assign(
    {
      default: colors['black'],
    },
    colors
  ),

  borderRadius: {
    none: '0',
    sm: '.125rem',
    default: '.25rem',
    lg: '.5rem',
    full: '9999px',
  },

  width: {
    auto: 'auto',
    px: '1px',
    sidebar: '13.75rem',
    // '1': '0.25rem',
    '2': '0.5rem',
    '3': '0.75rem',
    'editor-icon': '0.95rem',
    '4': '1rem',
    '5': '1.25rem',
    // '6': '1.5rem',
    '8': '2rem',
    '9': '2.25rem',
    // '10': '2.5rem',
    '11': '2.75rem',
    '12': '3rem',
    '16': '4rem',
    // '24': '6rem',
    // '32': '8rem',
    '40': '10rem',
    '48': '12rem',
    // '64': '16rem',
    search: '18.75rem',
    '1/2': '50%',
    '1/3': '33.33333%',
    '2/3': '66.66667%',
    '1/4': '25%',
    '3/4': '75%',
    '1/5': '20%',
    '2/5': '40%',
    '3/5': '60%',
    '4/5': '80%',
    '1/6': '16.66667%',
    '5/6': '83.33333%',
    full: '100%',
    screen: '100vw',
    error: '65rem',
    action: '460px',
    'action-fields': '767px',
  },

  height: {
    auto: 'auto',
    '!auto': 'auto !important',
    px: '1px',
    // '1': '0.25rem',
    '2': '0.5rem',
    '3': '0.75rem',
    'editor-icon': '0.95rem',
    '4': '1rem',
    '5': '1.25rem',
    '6': '1.5rem',
    '8': '2rem',
    '!8': '2rem !important',
    'dropdown-trigger': '2.25rem',
    '9': '2.25rem',
    // '10': '2.5rem',
    '12': '3rem',
    // '16': '4rem',
    // '24': '6rem',
    // '32': '8rem',
    // '48': '12rem',
    // '64': '16rem',
    full: '100%',
    screen: '100vh',
    header: '3.75rem',
    'btn-sm': '1.875rem',
  },

  minWidth: {
    '0': '0',
    '8': '2rem',
    '9': '2.25rem',
    '24': '6rem',
    site: '80rem',
    full: '100%',
    'table-cell': '56px',
  },

  minHeight: {
    '0': '0',
    input: '3rem',
    textarea: '4.875rem',
    full: '100%',
    screen: '100vh',
  },

  maxWidth: {
    '8': '2rem',
    login: '25rem',
    xs: '20rem',
    sm: '30rem',
    md: '40rem',
    lg: '50rem',
    xl: '60rem',
    '2xl': '70rem',
    '3xl': '80rem',
    '4xl': '90rem',
    '5xl': '100rem',
    full: '100%',
    main: '58.75rem',
  },

  maxHeight: {
    full: '100%',
    screen: '100vh',
    search: '24.5rem',
    '90px': '5.625rem',
  },

  padding: {
    px: '1px',
    '0': '0',
    '1': '0.25rem', // 4px
    '2': '0.5rem', // 8px
    '3': '0.75rem', // 12.75px
    '4': '1rem', // 16px
    '6': '1.5rem', // 24px
    '8': '2rem', // 32px
    search: '2.75rem',
    view: '3.125rem', // 50px
  },

  margin: {
    auto: 'auto',
    px: '1px',
    '0': '0',
    '1': '0.25rem',
    '2': '0.5rem',
    '3': '0.75rem',
    '4': '1rem',
    '6': '1.5rem',
    '8': '2rem',
    '11': '2.75rem',
  },

  negativeMargin: {
    px: '1px',
    '0': '0',
    '1': '0.25rem',
    '2': '0.5rem',
    '3': '0.75rem',
    '4': '1rem',
    '6': '1.5rem',
    '8': '2rem',
  },

  shadows: {
    default: '0 2px 4px 0 rgba(0,0,0,0.05)',
    md: '0 4px 8px 0 rgba(0,0,0,0.12), 0 2px 4px 0 rgba(0,0,0,0.08)',
    lg: '0 15px 30px 0 rgba(0,0,0,0.11), 0 5px 15px 0 rgba(0,0,0,0.08)',
    inner: 'inset 0 2px 4px 0 rgba(0,0,0,0.06)',
    outline: '0 0 0 3px var(--primary-50)',
    none: 'none',
  },

  zIndex: {
    auto: 'auto',
    '0': 0,
    '10': 10,
    '20': 20,
    '30': 30,
    '40': 40,
    '50': 50,
  },

  opacity: {
    '0': '0',
    '25': '.25',
    '50': '.5',
    '75': '.75',
    '100': '1',
  },

  svgFill: svgFillColors,

  svgStroke: {
    current: 'currentColor',
  },

  modules: {
    appearance: ['responsive'],
    backgroundAttachment: ['responsive'],
    backgroundColors: ['responsive', 'hover', 'focus', 'active'],
    backgroundPosition: ['responsive'],
    backgroundRepeat: ['responsive'],
    backgroundSize: ['responsive'],
    borderColors: ['responsive', 'hover'],
    borderRadius: ['responsive'],
    borderStyle: ['responsive'],
    borderWidths: ['responsive'],
    cursor: ['responsive'],
    display: ['responsive'],
    flexbox: ['responsive'],
    float: ['responsive'],
    fonts: ['responsive'],
    fontWeights: ['responsive', 'hover'],
    height: ['responsive'],
    leading: ['responsive'],
    lists: ['responsive'],
    margin: ['responsive'],
    maxHeight: ['responsive'],
    maxWidth: ['responsive'],
    minHeight: ['responsive'],
    minWidth: ['responsive'],
    negativeMargin: ['responsive'],
    opacity: ['responsive'],
    outline: ['focus'],
    overflow: ['responsive'],
    padding: ['responsive'],
    pointerEvents: ['responsive'],
    position: ['responsive'],
    resize: ['responsive'],
    shadows: ['responsive', 'hover', 'focus', 'active'],
    svgFill: [],
    svgStroke: [],
    textAlign: ['responsive'],
    textColors: ['responsive', 'hover'],
    textSizes: ['responsive'],
    textStyle: ['responsive', 'hover'],
    tracking: ['responsive'],
    userSelect: ['responsive'],
    verticalAlign: ['responsive'],
    visibility: ['responsive'],
    whitespace: ['responsive'],
    width: ['responsive'],
    zIndex: ['responsive'],
  },

  plugins: [
    require('tailwindcss/plugins/container')({
      // center: true,
      // padding: '1rem',
    }),
  ],

  options: {
    prefix: '',
    important: false,
    separator: ':',
  },
}
