---
name: Amber & Earth (Warm Style)
description: A warm, approachable, and trustworthy design system inspired by professional SaaS productivity tools with a cozy, organic touch.
version: 1.0.0

colors:
  primary: '#d97706' # Warm Amber
  on-primary: '#ffffff'
  primary-container: '#fef3c7'
  on-primary-container: '#92400e'
  
  secondary: '#78350f' # Deep Earthy Brown
  on-secondary: '#ffffff'
  
  surface: '#fbf8fc' # Warm Off-white
  surface-dim: '#dcd9dd'
  surface-bright: '#fbf8fc'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f5f3f6'
  surface-container: '#f0edf1'
  surface-container-high: '#ebe8eb'
  surface-container-highest: '#e5e2e6'
  
  on-surface: '#1c1b1f'
  on-surface-variant: '#49454f'
  outline: '#79747e'
  outline-variant: '#cac4d0'

typography:
  font-family: 'Hanken Grotesk, sans-serif'
  base-size: 16px
  scale: 1.25 # Major Third
  styles:
    display:
      weight: 700
      letter-spacing: -0.02em
    headline:
      weight: 600
      letter-spacing: -0.01em
    title:
      weight: 500
    body:
      weight: 400
      line-height: 1.6

shape:
  border-radius:
    none: 0px
    small: 4px
    medium: 8px # Default for cards and buttons
    large: 16px
    extra-large: 24px
    full: 9999px

spacing:
  base: 4px
  scale: [0, 4, 8, 12, 16, 24, 32, 48, 64, 96, 128]
  gutter: 24px
  margin-desktop: 80px
  margin-mobile: 16px

components:
  button:
    padding: '12px 24px'
    radius: 8px
    font-weight: 600
    transition: 'all 200ms ease'
  card:
    bg: surface-container-lowest
    border: '1px solid outline-variant'
    radius: 12px
    shadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)'

visual-principles:
  - softness: Use subtle border-radii and soft shadows to avoid a harsh technical feel.
  - hierarchy: High contrast for primary CTAs (Amber) against a neutral earthy background.
  - whitespace: Generous vertical stacking (stack-lg) between sections to allow content to breathe.
  - icons: Use thin-stroke, rounded icons to match the warm and modern aesthetic.
---