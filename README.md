# Firefox Triage Dashboard — Static Demo

This is a static HTML snapshot of a local FastAPI dashboard that turns Firefox
A/V bug triage into a focused review-and-approve flow. The dashboard itself is
not open source; this repo exists to make the design and workflow viewable
publicly without exposing the underlying app.

## What you're looking at

A point-in-time snapshot of the live dashboard with **real public Bugzilla A/V
bugs** in flight. Every bug shown is a normal public Bugzilla entry — clicking
through to `bugzilla.mozilla.org/show_bug.cgi?id=…` shows the same data the
demo surfaces.

The demo lets you:

- Browse the four tab states: `analyzed`, `needs info`, `close / reassign`,
  `awaiting reply`
- Click between cards in the rail to focus on different bugs
- Read the per-card draft comment and the proposed Bugzilla actions
- View the embedded investigation findings for analyzed bugs
- Add and remove fake pending feedback on a card (stored only in your
  browser's `localStorage`; each visitor's feedback is private to their
  browser)

What's disabled (no backend exists):

- `Apply` / `Apply & close` / `Reassign` buttons
- Process-queue drain actions
- Watch-list mutations
- Server-pushed live updates

## Layout

```
docs/                 static site, served by GitHub Pages
├── index.html        landing page (analyzed tab)
├── triaged.html      analyzed tab
├── needs-info.html   needs-info tab
├── close.html        close/reassign tab
├── watching.html     awaiting-reply tab
├── *-bug-*.html      per-bug focused-card permalinks
└── static/           CSS, favicon
investigations/       full investigation MDs for analyzed bugs
scripts/snapshot.py   one-shot script that built docs/ from the live app
```

The snapshot is **one-and-done** — this repo is not regenerated on a schedule.

## Why this repo exists

A/V triage involves a lot of context per bug. The dashboard consolidates the
draft comment, bug metadata, investigation findings, and proposed Bugzilla
actions into a single card, keeping the human-in-the-loop guarantee at the
final `bugzilla-cli apply` confirmation. This demo lets you see that shape
without standing up the app locally.

## License

MIT — see [LICENSE](LICENSE).
