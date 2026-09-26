# Free Food Map ("Your Last Name is Nieman.")

A local website that lists, day by day, the Harvard events that come with food (talks, panels,
reading groups, receptions) and pins them on a map of Cambridge. It is built for Nieman Fellows,
who may attend events across all Harvard schools. For each event it shows the time, title,
kind of food, whether registration is needed, **who may attend**, the location with walking time
from Lippmann House, and a link to the source listing. Fellows can mark events **Going** or **Skip**,
and on a phone the site installs to the home screen and works like an app.

## Start it

Double-click **`Start Free Food Map.bat`**, or run:

```
pip install -r requirements.txt
python serve.py
```

The site opens at <http://localhost:8765>. While it runs, it re-scans all sources every 3 hours
and picks up the new day at midnight. The **Rescan** button in the page triggers a scan right away.

| Command | What it does |
|---|---|
| `python serve.py --interval 1` | rescan every hour |
| `python serve.py --lan` | let phones and laptops on the same network open it (at `http://<this-PC's-IP>:8765`) |
| `PORT=10000 python serve.py` | how a hosting service starts it (listens publicly on `$PORT`) |
| `python serve.py --no-scan` | only serve the current `data/events.json` |
| `python scan.py` | one scan, no server (today + 7 days) |
| `python scan.py --only hls hks` | scan some sources only |

## How it works

```
sources (calendars, newsletters) -> classify (food? registration? audience?) -> geocode -> merge duplicates -> data/events.json -> web/
```

1. **Collect.** Each adapter in `freefood/sources/` reads one calendar, using its JSON API where
   there is one and parsing the event page where there is not.
2. **Classify** (`freefood/classify.py`). An event is a **confirmed** food event when one sentence
   names a food *and* says it is served ("A light lunch will be provided."). That sentence is
   shown on the card as evidence. It is **likely** when only the title suggests food
   ("Lunch Seminar", "Opening Reception"). Food as a topic ("food insecurity"), brown-bag,
   pay-for-food and online-only events are excluded. Registration is read the same way
   ("Registration is encouraged but not required" → *RSVP recommended*).
3. **Geocode** (`freefood/geo.py`, `freefood/places.py`). Room strings like `WCC 3019`, `L-166` or
   `CGIS South S354` are matched against a list of about 90 Harvard buildings with coordinates
   from OpenStreetMap. Other street addresses go to OpenStreetMap's Nominatim, with results cached.
4. **Audience** (`freefood/audience.py`). Nieman Fellows hold Harvard IDs but are not students of
   a particular school, undergraduates, House residents or members of student groups. Each event is
   labeled *open to public*, *Harvard ID holders* (fellows qualify), *not stated*, *probably only …*
   or *only …*. The label comes from the first of these that applies:
   - the calendar's own audience field: HLS "Audiences" ("All HLS students only", "1Ls", "All Harvard"),
     College class-year tags, Gazette "Harvard Key Required";
   - strong clues, which override "all welcome" sentences: 1L/2L/LLM or class-year titles, a House as
     host, club business (general body meetings, subcites, new-member trainings), advising, info
     sessions, recruiting, anything run by an HLS student organization or student-services office;
   - an explicit sentence ("open to HUID holders only", "by invitation");
   - calendar defaults: College calendar events count as undergrad-only, and HLS events count as
     "probably HLS only" unless an HLS research program hosts them. These defaults never override
     another calendar's listing of the same event.
   The default **Open to fellows** view hides both *only …* and *probably only …*. On the scan of
   25 Sep 2026 that left 18 of 80 food events. **Include restricted** shows everything.
5. **Merge.** The same talk often appears on 2–3 calendars. Those listings become one card that
   links to every source. The audience label from the most authoritative source wins.

## Going / Skip

Each card has **Going** and **Skip** buttons, shared by everyone using the same server. Each phone or
browser gets an anonymous device id, and fellows can optionally add a first name that appears
next to "going". Tapping the same button again takes the vote back. Votes live in `data/votes.json`
and expire after 30 days. "Sort by most going" in the filters puts popular events first.

## On phones (iOS and Android)

The site is a Progressive Web App: `web/manifest.webmanifest` gives it a name, icon and
full-screen mode, and `web/sw.js` makes it work offline with the last downloaded list.
On phones it switches to an app layout with List / Map / About tabs and a filter sheet.

- **iPhone:** open the site in Safari → Share → *Add to Home Screen*.
- **Android:** open it in Chrome → *Install app* (Chrome also offers it in a banner).

Phones need to reach the server:
- **Same network:** run `python serve.py --lan` and open `http://<this-PC's-IP>:8765` on the phone.
  This works for trying it out, but campus Wi-Fi often blocks device-to-device traffic. Over plain
  http, Android will not install it as a full app and offline mode is off, because browsers
  require HTTPS for those features.
- **For real use:** the GitHub Pages site below has HTTPS, so installing and offline mode work there.

## Sources

| id | Source | Method | Notes |
|---|---|---|---|
| `gazette` | Harvard Gazette calendar | Trumba JSON | university-wide, all schools can post |
| `hks` | Harvard Kennedy School | HTML | includes IOP, Belfer, CPL, M-RCBG, Bloomberg Center |
| `hls` | Harvard Law School | HTML | the richest source: many lunch talks |
| `college` | Harvard College events | LiveWhale JSON | departments, Houses, student groups |
| `ash` | Ash Center (HKS) | WordPress API | |
| `shorenstein` | Shorenstein Center (HKS) | WordPress API | journalism-focused |
| `fairbank` | Fairbank Center | The Events Calendar API | |
| `newsletter` | Newsletters | `inbox/` files or IMAP | see `inbox/README.txt` |

The adapters are reusable. For another Trumba, LiveWhale, The Events Calendar or ACF-WordPress
calendar, add one line to `freefood/sources/__init__.py`.

**Not yet covered:** WCFIA, the Divinity School, the Hutchins Center, CMES and DRCLAS return
"403 Forbidden" to scripts. Some of their events still arrive through the Gazette calendar. The Chan
School and HBS are blocked too, and they are far from Lippmann House anyway.

## Newsletters

Save newsletter emails as `.eml` files, or paste them as `.txt`/`.html`, into `inbox/`. Or point
the scanner at a mailbox that receives them (e.g. a Gmail address subscribed to the lists) through
environment variables. Details are in `inbox/README.txt`. Items are cut out at date lines and kept
only if the food rules fire. Their cards are labeled "Newsletter: <subject>".

## Files

```
serve.py, scan.py          entry points (serve.py also answers /api/votes, /api/vote, /api/name, /api/scan)
freefood/                  sources/, classify.py (food, registration), audience.py, geo.py, places.py,
                           pipeline.py, votes.py
web/                       index.html, app.js, style.css, manifest.webmanifest, sw.js, icons/,
                           basemap.json (self-drawn map), vendor/leaflet.css
artifact/index.html        the claude.ai-hosted page (built by tools/build_artifact.py)
data/events.json           latest scan: all events, food, audience, evidence, coordinates
data/votes.json            Going / Skip votes and optional first names
data/places.json           building coordinates (rebuild: python tools/build_places.py)
data/cache/                cached event pages (safe to delete)
tools/                     build_places.py, make_icons.py, build_basemap.py, build_artifact.py
tests/                     test_classify.py, test_audience.py, test_newsletter.py (run each with python)
```

## Limits

- The classifier uses rules, not judgment. It is precise on the usual phrasings but can miss
  unusual wording. A card never promises food; the evidence line and source link let you check.
- Audience labels inferred from context ("probably only …") are educated guesses. The **Who** line
  says what the guess is based on. Most listings do not state an audience at all.
- Votes are anonymous and not authenticated. Anyone who can open the site can vote, which is fine
  among fellows but should be revisited if the link is shared widely.
- Walking times are straight-line distance × 1.3 at 80 m/min.

## Hosting on GitHub Pages (the public website)

**Live at <https://nikwall.github.io/free-food/>** (repository `github.com/nikwall/free-food`;
votes in the Supabase project `free-food`, organization "nikwall's Org", Free plan).

GitHub hosts the site for free at `https://<your-username>.github.io/<repository>/`, with HTTPS, so
phones can install it as an app. A GitHub Actions workflow (`.github/workflows/pages.yml`) runs
`scan.py` at 6 AM and noon Boston time, builds the site with `tools/build_site.py`, and publishes it.
It also saves the day's `data/events.json` back to the repository. If a scan looks broken (fewer than
150 events, or HLS and HKS both failing), the workflow stops and yesterday's site stays up.

One-time setup:
1. Create a **public** repository on github.com (e.g. `free-food`), empty, without a README.
2. Upload this folder: in GitHub Desktop, *File → Add local repository* → this folder → *Commit to
   main* → *Publish repository*. Or from a terminal, after `git remote add origin <repo URL>`:
   `git add . && git commit -m "Free Food Map" && git push -u origin main`.
3. On github.com: *Settings → Pages → Build and deployment → Source: **GitHub Actions***.
4. *Actions → Scan and publish → Run workflow*. After about 2 minutes the site is live at the address
   shown on the run's summary page (and in *Settings → Pages*).

### Voting on the website (optional)

GitHub Pages only serves files, so the Going/Skip votes need a small free database:
1. Create a free project on supabase.com.
2. *SQL Editor → New query*: paste `hosting/supabase.sql`, click *Run*.
3. From the project's API settings, copy the **Project URL** and the **publishable** key (or the
   legacy "anon public" key) into `web/config.js`, then commit and push. The site redeploys with
   voting switched on.

Votes are anonymous and not tamper-proof (anyone with the site could change them through the API),
which is fine among fellows. Free Supabase projects pause after about a week without use; the
workflow pings the database on every run to keep it awake, and a paused project can be restored
from the Supabase dashboard.

## Hosting on claude.ai

The site is also published as a private claude.ai page (an "Artifact"):
<https://claude.ai/artifact/QdJLwx2dxEJ5upwKPSHSjp>. It opens on any phone signed in to Claude.
There, votes live in the page's own database (one document per person under `votes/`), and the
names shown next to "going" come from people's Claude accounts. The basemap is drawn from
`web/basemap.json` (OpenStreetMap data, `python tools/build_basemap.py`), because hosted pages
cannot load map tiles from other servers.

- **Refreshing the data:** the hosted copy shows the last scan published to it. A scheduled Claude task,
  `free-food-map-daily-refresh` (Claude desktop app → Scheduled), does this every day at 12:00 laptop
  time (6:00 AM in Boston while the laptop is on German time). It runs `python scan.py` and
  `python tools/build_artifact.py`, then republishes `artifact/index.html` with the files listed in
  `tools/build_artifact.py`. It skips publishing when a scan looks broken. It runs only while the
  Claude app is open, and otherwise catches up at the next launch.
- **Sharing:** a page with a shared database cannot have a public link. Invite fellows by email from
  the page's Share menu; to vote they need *Editor* access, and *Viewers* see the votes only.

## Design

Colors and type follow nieman.harvard.edu: the crimson #A51C30 wordmark box, warm grays
(#F7F6F5, #EBE9E8), serif text with grotesk headlines, and small mono kickers. Nieman's own
fonts (Optimo's Stanley and Basel, Klim's Pitch) are licensed to their site only. This site uses
the free fonts nieman.harvard.edu also loads (Source Serif 4, Work Sans) plus IBM Plex Mono.
This is an unofficial project and says so on the About page.

## Possible next steps

1. HTTPS hosting, so every fellow can install it on their phone (see "On phones" above).
2. A morning email or Slack digest of today's food events.
3. Model-based extraction for newsletters, whose layouts vary too much for rules.
4. Adapters for the blocked center sites, via their RSS feeds or a headless browser.
