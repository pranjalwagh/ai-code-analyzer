/** @type {import('tailwindcss').Config} */
module.exports = {
    content: [
      "./src/**/*.{js,jsx,ts,tsx}", // Scan all JS/JSX files in the src directory
    ],
    theme: {
      extend: {},
    },
    plugins: [
      require('@tailwindcss/typography'), // For styling the AI summary nicely
    ],
  }
  