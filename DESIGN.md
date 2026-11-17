# SLOWTRACE X design: the comparator

SLOWTRACE X is a blink comparator for NASA SPHEREx exposures. In 1930 Clyde
Tombaugh found Pluto, the original "Planet X", by flicking between two glass
plates in a brass-and-enamel blink comparator. This app does the same job with
infrared exposures from a telescope that photographs the sky through six
detector bands. The interface is designed as that instrument: a dark optical
bench where the sky image is the only bright thing, and everything around it is
scale, label and control.

Audience: Space Apps judges, students and citizen scientists, with some
astronomers. Primary job: enter a sky position, see what changed between dates,
and trace every pixel back to the archive.

## Principles

1. **The plate is the hero.** Every sky image sits in a plate: a true-black
   field with a measured border (arcminute ticks, north and east), and a label
   strip that says what it is. Nothing else on a page competes with it.
2. **Colour is data.** The interface itself is graphite and white. Colour
   appears in three places only: sky imagery, the wavelength code below, and
   status lamps. There is no brand accent colour.
3. **Wavelength has a colour.** SPHEREx's own first-light release tints its six
   detectors from violet to red. Those hues mark every epoch, band and spectral
   sample, so you can see at a glance which exposures are comparable.
4. **Recessed, not raised.** The page is the instrument body. Content sits in
   wells that are darker than the body, like displays set into a panel.
   Controls are keys that sit slightly above it. No shadows, no gradients
   except data ramps and scrims over photographs.
5. **Say what it is.** Sentence case, plain verbs, units on every number.
   Caveats are written as notes next to the thing they qualify, not hidden.

## Palette

| Name          | Hex       | Use                                              |
| ------------- | --------- | ------------------------------------------------ |
| Field         | `#000000` | Behind sky pixels and 3D scenes only             |
| Well          | `#0f1113` | Recessed surfaces: modules, inputs, tables       |
| Graphite      | `#1e2023` | Page and header, the instrument body             |
| Key           | `#2b2e33` | Raised controls                                  |
| Rule          | `#363a40` | Hairlines; `#4f545c` where a boundary must read  |
| Engraving     | `#efede6` | Primary text, primary key, selection, focus ring |
| Engraving dim | `#b6b4ad` | Secondary text; `#8d8b85` for labels             |

Status lamps (always with a text label): ready `#63d18f`, caution `#f2b84b`,
fault `#f26b5e`.

Wavelength code, sampled in hue from NASA's first SPHEREx images (PIA26280) and
lifted in lightness for a dark surface. Used for data only.

| Band | Range (µm) | Hex       |
| ---- | ---------- | --------- |
| D1   | 0.75–1.10  | `#b18cf5` |
| D2   | 1.10–1.64  | `#6ea4f2` |
| D3   | 1.64–2.42  | `#45c9b3` |
| D4   | 2.42–3.82  | `#a8cc4e` |
| D5   | 3.82–4.42  | `#e6b93f` |
| D6   | 4.42–5.00  | `#f07a55` |

## Type

Two families, both self-hosted from npm (`@fontsource`).

- **Old Standard TT** for titles, section headings and object names. It
  reproduces the "modern" faces of early twentieth-century scientific printing,
  the typography of the Lowell Observatory bulletins that announced the first
  Planet X search. Object names are set in its italic, as on a star atlas.
  Never below 20px.
- **B612** for everything else. Airbus commissioned it for cockpit displays; it
  is built to be read at small sizes at a glance. Its digits are tabular, so
  numbers align without a monospace. **B612 Mono** is used only for
  identifiers, checksums and raw JSON.

Scale (px): 12, 13, 14, 16, 20, 24, 32, 44, 64. Weights: 400 and 700. Body copy
is 14 in tools and 16 in prose, line-height 1.5, measure under 72 characters.
Labels are sentence case; nothing is set in capitals or letter-spaced.

## Space and shape

- 4px grid: 4, 8, 12, 16, 24, 32, 48, 64, 96.
- Page gutter 24px (16px under 760px). Content is left aligned; nothing is
  centred except empty states inside a well.
- Corners: 2px on keys and fields, 4px on wells. Plates are square.
- 1px rules. A module is separated from the body by its darker fill first and
  a rule second.

## Components

- **Plate** (`.plate`, `SkyCanvas`): black field, 1px rule, arcminute tick
  border, N/E mark, optional selection ring (white with a dark halo), and a
  label strip beneath: date, band chip, wavelength.
- **Well** (`.well`, legacy `.panel`): recessed module with an optional header
  row (title left, actions right).
- **Readout** (`.kv`): label left, value right, hairline between rows.
- **Figure** (`.figure`): an image plus a credit line. Every photograph has one.
- **Keys** (`.btn`): 30px tall. Default key is graphite; one primary key per
  view is white. Icon keys are square. Links are underlined text, never keys.
- **Fields**: 30px, recessed, label above or to the left.
- **Segments** (`.seg`): a recessed track; the chosen option is a raised key.
- **Band chip** (`.band`): a 3px bar in the band colour, then the text.
- **Lamp** (`.lamp`): 6px round dot plus text.
- **Note** (`.note-line`): a caveat with a rule on its left edge.
- **Table**: rules above the header and below the last row, hairlines between
  rows, numbers right aligned.
- **Charts**: drawn in wells on a faint graph-paper grid, engraving-white axes,
  band colours for wavelength or detector, white ring for the selected point.
  Series that are not wavelengths use white (`#efede6`), then warm grey
  (`#8d8b85`), then amber (`#f2b84b`), in that order. Status counts use the
  lamp colours.
- **3D scenes** (Solar System, track space): graphite grid lines, white for the
  object of interest, planets in warmed approximations of their visual tints.

## Layout

App frame: one header (brand, six destinations, a More menu) on every page.
Pages that work on the loaded field share a field bar: target picks, position
entry and tabs for the six field tools.

```
┌ SLOWTRACE X   Mission  Observe  Sky Atlas  Spectra  Discoveries  More ▾ ┐
├──────────────────────────────────────────────────────────────────────────┤
│ Targets [..][..][..][..][..]            RA [    ] Dec [    ] 5′ D1 [Search]│
│ Blink | DeepTrace | Spectra | Lab | Notebook | Planner        Export     │
├───────────────────────────────────────────────┬──────────────────────────┤
│ Barnard's Star  269.44620° +4.76883°          │ Field                    │
│ ┌───────────────── plate ──────────────────┐  │  readout rows            │
│ │ ticks                                N   │  │ Display                  │
│ │            sky pixels              E ┘   │  │  reference, stretch …    │
│ │                                          │  │ Next steps               │
│ └──────────────────────────────────────────┘  │  keys                    │
│ ▶ ◀ ▶ ───────●──────────────  2/8  1.1 fps    │ Field notes, provenance  │
│ [epoch][epoch][epoch] …                       │                          │
└───────────────────────────────────────────────┴──────────────────────────┘
```

Mission (landing): text left, plate right; then the five targets as plates you
can open; then how the instrument works, with photographs.

```
┌──────────────────────────────┬───────────────────────────────────────────┐
│ Title                        │  all-sky map (plate, credit)              │
│ one paragraph                │                                           │
│ RA [   ] Dec [   ] [Open]    │                                           │
├──────────────────────────────┴───────────────────────────────────────────┤
│ [plate][plate][plate][plate][plate]   five targets                       │
├──────────────────────────────────────────────────────────────────────────┤
│ how it works (3 steps)  |  live two-date comparison                      │
│ the telescope: photo + six detectors + filters, with credits             │
│ published survey figures → Discoveries, Statistics                       │
└──────────────────────────────────────────────────────────────────────────┘
```

Below 900px every two-column layout stacks, plate first. Below 760px the header
collapses to a menu and the field bar wraps.

## Motion

The blink is the only thing that moves by itself, and only when asked, except
on the Mission page where one plate blinks to show what the tool does. It stops
under `prefers-reduced-motion`. Everything else is a 120ms state change.

## Files

- `src/styles/tokens.css` defines every colour, size and font. It also aliases
  the older names (`--s1`, `--mono`, `--line`, ...) that the Atlas, Solar
  System and Statistics stylesheets still use, so they read the same tokens.
- `src/styles/base.css`, `components.css`, `shell.css`, `plate.css`,
  `observe.css`, `mission.css` and `tools.css` hold the rest, in that order.
- `src/wavelength.ts` holds the wavelength code for scripts and charts.

## Imagery

Only real mission imagery, stored in `public/images` as WebP with a visible
credit wherever it appears. Sources are listed in `public/images/CREDITS.md`.
The target plates are rendered from the SPHEREx cutouts bundled with the app by
`scripts/render_target_plates.py`.

## What was ruled out, and why

- A near-black page with one bright accent colour, and cards lighter than the
  page: the default look of a "space dashboard". Replaced by graphite with
  darker wells and no accent hue.
- All-caps eyebrow labels, middle-dot metadata strings and arrows on links:
  template chrome. Labels are sentence case; metadata is laid out as readouts.
- A monospace for small labels. B612's tabular digits do the aligning.
- Blue-tinted sky rendering as the default. Plates are grayscale; a negative
  (dark sources on white, as on glass plates) and the earlier blue rendering
  remain as options.
