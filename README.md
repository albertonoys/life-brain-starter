# Life brain

A second brain for your life admin — every workstream you have on, in one
place, with the three questions no to-do app answers:

- **What's decaying?** Deadlines gone past, things you haven't touched in
  weeks, things you never started.
- **Whose court is the ball in?** What's on you, what's on someone else, and
  who has gone quiet long enough that it's time to chase.
- **What should get my next free hour?** A short ranked list, not a wall of
  two hundred tasks.

It is plain markdown files, a page that renders them, and a map. Claude Code
does the upkeep so you never have to. No account, no app, no database, no
subscription beyond the Claude one you already have. Everything stays on your
machine.

## What you need

- **Python 3** — free, from [python.org/downloads](https://www.python.org/downloads/).
  On Windows, tick **"Add python.exe to PATH"** on the first screen of the
  installer — that one checkbox is the difference between everything working
  and nothing working. (Macs and most Linux machines already have it.)
- **[Claude Code](https://claude.com/claude-code)** — for the smart half.
  The page works without it; the "Ask Claude" box needs it.

## Start it

**Never used a terminal before?** Open **`START HERE (Mac).md`** or
**`START HERE (Windows).md`** instead of this file — same setup, walked
through step by step, assuming nothing. This README assumes you're already
comfortable at a command line.

Unzip this folder wherever you keep things (e.g. `Documents\life-brain`), then:

- **Windows:** double-click **`Open Brain.bat`**
- **Mac:** double-click **`Open Brain.command`**
- **Any terminal:** `python brain/tools/serve.py` (or `python3` / `py -3`,
  whichever your machine answers to)

Your browser opens `http://127.0.0.1:7718` with your brain page. Leave the
black window open while you use it — that little program *is* the sync
button you were told couldn't exist (more below). Closing it stops the
brain; nothing is lost, just double-click again.

## The five-minute setup

1. **Open Claude Code in this folder** (open a terminal in the folder and
   run `claude`) and run `/onboard`. You talk — about your projects, the
   people you owe replies to, the things you keep meaning to do — and it
   builds the whole brain from what you said. (Prefer doing it by hand?
   `brain/workstreams.md` explains its own format at the top. Been chatting
   with Claude for years already? `/import-history` folds an account
   export's worth of old conversations in too.)
2. **Open `brain/config.json`** and put your real project folders in
   `sources` — any folder with a `TODO.md`, `CLAUDE.md` or `README.md` in it.
   That's it: the page re-reads those folders on its own every 20 minutes
   (change `auto_sync_minutes` to taste), and each project shows up with its
   open items and how long since anyone worked on it. The green dot in the
   header shows when it last synced — click it to sync right now.
3. From then on, the habit is two commands: `/brief` when you sit down,
   `/wrap` when you get up. Claude keeps the files honest; you just read
   the page.

## Mornings that run themselves (optional)

The brain can write your daily plan before you're up and notify you only if
something is genuinely on fire:

- **Windows:** double-click **`Set Up Mornings (Windows).bat`** once. That
  registers a 7:00 task (if the PC is asleep, it runs on wake). Undo:
  `powershell -ExecutionPolicy Bypass -File brain\tools\setup_morning.ps1 -Remove`.
- **Mac:** `zsh brain/tools/setup_morning.sh` registers the same 7:00 job as
  a launchd agent (if the Mac is asleep, it runs on wake). Undo with
  ` --off`.

If `"ai": "careful"` in `brain/config.json`, the morning run does only the
free parts (sync + rebuild) and skips the scheduled Claude run.

## The extras — where the brain gets unfairly good

Each of these is optional and takes minutes; the **Connections** button on
the page (top right) shows the same list with live status. Ask Claude in
this folder to set up any of them.

- **Chats, without logging anything (Beeper).** Bridge your networks —
  WhatsApp, Instagram, Telegram, SMS — inside the free
  [Beeper Desktop](https://www.beeper.com) app once, keep it open, and the
  brain reads chat names and last-activity dates each morning (never
  message text). Your "last spoke" dates stay true by themselves; the
  People tab then flags who has quietly drifted.
- **A Telegram bot — text your brain from anywhere.** Two minutes: message
  @BotFather → /newbot, give the brain the token, pair with the code it
  shows. From then on a thought from the bus lands in your inbox, "plan"
  answers with today's list, and a voice note is transcribed on your
  machine and turned into tasks.
- **Email that you approve, per message.** Claude writes the draft; the
  page shows exactly what would be sent; you press the button. An app
  password from your provider lives in the system keychain. Close-circle
  contacts are draft-only in code — the brain will never message your
  family.
- **Your calendar in the plan** and **voice memos** — the two sections
  below.
- **Mornings that run themselves** — the section above.
- **The night shift.** Heavy jobs — queued asks, the end-of-day tidy — run
  at 01:00 in their own usage window, so they never eat your daytime
  allowance. Set it up once ("Set Up Night Shift" on Windows,
  `zsh brain/tools/setup_night.sh` on a Mac), then it's a switch on the
  page.

## Your calendar in the plan (optional, any OS)

The morning plan can fit itself around your real day. On a Mac, granting
Calendar access is enough. On any OS, subscribe the brain to your calendar's
private feed:

```
python3 brain/tools/calendar_read.py --add-feed <address>
```

Google Calendar calls the address "Secret address in iCal format" (calendar
settings); Outlook.com has "publish calendar". Then set `"calendar": true`
in `brain/config.json`. The feed is fetched and read on your machine —
titles and times only — and the address itself is a key, so it lives in a
git-ignored file that never leaves this computer. On Windows, add
`pip install tzdata` if your calendar has events from other timezones.

## Voice memos (optional, any OS)

Recordings dropped on the page get transcribed locally. A Mac with
`mlx_whisper` uses its own GPU; every other machine needs one install:

```
pip install faster-whisper
```

CPU works (a 20-minute memo takes a while); an NVIDIA GPU makes it quick.
Set the `BRAIN_WHISPER_MODEL` environment variable to `medium` or
`large-v3` for better accuracy if your machine can carry it — the default
is `small`. Audio never leaves the machine either way.

## What's different on Windows

Everything above works the same. Two notes:

- Secrets (the Beeper token, email app passwords) are stored in Windows
  Credential Manager, which needs one extra package: `pip install keyring`.
- Phone access via Tailscale is found automatically (PATH or the default
  install folder).

## Passing it on

Like it? Don't copy your folder — your whole life is in it, including the
git history. Run `python3 brain/tools/share.py --yes` instead: it builds a
clean copy in `dist/` (code and page, every data file empty), scans the
result to prove nothing personal slipped in, and zips it. Send the zip.

## Updating a brain you got from someone

When a newer zip arrives, don't start over — update in place. Your
workstreams, people, settings and history all stay exactly as they are;
only the code (tools, commands, pages) changes:

```
python3 brain/tools/update.py ~/Downloads/life-brain-<date>.zip        # preview
python3 brain/tools/update.py ~/Downloads/life-brain-<date>.zip --yes  # apply
```

New settings arrive with sensible defaults; every value you changed keeps
your value. Replaced files are archived under `brain/archive/` and your git
gets a snapshot first, so the whole update is undoable. If your current
version is old enough that `update.py` doesn't exist yet, unzip the new
package anywhere and run it from there instead:

```
python3 path/to/new/life-brain/brain/tools/update.py --into <your brain> --yes
```

Then restart the brain (close the black window, double-click the launcher).

## Connecting your other projects' Claude

If you use Claude Code inside your own repos, those conversations can know
the framework without ever opening this folder:

```
python3 brain/tools/project_prompt.py ~/path/to/repo
```

prints a short briefing — the two-brain boundary, the TODO.md wire, what
the room notes mean — to paste into that repo's conversations or its
CLAUDE.md. Add `--hook` and it also prints the one-time install that pushes
the project's room context into every prompt there automatically.

## How to read the page

The page opens on **Today**, which is a ranked answer to one question:
**what deserves your next hour?** The top is that answer — one thing, big,
with the reason it's there — then today's short plan and an editable week
strip, and a rail with your habits, your routine, and the people waiting on
a reply. The other tabs each hold one part of your life:

- **Plate** — everything you have on, ranked by what is rotting. Each tile
  carries a small decay bar showing how far it has slid toward its
  threshold; the fine stuff sits below, quiet on purpose.
- **People** — everyone you decided to keep warm, grouped by closeness,
  with how long it has been. Owed replies, promises and birthdays surface
  on Today by themselves.
- **Season** — a bucket list for the current stretch of your life, with a
  countdown instead of a nag. Drag an item onto a day when you're ready to
  commit; any calendar app can subscribe to the result.
- **Rooms** — one workspace per project: notes Claude reads before every
  session in that repo, and where tester feedback lands.
- **Map** — everything as one picture, three ways: **Horizon** (by when it
  needs you), **Web** (a mind-map by area), **Circles** (your people by
  closeness). Red = late, amber = they owe you a reply, blue = going cold.
- **Claude** — the ask box, drafts ready for you to send, live sessions,
  and what everything cost.

It also keeps itself fresh: the server re-reads your project folders on a
timer, and the page notices any change — a tick, a Claude session finishing,
an edit you made in a text editor — and reloads itself within seconds. You
never press refresh.

- A workstream where the ball is with someone else and `Since` is more than a
  week old gets flagged **needs a chase** — that's your "do I need to chase?"
  answered automatically.
- A workstream that's yours and untouched for two weeks goes **cold** — that's
  your decay. (Both thresholds are yours to change in `config.json`.)

Every button on the page writes back to the markdown files, so the files and
the page can never disagree. Ticking a task also stamps the workstream as
touched today — ticking *is* touching.

## The "Ask Claude" box

Type what you want — *"chase the letting agency, draft the email for me"* —
pick a mode (just do it / look into it first / draft something / just answer)
and hit **Queue it**. That writes a file into `brain/queue/` and costs
nothing. Next time you open Claude Code here, `/queue` works through them,
and each card on the page gets a "What Claude did" answer.

**Work the queue now** goes one further: it starts Claude Code from the page
and streams what it's doing, live, so you never have to open a terminal. Two
honest warnings: it runs with permission to edit files in this folder (that's
what makes it useful), and each run costs real usage on your Claude
subscription — so batch five asks into one run rather than firing five runs.

## How this works (the part that sounds impossible)

You may have been told a browser page can't touch your computer, so a "sync
button" is impossible. That's true for a page you double-click open
(`file://...`) — browsers wall that off deliberately.

The workaround is that you don't open the page as a file. `serve.py` is a tiny
web server — 400 lines of Python, standard library only — that **you** start,
and it serves the page at `127.0.0.1`, an address only your own machine can
reach. Now the buttons send requests to that little program, and since you
started it, it's allowed to do what you're allowed to do: read your project
folders, rewrite a checkbox in a markdown file, regenerate the page, even
start Claude Code. The browser never touches your computer; your own program
does, and the page is just its remote control.

No server on the internet, nothing uploaded anywhere, nothing running when the
Terminal window is closed.

## The files, honestly

| | |
|---|---|
| `brain/workstreams.md` | **The whole system.** Everything else is a view of this file. |
| `brain/next.md` | The 3–5 things worth your next free hour. Claude re-ranks it. |
| `brain/people.md` | The relationships you decided to keep warm, and whether they are. |
| `brain/habits.md`, `goals.md`, `season.md` | What you're building in yourself, your finish lines, and the season's bucket list. |
| `brain/waiting.md` | Small "waiting on someone" items that don't merit a workstream. |
| `brain/inbox.md` | Dump one-liners here (or the Capture button). Claude sorts them. |
| `brain/decisions.md` | Choices you've made, append-only, so you stop re-deciding them. |
| `brain/config.json` | Your decay thresholds and your project folders. |
| `brain/index.html`, `map.html`, `synced.md` | **Generated. Never edit these** — edit the markdown and they rebuild. |

Because it's all markdown, nothing is locked in: it works in Obsidian, greps
fine, diffs fine, and if you ever abandon the tooling the files still read as
plain English.

## Day-to-day rhythm

- Something new lands in your head → **Capture** button, one line, move on.
- Each morning → `/today` writes a three-item plan sized to your real day
  (or the 7am job writes it before you're up).
- Sitting down to work → `/brief`. Six sentences on where everything stands,
  inbox triaged, page rebuilt.
- Getting up → `/wrap`. What happened gets written back so next week's you
  isn't relying on this week's memory.
- A head too full to sort → `/dump`. Talk in any order; everything gets
  filed and nothing is lost.
- Any moment of "wait, what am I forgetting?" → open the page. The tiles
  answer it.

## If something breaks

- **Page won't load** → is the black window with `serve.py` still open?
- **`Open Brain.bat` flashes and vanishes, or says Python isn't installed** →
  install Python from python.org and tick **"Add python.exe to PATH"** in the
  installer. If Python is already installed, re-run the installer, choose
  Modify, and tick it there.
- **Buttons say the page can't write** → you opened `index.html` as a file;
  start the brain with the launcher instead.
- **A workstream isn't showing up** → its `Status:` line is probably a word
  the system doesn't know. Stick to: Moving, Stalled, Blocked, Waiting,
  Not started, Done, Dropped, Parked.
- **Port already in use** → set the environment variable `BRAIN_PORT` to
  another number (e.g. `set BRAIN_PORT=7799` on Windows,
  `BRAIN_PORT=7799 python3 brain/tools/serve.py` on Mac/Linux).
- **Paths in `config.json` on Windows** → write them with forward slashes or
  doubled backslashes: `"C:/Users/you/projects/thing"` works,
  `"C:\\Users\\you\\projects\\thing"` works, single backslashes break JSON.
- Anything else → open Claude Code here and describe it. It has instructions
  (`CLAUDE.md`) that explain how the whole thing fits together.
