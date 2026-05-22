# Design System — PCR-Electrophoresis Diagnostic Assistant

## 1. Color Palette

```css
:root {
  --bg: #F6FAFC;
  --surface: #FFFFFF;
  --fg: #161616;
  --muted: #525252;
  --border: #D8E3EA;

  --accent: #2563EB;
  --accent-hover: #1D4ED8;
  --accent-active: #1E40AF;
  --accent-tint: #EFF6FF;

  --domain: #0EA5B7;
  --domain-muted: #E0F7FA;

  --dark: #0B1F3A;
  --dark-text: #F6FAFC;

  --danger: #DA1E28;
  --success: #24A148;
  --warning: #F1C21B;

  --gray-10: #F4F4F4;
  --gray-20: #E0E0E0;
  --gray-30: #C6C6C6;
  --gray-60: #6F6F6F;
  --gray-70: #525252;
  --gray-100: #161616;
}
```

## 2. Typography Scale

| Token | Font | Size | Weight | Line Height | Letter Spacing |
|-------|------|------|--------|-------------|----------------|
| Display | IBM Plex Sans | 52px | 300 | 1.15 | 0 |
| H1 | IBM Plex Sans | 36px | 300 | 1.20 | 0 |
| H2 | IBM Plex Sans | 28px | 400 | 1.25 | 0 |
| H3 | IBM Plex Sans | 22px | 400 | 1.30 | 0 |
| H4 | IBM Plex Sans | 18px | 600 | 1.35 | 0 |
| Body | IBM Plex Sans | 16px | 400 | 1.60 | 0 |
| Body-sm | IBM Plex Sans | 14px | 400 | 1.50 | 0.16px |
| Label | IBM Plex Sans | 14px | 600 | 1.40 | 0 |
| Caption | IBM Plex Sans | 12px | 400 | 1.40 | 0.32px |
| Mono | IBM Plex Mono | 14px | 400 | 1.50 | 0.16px |

## 3. Spacing Scale (8px grid)

| Token | Value |
|-------|-------|
| space-1 | 4px |
| space-2 | 8px |
| space-3 | 16px |
| space-4 | 24px |
| space-5 | 32px |
| space-6 | 48px |
| space-7 | 64px |
| space-8 | 80px |
| space-9 | 96px |

## 4. Component Styles

### Primary Button
- Background: var(--accent) #2563EB
- Text: #FFFFFF
- Padding: 14px 32px
- Border-radius: 0px (Carbon signature)
- Height: 48px
- Hover: var(--accent-hover) #1D4ED8
- Active: var(--accent-active) #1E40AF
- Font: 14px weight 600, letter-spacing 0.16px

### Secondary Button
- Background: transparent
- Text: var(--accent) #2563EB
- Border: 1px solid var(--accent)
- Padding: 14px 32px
- Border-radius: 0px
- Hover: background var(--accent-tint)

### Ghost Button
- Background: transparent
- Text: var(--muted) #525252
- Border: 1px solid var(--border)
- Padding: 12px 24px
- Hover: background var(--gray-10)

### Card
- Background: var(--surface) #FFFFFF
- Border: 1px solid var(--border) #D8E3EA
- Border-radius: 4px (modern lab-tool feel, slightly softer than Carbon's 0px)
- Padding: 32px
- Hover: border-color var(--accent), subtle translateY(-2px)

### Problem Card (darker variant)
- Background: var(--dark) #0B1F3A
- Text: var(--dark-text)
- Border-radius: 4px
- Padding: 32px

### Tag / Pill
- Background: var(--accent-tint) #EFF6FF
- Text: var(--accent) #2563EB
- Padding: 4px 12px
- Border-radius: 24px
- Font: 12px weight 600

### Input (implied for Streamlit context)
- Background: var(--gray-10) #F4F4F4
- Bottom-border: 2px solid var(--gray-30)
- Focus bottom-border: 2px solid var(--accent)
- Border-radius: 0px top

## 5. Layout Rules

- Max container width: 1200px
- Section vertical padding: 80px desktop, 48px tablet, 32px mobile
- Container horizontal padding: 32px desktop, 16px mobile
- Grid gap: 24px
- Card gap: 24px
- Sidebar hint: 1px solid var(--border) left edge on hero, 48px reserved zone

## 6. Elevation / Depth

- No box-shadows on cards (Carbon flatness)
- Depth via background-color layering: dark hero → light bg → white cards
- Optional very subtle shadow on hover: 0 4px 12px rgba(11, 31, 58, 0.08)

## 7. Responsive Breakpoints

| Name | Width | Key Changes |
|------|-------|-------------|
| sm | 640px | Single column, stacked cards, reduced padding |
| md | 768px | 2-column grids |
| lg | 1024px | Full layout, 3-4 column grids |
| xl | 1280px | Max container, full spacing |

## 8. Do's and Don'ts

- DO use IBM Plex Sans weight 300 for display headlines
- DO keep 0px radius on buttons (Carbon identity)
- DO use 4px radius on cards (slight modern softening for lab tool)
- DO use bottom-border inputs, not boxed
- DO keep one primary accent (diagnostic blue) + one domain accent (gel cyan)
- DON'T add gradient backgrounds
- DON'T use shadows as primary depth mechanism
- DON'T use weight 700 (Bold) — stop at 600
- DON'T add generic emoji icons
- DON'T use warm beige/cream/peach backgrounds
