import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './app/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        teal: { DEFAULT: '#0D7377', 700: '#0A5C60' },
        dark: '#0D1B2A',
      },
    },
  },
  plugins: [],
}

export default config
