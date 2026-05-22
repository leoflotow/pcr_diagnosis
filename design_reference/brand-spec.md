# Brand Spec — PCR-Electrophoresis Diagnostic Assistant

## Direction
IBM Carbon Design System inspired, with a lab-science domain accent.

## Color Tokens (OKLch + Hex)

| Token | Hex | OKLch | Usage |
|-------|-----|-------|-------|
| --bg | #F6FAFC | oklch(98% 0.004 240) | Page background |
| --surface | #FFFFFF | oklch(100% 0 0) | Card / tile surfaces |
| --fg | #161616 | oklch(20% 0.018 70) | Primary text, headings |
| --muted | #525252 | oklch(40% 0.012 70) | Secondary text, descriptions |
| --border | #D8E3EA | oklch(90% 0.008 250) | Borders, dividers |
| --accent | #2563EB | oklch(58% 0.18 255) | Primary action, links, CTAs |
| --accent-hover | #1D4ED8 | oklch(52% 0.16 255) | Primary hover |
| --accent-active | #1E40AF | oklch(45% 0.14 255) | Primary active |
| --domain | #0EA5B7 | oklch(65% 0.12 195) | Secondary accent — gel cyan, science signals |
| --domain-muted | #E0F7FA | oklch(96% 0.03 195) | Tinted surface for domain moments |
| --dark | #0B1F3A | oklch(18% 0.06 250) | Hero dark surface, deep lab blue |
| --dark-text | #F6FAFC | oklch(98% 0.004 240) | Text on dark backgrounds |
| --danger | #DA1E28 | oklch(55% 0.18 25) | Error / warning |
| --success | #24A148 | oklch(60% 0.16 145) | Success states |
| --warning | #F1C21B | oklch(85% 0.15 95) | Warning states |

## Typography

- **Display / Headings**: IBM Plex Sans, weight 300 (Light) at 48–60px, weight 400 at ≤32px
- **Body**: IBM Plex Sans, weight 400, 16px, line-height 1.5
- **Emphasis / Labels**: IBM Plex Sans, weight 600, 14–16px
- **Mono / Code / Data**: IBM Plex Mono, weight 400, 14px, letter-spacing 0.16px
- **Captions / Meta**: IBM Plex Sans, weight 400, 12px, letter-spacing 0.32px

## Layout Posture

- 8px spacing grid (Carbon 2x grid)
- 0px border-radius on primary buttons (Carbon signature), 4px on cards for modern lab-tool feel
- Bottom-border inputs (not boxed)
- Depth via background-color layering (white → gray-10 → dark hero), minimal shadows
- Hairline borders (#D8E3EA) for separation
- One primary accent (diagnostic blue) + one domain accent (gel cyan)
- Max content width 1200px
- Section padding 80px vertical desktop, 48px mobile
