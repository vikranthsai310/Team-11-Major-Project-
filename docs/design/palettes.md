# Dashboard colour palettes

Saved palettes for the presentation dashboard (`src/batcher/dashboard/static/`). Each one lists
every token the stylesheet, the light strands (`fx.js`) and the intro (`intro.js`) use, so a
palette can be restored by swapping these values back in.

---

## Walnut Noir

Taken from the "Walnut Noir" premium gradient reference: a two-tone gradient from
`#2E1F1B` to `#5E4B43` on frosted-glass panels with thin light edges and deep soft shadows,
with a silver label chip (`#C5C6CA`). Used in commit `181bf4d` (strands dimmed on data pages in
`38a62e2`).

### CSS tokens (`:root` in `style.css`)

```css
--page: #1d1412;
--page-2: #211714;
--surface: rgba(62, 46, 41, 0.74);
--surface-2: rgba(94, 75, 67, 0.7);
--chart: rgba(29, 20, 18, 0.6);
--ink: #eee9e6;
--ink-2: #c4b8b2;
--muted: #8e817b;
--grid: rgba(255, 255, 255, 0.07);
--line: rgba(255, 255, 255, 0.09);
--line-2: rgba(220, 208, 200, 0.22);
--accent: #b5a197;
--accent-2: #5e4b43;
--accent-soft: #dcd0c8;
--glow: rgba(181, 161, 151, 0.18);
--good: #8cc9a8;
--warn: #d8b56e;
--serious: #d69a72;
--critical: #d88a84;
--static: #93b4c3;
--band: rgba(216, 138, 132, 0.09);
```

### Surfaces and details

| Element | Value |
|---|---|
| Page background | `linear-gradient(180deg, #2e1f1b 0%, #211714 45%, #1d1412 100%)` |
| Glass card | `linear-gradient(180deg, rgba(94, 75, 67, 0.58), rgba(46, 31, 27, 0.9))`, border `rgba(255, 255, 255, 0.09)`, `backdrop-filter: blur(26px) saturate(115%)` |
| Card edge highlight | `linear-gradient(165deg, rgba(255, 255, 255, 0.22), transparent 26%, transparent 74%, rgba(255, 255, 255, 0.05))` |
| Section number chip | `linear-gradient(180deg, #e4e2e1, #c5c6ca)`, text `#2e1f1b` |
| Light button / active switch | background `#eee9e6`, text `#2e1f1b` |
| Active nav tab | `linear-gradient(180deg, rgba(238, 233, 230, 0.16), rgba(238, 233, 230, 0.07))` |
| Brand mark gradient | `#eee9e6` → `#c2afa5` → `#5e4b43` |
| Headline gradient | `#ffffff` → `#e6ddd8` → `#c2afa5` → `#8f7a70` |
| Fixed-rule policy tag | `#b4cdd8` |

### Light strands (`fx.js`)

| Gradient | Stops |
|---|---|
| Main strands | `rgba(248,245,242,1)` → `#dcd0c8` → `#b09c92` → `#5e4b43` → `rgba(94,75,67,0.05)` |
| Second tone | `rgba(244,240,237,1)` → `#c9b8ae` → `#5e4b43` → `#43322b` → `rgba(94,75,67,0.05)` |
| Sparks | `#dcd0c8` halo, `#ffffff` core |
| Orbs | `rgba(240,234,230,a)` → `rgba(220,208,200,a)` → `rgba(181,161,151,0)` |
| Glow | `rgba(236,229,225,a)` → `rgba(181,161,151,a)` |

### Intro (`intro.js`)

| Element | Value |
|---|---|
| Stage | `#3a2924` → `#2e1f1b` → `#1d1412` |
| Vignette | `rgba(94,75,67,0.30)` → `rgba(62,46,41,0.10)` |
| Spark / trail tints | `220,208,200` and `206,192,184` |
| Rings and labels | `194,175,165`, `143,122,112`, `196,184,178` |
| Locked pool | `216,181,110` |
| Submit label | `140,201,168` |

---

## Rose Wine (current)

Taken from a dusty-rose glass sidebar reference: a deep wine stage lit by a soft pink glow in
the top corner, rose-to-wine frosted panels with thin pinkish-white borders, a light rose pill
for the active item and white text.

### CSS tokens (`:root` in `style.css`)

```css
--page: #1f0d0f;
--page-2: #2a1316;
--surface: rgba(92, 42, 46, 0.74);
--surface-2: rgba(142, 74, 78, 0.7);
--chart: rgba(31, 13, 15, 0.6);
--ink: #fbf1f0;
--ink-2: #ecd3d1;
--muted: #bf9a98;
--grid: rgba(255, 255, 255, 0.07);
--line: rgba(255, 255, 255, 0.09);
--line-2: rgba(240, 201, 198, 0.22);
--accent: #c98583;
--accent-2: #8e4a4e;
--accent-soft: #f0c9c6;
--glow: rgba(201, 133, 131, 0.18);
--good: #8fd0a8;
--warn: #f0c96a;
--serious: #e9a07a;
--critical: #ff8f8a;
--static: #9cc3d6;
--band: rgba(255, 143, 138, 0.09);
```

### Surfaces and details

| Element | Value |
|---|---|
| Page background | `linear-gradient(180deg, #3a1a1d 0%, #2a1316 45%, #1f0d0f 100%)` with a `rgba(217, 174, 171, 0.2)` glow in the top-left corner |
| Glass card | `linear-gradient(180deg, rgba(142, 74, 78, 0.58), rgba(58, 26, 29, 0.9))`, border `rgba(255, 255, 255, 0.09)` |
| Section number chip | `linear-gradient(180deg, #fbeceb, #efd0cd)`, text `#3a1a1d` |
| Light button / active switch | background `#fbf1f0`, text `#3a1a1d` |
| Active nav tab | `linear-gradient(180deg, rgba(251, 241, 240, 0.16), rgba(251, 241, 240, 0.07))` |
| Brand mark gradient | `#fbf1f0` → `#e3aeb0` → `#8e4a4e` |
| Headline gradient | `#ffffff` → `#f6dedc` → `#e3aeb0` → `#b86f72` |
| Fixed-rule policy tag | `#bcd6e2` |

### Light strands (`fx.js`)

| Gradient | Stops |
|---|---|
| Main strands | `rgba(255,245,244,1)` → `#f0c9c6` → `#c98583` → `#8e4a4e` → `rgba(142,74,78,0.05)` |
| Second tone | `rgba(255,236,234,1)` → `#e3aeb0` → `#8e4a4e` → `#5c2a2e` → `rgba(142,74,78,0.05)` |
| Sparks | `#f0c9c6` halo, `#ffffff` core |
| Orbs | `rgba(255,238,236,a)` → `rgba(240,201,198,a)` → `rgba(201,133,131,0)` |
| Glow | `rgba(250,232,230,a)` → `rgba(201,133,131,a)` |

### Intro (`intro.js`)

| Element | Value |
|---|---|
| Stage | `#4d2529` → `#3a1a1d` → `#1f0d0f` |
| Vignette | `rgba(142,74,78,0.30)` → `rgba(92,42,46,0.10)` |
| Spark / trail tints | `240,201,198` and `232,180,182` |
| Rings and labels | `227,174,176`, `184,111,114`, `236,211,209` |
| Locked pool | `240,201,106` |
| Submit label | `143,208,168` |
