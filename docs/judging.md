# Challenge and judging evidence

SLOWTRACE X addresses **Planet X and SPHEREx** by making real infrared sky observations accessible through coordinates and time comparison. Advanced analysis supports that experience; it does not replace the official challenge.

The supplied 2026 Judging & Awards Guide scores each criterion from 1 to 5. This table is a guide to evidence reviewers can inspect, not a prediction of judges' scores.

| Criterion | Evidence to inspect | Claim boundary |
| --- | --- | --- |
| Impact | Public coordinate search, approachable time comparison, downloadable provenance | No measured user-impact or discovery claim |
| Creativity | Connected observation → motion hypothesis → injection experiment → evidence workflow | Shift-and-stack is an established method; the product integration is the contribution |
| Validity | Real FITS values, timestamps, coordinate alignment, quality masks, variance, explicit tests | Candidate scores are exploratory; incomplete calibration is disclosed |
| Relevance | NASA/IPAC SPHEREx DR1/QR3 supplies the actual observed images | Simulations are never substituted for missing observations |
| Presentation | Visible image provenance, observation timeline, direct coordinate URLs, concise limitations | A website alone does not satisfy the separate demo requirement |

## Recommended judge walkthrough

1. Open the observation workspace, select one of the five challenge targets, or enter ICRS RA/Dec. Search the archive.
2. Inspect the returned release, detector, time and source URL. Load real image cutouts and play the time sequence. Keep wavelength differences in mind: changing brightness is not automatically variability.
3. Compare two observations and inspect quality/coverage. Download the originating FITS data to independently inspect them.
4. Run an available motion/stacking analysis and examine its assumptions, supporting frames and limitations. Unidentified residuals are investigation leads, never confirmed new objects.
5. Run a seeded injection experiment on those observed images. Inspect measured recovery and controls, including cases where a method does worse. Export parameters/results for reproduction.
6. Use the follow-up planner for a **fixed coordinate** and specified terrestrial observer. Its UTC altitude/darkness calculations do not determine a candidate's future orbit.

## Submission checklist for the team

Based on the user-provided Project Submission Guide (Nov 13, 2026):

- Provide the public project URL and a separate public demo: **no more than 7 slides including title/intro**, or a video **no longer than 30 seconds**.
- Use English in the project page and linked materials. A non-English video needs English subtitles.
- Verify every link without login, permission requests or registration.
- Complete the project name, high-level summary, detailed description, NASA data and external-reference fields. Disclose AI assistance.
- Credit code, text, data and imagery, including freely available resources. Keep license notices for reused code.
- Confirm team/event eligibility and click **Submit for Judging** on the official team page. Deployment does not submit the entry.

The supplied guide states the deadline as November 15, 2026, 11:59 p.m. in the Local Event timezone; for the Universal Event, use the Team Owner's timezone. The team must verify its applicable deadline and registration. Team names and member details are not invented by this project.

## AI assistance disclosure

The team supplied the scientific/product vision and challenge priorities. OpenAI Codex assisted with research, implementation, documentation and tests. The code and documentation are AI-assisted and require normal scientific and software review. Astronomical observations are obtained from their cited archives; AI does not generate observations, measured recoveries, catalog matches or claimed discoveries. Synthetic injected sources are explicitly labelled and parameterized. No generated NASA logo or mission artwork is used.
