#!/usr/bin/env python3
"""Build brain/index.html — the page you actually read.

    python3 brain/tools/build.py

GENERATED. Never hand-edit index.html; edit the markdown and rebuild, or your
change disappears the next time anything runs. The markdown is the system; this
file only decides how it looks.

The design has one idea: the page is a ranked answer to "what deserves my next
hour?", not a wall of equal cards. The top priority gets the hero; the rest of
the urgent list is a numbered stack with decay bars; everything calm is pushed
down and quieted so the urgent things own the contrast.

Self-contained: everything it needs is bundled, so it renders with no netwraries. Works opened as
a plain file, but the buttons only write when it is served (see serve.py).
"""

import html
import json
import os
import re
import urllib.parse
import sys
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import md as MD          # noqa: E402
import model as M        # noqa: E402
import usage as USAGE    # noqa: E402  (per-job "last ran" on the Claude tab)
import tour as TOUR      # noqa: E402  (the guided walkthrough)
import chrome as CHROME  # noqa: E402  (one nav for every page)
import talk as TALK      # noqa: E402  (dictation on Claude-facing inputs)
import news as NEWS      # noqa: E402  (the briefing on the News tab)

BRAIN = M.BRAIN
OUT = os.path.join(BRAIN, "index.html")


def now_minutes():
    """Minutes since midnight, in one place, so every part of the page agrees
    about what time it is. Before this, exactly one line in the whole builder
    read the clock — which is how the routine card came to say "Evening" while
    the hero above it still said "Your next hour" and the forecast still
    offered three hours that had already gone.

    BRAIN_NOW=HH:MM overrides it. That is for checking the page at nine in the
    morning and at ten at night without waiting thirteen hours.
    """
    stamp = os.environ.get("BRAIN_NOW", "").strip()
    if stamp:
        m = re.match(r"^(\d{1,2}):(\d{2})$", stamp)
        if m:
            return min(23, int(m.group(1))) * 60 + min(59, int(m.group(2)))
    n = datetime.now()
    return n.hour * 60 + n.minute


def hero_eyebrow():
    """The hero's label follows the day. "Your next hour" is a promise the
    page cannot keep at ten at night, and breaking it is what made the whole
    top of the page read as stale."""
    return {"morning": "Your next hour",
            "evening": "Still open tonight",
            "closed": "First thing tomorrow"}[day_phase()]


def day_phase():
    """morning | evening | closed — the day as the page should speak about it.
    17:00 is where the routine already turns the plan into a mirror, and 22:00
    is where the When card already stops drawing the day."""
    mins = now_minutes()
    if mins >= M.DAY_END_MINUTES:
        return "closed"
    return "evening" if mins >= 17 * 60 else "morning"


def read(name):
    try:
        with open(os.path.join(BRAIN, name), encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def e(s):
    return html.escape(str(s or ""), quote=True)


# --------------------------------------------------------------------------
# The queue — requests written from the page, worked by Claude Code.

# The People intro (rhythm-load advice + sync note) is read-once: one
# dismiss hides it on this device until the text would matter again.
_PINTRO_JS = """<script>
(function(){
  var pi = document.getElementById('pintro');
  if(!pi) return;
  var seen = null;
  try { seen = localStorage.getItem('people-intro-seen'); } catch(e){}
  if(!seen) pi.hidden = false;
  var x = document.getElementById('pintrox');
  if(x) x.onclick = function(){
    pi.hidden = true;
    try { localStorage.setItem('people-intro-seen', '1'); } catch(e){}
  };
})();
</script>"""

_WS_ROOM_CACHE = None


def _ws_room_slug(name):
    """workstream -> its room on rooms.html, from the rooms config."""
    global _WS_ROOM_CACHE
    if _WS_ROOM_CACHE is None:
        _WS_ROOM_CACHE = {}
        try:
            with open(os.path.join(BRAIN, "config.json"), encoding="utf-8") as f:
                cfg = json.load(f)
            for wing in ((cfg.get("rooms") or {}).get("wings") or []):
                for room in (wing.get("rooms") or []):
                    sl = room.get("slug") or M.room_slug(room.get("name", ""))
                    for wsn in (room.get("ws") or []):
                        _WS_ROOM_CACHE[wsn] = sl
        except Exception:
            pass
    return _WS_ROOM_CACHE.get(name, "")


def queue_items():
    qdir = os.path.join(BRAIN, "queue")
    out = []
    if not os.path.isdir(qdir):
        return out
    for fn in sorted(os.listdir(qdir)):
        if not fn.endswith(".md") or fn.startswith("_"):
            continue
        try:
            with open(os.path.join(qdir, fn), encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        meta, body = MD.split_frontmatter(text)
        outcome = ""
        m = re.search(r"^##\s+Outcome\s*$(.*)", body, re.M | re.S)
        if m:
            outcome = m.group(1).strip()
            body = body[:m.start()]
        out.append({
            "file": fn,
            "title": meta.get("title", fn[:-3]),
            "status": (meta.get("status") or "pending").lower(),
            "mode": meta.get("mode", ""),
            "created": meta.get("created", ""),
            "body": body.strip(),
            "outcome": outcome,
        })
    rank = {"working": 0, "pending": 1, "done": 2, "dropped": 3}
    # Active items oldest-first (a queue is FIFO); finished ones newest-first
    # (what just happened belongs on top of the pile).
    active = sorted((q for q in out if rank.get(q["status"], 9) < 2),
                    key=lambda q: (rank[q["status"]], q["created"]))
    closed = sorted((q for q in out if rank.get(q["status"], 9) >= 2),
                    key=lambda q: q["created"], reverse=True)
    return active + closed


# --------------------------------------------------------------------------
# Derived display pieces

def artvid(name, size=132, cls="cardart"):
    """A looping mascot clip. Poster and video share a base name and the same
    framing, so nothing jumps when the video takes over.

    Video cannot carry alpha, so these rely on `mix-blend-mode: multiply`
    against the paper — which only disappears if the clip's ground is PURE
    white, and Veo's is a few points under. The CSS lifts it the rest of the
    way; see .artvid.
    """
    return (f'<video class="artvid {cls}" autoplay muted loop playsinline '
            f'poster="art/{name}.png?v=2" width="{size}" height="{size}" '
            f'aria-hidden="true">'
            f'<source src="art/{name}.mp4?v=2" type="video/mp4"></video>')


def artimg(name, size=72, cls="cardart"):
    """A still. These are real transparent PNGs, so they must NOT get the
    multiply treatment — it would darken the olive against the paper for no
    reason. Different class on purpose."""
    return (f'<img class="artpng {cls}" src="art/{name}.png?v=2" alt="" '
            f'width="{size}" height="{size}" aria-hidden="true">')


def cardhead(inner, art=""):
    """A card's heading with its mascot beside it, as a flex row.

    Floating the art instead put it in the flow of the rows below, and an
    `<li>` that is a flex container is a block-formatting-context root — so
    it shortens itself to avoid a float. That is exactly why one row's
    buttons sat left of every other row's. A row of its own cannot collide
    with anything.
    """
    if not art:
        return inner
    return f'<div class="cardhead">{inner}<span class="cardhead-art">{art}</span></div>'


def heroline(eyebrow_html, art=""):
    """The hero's eyebrow and its mascot on one row — the same shape every
    other card uses.

    The hero used to float its mascot right, which parked it a gutter's width
    from the routine card's own mascot: two brains at the same height staring
    at each other across the page. On the left of its own heading it reads as
    this section's picture, like every other one, and the two are at opposite
    ends of the row.
    """
    return cardhead(f'<div class="heroline">{eyebrow_html}</div>', art)


def clip(s, n):
    """Cut to a word boundary, not mid-word. A label ending "finish &" reads
    like a bug even when the data behind it is right."""
    s = (s or "").strip()
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0].rstrip(" ,;:—-&")
    return (cut or s[:n]) + "…"


def why_line(w, hero=False, skip_task="", plain_urgent=False):
    """The one sentence that says why this is at the top. Plain words a person
    can act on beat a coloured dot they have to decode.

    `skip_task` is the text the CALLER is already showing. The reason and the
    task name are two different fields that usually resolve to the same
    sentence, and the hero was printing both four lines apart — the urgency
    ("needed doing 13 days ago") is the part she cannot work out for herself,
    so that stays and the restatement goes.

    `plain_urgent` drops the "you marked this urgent" badge and leads with the
    task. She marks nearly everything urgent, so the flag lands on a third of
    the priority stack and most of the digest — at that density it sorts
    nothing, and it eats the width the row needs to say WHICH thing it is.
    """
    def tail(task):
        task = task or ""
        if not task or (skip_task and _same_thing(task, skip_task)):
            return ""
        return f" &mdash; {e(task)}"

    bits = []
    if w["overdue"]:
        d = abs(w["days_to_due"])
        bits.append(f"<b>{d} day{'s' if d != 1 else ''} overdue</b>")
    elif w["due_soon"]:
        d = w["days_to_due"]
        bits.append("<b>due today</b>" if d == 0 else f"due in <b>{d} day{'s' if d != 1 else ''}</b>")
    # The lead-time reason first, because it is the one she cannot work out
    # for herself. "Due the 24th" looks calm in the middle of the month; "the
    # seat should have been bought a week ago" is the same fact, acted on.
    if w.get("pressed_late"):
        d = abs(w.get("pressed_act_days") or 0)
        bits.append(f'<b>needed doing {d} day{"s" if d != 1 else ""} ago</b>'
                    + tail(w.get("pressed_task", "")))
    elif w.get("pressed_lead") and (w.get("pressed_act_days") or 99) <= 7:
        d = w.get("pressed_act_days") or 0
        when = "today" if d == 0 else f"in {d} day{'s' if d != 1 else ''}"
        bits.append(f"<b>do this {when}</b>" + tail(w.get("pressed_task", "")))
    elif w.get("task_overdue"):
        bits.append("<b>a task inside is overdue</b>"
                    + tail(w.get("next_due_task", "")))
    elif w.get("task_urgent"):
        t = w.get("next_due_task", "")
        if not plain_urgent:
            bits.append("<b>you marked this urgent</b>" + tail(t))
        elif t and not (skip_task and _same_thing(t, skip_task)):
            # WHICH task she flagged still discriminates even where the flag
            # itself doesn't — unless the row already has that task on its
            # face, in which case the whole reason line goes quiet. A row with
            # nothing to add says nothing.
            bits.append(e(t))
    elif w.get("task_due_soon") and not w["due_soon"] and not w["overdue"]:
        bits.append("a task inside is due soon"
                    + tail(w.get("next_due_task", "")))
    if w.get("goal_pull") and not w.get("goal_overdue"):
        d = w.get("goal_days")
        if d is not None and d <= 45:
            bits.append(f'your finish line is in <b>{d} days</b> &mdash; {e(w.get("goal_text", ""))}')
    if w["chase"]:
        who = f" from {e(w['ball_who'])}" if w["ball_who"] else ""
        bits.append(f"silence{who} for <b>{w['days_waiting']} days</b>")
    if w["cold"]:
        bits.append(f"untouched for <b>{w['days_untouched']} days</b>")
    if w["never_touched"] and not w["cold"]:
        bits.append("never started")
    if w.get("stale_text"):
        s2 = w["stale_text"][0]
        bits.append(f'written before <b>{e(s2["label"])}</b>, which has passed'
                    " &mdash; the next session will reword it")
    if w["status"] == "blocked" and not bits:
        bits.append("blocked")
    return " &middot; ".join(bits)


def decay(w, cfg):
    """0..1: how far this item has slid toward its threshold. The bar under
    each priority row — you can see things rotting before they're rotten."""
    if w["overdue"]:
        return 1.0
    vals = []
    if w["ball"] == "them" and w["days_waiting"] is not None:
        vals.append(w["days_waiting"] / max(int(cfg.get("chase_days", 7)), 1))
    if w["days_untouched"] is not None:
        vals.append(w["days_untouched"] / max(int(cfg.get("cold_days", 14)), 1))
    if w["days_to_due"] is not None and w["days_to_due"] >= 0:
        # Deadline pressure: full as the date arrives.
        span = max(int(cfg.get("soon_days", 7)), 1)
        vals.append(1.0 - min(w["days_to_due"], span) / span)
    if w["never_touched"]:
        vals.append(0.85)
    return min(max(vals, default=0.0), 1.0)


# The chip must say what it means on its own: whose court the next move is in.
BALLS = {"me": ("on you", "mine"), "them": ("with them", "wait"),
         "nobody": ("no one waiting", "unk")}


def ballchip(w):
    label, cls = BALLS[w["ball"]]
    who = f" &middot; {e(w['ball_who'])}" if w["ball"] == "them" and w["ball_who"] else ""
    return f'<span class="v v-{cls}">{label}{who}</span>'


def actions(w, labelled=False):
    """Grouped, not five identical pills in a row: what you do most (add a
    task, mark it worked) sits on the left, whose-court is one labelled
    control, and Claude is the odd one out on the right. `labelled` names
    the workstream in the row — on the hero, other cards sit between the
    title and these buttons and the scope stops being obvious.

    Ten controls on the hero was more decision than the thing itself needed.
    "Not today" and "Snooze" were one gesture wearing two labels, so Snooze
    keeps it and says how long; "Done" is irreversible and sat directly beside
    "Worked on it today", the one you press most, so it moves to the far end.

    Eight was still eight, all the same shape, and reading them took longer
    than doing any of them. Four now — add work, mark it worked, whose move,
    the way in — and the five you reach for occasionally live behind one "…".
    Done goes in there on purpose: it cannot be undone and should not be one
    stray tap from the button you press most.
    """
    n = e(w["name"])
    lab = (f'<span class="actsfor">for {n}:</span>' if labelled else "")
    me = " on" if w["ball"] == "me" else ""
    them = " on" if w["ball"] == "them" else ""
    focused = bool(w.get("focus_until"))
    foc = "&#9733; Focused" if focused else "&#9734; Focus on this"
    return ('<div class="acts needs-server">' + lab
            + f'<button class="act" data-addtask="{n}"><b>+</b> Task</button>'
            + f'<button class="act" data-touch="{n}" title="Stamps today as the last '
            f'day you touched this &mdash; resets its going-cold clock">Worked on it today</button>'
            '<span class="ballgroup" role="group" aria-label="Whose court">'
            '<span class="balllabel" title="Whose move is next on this">Next move</span>'
            f'<button class="ball{me}" data-ball="me" data-name="{n}">mine</button>'
            f'<button class="ball{them}" data-ball="them" data-name="{n}">theirs</button>'
            "</span>"
            f'<button class="act" data-wsopen="{n}" title="The whole project on one '
            'side screen: dates, people, tasks, notes, its folder">Details</button>'
            # everything below is real but occasional — one button, not five
            + '<span class="moreWrap">'
            + f'<button class="act moreBtn" aria-haspopup="true" aria-expanded="false"'
            f' data-more="{n}" title="Focus, snooze, tell Claude, mark it done">'
            '&hellip;</button>'
            + '<span class="moreMenu" hidden>'
            + f'<button class="mi wsfocus{" on" if focused else ""}"'
            f' data-wsfocus="{n}" data-until="{e(w.get("focus_until") or "")}"'
            ' title="Work on this for a few days — it holds the top of the list '
            'without you inventing a task, and lapses by itself">' + foc + "</button>"
            + f'<button class="mi" data-snooze="{n}" title="Out of sight until a wake '
            'date you pick — it comes back by itself, nothing is lost">Snooze&hellip;</button>'
            + f'<button class="mi" data-ask="{n}">Tell Claude</button>'
            + '<span class="misep"></span>'
            + f'<button class="mi danger wsdone" data-wsdone="{n}"'
            ' title="Finished — it leaves the plate">&#10003; Done</button>'
            + "</span></span>"
            "</div>")


# Names of everyone in people.md, longest first — set once per build so task
# text can link "Ellis" straight to Ellis on the People tab.
PERSON_NAMES = []
# alias → the person it belongs to ("Mum" → "Maman"), set per build
PERSON_ALIAS = {}


def linknames(escaped):
    """Wrap known person names in already-escaped text with a People-tab link.
    Aliases count: "Mum" is a door to Maman, because that is the word she
    writes — and the alias pass runs LAST behind a placeholder, so the
    canonical pass cannot rewrite a name sitting inside the link it just
    made (which produced nested anchors)."""
    for nm in PERSON_NAMES:
        enm = e(nm)
        pat = re.compile(r"\b" + re.escape(enm) + r"\b")
        if not M.name_in(enm, escaped):
            continue                 # "May merge…" is grammar, not the person
        if pat.search(escaped):
            escaped = pat.sub(
                f'<a class="plink" href="#people" data-plink="{enm}">{enm}</a>',
                escaped, count=1)
    # Aliases afterwards, with the target name hidden in a placeholder so no
    # later pass can see it as prose.
    for al in sorted(PERSON_ALIAS, key=len, reverse=True):
        eal = e(al)
        if "data-plink" in escaped and eal in escaped.split(">")[0]:
            continue
        if not M.name_in(eal, escaped):
            continue
        pat = re.compile(r"\b" + re.escape(eal) + r"\b(?![^<]*>)")
        if pat.search(escaped):
            who = "\x00" + e(PERSON_ALIAS[al]) + "\x00"
            escaped = pat.sub(
                f'<a class="plink" href="#people" data-plink="{who}">{eal}</a>',
                escaped, count=1)
    return escaped.replace("\x00", "")


# Live workstream names, longest first — set per build alongside PERSON_NAMES.
WS_NAMES = []
# Recent done queue outcomes attached to their workstreams — set per build.
WS_OUTCOMES = {}


def prepared_fold(wsname, open_fresh=False):
    """The '✦ Claude prepared this' block: recent outcomes rendered ON the
    thing they belong to — the train options live on the Ellis hero, not
    only in the Claude tab archive. Open by default when the work landed
    today and the caller asks (the hero); a quiet fold everywhere else."""
    its = WS_OUTCOMES.get((wsname or "").lower(), [])
    if not its:
        return ""
    today_s = date.today().isoformat()
    is_open = open_fresh and (its[0]["created"] or "")[:10] == today_s
    # Only the NEWEST outcome shows in full — an older card's "what you need
    # to do" list is stale the moment newer work supersedes it. Earlier items
    # fold away instead of stacking up as clutter.
    def _item(i):
        return ('<div class="prepitem">' + linkify_html(MD.render(i["outcome"]))
                + f'<p class="meta">{e(i["created"])} &middot; '
                '<a href="#/claude">the full card</a></p></div>')
    inner = _item(its[0])
    if len(its) > 1:
        inner += ('<details class="prepolder"><summary>earlier work '
                  f'({len(its) - 1}) &mdash; superseded</summary>'
                  + "".join(_item(i) for i in its[1:3]) + "</details>")
    # The response is a conversation, not a verdict: a follow-up asked right
    # here continues from what was already found instead of starting over.
    ask = ('<div class="prepask needs-server">'
           f'<input class="prepin" data-prepctx="{e(its[0]["title"][:90])}"'
           f' data-prepws="{e(wsname)}" autocomplete="off"'
           ' placeholder="Ask a follow-up &mdash; continues from this&hellip;">'
           '<button class="mini prepgo">ask &amp; run</button>'
           f'<button class="mini prepshot" data-shotctx="{e(its[0]["title"][:90])}"'
           f' data-shotws="{e(wsname)}" title="Bought it / did it? Attach the '
           'confirmation screenshot &mdash; Claude ticks the task and files the '
           'details">done &mdash; add screenshot</button></div>')
    return (f'<details class="prep"{" open" if is_open else ""}>'
            f'<summary>&#10022; Claude prepared this'
            f'{f" &middot; {len(its)}" if len(its) > 1 else ""}</summary>'
            + inner + ask + "</details>")


def ready_marks(drafts, qitems, ws, today_md):
    """Finished Claude work, mapped back to the task row it came from.

    She asks for help from a task row, the work lands in a draft or a queue
    outcome, and then she has to go looking for it — which is the whole
    complaint. Two links already exist in the data and were going unused: a
    draft's `task:` field, and the task name the row's &#10022; button writes
    into the ask's title. Both resolve to the row's own tick key, so the row
    can say "this one is answered" and open the answer.

    Returns {taskkey: [{kind, file, label, id, created}, ...]}, newest first.
    """
    # Every task the page can show a row for, keyed the way its tickbox is.
    rows = {}                      # taskkey -> normalised text
    def _add(raw):
        try:
            key = MD.taskkey(MD.bare(raw))
        except Exception:
            return
        n = M._dnorm(MD.plain(raw))
        if len(n) >= 16:
            rows.setdefault(key, n)
    for mt in re.finditer(r"^\s*[-*]\s+\[[ xX]\]\s+(.*)$", today_md or "", re.M):
        _add(mt.group(1))
    for w in ws:
        for t in w["tasks"]:
            _add(t["text"])

    marks = {}
    def _hit(needle, kind, file, label, created, ident):
        if len(needle) < 16:
            return
        for key, n in rows.items():
            # A queue title is truncated to ~60 chars, so a prefix counts.
            if needle in n or n in needle or n.startswith(needle):
                marks.setdefault(key, []).append(
                    {"kind": kind, "file": file, "label": label,
                     "created": created, "id": ident})
                return

    for d in drafts:
        if d.get("stale") or not d.get("task"):
            continue
        _hit(M._dnorm(d["task"]), "draft", d["file"],
             {"email": "draft ready", "message": "draft ready",
              "form": "form text ready"}.get(d["kind"], "notes ready"),
             d.get("created", ""), "d:" + d["file"])

    for it in qitems:
        if it["status"] != "done" or not it["outcome"]:
            continue
        m = re.search(r"(?:for me|task)\s*:\s*[\"“]([^\"”]+)",
                      it["title"] or "")
        if not m:
            continue
        _hit(M._dnorm(m.group(1)), "work", it["file"], "Claude answered",
             it.get("created", ""), "q:" + it["file"])

    for key in marks:
        marks[key].sort(key=lambda x: x["created"] or "", reverse=True)
    return marks


def ready_templates(marks):
    """The grafts themselves. Templates rather than inline markup because the
    same row is rendered in three places (the plan, the plate, a drawer) and
    the JS puts the pill on whichever copies exist."""
    if not marks:
        return ""
    out = ['<div id="rdytpls" hidden>']
    for key, its in marks.items():
        i = its[0]
        extra = f' &middot; {len(its)}' if len(its) > 1 else ""
        out.append(
            f'<template class="rdytpl" data-rdykey="{e(key)}"'
            f' data-rdyid="{e(i["id"])}">'
            f'<button class="rdy" data-rdykind="{e(i["kind"])}"'
            f' data-rdyfile="{e(i["file"])}" data-rdyid="{e(i["id"])}"'
            ' title="Claude already did this one &mdash; open what it wrote">'
            f'&#10022; {e(i["label"])}{extra}</button></template>')
    out.append("</div>")
    return "".join(out)


def ask_label(item, cap=64):
    """A short human label for a queued ask — markdown stripped, cut at a word
    boundary. An ask sent from a room opens with a context preamble the page
    wrote, so every card in a room read "About the project X (workstream…" and
    none of them said what she had actually asked. Her own words follow "The
    ask:", and those are the label when they are there."""
    body = item.get("body") or ""
    m = re.search(r"The ask:\s*(.+)", body)
    src = (m.group(1) if m
           else (item.get("title") or body or item.get("file") or "")).strip()
    t = re.sub(r"\s+", " ", MD.plain(src.split("\n")[0]))
    if len(t) > cap:
        t = t[:cap].rsplit(" ", 1)[0] + "…"
    return t


def draft_label(fname):
    """A draft's file name as words: 2026-09-10-mtr-reponse-bexley.md reads
    "the mtr reponse bexley draft". The date goes; she knows when."""
    stem = re.sub(r"\.md$", "", fname)
    stem = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", stem)
    words = stem.replace("-", " ").replace("_", " ").strip()
    return f"the {words} draft" if words else "the draft"


def linkify_html(html):
    """Turn plain mentions inside already-rendered HTML into doors: person
    names to their People row, workstream names to their drawer. The feed
    becomes the connective tissue of the app instead of a transcript."""
    parts = re.split(r"(<[^>]+>)", html)
    for i, seg in enumerate(parts):
        if not seg or seg.startswith("<"):
            continue
        seg = linknames(seg)
        for wn in WS_NAMES:
            ewn = e(wn)
            pat = re.compile(r"\b" + re.escape(ewn) + r"\b")
            if pat.search(seg):
                seg = pat.sub(f'<a class="plink" href="#" data-wsopen="{ewn}">{ewn}</a>',
                              seg, count=1)
        # A draft mentioned by path becomes a door to the draft itself.
        # "(draft ready in drafts/)" — the shorthand she actually sees
        seg = re.sub(r"\bdrafts/(?![A-Za-z0-9._\-]*\.md)",
                     '<a class="plink draftjump" href="#/claude">Ready for you'
                     ' &#8599;</a>', seg)
        # Named, because two drafts in one paragraph both reading "the draft"
        # is a link she has to click to identify.
        seg = re.sub(r"brain/drafts/([A-Za-z0-9._\-]+\.md)",
                     lambda m2: ('<a class="plink draftjump" href="#/claude"'
                                 f' data-draftjump="{m2.group(1)}">'
                                 + e(draft_label(m2.group(1)))
                                 + " &#8599;</a>"),
                     seg)
        parts[i] = seg
    return "".join(parts)


def room_labels(cfg):
    """Workstream name -> the short room name she uses for it.

    "Dossier — family dossier for Bexley" is the workstream's full name and
    the wrong size for a chip; the room it sits in is called "Dossier Champagne".
    Falls back to the workstream name when a workstream has no room.
    """
    out = {}
    for wing in (cfg.get("rooms", {}).get("wings") or []):
        for room in (wing.get("rooms") or []):
            for name in (room.get("ws") or []):
                if room.get("name"):
                    out[name] = room["name"]
    return out


TALK_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"'
            ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
            ' aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0'
            ' 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>')


def taskrow(t, src="workstreams.md", ws="", show_ws=False, ws_label=""):
    """One task, with its three honest endings behind a menu: done, parked
    until a date, or dropped — and the assistant's hand: a one-tap "Claude
    starts this" on every open task."""
    key = MD.taskkey(MD.bare(t["text"]))
    cls = " ".join(filter(None, [
        "done" if t["done"] else "",
        "parked" if t.get("parked") else "",
        "dropped" if t.get("dropped") else ""]))
    note = ""
    if t.get("dropped"):
        note = f'<span class="tnote">dropped</span>'
    elif t.get("parked"):
        d = t.get("until_days")
        when = "tomorrow" if d == 1 else f"in {d} days" if d and d < 32 else t["until"]
        note = f'<span class="tnote">waiting until {e(t["until"])} &middot; {when}</span>'
    elif t.get("due") and not t["done"]:
        dd = t.get("due_days")
        lab = t.get("due_label") or t.get("due")
        if dd is not None and dd < 0:
            when = f"{abs(dd)}d overdue"
            cls += " tdue-bad"
        elif dd == 0:
            when = "due today"; cls += " tdue-soon"
        elif t.get("due_fuzzy"):
            # a window, not a day: show it as words/range ("due this week")
            when = f"due {lab}"
            if dd is not None and dd <= 7:
                cls += " tdue-soon"
        elif dd is not None and dd <= 7:
            when = f"due in {dd}d"; cls += " tdue-soon"
        else:
            when = f"due {lab}"
        note = f'<span class="tnote tdue">{when}</span>'
    # How long she said it takes, wherever the task appears. "Off your plate in
    # minutes" was listing six things with no durations at all, so the heading
    # was asking to be trusted rather than showing its working — and half of
    # them read long while actually being fifteen-minute jobs.
    est = ""
    if t.get("est") and not t["done"]:
        est = f'<span class="test">{e(M.fmt_dur(t["est"]))}</span>'
    # Which project this belongs to, wherever the task has been lifted out of
    # its workstream. On the plate the heading above already says it; in "Off
    # your plate in minutes" five tasks from five projects looked like one
    # undifferentiated list, and "ask for the cellar breakdown" means nothing
    # without knowing whose cellar.
    wschip = ""
    if show_ws and ws:
        wschip = (f'<button class="tws" data-wsopen="{e(ws)}" title="{e(ws)}'
                  ' — open the project">' + e(ws_label or ws) + "</button>")
    start = ""
    if not t["done"] and not t.get("parked") and not t.get("dropped"):
        start = (f'<button class="ttalk needs-server" data-claudetalk="{e(t["text"])}"'
                 + (f' data-claudews="{e(ws)}"' if ws else "")
                 + ' title="Talk it through — a live conversation that opens'
                 ' already knowing this task and the people in it"'
                 ' aria-label="Talk this through with Claude">'
                 + TALK_SVG + "</button>"
                 f'<button class="tstart needs-server" data-claudestart="{e(t["text"])}"'
                 + (f' data-claudews="{e(ws)}"' if ws else "")
                 + ' title="Claude starts this now: options researched into the task,'
                 ' numbers found, drafts written. It never sends anything."'
                 ' aria-label="Have Claude start this">&#10022;</button>')
    return (f'<li class="{cls}">'
            f'<button class="box tick" aria-pressed="{"true" if t["done"] else "false"}"'
            f' data-src="{src}" data-key="{key}" title="Tick it off">'
            f'{"&#10003;" if t["done"] else ""}</button>'
            f'<span class="ttext">{linknames(e(t["text"]))}{est}{note}</span>'
            f"{wschip}{start}"
            f'<button class="tmenu needs-server" data-task="{key}" data-src="{src}"'
            + (f' data-ws="{e(ws)}"' if ws else "")
            + ' aria-label="More ways to close this">&#8943;</button>'
            "</li>")


def tasklist(w):
    if not w["tasks"]:
        return ""
    return ('<ul class="tasks">'
            + "".join(taskrow(t, ws=w["name"]) for t in w["tasks"]) + "</ul>")


def sevclass(w):
    if w["overdue"] or w.get("task_overdue") or w.get("task_urgent") \
            or w.get("urgent_name"):
        return "sev-bad"
    if w["chase"]:
        return "sev-wait"
    if w["cold"] or w["never_touched"]:
        return "sev-cold"
    if w["due_soon"] or w.get("task_due_soon"):
        return "sev-soon"
    return "sev-none"



def hint(text):
    """A small ? that opens the explanation on tap. The explanation still
    exists; it just stops occupying the page while you already know it."""
    return ('<span class="hintwrap"><button class="hint" aria-expanded="false"'
            ' aria-label="What is this?">?</button>'
            f'<span class="tip" role="note" hidden>{text}</span></span>')


def _mon_day(d):
    """"Oct 17" without strftime's %-d, which Windows spells %#d."""
    return d.strftime("%b") + " " + str(d.day)


def _seasonchip(i):
    """A bucket item as a draggable chip — on a day of the grid or in the
    idea tray. Click opens the exact-date box (also the touch path, since
    touch has no drag-and-drop)."""
    key = MD.taskkey(MD.bare(i["text"]))
    planned = i["planned"]["start"].isoformat() if i["planned"] else ""
    pend = (i["planned"]["end"].isoformat()
            if i["planned"] and i["planned"]["end"] != i["planned"]["start"]
            else "")
    span = ""
    if pend:
        span = f'<span class="szspan">&rarr; {_mon_day(i["planned"]["end"])}</span>'
    who = (f'<span class="szwho">{e(", ".join(i["with"]))}</span>'
           if i["with"] else "")
    rep = ""
    if i["repeat"]:
        n = len(i["did"])
        rep = ('<span class="szrep">' + e(i["repeat"])
               + (f" &middot; {n}&times;" if n else "") + "</span>")
    # title=: the tray clips a chip to one line, so the full wording of a long
    # idea has to be reachable without opening anything.
    return (f'<button class="szchip needs-server" draggable="true"'
            f' data-key="{key}" data-planned="{planned}" data-pend="{pend}"'
            f' data-title="{e(i["text"])}" title="{e(i["text"])}">'
            f'{e(clip(i["text"], 72))}{who}{span}{rep}</button>')


def _seasonrow(i):
    """A bucket item in the list below the grid: tickable, with its people
    and its day where the eye already is."""
    key = MD.taskkey(MD.bare(i["text"]))
    notes = []
    if i["with"]:
        notes.append('<span class="szwho">'
                     + e("with " + ", ".join(i["with"])) + "</span>")
    if i["planned"]:
        lab = _mon_day(i["planned"]["start"])
        if i["planned"]["end"] != i["planned"]["start"]:
            lab += "&ndash;" + _mon_day(i["planned"]["end"])
        notes.append(f'<span class="tnote">{lab}</span>')
    elif i["when_label"] and not i["done"]:
        notes.append(f'<span class="tnote">sometime {e(i["when_label"])}</span>')
    if i["repeat"]:
        n = len(i["did"])
        notes.append('<span class="szrep">' + e(i["repeat"])
                     + (f" &middot; {n}&times; so far" if n else "") + "</span>")
    est = (f'<span class="test">{e(M.fmt_dur(i["est"]))}</span>'
           if i.get("est") and not i["done"] else "")
    tick_tip = ("It happened — logs the date, and it comes back for next time"
                if i["repeat"] else "It happened")
    return (f'<li class="{"done" if i["done"] else ""}">'
            f'<button class="box tick" aria-pressed="{"true" if i["done"] else "false"}"'
            f' data-src="season.md" data-key="{key}" title="{tick_tip}">'
            f'{"&#10003;" if i["done"] else ""}</button>'
            f'<span class="ttext">{linknames(e(i["text"]))}{est}{"".join(notes)}</span>'
            f'<button class="tmenu needs-server" data-task="{key}" data-src="season.md"'
            ' aria-label="More ways to close this">&#8943;</button>'
            "</li>")


_EVLINE = re.compile(
    r"^- (?:(\d{4}-\d{2}-\d{2})(?:\.\.(\d{4}-\d{2}-\d{2}))?\s+[—–-]+\s+)?(.+)$")
_EVURL = re.compile(r"https?://[^\s)\]<>]+")
_MONTHNAMES = ("January February March April May June July August September "
               "October November December").split()


def _eventsview(today):
    """The "Out there" block on the Season tab: the scouted going-out
    shortlist from brain/events.md, rewritten weekly by /scout. Past items
    drop out at render time, so a missed scout week shrinks the list
    instead of letting it lie. Returns (html, count) — the count feeds the
    chip at the top of the tab, because this block sits below a
    full-height planner and was invisible without one.

    Each row carries the two things a listing is for: the booking link, and
    a one-click "put it in my season" that writes the item to season.md
    already slotted on its date. Slotting stays HER action — this is a
    button she presses, never something a run decides."""
    path = os.path.join(BRAIN, "events.md")
    if not os.path.exists(path):
        return "", 0
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except Exception:
        return "", 0
    meta, groups, cur = {}, [], None
    lines = raw.splitlines()
    if lines and lines[0].strip() == "---":
        for n, ln in enumerate(lines[1:], 1):
            if ln.strip() == "---":
                lines = lines[n + 1:]
                break
            k, _, v = ln.partition(":")
            meta[k.strip()] = v.strip()
    for ln in lines:
        ln = ln.rstrip()
        if ln.startswith("## "):
            cur = {"label": ln[3:].strip(), "items": []}
            groups.append(cur)
            continue
        m = _EVLINE.match(ln)
        if not m or cur is None:
            continue
        d1 = d2 = None
        try:
            if m.group(1):
                d1 = date.fromisoformat(m.group(1))
                d2 = date.fromisoformat(m.group(2)) if m.group(2) else d1
        except ValueError:
            pass
        if d2 and d2 < today:
            continue        # it happened; the list only looks forward
        text = m.group(3).strip()
        url = ""
        um = _EVURL.search(text)
        if um:
            url = um.group(0).rstrip(".,;")
            text = _EVURL.sub("", text)
        unconfirmed = bool(re.search(r"\(?unconfirmed\)?", text, re.I))
        text = re.sub(r"\(?unconfirmed\)?", "", text, flags=re.I)
        # Lifting the URL and the unconfirmed tag out of the middle of a line
        # leaves its separators behind, so strip every trailing one, not one.
        text = re.sub(r"(?:\s*[—–]+)+\s*$", "", text.strip()).strip()
        if text:
            cur["items"].append((d1, d2, text, url, unconfirmed))
    groups = [g for g in groups if g["items"]]
    if not groups:
        return "", 0

    def _lab(d1, d2):
        if not d1:
            return ""
        if d2 != d1:
            return f"{_mon_day(d1)} &ndash; {_mon_day(d2)}"
        return d1.strftime("%a") + " " + _mon_day(d1)

    def _add(d1, d2, text):
        """What the ＋ writes into season.md. A one-day event lands already
        slotted; a run of dates (an exhibition open for four months) lands
        in the tray with its month, because pinning a Monet show to its
        opening day would be a guess she then has to undo."""
        t = clip(re.sub(r"\s*[—–]\s*(?:€|from €|free\b).*$", "", text,
                        flags=re.I).strip(), 150)
        if not d1:
            return t
        if d2 != d1:
            return f"{t} (when: {_MONTHNAMES[d1.month - 1]})"
        return f"{t} (planned: {d1.isoformat()})"

    where = meta.get("where", "")

    def _search(text):
        """Everything the listing doesn't answer — is it any good, who else
        is playing, what the room is like. Always present, including on the
        lines that have no ticket page at all."""
        q = re.sub(r"\s*[—–]\s*(?:€|from €|free\b).*$", "", text, flags=re.I)
        q = re.sub(r"\([^)]*\)", "", q).strip()
        return ("https://duckduckgo.com/?q="
                + urllib.parse.quote_plus(f"{q} {where}".strip()))

    rows, n = [], 0
    for g in groups:
        rows.append(f'<p class="szglabel">{e(g["label"])}</p><ul class="szout">')
        for d1, d2, text, url, unconf in g["items"]:
            url = MD.safe_href(url)     # scouted from the web: links only
            n += 1 if d1 else 0     # the undated "Watching for" notes are
            lab = _lab(d1, d2)      # announcements, not things she can go to
            book = (f'<a class="szoutb" href="{e(url)}" target="_blank"'
                    ' rel="noopener noreferrer">Book &#8599;</a>' if url else "")
            # The title is the link too. On a wide screen the button at the
            # far right is a metre away from the words being read, which is
            # how a row full of links reads as a row with none.
            t = e(text)
            title = (f'<a class="szoutt" href="{e(url)}" target="_blank"'
                     f' rel="noopener noreferrer">{t}</a>' if url
                     else f'<span class="szoutt">{t}</span>')
            rows.append(
                '<li>'
                + (f'<span class="szoutd">{lab}</span>' if lab else "")
                + title
                + ('<span class="szunc" title="Not verified on an official '
                   'page — check before you count on it">unconfirmed</span>'
                   if unconf else "")
                + f'<a class="szouti" href="{e(_search(text))}" target="_blank"'
                ' rel="noopener noreferrer" title="Look it up — reviews, the'
                ' lineup, what the room is like">info &#8599;</a>' + book
                # No date, no ＋. The "Watching for" lines are announcements
                # to catch ("that show is sold out"), not things she can put
                # on a day — a ＋ there would file a sentence as a plan.
                + (('<button class="szouta needs-server"'
                    f' data-add="{e(_add(d1, d2, text))}"'
                    ' title="Put this in my season">&#43;</button>')
                   if d1 else "") + "</li>")
        rows.append("</ul>")
    scouted = meta.get("updated", "")
    try:
        scouted = _mon_day(date.fromisoformat(scouted))
    except ValueError:
        pass
    note = " &middot; ".join(x for x in (
        f"last scouted {scouted}" if scouted else "never scouted",
        e(where), "runs weekly") if x)
    return ('<h3 class="szh" id="szout">Out there'
            + f' <span class="meta">{note}</span>'
            + '<button class="mini needs-server" data-job="scout"'
            ' title="Search the web now for what is on where you are. Nothing'
            ' is ever booked.">Scout now</button>'
            + '<span class="meta">&#43; puts one in your season</span>'
            + "</h3>" + "".join(rows)), n


def seasonview(cfg, today):
    """The Season tab: the bucket list for this stretch of life, and the two
    months it has to land in. Ideas without a day sit in the tray; dragging
    one onto a day writes its (planned: …) in brain/season.md. Nothing here
    decays — the number of weekends left is the only pressure."""
    s = M.load_season(today=today)
    if not s:
        return ('<section class="season"><p class="eyebrow">Season</p>'
                '<span class="wav"></span>'
                '<div class="empty">No season yet. Tell Claude the stretch of '
                'life you are in and when it ends &mdash; &ldquo;my last term, '
                'until December 11&rdquo; &mdash; and the bucket list for it '
                'lives here.</div></section>')
    items = [i for i in s["items"] if not i["dropped"]]
    done = [i for i in items if i["done"]]
    opens = [i for i in items if not i["done"]]
    slotted = [i for i in opens if i["planned"]]
    tray = [i for i in opens if not i["planned"]]

    stats = []
    if s["end"]:
        wl = s["weekends_left"]
        stats.append(f'<span class="szstat"><b>{wl}</b> weekend'
                     f'{"s" if wl != 1 else ""} left</span>')
        stats.append(f'<span class="szstat">ends {_mon_day(s["end"])}</span>')
    happened = len(done) + sum(len(i["did"]) for i in items)
    stats.append(f'<span class="szstat"><b>{happened}</b> happened &middot; '
                 f'<b>{len(opens)}</b> to go</span>')
    # The events block lives below a full-height planner, so from up here it
    # may as well not exist. This is its doorbell.
    evhtml, evn = _eventsview(today)
    if evn:
        stats.append(f'<button class="mini" id="szgo"><b>{evn}</b> things on'
                     ' &darr;</button>')
    stats.append('<button class="mini needs-server" id="szplan"'
                 ' title="Claude proposes a day for every idea in the tray —'
                 ' you drag the ones you agree with">Plan my month</button>')
    stats.append('<button class="mini needs-server" id="szsub"'
                 ' title="Subscribe your calendar app to the season: slotted'
                 ' ideas appear as all-day events and move when you drag'
                 ' them">Show in my calendar</button>')
    stats.append(hint(
        "Slotted items double as a calendar feed: subscribe to "
        "<code>http://&lt;this machine&gt;:7718/season.ics</code> from any "
        "calendar app and they appear as all-day events, moving when you "
        "drag them."))

    # Which days already hold real life, so a free Saturday looks free and a
    # booked one doesn't lie. The horizon reaches the season's end (stepped
    # to 30-day marks so the cache key holds still for weeks), and it keeps
    # times and titles — the views show the day's real shape, not a dot.
    busy, calnote, calok = {}, "", False
    hz = 62
    if s["end"] and s["end"] > today:
        hz = min(180, max(62, (((s["end"] - today).days + 14 + 29) // 30) * 30))
    def _dedupe(evs):
        """The HEC feed lists most classes twice — a short spelling and a
        long one with lecturer and room. Same time + one title a prefix of
        the other = one event; keep the detailed spelling."""
        out = []
        for hhmm, t in evs:
            t = html.unescape(t).strip()
            for o in out:
                if o[0] == hhmm and (o[1].lower().startswith(t.lower())
                                     or t.lower().startswith(o[1].lower())):
                    if len(t) > len(o[1]):
                        o[1] = t
                    break
            else:
                out.append([hhmm, t])
        return out

    if cfg.get("calendar"):
        try:
            import calendar_read
            for when, t in calendar_read.events(hz):
                if re.match(r"\s*canceled", t, re.I):
                    continue          # a cancelled slot is a FREE slot
                d8, _, hhmm = when.partition(" ")
                busy.setdefault(d8, []).append([hhmm[:5], t])
            busy = {k: _dedupe(v) for k, v in busy.items()}
            st = calendar_read.status(hz)
            calok = st == "ok"
            if not busy and st != "ok":
                # An unshaded month after a failed or unfinished read must
                # not pass for a free month.
                # This warning is load-bearing: an unshaded grid without it
                # reads as a free month. It goes ABOVE the grid, styled as a
                # warning — as a grey caption underneath it was mistaken for
                # a footnote, which is the one way it could fail.
                calnote = ('<p class="sznote">Your calendar is being read in '
                           'the background &mdash; the busy shading joins '
                           'the grid on the next rebuild.</p>'
                           if st == "warming" else
                           '<p class="sznote warn">The days below are unshaded '
                           'because your calendar could not be read, not '
                           'because they are free. Tell Claude if it '
                           'persists.</p>')
        except Exception:
            busy, calok = {}, False

    # The recurring week shades the season too: a fixed-evening routine
    # (volleyball) books its days as surely as any calendar event does.
    try:
        import routines as RT
        rblocks = []
        for r in RT.load():
            m = RT._CLOCK.search(r["time"] or "")
            rota_days = [dw for dw in RT.DAYS
                         if any(v for v in (r["rota"].get(dw) or []))]
            if m and rota_days:
                rblocks.append((rota_days,
                                f"{int(m.group(1)):02d}:{m.group(2)}",
                                r["name"]))
        for i in range(hz if rblocks else 0):
            d = today + timedelta(days=i)
            dw = RT.DAYS[d.weekday()]
            for rota_days, hhmm, name in rblocks:
                if dw in rota_days:
                    busy.setdefault(d.isoformat(), []).append([hhmm, name])
        for k in busy:
            busy[k].sort()
    except Exception:
        pass

    # The planner renders client-side from this payload: three views (week,
    # month, two months) over the same data, navigable to the season's end
    # without a rebuild.
    payload = {
        "today": today.isoformat(),
        "start": s["start"].isoformat() if s["start"] else "",
        "end": s["end"].isoformat() if s["end"] else "",
        # Whether the calendar was actually read. Without it the weekends view
        # would stamp "free" on every card precisely when it knows least —
        # the same lie the note above the grid exists to prevent.
        "calok": calok,
        "events": busy,
        "chips": [{
            "key": MD.taskkey(MD.bare(i["text"])),
            "title": i["text"],
            "label": clip(i["text"], 44),
            "planned": i["planned"]["start"].isoformat(),
            "pend": (i["planned"]["end"].isoformat()
                     if i["planned"]["end"] != i["planned"]["start"] else ""),
            "with": ", ".join(i["with"]),
            "repeat": i["repeat"],
            "times": len(i["did"]),
        } for i in slotted],
    }
    pjson = MD.json_for_script(payload, ensure_ascii=False)
    months = (
        calnote
        + '<div class="szbar">'
        '<div class="sznav">'
        '<button class="mini" id="szprev" aria-label="Earlier">&lsaquo;</button>'
        '<b id="szlabel"></b>'
        '<button class="mini" id="sznext" aria-label="Later">&rsaquo;</button>'
        '</div>'
        '<div class="szviews" role="tablist">'
        '<button class="szvbtn" data-v="we">Weekends</button>'
        '<button class="szvbtn" data-v="w">Week</button>'
        '<button class="szvbtn" data-v="m">Month</button>'
        '<button class="szvbtn" data-v="mm">2 months</button>'
        '</div></div>'
        '<div id="szplanner"></div>'
        + ('<p class="meta" style="margin:6px 2px 0">Shaded days already '
           'hold something — the deeper the wash, the fuller the day. '
           'Volleyball and the calendar both count.</p>' if busy else "")
        + f'<script type="application/json" id="szdata">{pjson}</script>')

    # The tray groups by the (when:) intention — twenty loose chips are a
    # wall; "September / October / whenever" is a plan taking shape.
    # Items with no month fall back to (fits:), which answers the question
    # actually being asked of the tray: a free Saturday is here, what can
    # land on it? "An afternoon in Paris" and "a day out of Paris" are
    # different answers; sorting them by topic would not be.
    buckets, seen = [], {}
    for i in tray:
        lab = (i["when_label"] or "").strip()
        fits = "" if lab else (i["fits"] or "").strip()
        k = (lab or fits).lower()
        if k not in seen:
            pd = M.parse_due(lab, today) if lab else None
            seen[k] = {"label": lab or fits, "end": pd["end"] if pd else None,
                       "dated": bool(lab), "items": []}
            buckets.append(seen[k])
        seen[k]["items"].append(i)
    # Months first in date order, then the fits groups alphabetically, then
    # the untagged remainder last — it is the pile that still needs a think.
    buckets.sort(key=lambda b: (not b["dated"], b["end"] or date.max,
                                not b["label"], b["label"].lower()))
    rows = []
    for b in buckets:
        lab = e(b["label"]) if b["label"] else "whenever"
        if len(buckets) == 1 and not b["label"]:
            lab = ""
        rows.append('<div class="szgroup">'
                    + (f'<span class="szglabel">{lab}</span>' if lab else "")
                    + "".join(_seasonchip(i) for i in b["items"]) + "</div>")

    trayhtml = ('<div class="sztray" data-day="">'
                '<div class="sztrayhead">'
                '<p class="eyebrow">Ideas without a day'
                + (f' &middot; {len(tray)}' if tray else "") + '</p>'
                '<span class="meta">drag one onto a day, or click it to pick '
                'a date, tick it off, or drop it</span></div>'
                + ("".join(rows) if tray else
                   '<p class="meta">Every idea has a day. Add another below.</p>')
                + '<div class="szadd needs-server">'
                '<input id="szaddin" type="text" maxlength="300"'
                ' placeholder="Something this season should hold&hellip;">'
                '<button class="mini" id="szaddbtn">Add</button></div>'
                "</div>")

    # Only the things that have a day. The tray above already shows every
    # idea that doesn't, and listing all of them twice — chip and row, same
    # words, same order — was most of this page's length.
    bucket = ""
    if slotted:
        bucket = ('<h3 class="szh">Has a day</h3><ul class="tasks">'
                  + "".join(_seasonrow(i) for i in slotted) + "</ul>")
    donehtml = ""
    if done:
        donehtml = ('<h3 class="szh">Happened</h3><ul class="tasks szdone">'
                    + "".join(_seasonrow(i) for i in done) + "</ul>")

    return ('<section class="season"><p class="eyebrow">Season</p>'
            '<span class="wav"></span>'
            f'<h2 class="szname">{e(s["name"])}</h2>'
            + (f'<p class="coach">{e(s["why"])}</p>' if s["why"] else "")
            + f'<div class="szstats">{"".join(stats)}</div>'
            + months + trayhtml + bucket + donehtml
            + evhtml + "</section>")


def season_ics(today=None):
    """brain/season.ics — the slotted season items as all-day events, one
    feed any calendar app can subscribe to (her phone over the tailnet, a
    friend's Outlook on Windows). Regenerated on every rebuild, so a dragged
    chip moves its event on the subscriber's next refresh. This EXPORTS the
    brain's own plans; it never reads or touches her real calendars —
    that direction stays calendar_read/calendar_write's job."""
    s = M.load_season(today=today or date.today())
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             "PRODID:-//life-brain//season//EN",
             "X-WR-CALNAME:Season", "CALSCALE:GREGORIAN"]
    for i in (s["items"] if s else []):
        if not i["planned"] or i["dropped"]:
            continue
        summ = i["text"] + (" — with " + ", ".join(i["with"])
                            if i["with"] else "")
        summ = (summ.replace("\\", "\\\\").replace(";", "\\;")
                .replace(",", "\\,").replace("\n", " "))
        lines += ["BEGIN:VEVENT",
                  f"UID:{MD.taskkey(i['text'])}@life-brain",
                  f"DTSTAMP:{stamp}",
                  # DTEND is exclusive: a one-day event ends the next morning.
                  f"DTSTART;VALUE=DATE:{i['planned']['start'].strftime('%Y%m%d')}",
                  ("DTEND;VALUE=DATE:"
                   + (i["planned"]["end"] + timedelta(days=1)).strftime("%Y%m%d")),
                  f"SUMMARY:{summ}",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    path = os.path.join(BRAIN, "season.ics")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\r\n".join(lines) + "\r\n")
    return path


def _nwpara(p):
    m = re.match(r"(Term worth knowing:|Terms from the week:)\s*(.*)", p)
    if m:
        return (f"<p><b>{html.escape(m.group(1))}</b> "
                f"{html.escape(m.group(2))}</p>")
    return f"<p>{html.escape(p)}</p>"


def _nwglossary():
    """brain/news-glossary.md as a rail box, newest term first — the file
    keeps journal order, the page answers 'what was that word again'."""
    try:
        with open(os.path.join(BRAIN, "news-glossary.md"),
                  encoding="utf-8") as f:
            body = f.read()
    except Exception:
        return ""
    entries = re.findall(r"^- \*\*(.+?)\*\* — (.+?)(?:\s*\*\((.+?)\)\*)?\s*$",
                         body, flags=re.M)
    if not entries:
        return ""
    rows = []
    for term, definition, tag in list(reversed(entries))[:14]:
        rows.append(f"<dt>{html.escape(term)}</dt><dd>{html.escape(definition)}"
                    + (f' <span class="meta">{html.escape(tag)}</span>'
                       if tag else "") + "</dd>")
    n = len(entries)
    more = (f'<p class="meta">All {n} live in news-glossary.md.</p>'
            if n > 14 else "")
    return ('<div class="nrbox nwgloss"><p class="eyebrow">Your glossary</p>'
            '<p class="meta">One term a day, from the breakdowns.</p>'
            "<dl>" + "".join(rows) + "</dl>" + more + "</div>")


def _readmin(text):
    """Minutes at an ordinary reading pace. Only ever called on text the
    page actually holds — a guess from a headline would be a number she
    could not trust, so items without their text simply say nothing."""
    words = len((text or "").split())
    return max(1, round(words / 240)) if words else 0


def _nwitem(i):
    disc = ""
    # Feed links are the outlet's words, not ours: a javascript: one would
    # run on her page, so anything but a web address links nowhere.
    link = MD.safe_href(i["link"]) or "#"
    if i.get("discuss") and i["link"] != i["discuss"] and MD.safe_href(i["discuss"]):
        disc = (f' &middot; <a href="{html.escape(MD.safe_href(i["discuss"]))}"'
                ' target="_blank" rel="noopener">discussion</a>')
    # The reader gets the full article where it can: Guardian text rides in
    # .news.json; other outlets are pulled reader-mode on her click, with
    # the summary as the honest fallback (paywalls, offline).
    tip = ("Speed-read the full article"
           if i.get("body") else
           "Speed-read — pulls the article when it can, else the summary")
    read = (f'<button class="nwread" data-link="{html.escape(i["link"])}"'
            f' data-title="{html.escape(i["title"])}" title="{tip}">'
            "speed-read</button>") if i.get("summary") or i.get("body") else ""
    talk = (f'<button class="nwread nwtalk needs-server"'
            f' data-link="{html.escape(i["link"])}"'
            f' data-title="{html.escape(i["title"])}"'
            f' data-outlet="{html.escape(i["outlet"])}"'
            ' title="Open a conversation about this article">'
            "talk to Claude</button>")
    # The same three actions sit under all thirty-odd stories. At rest the
    # line is just the outlet and the time — what she actually scans.
    # How long it takes to read, but only where the page holds the article.
    # Most outlets arrive as a headline, so most stories carry no number.
    mins = _readmin(i.get("body"))
    dur = f" &middot; {mins} min" if mins else ""
    acts = ('<span class="nwacts">' + disc
            + (f" &middot; {read}" if read else "")
            + f" &middot; {talk}</span>")
    return ('<article class="nwitem">'
            f'<a class="nwhead" href="{html.escape(link)}" target="_blank"'
            f' rel="noopener">{html.escape(i["title"])}</a>'
            f'<p class="meta">{html.escape(NEWS._item_meta(i))}{dur}{acts}</p>'
            + (f'<p class="nwsum">{html.escape(i["summary"])}</p>'
               if i.get("summary") else "")
            + "</article>")


def newsview(cfg):
    """The News tab: the day's briefing, built mechanically by news.py from
    the outlets in config — no model reads or writes a word of it. The
    morning job refreshes it; so do /brief, /wrap and the Refresh button."""
    data = None
    try:
        with open(os.path.join(BRAIN, ".news.json"), encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        pass
    topics = [i.get("topic", "")
              for i in ((cfg.get("news") or {}).get("interests") or [])]
    chips = "".join(
        f'<span class="nwchip">{html.escape(t)}'
        f'<button class="nwdel needs-server" data-topic="{html.escape(t)}"'
        f' title="Stop following {html.escape(t)}">&times;</button></span>'
        for t in topics)
    upd = ""
    if data:
        try:
            dt = datetime.strptime(data["updated"], "%Y-%m-%d %H:%M")
            upd = (dt.strftime("%A %d %B").replace(" 0", " ")
                   + " &middot; updated " + dt.strftime("%H:%M"))
            if (datetime.now() - dt).total_seconds() > 18 * 3600:
                upd += " &mdash; press Refresh for today&rsquo;s"
        except Exception:
            upd = f'updated {html.escape(data["updated"])}'
    topicbox = ('<div class="nrbox"><p class="eyebrow">Following</p>'
                '<div class="nwints">' + chips
                + '<input id="nwaddin" class="needs-server" maxlength="60"'
                ' placeholder="Follow a topic&hellip;" autocomplete="off">'
                '<button class="mini needs-server" id="nwaddbtn">Add</button>'
                "</div></div>")
    head = ('<section class="newsv"><p class="eyebrow">News</p>'
            '<div class="nwtop"><h2>Your briefing</h2>'
            + '<button class="mini needs-server" id="nwrefresh">Refresh</button>'
            '</div>'
            + (f'<p class="nwdate">{upd}</p>' if upd else ""))
    have = data and (data.get("front")
                     or any(t["items"] for t in data.get("topics", [])))
    if not have:
        return (head + topicbox
                + '<div class="empty">No briefing yet. Press Refresh '
                "&mdash; after that it rebuilds itself each morning.</div>"
                "</section>")
    main = []
    if data.get("guardian") == "rss":
        main.append('<p class="meta">The Guardian is on headlines only '
                    "&mdash; its free API key unlocks full excerpts. Tell "
                    "Claude to set it up.</p>")

    def expbox(eyebrow, text):
        paras = "".join(_nwpara(p.strip())
                        for p in text.splitlines() if p.strip())
        # The breakdown looks like a wall next to the headlines around it.
        # Its length is the one thing she can't see before starting, so say it.
        return ('<div class="nwexplain"><div class="nwexphead">'
                f'<p class="eyebrow">{eyebrow}</p>'
                f'<span class="nwexpact">{_readmin(text)} min &middot; '
                '<button class="nwread" title="Speed-read this">'
                "speed-read</button></span></div>" + paras + "</div>")

    def block(title, items, explainer=""):
        if not items:
            return
        exp = expbox("In plain terms", explainer) if explainer else ""
        main.append(f'<div class="nwsec"><h3>{html.escape(title)}</h3>' + exp
                    + "".join(_nwitem(i) for i in items) + "</div>")

    block("The front page", data.get("front") or [])
    for t in data.get("topics", []):
        block(t["topic"], t["items"], t.get("explainer") or "")
    for r in data.get("recaps") or []:
        if r.get("text"):
            main.append('<div class="nwsec">'
                        f'<h3>The week in {html.escape(r["topic"])}</h3>'
                        + expbox("Sunday recap", r["text"]) + "</div>")
    if data.get("failed"):
        names = ", ".join(f["name"] for f in data["failed"])
        main.append(f'<p class="meta">Couldn&rsquo;t reach {html.escape(names)}'
                    " on the last fetch.</p>")
    # The reading column keeps a text measure; the rail spends the rest of
    # a wide screen on the controls and the glossary instead of whitespace.
    return (head + '<div class="newsgrid"><div class="newsmain">'
            + "".join(main) + "</div>"
            + '<aside class="newsrail">' + topicbox + _nwglossary()
            + "</aside></div></section>")



# --------------------------------------------------------------------------
# Appearance: the palette is generated from three seeds so it can be a
# person's own — a neutral BASE (paper tint), an ACCENT (the "yours/good"
# hue), and a FONT pairing. The semantic colours (bad/wait/cold) stay fixed
# because they carry meaning; only personality moves.

BASES = {          # neutral hue, and a chroma multiplier for how tinted it is
    "warm":  (100, 1.0),
    "cool":  (250, 0.9),
    "rose":  (20, 1.0),
    "mono":  (100, 0.18),
}
ACCENTS = {        # the primary/"yours" hue
    "olive": 135, "forest": 150, "teal": 185, "ocean": 245,
    "indigo": 280, "plum": 325, "rose": 12, "amber": 70,
}
FONTS = {
    "editorial": ("'Literata',Georgia,serif", "'Schibsted',-apple-system,sans-serif"),
    "clean":     ("'Schibsted',-apple-system,sans-serif", "'Schibsted',-apple-system,sans-serif"),
    # Chunky, characterful headings over a clean body — the hand-drawn layer.
    "playful":   ("'Bricolage',Georgia,sans-serif", "'Schibsted',-apple-system,sans-serif"),
    # The 2026 redesign's own pairing: a tall condensed display voice over a
    # quiet workhorse sans, with Petrona italic carrying the coaching lines.
    "brain":     ("'Darker','Bricolage',Georgia,sans-serif",
                  "'Figtree','Schibsted',-apple-system,sans-serif"),
}
# The coaching voice — the italic margin-note sentences — is its own slot,
# because it must stay a serif whatever pairing the display/body use.
COACH_FONT = "'Petrona','Literata',Georgia,serif"
# A palette is the whole look at once — the accent, the paper it sits on,
# the type, and the map's dot scheme — because picking a hue on its own
# barely moved the page and made the controls feel dead.
# Each palette carries the three colours its chip shows: the paper it puts
# under everything, the accent that does the work, and the warm second voice.
# The chip is a tiny page — paper with two inks on it — rather than three
# stripes, which only ever read as a flag.
PALETTES = {
    "burgundy":  {"accent": "plum",   "base": "rose", "font": "brain",     "dots": "berry",
                  "label": "Burgundy", "note": "plum on blush",
                  "sw": ("oklch(96% .012 340)", "oklch(50% .13 325)", "oklch(52% .13 356)")},
    "forest":    {"accent": "forest", "base": "warm", "font": "brain",     "dots": "clay",
                  "label": "Forest", "note": "green on cream",
                  "sw": ("oklch(96.5% .012 100)", "oklch(48% .11 150)", "oklch(55% .12 40)")},
    "harbour":   {"accent": "ocean",  "base": "cool", "font": "clean",     "dots": "ocean",
                  "label": "Harbour", "note": "blue on cool grey",
                  "sw": ("oklch(96.5% .01 250)", "oklch(52% .12 245)", "oklch(56% .11 250)")},
    "olive":     {"accent": "olive",  "base": "warm", "font": "editorial", "dots": "clay",
                  "label": "Olive", "note": "olive on cream, serif",
                  "sw": ("oklch(96.5% .014 100)", "oklch(48% .11 135)", "oklch(58% .1 45)")},
    "ember":     {"accent": "amber",  "base": "warm", "font": "playful",   "dots": "sunset",
                  "label": "Ember", "note": "amber and red",
                  "sw": ("oklch(96.5% .015 90)", "oklch(60% .12 70)", "oklch(54% .17 25)")},
    "midnight":  {"accent": "indigo", "base": "cool", "font": "brain",     "dots": "ink",
                  "label": "Midnight", "note": "indigo on cool grey",
                  "sw": ("oklch(96% .01 260)", "oklch(50% .13 280)", "oklch(46% .14 288)")},
    "paper":     {"accent": "teal",   "base": "mono", "font": "editorial", "dots": "ink",
                  "label": "Paper", "note": "teal on near-white, serif",
                  "sw": ("oklch(96.5% .004 200)", "oklch(52% .11 185)", "oklch(44% .03 90)")},
}


def palette_chips(cfg):
    """The palette picker. Each chip names itself — a 34px swatch cannot tell
    you what "Harbour" is, and an unlabelled grid of seven made choosing a
    look into guesswork."""
    ap = (cfg.get("appearance") or {})
    cur = ap.get("palette") or ""
    out = []
    for key, p in PALETTES.items():
        paper, ink, second = p["sw"]
        on = " on" if key == cur else ""
        out.append(
            f'<button class="palchip{on}" data-palette="{key}" title="{p["note"]}" '
            f'style="--pp:{paper};--pi:{ink};--p2:{second}">'
            '<span class="palswatch" aria-hidden="true"></span>'
            f'<span class="pallabel">{p["label"]}</span></button>')
    # Picking an accent on its own leaves no palette selected, which used to
    # look like a bug. Say what actually happened instead.
    if not cur:
        out.append('<p class="palnote">Mixed by hand below &mdash; pick a '
                   'palette to reset all four at once.</p>')
    return "".join(out)

# One exception to "semantic colours stay fixed": the map's relationship
# dots may be re-dressed (appearance.dots). Every option keeps the same
# hot-to-calm ordering — overdue is always the loudest, cold the quietest —
# so the colour still MEANS what it always meant; only the wardrobe changes.
# "moving" is untouched everywhere: good news stays the page's accent green.
DOTS = {
    "clay":   ({}, {}),                      # the built-in terracotta scheme
    "berry":  ({"overdue": "oklch(50% .15 356)", "soon": "oklch(59% .12 330)",
                "chase": "oklch(64% .09 300)", "cold": "oklch(56% .05 262)"},
               {"overdue": "oklch(72% .14 356)", "soon": "oklch(74% .11 330)",
                "chase": "oklch(76% .09 300)", "cold": "oklch(70% .05 262)"}),
    "ocean":  ({"overdue": "oklch(46% .14 288)", "soon": "oklch(56% .11 250)",
                "chase": "oklch(63% .08 225)", "cold": "oklch(70% .05 200)"},
               {"overdue": "oklch(74% .13 288)", "soon": "oklch(77% .1 250)",
                "chase": "oklch(80% .08 225)", "cold": "oklch(82% .05 200)"}),
    "sunset": ({"overdue": "oklch(54% .17 25)", "soon": "oklch(63% .13 55)",
                "chase": "oklch(72% .11 85)", "cold": "oklch(62% .06 320)"},
               {"overdue": "oklch(72% .15 25)", "soon": "oklch(76% .12 55)",
                "chase": "oklch(80% .1 85)", "cold": "oklch(72% .06 320)"}),
    "ink":    ({"overdue": "oklch(28% .03 90)", "soon": "oklch(44% .025 90)",
                "chase": "oklch(57% .02 90)", "cold": "oklch(70% .015 90)"},
               {"overdue": "oklch(92% .02 90)", "soon": "oklch(76% .02 90)",
                "chase": "oklch(62% .02 90)", "cold": "oklch(48% .015 90)"}),
}
DAY_HUE = 55       # the "today" terracotta pop — warm, and left constant

# ---------------------------------------------------------------- styles
# The skin registry lives in skins.py: preview blocks (all skins, tiny,
# instant picker preview) and full skins (skins/<key>.css + fonts, baked
# only for the active one). serve.py validates against STYLES.
import skins as SK
STYLES = SK.SKINS
style_css = SK.preview_css
style_chips = SK.chips


def _ok(l, c, h):
    return f"oklch({l}% {round(c, 4)} {h})"


def _mix_hue(h1, h2, k):
    """Blend two hues along the shorter way round the wheel (k=0 → h1, 1 → h2)."""
    d = ((h2 - h1 + 180) % 360) - 180
    return round((h1 + d * k) % 360, 1)


def _palette(base, accent, dark=False):
    nh, cm = BASES.get(base, BASES["warm"])
    ah = ACCENTS.get(accent, ACCENTS["olive"])
    # The neutrals — paper, text, lines — lean toward the accent hue, so
    # choosing an accent recolours the whole page and not just the FAB. Their
    # chroma is nudged up a touch so the tint actually reads. Mono has no base
    # temperature of its own, but the ACCENT still tints its greys — it just
    # does so gently, so mono reads as "your colour on grey," not a full wash.
    if base == "mono":
        th, cmn = ah, 0.5
    else:
        th, cmn = _mix_hue(nh, ah, .5), cm
    if not dark:
        n = {
            "paper": _ok(96.5, .014 * cmn, th), "surface": _ok(98.2, .009 * cmn, th),
            "sunken": _ok(93.8, .02 * cmn, th), "ink": _ok(25, .022 * cmn, th + 15),
            "dim": _ok(45, .026 * cmn, th + 10), "faint": _ok(60, .024 * cmn, th + 5),
            "line": _ok(89, .02 * cmn, th), "line2": _ok(81, .026 * cmn, th),
            "green": _ok(43, .105, ah), "greenbg": _ok(92, .05, ah),
            "terra": _ok(54, .11, DAY_HUE),
            "bad": _ok(49, .13, 32), "badbg": _ok(93, .035, 32),
            "wait": _ok(55, .1, 78), "waitbg": _ok(93.5, .045, 85),
            "cold": _ok(50, .05, 245), "coldbg": _ok(92.5, .02, 240),
            "shadow": "0 1px 2px oklch(25% .02 " + str(th + 15) + " / .06)",
            "shadow-lift": ("0 1px 2px oklch(25% .02 " + str(th + 15) + " / .05),"
                            "0 14px 36px -18px oklch(25% .04 " + str(th + 15) + " / .22)"),
        }
    else:
        n = {
            "paper": _ok(20, .016 * cmn, th + 10), "surface": _ok(23.5, .02 * cmn, th + 10),
            "sunken": _ok(17.5, .018 * cmn, th + 10), "ink": _ok(91, .018 * cmn, th),
            "dim": _ok(69, .026 * cmn, th + 5), "faint": _ok(54, .026 * cmn, th + 5),
            "line": _ok(30.5, .024 * cmn, th + 10), "line2": _ok(38, .028 * cmn, th + 10),
            "green": _ok(77, .12, ah), "greenbg": _ok(33, .06, ah),
            "terra": _ok(72, .1, DAY_HUE + 5),
            "bad": _ok(70, .12, 30), "badbg": _ok(29.5, .05, 30),
            "wait": _ok(76, .1, 85), "waitbg": _ok(30.5, .045, 85),
            "cold": _ok(72, .06, 240), "coldbg": _ok(28.5, .03, 240),
            "shadow": "none",
            "shadow-lift": "0 14px 36px -18px oklch(0% 0 0 / .5)",
        }
    out = "".join(f"--{k}:{v};" for k, v in n.items())
    # ---- the 2026 redesign's vocabulary, aliased onto the generated palette.
    # The design names its tokens card/wash/ink2/ink3/rule/accent/red/amber/
    # blue; mapping rather than hard-coding keeps her accent, paper and dark
    # switches working — pick a different accent and the whole design moves
    # with it, exactly as before.
    alias = {
        # --bg/--text are the map's and the tour's names for paper and ink.
        # The brain page never defined them, so shared components that used
        # them (the tour's Next button asked for color:var(--bg)) fell back
        # to inherited dark text on a dark button — unreadable. Defining
        # them here fixes every such component at once.
        "bg": "var(--paper)", "text": "var(--ink)",
        "card": "var(--surface)", "wash": "var(--sunken)",
        "ink2": "var(--dim)", "ink3": "var(--faint)",
        "rule": "var(--line2)", "rule2": "var(--line)",
        "accent": "var(--green)", "atint": "var(--greenbg)",
        "red": "var(--bad)", "redt": "var(--badbg)",
        "amber": "var(--wait)", "ambert": "var(--waitbg)",
        "blue": "var(--cold)", "bluet": "var(--coldbg)",
        # the design's --green means "healthy/moving", which in her semantic
        # palette is the success hue, not the accent
        "ok": _ok(50, .068, 155) if not dark else _ok(77, .07, 155),
        "okt": _ok(94.5, .028, 155) if not dark else _ok(31, .05, 155),
    }
    return out + "".join(f"--{k}:{v};" for k, v in alias.items())


def palette_css(cfg):
    ap = cfg.get("appearance", {}) or {}
    base = ap.get("base", "warm")
    accent = ap.get("accent", "olive")
    font = ap.get("font", "editorial")
    serif, sans = FONTS.get(font, FONTS["editorial"])
    scale = ("--serif:" + serif + ";--sans:" + sans + ";"
             "--coach:" + COACH_FONT + ";"
             "--s1:4px;--s2:8px;--s3:12px;--s4:16px;--s5:24px;--s6:32px;--s7:48px;--s8:64px;--s9:96px;"
             "--t-xs:.75rem;--t-sm:.8125rem;--t-base:.9375rem;--t-lg:1.1875rem;--t-xl:1.5rem;"
             "--t-2xl:1.875rem;--r-xl:18px;--r-lg:16px;--r-card:14px;--r-md:12px;"
             "--r-btn:10px;--r-sm:8px;--ease:cubic-bezier(.16,1,.3,1);")
    light = _palette(base, accent, dark=False)
    dark = _palette(base, accent, dark=True)
    ap_style = SK.active(cfg)
    return (":root{" + light + scale + "}\n"
            ":root[data-theme=\"dark\"]{" + dark + "}\n"
            "@media (prefers-color-scheme:dark){:root:not([data-theme=\"light\"]){"
            + dark + "}}\n"
            # After the theme blocks on purpose: a style block of equal
            # specificity must win by order, in both light and auto-dark.
            + style_css()
            # The ACTIVE skin's fonts and full stylesheet, last so it wins
            # over its own preview block. Other skins ship preview only.
            + "\n" + SK.faces_css(ap_style)
            + "\n" + SK.full_css(ap_style))



def _offer_verb(text):
    """What Claude would actually do for this task, or "" when the answer is
    nothing. A dated line like "Bachelorette: 4-7 September (Montenegro)" is
    a fact in her calendar, not a job — offering to start it was noise."""
    t = (text or "").lower()
    for words, what in (
        (("book", "buy", "train", "flight", "ticket", "reserve"),
         "would price the real options and put the links on this task"),
        (("call", "phone", "ring"),
         "would find the number and the hours"),
        (("email", "message", "write", "reply", "send", "draft", "text"),
         "would write a draft for you to approve"),
        (("submit", "form", "apply", "register", "renew"),
         "would find what the form needs and pre-fill what it can"),
        (("find", "research", "compare", "look into", "quote", "price"),
         "would do the search and bring back the shortlist"),
        (("read", "review", "check"),
         "would read it and tell you what matters in it"),
    ):
        if any(w in t for w in words):
            return what
    return ""


def routine_card(today):
    """The routine, one step at a time — whichever moment she is actually in.

    Two lives, both terse. For the first fortnight it teaches the shape: the
    step, its button, and one faint line (what comes next, day N of 14).
    After that it shrinks to the imperative and its button. All reasoning
    lives behind the one fold. The steps and their words come from
    brain/routine.md, so editing the file changes the card (that file says
    so, and means it)."""
    try:
        raw = read("routine.md")
    except Exception:
        return ""
    meta, body = MD.split_frontmatter(raw)
    started = M.parse_date(meta.get("started", "")) if meta.get("started") else None
    day_n = (today - started).days + 1 if started else 1
    learning = day_n <= 14

    # Each step: heading match, when it applies, and the control that does it.
    hour = now_minutes() // 60
    steps = []
    for m in re.finditer(r"^## ([^\n]+)\n(.*?)(?=\n## |\Z)", body, re.S | re.M):
        head, chunk = m.group(1).strip(), m.group(2).strip()
        if head.lower().startswith("how this adapts") or head.lower().startswith("what it"):
            continue
        # the lead is a paragraph and wraps; taking its first line only was
        # what cut "…Questions for you, then" off mid-sentence
        ml = re.search(r"^\*\*.+?(?=\n\s*\n|\n\s*-\s|\Z)", chunk, re.S | re.M)
        lead = re.sub(r"\s+", " ", ml.group(0)).strip() if ml else ""
        # the "why" bullet wraps across lines in the file, so take it whole
        mw = re.search(r"-\s*Why it works:\s*(.+?)(?=\n\s*-\s|\n\s*\n|\Z)",
                       chunk, re.S | re.I)
        why = re.sub(r"\s+", " ", mw.group(1)).strip() if mw else ""
        if why:
            why = why[0].upper() + why[1:]
        steps.append({"head": head, "lead": lead, "why": why, "body": chunk})
    if not steps:
        return ""

    # Which moment of the DAY is it? The weekly step never takes the day's
    # place — it rides underneath on Sundays.
    idx = 0
    if hour >= 17:
        idx = min(2, len(steps) - 1)
    elif hour >= 11:
        idx = min(1, len(steps) - 1)
    step = steps[idx]
    weekly = steps[3] if (today.weekday() == 6 and len(steps) > 3) else None
    ACTION = {0: ('<button class="mini needs-server" data-job="today">'
                  "Rewrite today&rsquo;s plan</button>"
                  '<button class="mini needs-server" id="rt-upd">What happened?</button>'),
              1: ('<button class="mini needs-server" id="rt-cap">'
                  "Capture a thought</button>"),
              2: ('<button class="mini" id="rt-eve">Go to the evening check</button>'),
              3: ('<a class="mini" href="rooms.html">Audit a wing</a>'
                  '<a class="mini" href="#questions">Answer the questions</a>')}
    def _name(st):
        return st["head"].split("·")[0].strip()

    def _when(st):
        return st["head"].split("·")[1].strip() if "·" in st["head"] else ""

    # The card's job is to say what to do, in one line, and hand over the
    # button that does it. The lead in routine.md is an imperative followed by
    # a sentence or two of elaboration; only the imperative belongs on the
    # face of the card.
    _m_imp = re.match(r"^\*\*(.+?)\*\*\s*(.*)$", step["lead"] or "", re.S)
    imperative = (_m_imp.group(1) if _m_imp else step["lead"] or "").strip()
    lead_html = (f'<p class="rtlead">{linkify_html(MD.inline(imperative))}</p>'
                 if imperative else "")
    # The first sentence after the imperative names what the card is about.
    # Without it the slim card was a four-word aphorism with no subject —
    # "Capture, never file." meant nothing on sight (her report, 10 Sep).
    _elab = (_m_imp.group(2) if _m_imp else "").strip()
    elab_first = (re.split(r"(?<=[.!?])\s+",
                           re.sub(r"\s+", " ", _elab))[0] if _elab else "")
    extra = ""
    if weekly:
        wk_head = ('<p class="rtstep"><b>' + e(_name(weekly)) + "</b>"
                   + (f'<span class="rtwhen">{e(_when(weekly))}</span>'
                      if _when(weekly) else "")
                   + "</p>")
        extra = ('<div class="rtweekly">'
                 + cardhead(wk_head, artimg("wayfinding", 46))
                 + (linkify_html(MD.render(weekly["lead"])) if weekly["lead"] else "")
                 + f'<div class="rtacts">{ACTION.get(3, "")}</div></div>')
    whole = ('<details class="ghost rtall"><summary>The whole routine</summary>'
             + linkify_html(MD.render(body)) + "</details>")

    # Settled: the habit is hers, so the card keeps its promise and gets out
    # of the way — the imperative and its button on one line, the file one
    # fold away. Sundays still bring the weekly step.
    if not learning:
        return ('<section class="railcard routinecard rtslim">'
                + '<p class="eyebrow">Routine</p>'
                + '<div class="rtrow">' + lead_html
                + f'<div class="rtacts">{ACTION.get(idx, "")}</div></div>'
                + (f'<p class="rtsub">{linkify_html(MD.inline(elab_first))}</p>'
                   if elab_first else "")
                + extra + whole + "</section>")

    # Teaching: the step and its button, plus ONE faint line of context —
    # what comes next and how far into the fortnight she is. The reasoning
    # stays in the file, one fold away; prose on the card's face reads as
    # filler no matter how true it is.
    day_steps = steps[:3]
    n = day_steps[(idx + 1) % len(day_steps)]
    foot = (f'{"Tomorrow" if idx + 1 >= len(day_steps) else "Next"}: '
            + e(_name(n).lower())
            + (f', {e(_when(n))}' if _when(n) else ""))
    if started:
        foot += f' &middot; day {day_n} of 14'
    # A face per moment — the evening step is the one she skips, and a
    # picture of sitting down is a better argument than another sentence.
    MOMENT_ART = {2: "evening", 3: "wayfinding"}
    return ('<section class="railcard routinecard">'
            + cardhead('<h3 class="area">The routine</h3>',
                       artimg(MOMENT_ART[idx], 46) if idx in MOMENT_ART else "")
            + f'<p class="rtstep"><b>{e(_name(step))}</b>'
            + (f'<span class="rtwhen">{e(_when(step))}</span>' if _when(step) else "")
            + "</p>"
            + lead_html
            + f'<div class="rtacts">{ACTION.get(idx, "")}</div>'
            + f'<p class="rtfoot">{foot}</p>'
            + extra
            + whole + "</section>")


def countdown_card(today):
    """Counting down — the owner's days-until numbers, from
    brain/countdowns.md. One line per event; a date in words resolves to the
    day it starts; past dates drop off the page on their own. The card face
    is just the rows — the anticipation is the content."""
    try:
        raw = read("countdowns.md")
    except Exception:
        return ""
    rows = []
    for ln in raw.split("\n"):
        m = re.match(r"^\s*[-*]\s+(.*)$", ln)
        if not m:
            continue
        txt = m.group(1).strip()
        d, label = None, txt
        md = re.search(r"\d{4}-\d{2}-\d{2}", txt)
        if md:
            d = M.parse_date(md.group(0))
            label = txt.replace(md.group(0), "")
        else:
            parts = re.split(r"\s+[—–-]\s+", txt, maxsplit=1)
            if len(parts) == 2:
                pd = M.parse_due(parts[1], today)
                if pd:
                    d, label = pd["start"], parts[0]
        if not d or d < today:
            continue
        label = re.sub(r"\(\s*\)", "", label).strip(" .,·—–-")
        n = (d - today).days
        when = "today" if n == 0 else ("tomorrow" if n == 1 else f"{n} days")
        rows.append((n, label, when, d))
    if not rows:
        return ""
    rows.sort(key=lambda r: r[0])
    body = "".join(
        f'<p class="cdrow"><span class="cdlab">{e(lab)}</span>'
        f'<b class="cdn">{e(when)}</b>'
        f'<span class="cddate">{d.day} {d.strftime("%b")}</span></p>'
        for n, lab, when, d in rows)
    return ('<section class="railcard cdcard">'
            '<h3 class="area">Counting down</h3>' + body + "</section>")


def week_strip(cfg, today, today_md=""):
    """This week as seven columns she can rearrange. Placed tasks come from
    week-plan.md, today's column mirrors today.md, events come from the
    calendar, and each day carries its load against her capacity. Dragging
    (or tapping) a task is a decision the files record — never a model call.
    Collapsed to one line when nothing is placed and no events are known."""
    try:
        raw = read("week-plan.md")
    except Exception:
        raw = ""
    cap = cfg.get("capacity") or {}
    daily = int(cap.get("daily_minutes") or 180)
    dflt = int(cap.get("default_task_minutes") or 30)

    def est_mins(text):
        mm = re.search(r"~\s*(\d+)h(\d*)\b|~\s*(\d+)m\b", text, re.I)
        if not mm:
            return None
        if mm.group(3):
            return int(mm.group(3))
        return int(mm.group(1)) * 60 + int(mm.group(2) or 0)

    def disp(text):
        return MD.plain(re.sub(
            r"\s*\((?:due|waiting until|urgent|carrying)[^)]*\)", "",
            re.sub(r"~\s*(?:\d+h\d*|\d+m)\b", "", text, flags=re.I))).strip()

    placed = {}
    for ms in re.finditer(r"^## [^\n]*?(\d{4}-\d{2}-\d{2})[^\n]*$\n(.*?)(?=\n## |\Z)",
                          raw, re.M | re.S):
        d = M.parse_date(ms.group(1))
        if not d:
            continue
        for mt in re.finditer(r"^\s*[-*]\s+\[([ xX])\]\s+(.*)$", ms.group(2), re.M):
            placed.setdefault(d, []).append(
                {"text": mt.group(2).strip(), "done": mt.group(1) != " ",
                 "key": MD.taskkey(MD.bare(mt.group(2)))})

    # Yesterday's unmoved placements ride today's column with their old day
    # on them — a slipped plan that hides is a plan that lies.
    slipped = []
    for d in sorted(placed):
        if d < today:
            slipped += [dict(t, was=d.strftime("%a")) for t in placed[d]
                        if not t["done"]]

    ttasks = []
    for mt in re.finditer(r"^\s*[-*]\s+\[([ xX])\]\s+(.*)$", today_md or "", re.M):
        rawt = mt.group(2)
        if mt.group(1) != " " or MD.DROPPED.search(rawt) or MD.UNTIL.search(rawt):
            continue
        ttasks.append({"text": rawt, "key": MD.taskkey(MD.bare(rawt))})

    ev = {}
    if cfg.get("calendar"):
        try:
            import calendar_read
            for when, title in calendar_read.events(7):
                ev.setdefault(when.split(" ")[0], []).append(title)
        except Exception:
            pass

    n_placed = sum(len(v) for d, v in placed.items() if d >= today) + len(slipped)
    # ONE TASK, ONE DAY. Today's column is filled from today.md first, so a
    # week-plan placement of the same task later in the week is a sketch the
    # plan has already overtaken. Drawing both put "Call Dr Albusel" on Monday
    # and Sunday at once — the line repeated, and its twenty minutes were
    # booked against two days' capacity, so neither day's bar told the truth.
    seen_keys = set()
    drawn_week = 0          # placements actually drawn, so the count can't
    cols = []               # promise a task the columns no longer show
    for k in range(7):
        d = today + timedelta(days=k)
        iso = d.isoformat()
        if k == 0:
            day_tasks = ([dict(t, src="today") for t in ttasks]
                         + [dict(t, src="week") for t in slipped]
                         + [dict(t, src="week") for t in placed.get(d, [])])
        else:
            day_tasks = [dict(t, src="week") for t in placed.get(d, [])]
        rows = []
        used = 0
        for t in day_tasks:
            if t["key"] in seen_keys:
                continue
            seen_keys.add(t["key"])
            if t["src"] == "week":
                drawn_week += 1
            if not t.get("done"):
                used += est_mins(t["text"]) or dflt
            rows.append(
                f'<div class="wtask{" wdone" if t.get("done") else ""}"'
                f' draggable="true" data-key="{t["key"]}" data-wsrc="{t["src"]}"'
                + (' title="Drag to a day"' if t["src"] == "today" else "")
                + f'>{e(clip(disp(t["text"]), 52))}'
                + (f'<i>{e(t["was"])}</i>' if t.get("was") else "")
                + "</div>")
        evs = ev.get(iso) or []
        used += 60 * len(evs)
        evline = ""
        if evs:
            evline = ('<p class="wevents">' + e(clip(evs[0], 26))
                      + (f' +{len(evs) - 1}' if len(evs) > 1 else "") + "</p>")
        pct = min(100, round(used * 100 / daily)) if daily else 0
        over = (f'<p class="wcolover">over by ~{e(M.fmt_dur(used - daily))}</p>'
                if used > daily else "")
        head = "Today" if k == 0 else f'{d.strftime("%a")} {d.day}'
        cols.append(
            f'<div class="wcol{" wtoday" if k == 0 else ""}" data-date="{iso}"'
            f' data-today="{1 if k == 0 else 0}">'
            f'<p class="wchead">{e(head)}'
            f'<button class="wadd" data-dow="{e(d.strftime("%A"))}"'
            ' title="Capture something for this day">+</button></p>'
            + evline + "".join(rows)
            + f'<div class="wbar"><i style="width:{pct}%"></i></div>'
            + over + "</div>")
    n_placed = drawn_week
    openattr = " open" if (n_placed or ev) else ""
    sketch = ("" if n_placed else
              '<p class="wsketchrow"><button class="mini needs-server" '
              'id="wsketch">Sketch my week</button></p>')
    return (f'<details class="weekstrip"{openattr}><summary>This week'
            + (f' &middot; {n_placed} placed' if n_placed else "")
            + f'</summary>{sketch}'
            # The strip never said what it was FOR — "is the idea for me to
            # move things around?" (31 Aug). One line, above the columns.
            '<p class="whint">Drag a task onto a day to plan it &mdash; the '
            '+ on a day adds something new. Moves save on their own.</p>'
            f'<div class="wcols">{"".join(cols)}</div></details>')


def dayshape(cfg, today, today_md=""):
    """WHEN — the day as a vertical timeline: the fixed things (calendar
    events, this weekday's standing blocks), the free windows between them,
    and today's unfinished tasks slotted into those windows so the plan is
    read against real hours rather than an imaginary empty day."""
    items = []
    if cfg.get("calendar"):
        try:
            import calendar_read
            for when, title in calendar_read.events(1):
                hhmm = when.split(" ")[-1][:5] if " " in when else ""
                if hhmm:
                    items.append((hhmm, title, "cal"))
        except Exception:
            pass
    wk = cfg.get("week") or {}
    interm = False
    t = (wk.get("term") or {})
    try:
        if t.get("start") and t.get("end"):
            interm = (M.parse_date(t["start"]) <= today <= M.parse_date(t["end"]))
    except Exception:
        interm = False
    if interm:
        key = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][today.weekday()]
        for label in ((wk.get("days") or {}).get(key) or []):
            items.append(("", label, "week"))
    # Today's still-open tasks, in the plan's own order, with any estimate.
    tasks = []
    for ln in (today_md or "").split("\n"):
        mt = re.match(r"^\s*[-*]\s+\[([ xX])\]\s+(.*)$", ln)
        if not mt:
            continue
        raw = mt.group(2)
        if MD.DROPPED.search(raw):
            continue
        est = ""
        me = re.search(r"~\s*(\d+h\d*|\d+m)\b", raw, re.I)
        if me:
            est = me.group(1)
        txt = MD.plain(re.sub(r"\s*\((?:due|waiting until|urgent|carrying)[^)]*\)", "",
                              re.sub(r"~\s*(?:\d+h\d*|\d+m)\b", "", raw,
                                     flags=re.I))).strip()
        if not txt:
            continue
        tasks.append({"t": txt, "done": mt.group(1).lower() == "x", "est": est,
                      "carry": bool(MD.CARRYING.search(raw))})
    # Nothing fixed today means there is no day-shape to draw — the plan
    # under the hero already lists the tasks, so a card holding only a "now"
    # marker is dead weight. Show it only when something is actually fixed.
    if not items:
        return ""

    timed = sorted([x for x in items if x[0]], key=lambda x: x[0])
    untimed = [x for x in items if not x[0]]
    now = datetime.now().strftime("%H:%M")

    def mins(hhmm):
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)

    # The gaps between the fixed things — where work can actually happen.
    DAY_START, DAY_END = 8 * 60, 22 * 60
    edges, cur = [], DAY_START
    for hhmm, label, kind in timed:
        s = mins(hhmm)
        if s - cur >= 45:
            edges.append((cur, s))
        cur = max(cur, s + 60)          # assume an hour unless told otherwise
    if DAY_END - cur >= 45:
        edges.append((cur, DAY_END))
    free = [(a, b) for a, b in edges if b > mins(now)]     # only what's left

    def hm(x):
        return f"{x // 60:02d}:{x % 60:02d}"

    open_tasks = [t for t in tasks if not t["done"]]
    rows, placed_now, ti = [], False, 0
    for hhmm, label, kind in timed:
        if not placed_now and hhmm > now:
            rows.append(f'<li class="wnow"><i></i><b>{e(now)}</b> &mdash; now</li>')
            placed_now = True
        rows.append(f'<li class="wfix"><span class="wt">{e(hhmm)}</span>'
                    f'<span class="wl">{e(label[:60])}</span></li>')
        # after each fixed thing, offer the window that follows it
        for a, b in free:
            if a >= mins(hhmm) and a < mins(hhmm) + 120 and ti < len(open_tasks):
                t = open_tasks[ti]; ti += 1
                rows.append(
                    f'<li class="wfree"><span class="wt">{e(hm(a))}&ndash;{e(hm(b))} '
                    '&middot; free</span>'
                    f'<span class="wtask">{e(t["t"][:70])}'
                    + (f'<em>{e(t["est"])}</em>' if t["est"] else "")
                    + ("<em>carrying</em>" if t["carry"] else "")
                    + "</span></li>")
                break
    for hhmm, label, kind in untimed:
        rows.append(f'<li class="wfix wweek"><span class="wl">{e(label[:60])}</span></li>')
    if not placed_now:
        rows.append(f'<li class="wnow past"><i></i><b>{e(now)}</b> &mdash; now</li>')
    done_n = len([t for t in tasks if t["done"]])
    sub = f'{today.strftime("%A")} {today.day} {today.strftime("%B")}'
    return ('<section class="whenwrap railcard"><p class="eyebrow">When</p>'
            '<span class="wav"></span>'
            f'<p class="whenday">{e(sub)}</p>'
            f'<p class="whensub">{e(now)}'
            + (f' &middot; {done_n} of {len(tasks)} done' if tasks else "")
            + "</p>"
            f'<ul class="when">{"".join(rows)}</ul></section>')


def _mailread_row(cfg, have_account=True):
    """Reading mail: the switch, the button, and what the last look found.

    Separate from the Mail row above because the two directions are different
    promises. Sending is her pressing send. Reading is a stranger getting to
    put text near Claude, which is why it is headers only and why it never
    happens on a schedule."""
    on = bool(((cfg.get("email") or {}).get("read") or {}).get("on"))
    try:
        import email_read as _er
        st = _er.last_check()
    except Exception:                                    # noqa: BLE001
        st = {}
    owed = st.get("owed") or []
    if owed:
        who = ", ".join(e(n) for n in owed[:4])
        more = f" and {len(owed) - 4} more" if len(owed) > 4 else ""
        found = (f'<span class="mrfound">Waiting on a reply from you: '
                 f"<b>{who}</b>{more}.</span>")
    elif st.get("checked"):
        found = ('<span class="mrfound">Last look found nobody waiting on '
                 "you.</span>")
    else:
        found = ""
    if not have_account:
        state = ("Needs a mail account first &mdash; reading borrows the app "
                 "password you set up for sending, above. Gmail, Yahoo or "
                 "iCloud: Microsoft no longer allows password logins for "
                 "reading, so an Outlook or school account can&rsquo;t be "
                 "read whatever you do.")
    elif on:
        state = ("On &mdash; reads who wrote and when, never what they wrote. "
                 '<button class="mini" id="mr-check">Check now</button> '
                 '<button class="mini" id="mr-off">Turn off</button>')
    else:
        state = ("Off &mdash; the brain can&rsquo;t see who is waiting on a "
                 'reply. <button class="mini" id="mr-on">Turn on</button>')
    return (
        '<div class="connrow needs-server"><i class="cdot'
        + (" on" if on else "") + '"></i><b>Mail in</b><span>'
        + state
        + '<span class="mshelp" id="mr-help"></span>'
        + found
        + '<details class="connhow"><summary>What it does and doesn&rsquo;t '
        "read</summary>Per message it asks your mail server for the From, To "
        "and Cc lines and the date. It never asks for the subject or the body, "
        "and messages stay unread. From that it works out "
        "who has written to you more recently than you wrote back, which is "
        "the thing you actually lose track of. People you don&rsquo;t track "
        "are counted and dropped, so marketing mail leaves nothing behind. "
        "It runs when you press the button; the morning plan and the night "
        "shift can&rsquo;t start it. It uses the app password already in your "
        "Keychain, so there is nothing new to set up."
        "</details></span></div>")


def _mailtasks_tray(cfg=None):
    """The suggestions themselves, on Today. Accepting one writes a line to
    the inbox for normal triage; dismissing closes it. The whitelist that
    feeds this lives in Connections — that part IS a setting."""
    try:
        import mail_tasks as _mt
        pend = _mt.pending()
    except Exception:                                    # noqa: BLE001
        pend = []
    if not pend:
        return ""
    # The email itself, one click away — in HER mail client, not here. The
    # message-id (or, for older suggestions, the subject) makes a Gmail
    # search URL; the brain still stores nothing of what the mail said.
    _gmail = any((a.get("provider") == "gmail")
                 for a in (((cfg or {}).get("email") or {})
                           .get("accounts") or []))

    def _maillink(s):
        if not _gmail:
            return ""
        import urllib.parse as _up
        mid = (s.get("msgid") or "").strip().strip("<>")
        q = ("rfc822msgid:" + mid) if mid else (
            'subject:"' + s["subject"][:60] + '"' if s.get("subject") else "")
        if not q:
            return ""
        return ("https://mail.google.com/mail/u/0/#search/"
                + _up.quote(q, safe=""))

    def _row(s):
        due = (f' <span class="mtdue">due {e(s["due"])}</span>'
               if s.get("due") else "")
        src = s.get("subject") or s.get("from") or ""
        link = _maillink(s)
        srchtml = (f'<a href="{e(link)}" target="_blank" rel="noopener"'
                   ' title="Open the email itself in your mail">'
                   + e(src) + "</a>") if link else e(src)
        return ('<div class="mtrow"><span class="mttask">'
                f'{e(s["task"])}{due}<i>{srchtml}</i></span>'
                f'<button class="mini" data-mtact="accept" data-mtid="{e(s["id"])}">'
                "Add</button>"
                f'<button class="mini" data-mtact="dismiss" data-mtid="{e(s["id"])}">'
                "No</button></div>")

    # A suggestion whose date has passed stopped being a question worth the
    # page's front — folded, not hidden: she may still want to No them away.
    _today = date.today().isoformat()
    fresh = [s for s in pend if not (s.get("due") and s["due"] < _today)]
    stale = [s for s in pend if s.get("due") and s["due"] < _today]
    rows = [_row(s) for s in fresh[:12]]
    if stale:
        rows.append('<details class="ghost mtstale"><summary>'
                    f'{len(stale)} whose date has passed</summary>'
                    + "".join(_row(s) for s in stale[:12]) + "</details>")
    more = (f'<p class="mtmore">and {len(fresh) - 12} more</p>'
            if len(fresh) > 12 else "")
    # The feedback span lives IN the tray. Errors used to land in #mt-help,
    # a span inside the Connections settings row on another part of the page
    # — so a failed Add looked like a dead button (her report, 10 Sep).
    return ('<section class="mttray needs-server"><h2>From your email'
            + hint("Tasks proposed from the senders you whitelisted. Add puts "
                   "one in your inbox for Claude to file; No drops it — and "
                   "teaches the reader what not to suggest again. The grey "
                   "line under each is the email itself; click it to open "
                   "the message in your mail.")
            + f'</h2>{"".join(rows)}{more}'
            '<span class="mshelp" id="mttray-help"></span></section>')


def _school_tray(cfg=None):
    """Dates found in the class slides, waiting on a yes or a no.

    Blackboard has no API worth having and the syllabi carry almost no dates —
    they sit in the decks. school.py reads whatever lands in the class folder
    and proposes what looks like a commitment; this is where she answers.
    Accepting writes a line to the inbox, the same road as anything else."""
    try:
        import school as _sc
        pend = _sc.pending()
    except Exception:                                    # noqa: BLE001
        pend = []
    # The card stays even with an empty tray: when a deck lands mid-week she
    # needs a way to say "read them now", and a card that only appears when
    # the brain already found something is no way at all.
    seen, last = 0, ""
    try:
        with open(os.path.join(BRAIN, ".school.json")) as fh:
            seen = len((json.load(fh).get("seen") or {}))
        last = ago((date.today() - date.fromtimestamp(os.path.getmtime(
            os.path.join(BRAIN, ".school.json")))).days)
    except Exception:                                    # noqa: BLE001
        pass
    scan = ('<div class="scacts"><button class="ghostbtn" id="scscan">'
            "Read the class slides now</button>"
            '<span class="mshelp" id="scscanhelp">%s</span></div>'
            % e(" \u00b7 ".join(x for x in (
                ("%d files read" % seen) if seen else "",
                ("last looked %s" % last) if last else "") if x)))
    if not pend:
        return ('<section class="mttray needs-server"><h2>Your slides</h2>'
                '%s</section>' % scan)

    def _row(s):
        due = (f' <span class="mtdue">due {e(s["due"])}</span>'
               if s.get("due") else "")
        guess = ((" · from a %d deck, probably last year's date"
                  % s["old_year"]) if s.get("old_year")
                 else "" if s.get("exact") else " · year inferred")
        src = f'{s.get("course", "")}{guess}'
        return ('<div class="mtrow"><span class="mttask">'
                f'{e(s["task"])}{due}<i title="{e(s.get("line", ""))}">'
                f'{e(src)}</i></span>'
                f'<button class="mini" data-scact="accept" data-scid="{e(s["id"])}">'
                "Add</button>"
                f'<button class="mini" data-scact="dismiss" data-scid="{e(s["id"])}">'
                "No</button></div>")

    _today = date.today().isoformat()
    fresh = [s for s in pend if not (s.get("due") and s["due"] < _today)]
    stale = [s for s in pend if s.get("due") and s["due"] < _today]
    rows = [_row(s) for s in fresh[:12]]
    if stale:
        rows.append('<details class="ghost mtstale"><summary>'
                    f'{len(stale)} whose date has passed</summary>'
                    + "".join(_row(s) for s in stale[:12]) + "</details>")
    return ('<section class="mttray needs-server"><h2>Found in your slides'
            + hint("Dates the brain read out of the decks in your class "
                   "folder. Add puts one in your inbox for Claude to file; "
                   "No drops it. Hover the grey line to see the slide's own "
                   "words — and check any marked \"year inferred\", where the "
                   "slide gave a day and a month but no year.")
            + f'</h2>{"".join(rows)}'
            + scan
            + '<span class="mshelp" id="sctray-help"></span></section>')


SCHOOL_WS = ("School", "Venture", "Class lead")

# Words that mark a calendar entry as school rather than life. Course names
# come from her class folder; these cover what a course name doesn't — the
# programme itself, her project, and the CDL stream.
_SCHOOL_MARKS = ("hec", "mba", "learning by doing", "venture", "venture lab",
                 "cdl", "creative destruction", "capstone", "e-lab", "elab")


def _is_school_event(title, known=None):
    """True for a class or a school commitment, false for lunch with a friend.

    Without this the School views listed every calendar entry, so a lunch sat
    between Entrepreneurial Finance and Managing Innovation as if it were a
    session."""
    low = (title or "").lower()
    if any(m in low for m in _SCHOOL_MARKS):
        return True
    for c in (known or []):
        if sum(1 for w in c["words"] if w in low) >= 2:
            return True
        if any(p in low for p in c["profs"]):
            return True
    return False


def area_groups(items, area_of, sort_key, row, cap=3):
    """A mixed task list, split into one subsection per area of her life.

    Her rule (16 Sep 2026): in one ranked list a busy area crowds out the
    single important task from another part of her life — eight Venture
    rows and the one class-lead deadline scrolls away. So every area gets its
    own small heading, the areas lead with their most pressing item (the
    same order "Front by front" uses), and when more than one area shares a
    list each shows only its top few, with the rest folded under it. A list
    holding a single area is never capped: there is nothing to protect."""
    groups = {}
    for it in items:
        groups.setdefault(area_of(it) or "Other", []).append(it)
    if not groups:
        return ""
    for g in groups.values():
        g.sort(key=sort_key)
    order = sorted(groups, key=lambda a: sort_key(groups[a][0]))
    limit = cap if len(groups) > 1 else None
    out = []
    for a in order:
        g = groups[a]
        shown, rest = (g[:limit], g[limit:]) if limit else (g, [])
        html = ('<div class="agroup"><h3 class="area agh">%s'
                '<span class="agn">%d</span></h3><ul class="tasks">%s</ul>'
                % (e(a), len(g), "".join(row(it) for it in shown)))
        if rest:
            html += ('<details class="ghost amore"><summary>'
                     '<span class="amc">Show %d more</span>'
                     '<span class="amo">Show fewer</span></summary>'
                     '<ul class="tasks">%s</ul></details>'
                     % (len(rest), "".join(row(it) for it in rest)))
        out.append(html + "</div>")
    return "".join(out)


def _school_open():
    """Every open school task with its workstream, enriched by model.py.

    One reader for the School tab and the Today strip, so the two can never
    disagree about what is due."""
    out = []
    for w in M.load():
        if not w.get("name", "").startswith(SCHOOL_WS):
            continue
        for t in w.get("tasks") or []:
            if t.get("done") or t.get("dropped") or t.get("parked"):
                continue
            out.append((w, t))
    return out


def _ws_short(name):
    if name.startswith("Venture"):
        return "Venture"
    if name.startswith("Class lead"):
        return "Class lead"
    return "Courses"


def _task_head(text):
    """What a school row shows: the instruction, not the reasoning after it.

    These tasks were filed with their why attached, which is right in the
    file and wrong on a card — her rule is an imperative and one faint line.
    The full text stays in the tooltip, and the tick is still keyed to it."""
    t = re.sub(r"\s*\((?:class|urgent)\)", "", text or "").strip()
    head = re.split(r"\s+[—–]\s+", t)[0].strip()
    return head if len(head) >= 14 else t


def _school_row(w, t, chip=True):
    """A school task as the page's own task row, made quieter.

    Tickable, and the tick is keyed to the full text, so only what is shown
    changes: the instruction without its reasoning (full line in the tooltip),
    and one faint line under it for when it is due and how long it takes —
    "Tomorrow · 1h" — instead of an estimate pill in the sentence and a red
    "due in 1d" under every row of a week that is, by definition, soon."""
    name = w.get("name", "")
    row = taskrow(t, src="workstreams.md", ws=name, show_ws=chip,
                  ws_label=_ws_short(name))
    full = linknames(e(t["text"]))
    short = linknames(e(_task_head(t["text"])))
    if short != full:
        row = row.replace('<span class="ttext">' + full,
                          '<span class="ttext" title="%s">' % e(t["text"])
                          + short, 1)
    dur = ""
    if t.get("est") and not t.get("done"):
        dur = M.fmt_dur(t["est"])
        row = row.replace('<span class="test">%s</span>' % e(dur), "", 1)
    meta = " · ".join(x for x in (_due_words(t), dur) if x)
    if t.get("due_days") in (0, 1):
        row = row.replace('<li class="', '<li class="tdue-now ', 1)
    m = re.search(r'<span class="tnote tdue">.*?</span>', row)
    if m:
        row = (row[:m.start()] + '<span class="tnote tdue">%s</span>' % e(meta)
               + row[m.end():])
    elif meta:
        i = row.find('<span class="ttext"')
        j = row.find("</span>", i)
        if i >= 0 and j > i:
            row = row[:j] + '<span class="tnote tdue">%s</span>' % e(meta) + row[j:]
    return row


def _due_words(t):
    """When a task is due, the way she would say it."""
    dd = t.get("due_days")
    if dd is None:
        return ""
    if dd < 0:
        return "%d day%s late" % (-dd, "" if dd == -1 else "s")
    if dd == 0:
        return "Today"
    if dd == 1:
        return "Tomorrow"
    if t.get("due_fuzzy") and t.get("due_label"):
        return str(t["due_label"])
    d = date.today() + timedelta(days=dd)
    if dd < 7:
        return d.strftime("%A")
    return "%s %d" % (d.strftime("%b"), d.day)


def _by_due(pairs):
    return sorted(pairs, key=lambda p: (
        p[1]["due_days"] if p[1].get("due_days") is not None else 9999,
        p[1]["text"]))


def _due_key(p):
    t = p[1]
    return (t["due_days"] if t.get("due_days") is not None else 9999,
            t["text"])


def _front_groups(pairs, cap=3):
    return area_groups(pairs, lambda p: _ws_short(p[0].get("name", "")),
                       _due_key, lambda p: _school_row(p[0], p[1], chip=False),
                       cap=cap)


def _school_card(title, pairs, extra_cls=""):
    if not pairs:
        return ""
    return ('<section class="pdtray schoolcard %s"><h2>%s'
            '<span class="sccount">%d</span></h2>%s</section>'
            % (extra_cls, e(title), len(pairs), _front_groups(pairs)))


_SHORT_CLASS = (("entrepreneurial finance", "Entrepreneurial Finance"),
                ("managing innovation", "Managing Innovation"),
                ("innovative marketing", "Innovative Marketing"),
                ("scale", "Scale-up"),
                # before "learning by doing": the course folder is named for
                # both, and the Backbone is the course; LbD is its option
                ("advanced entrepreneurship", "Advanced Entrepreneurship"),
                ("learning by doing", "Learning by Doing"),
                ("venture", "Venture"))


def _short_class(name):
    low = (name or "").lower()
    for key, short in _SHORT_CLASS:
        if key in low:
            return short + (" kick-off" if "kick" in low else "")
    n = name.strip()
    return n if len(n) <= 34 else n[:32].rstrip() + "…"


def _school_events(days):
    """School calendar entries as {day: [(time, short name)]}, deduplicated.

    Her calendar carries each class twice (two feeds, one with the title
    HTML-escaped), so names are unescaped and deduplicated per day."""
    import html as _h
    try:
        import calendar_read
        import school as _sc
        known = _sc.courses()
        evs = calendar_read.events(days)
    except Exception:                                    # noqa: BLE001
        return {}
    out = {}
    for when, title in evs:
        t = _h.unescape(_h.unescape(title or ""))
        if not _is_school_event(t, known):
            continue
        name = _short_class(re.split(r"\s+-\s+", t)[0])
        day, hm = str(when)[:10], str(when)[11:16]
        got = out.setdefault(day, [])
        if not any(n == name for _, n in got):
            got.append((hm, name))
    return {d: sorted(v) for d, v in out.items()}


def _term_hero(cfg, today, pairs):
    """The School tab's headline, in the same voice as Today's."""
    now = (cfg or {}).get("now") or {}
    until = M.parse_date(now.get("until", "")) if now.get("until") else None
    if until and until >= today:
        weeks = max(1, -(-(until - today).days // 7))
        head = "%s. %d week%s left." % (now.get("phase") or "This term",
                                       weeks, "" if weeks == 1 else "s")
    else:
        head = "School."
    bits = []
    nxt = [p for p in _by_due(pairs)
           if p[1].get("due_days") is not None and p[1]["due_days"] >= 0
           and "(class)" in p[1]["text"]]
    if nxt:
        dd = nxt[0][1]["due_days"]
        when = ("today" if dd == 0 else "tomorrow" if dd == 1 else
                (today + timedelta(days=dd)).strftime("%A") if dd < 7 else
                "in %d days" % dd)
        name = re.split(r"\s+\(|,\s", _task_head(nxt[0][1]["text"]))[0]
        if len(name) > 48:
            name = name[:48].rsplit(" ", 1)[0] + "\u2026"
        bits.append("Next hand-in: %s, %s" % (name, when))
    for w in M.load():
        if w.get("name", "").startswith("Venture") and w.get("due"):
            d = M.parse_date(str(w["due"]))
            if d and d >= today:
                bits.append("Venture jury in %d days" % (d - today).days)
    if until:
        bits.append("term ends %s" % until.strftime("%a %d %b"))
    return ('<h2 class="skinx skinx-greet">%s</h2>' % e(head)
            + ('<p class="wxline">%s</p>' % e(" · ".join(bits))
               if bits else ""))


def _tracker_card():
    """The shared class sheet's gaps, with one button to copy them.

    It never writes to the sheet — classmates plan around it, so a row lands
    there because she pasted it. Rows she decides the class doesn't need are
    dismissed (kept in config, restorable) and drop out of the copy too."""
    try:
        import tracker as _tr
        if not _tr.sheet_url():
            return ""
        raw = _tr.compare_cached()
        data = _tr.without_dismissed(raw)
        gaps = data.get("missing") or []
        gone = data.get("dismissed_rows") or []
        if not gaps and not gone:
            return ""
        lines = _tr.paste_rows(data=raw)
    except Exception:                                    # noqa: BLE001
        return ""

    def when(g):
        try:
            d = date.fromisoformat(str(g["due"])[:10])
            return "%d %s" % (d.day, d.strftime("%b"))
        except ValueError:
            return str(g.get("due") or "")

    live = "".join(
        '<li data-row="%s"><span>%s</span><i>%s &middot; %s</i>'
        '<button class="scx" data-trkey="%s" title="The class sheet doesn\'t '
        'need this — leave it out of the copy" aria-label="Dismiss">&times;'
        "</button></li>"
        % (e(line), e(g["assignment"][:90]), e(_short_class(g["course"])),
           e(when(g)), e(_tr.gap_key(g)))
        for g, line in zip(gaps, lines))
    body = ('<ul class="scgaps">%s</ul>' % live if gaps else
            '<p class="scsub">Nothing missing.</p>')
    if gaps:
        body += ('<div class="scacts"><button class="ghostbtn scopy" '
                 'data-rows="%s">Copy %d row%s to paste</button>'
                 '<span class="schelp"></span></div>'
                 % (e("\n".join(lines)), len(gaps), "" if len(gaps) == 1 else "s"))
    if gone:
        body += ('<details class="ghost scgone"><summary>%d dismissed</summary>'
                 '<ul class="scgaps">%s</ul></details>'
                 % (len(gone), "".join(
                     '<li><span>%s</span><i>%s</i><button class="screstore" '
                     'data-trkey="%s" data-restore>Restore</button></li>'
                     % (e(g["assignment"][:90]), e(when(g)), e(_tr.gap_key(g)))
                     for g in gone)))
    return ('<section class="pdtray schoolcard sctracker needs-server">'
            '<h2>Class tracker<span class="sccount">%d</span></h2>'
            '<p class="scsub">Missing from the sheet your classmates use.</p>'
            "%s</section>" % (len(gaps), body))


def _week_rail():
    """This week's classes: a day, then its classes one per line with the
    time in its own column — they used to run together on one wrapped line."""
    ev = _school_events(7)
    if not ev:
        return ""
    today = date.today()
    blocks = ""
    for day in sorted(ev)[:7]:
        try:
            d = date.fromisoformat(day)
        except ValueError:
            continue
        gap = (d - today).days
        label = ("Today" if gap == 0 else "Tomorrow" if gap == 1
                 else "%s %d" % (d.strftime("%a"), d.day))
        slots = "".join('<span class="scslot"><em>%s</em><span>%s</span></span>'
                        % (e(hm), e(n)) for hm, n in ev[day])
        blocks += ('<div class="scday%s"><b>%s</b><div class="scslots">%s</div>'
                   "</div>" % (" sctoday" if gap == 0 else "", e(label), slots))
    return ('<section class="railcard scweek"><h3 class="area">Classes this '
            "week</h3>%s</section>" % blocks)


def _left_out_of_guides():
    """The class files that are not slides, folded under one line. Guides
    are built from slides alone (25 Sep): a case, an article or a guest's
    deck may be something the professor would rather not see in a model, so
    it only goes in when she says so, one file at a time. They are still
    read on this Mac for dates."""
    try:
        import school as _sc
        files = _sc.files()
        extra = _sc.guide_extras()
    except Exception:                                    # noqa: BLE001
        return ""
    rows = []
    for f in sorted(files, key=lambda f: (f["course"], f["name"].lower())):
        low = f["name"].lower()
        if os.path.splitext(low)[1] not in (".pdf", ".pptx") \
                or _sc.is_slides(f["name"]) or "syllabus" in low \
                or "recommended reading" in low or _sc.is_confidential(low):
            continue
        on = f["rel"] in extra
        rows.append(
            '<div class="scbook"><span>%s<i>%s</i></span>'
            '<button class="scbuild needs-server" data-guideadd="%s" '
            'data-on="%s">%s</button></div>'
            % (e(os.path.splitext(f["name"])[0]),
               e(_short_class(f["course"])), e(f["rel"]),
               "0" if on else "1",
               "In the guide &mdash; take out" if on else "Add to guide"))
    if not rows:
        return ""
    return ('<details class="scbooks"><summary>Left out of the guides'
            '<b>%d</b></summary>%s</details>' % (len(rows), "".join(rows)))


def _guides_rail():
    """The guides, and the books that don't have one yet.

    Course guides and finished book guides are links. A book being read shows
    how far it has got. The rest sit folded under one line, each with a Build
    button — one at a time, since a book is a few dozen calls against her
    subscription."""
    root = os.path.join(BRAIN, "school", "guides")
    rows = []
    if os.path.isdir(root):
        for course in sorted(os.listdir(root)):
            cdir = os.path.join(root, course)
            if course.startswith(".") or not os.path.isdir(cdir):
                continue
            if os.path.exists(os.path.join(cdir, "_course.html")):
                rows.append('<a href="school/guides/%s/_course.html" target="_blank" '
                            'rel="noopener">%s<i>course guide</i></a>'
                            % (e(course), e(_short_class(course.replace("-", " ")))))
    try:
        import guide as _gd
        books = _gd.book_status()
    except Exception:                                    # noqa: BLE001
        books = []
    busy = any(b["running"] for b in books)
    for bk in books:
        if bk["guide"] and not bk["running"]:
            rows.append('<a href="%s" target="_blank" rel="noopener">%s'
                        "<i>book guide</i></a>" % (e(bk["href"]), e(bk["title"])))
    for bk in books:
        if bk["running"]:
            rows.append('<div class="scbuilding" data-book="%s"><span>%s</span>'
                        "<i>%s</i></div>" % (e(bk["slug"]), e(bk["title"]),
                                             e(bk["stage"] or "Starting")))
    # The other kind of guide — the book on its own terms — is a second row
    # per book, which would double this card. Folded, it stays one line.
    gen = [bk for bk in books if bk.get("general")]
    if gen:
        rows.append(
            '<details class="scbooks"><summary>The books on their own terms'
            "<b>%d</b></summary>%s</details>"
            % (len(gen), "".join(
                '<a href="%s" target="_blank" rel="noopener">%s'
                "<i>the book itself</i></a>" % (e(bk["general_href"]),
                                                e(bk["title"]))
                for bk in gen)))
    rows.append(_left_out_of_guides())
    todo = [bk for bk in books if not bk["guide"] and not bk["running"]]
    if todo:
        items = "".join(
            '<div class="scbook"><span>%s%s</span>'
            '<button class="scbuild" data-bookbuild="%s"%s>%s</button></div>'
            % (e(bk["title"]),
               ('<i>%s</i>' % e(bk["author"])) if bk["author"] else "",
               e(bk["slug"]), " disabled" if busy else "",
               "Try again" if bk["failed"] else "Build")
            for bk in todo)
        rows.append('<details class="scbooks"><summary>Guides for the other books'
                    '<b>%d</b></summary>%s<p class="scbhelp">%s</p></details>'
                    % (len(todo), items,
                       "One is being built — the next can start when it's done."
                       if busy else
                       "Reads the book, then writes the guide. About ten minutes."))
    if not rows:
        return ""
    return ('<section class="railcard scguides needs-server">'
            '<h3 class="area">Guides</h3>%s</section>' % "".join(rows))


def school_strip(cfg=None, seen=None, claim=None):
    """The thin school layer on Today: classes today and what is due within
    three days that the plan above doesn't already show. Depth lives on the
    School tab.

    Late work is a count, not rows. `<= 3` used to let every overdue task
    through, and on 24 Sep that was seventeen tickboxes above the plan —
    a second to-do list competing with the three. `seen`/`claim` are the
    page's one-owner register, so a task shown here is not shown again
    below."""
    today = date.today()
    try:
        plan = read("today.md")
    except Exception:                                    # noqa: BLE001
        plan = ""
    school = _school_open()
    pairs = [p for p in _by_due(school)
             if p[1].get("due_days") is not None
             and 0 <= p[1]["due_days"] <= 3 and not p[1].get("expired")
             and _task_head(p[1]["text"])[:40] not in plan
             and not (seen and seen(p[1]["text"]))]
    late = sum(1 for _w, t in school
               if t.get("overdue") and not t.get("expired"))
    for p in pairs:
        if claim:
            claim(p[1]["text"])
    classes = _school_events(1).get(today.isoformat(), [])
    if not pairs and not classes and not late:
        return ""
    line = (" &middot; ".join("%s <em>%s</em>" % (e(n), e(hm))
                              for hm, n in classes) if classes else "")
    return ('<section class="pdtray schoolcard schoolstrip"><h2>School today'
            "</h2>"
            + ('<p class="scsub scclasses">%s</p>' % line if line else "")
            + (_front_groups(pairs, cap=2) if pairs else "")
            + '<p class="scmore"><a href="#/school">%s</a></p></section>'
            % ("%d late &mdash; the whole term &rarr;" % late if late
               else "The whole term &rarr;"))


def _recordings_rail():
    """The meeting recordings sitting in the projects' own folders.

    They stay where she and her team keep them; this only says which ones
    have a transcript beside them and starts the ones that do not. Nothing
    transcribes itself: it is twenty minutes of GPU and her call."""
    try:
        import transcribe as TR
        items = TR.meetings()[:8]
    except Exception:                                    # noqa: BLE001
        return ""
    if not items:
        return ""
    busy = any(m["running"] for m in items)
    rows = []
    for m in items:
        mins = ("%g min" % m["minutes"]) if m["minutes"] else ""
        meta = " &middot; ".join(x for x in (m["when"][:10], mins) if x)
        if m["running"]:
            rows.append('<div class="scbuilding" data-rec="%s"><span>%s</span>'
                        "<i>%s</i></div>"
                        % (e(m["path"]), e(m["name"]), e(m["stage"] or "starting")))
        elif m["transcript"]:
            rows.append('<div class="screc"><span>%s<i>%s &middot; transcript '
                        'beside it</i></span>'
                        '<button class="scbuild" data-reveal="%s">Show it</button>'
                        "</div>" % (e(m["name"]), meta, e(m["transcript"])))
        else:
            rows.append('<div class="screc"><span>%s<i>%s</i></span>'
                        '<button class="scbuild" data-transcribe="%s"%s>%s</button>'
                        "</div>" % (e(m["name"]), meta, e(m["path"]),
                                    " disabled" if busy else "",
                                    "Try again" if m["failed"] else "Transcribe"))
    note = ("One is running — the next can start when it is done."
            if busy else
            "Runs on this Mac, about five minutes per half hour of audio.")
    return ('<section class="railcard scguides needs-server">'
            '<h3 class="area">Recordings</h3>%s'
            '<p class="scbhelp">%s</p></section>' % ("".join(rows), note))


def school_view(cfg=None):
    """The School tab: the term in one place, for as long as the term lasts.

    Every task appears once, grouped by when it is due, with its front as a
    chip — Venture, class lead or courses. Built from the page's own parts
    (task rows, cards, the Today grid) so the skin styles it like everything
    else."""
    today = date.today()
    pairs = _school_open()
    late, week, soon, later = [], [], [], []
    for p in _by_due(pairs):
        dd = p[1].get("due_days")
        if dd is None or dd > 21:
            later.append(p)
        elif dd < 0:
            late.append(p)
        elif dd <= 7:
            week.append(p)
        else:
            soon.append(p)
    main = [_term_hero(cfg, today, pairs),
            _school_tray(cfg).replace('class="mttray', 'class="pdtray '
                                      'schoolcard mttray', 1),
            _school_card("Late", late, "sclate"),
            _school_card("This week", week),
            _school_card("Next two weeks", soon),
            _tracker_card()]
    if later:
        main.append('<details class="ghost schoolmore"><summary>Later this '
                    "term &middot; %d</summary>%s</details>"
                    % (len(later), _front_groups(later, cap=None)))
    rail = [_week_rail(), countdown_card(today), _recordings_rail(),
            _guides_rail()]
    return ('<div class="todaygrid schoolview"><div class="todaymain">%s</div>'
            '<aside class="todayrail">%s</aside></div>'
            % ("".join(m for m in main if m), "".join(r for r in rail if r)))


def _classes_today(cfg=None):
    """Today's classes, each with its guide if one exists.

    The calendar already holds the whole term and the page was not using it
    for this. Between sessions the question is "what am I in next, and where
    is the material" — two clicks that should be none."""
    try:
        import calendar_read
        evs = calendar_read.events(1)
    except Exception:                                    # noqa: BLE001
        return ""
    import html as _h
    seen, rows = set(), []
    guides = {}
    groot = os.path.join(BRAIN, "school", "guides")
    if os.path.isdir(groot):
        for course in os.listdir(groot):
            if course.startswith("."):
                continue
            cdir = os.path.join(groot, course)
            if not os.path.isdir(cdir):
                continue
            for fn in sorted(os.listdir(cdir)):
                if fn.endswith(".html"):
                    guides.setdefault(course, []).append(
                        ("school/guides/%s/%s" % (course, fn), fn[:-5]))
    try:
        import school as _sc
        known = _sc.courses()
    except Exception:                                    # noqa: BLE001
        known = []

    for when, title in evs:
        t = _h.unescape(title or "")
        if not _is_school_event(t, known):
            continue
        name = re.split(r"\s+-\s+", t)[0].strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        # Which course folder is this, so the right guides attach.
        low = name.lower()
        slug = ""
        for c in known:
            if sum(1 for w in c["words"] if w in low) >= 2:
                slug = re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-",
                                                 c["name"].lower())).strip("-")
                break
        link = ""
        if slug and guides.get(slug):
            href, label = guides[slug][-1]
            link = ('<a href="%s" target="_blank" rel="noopener">guide</a>'
                    % e(href))
        rows.append('<div class="mtrow"><span class="mttask">%s'
                    '<i>%s</i></span>%s</div>'
                    % (e(name[:70]), e(str(when)[-5:]), link))
    if not rows:
        return ""
    return ('<section class="mttray"><h2>Today'
            + hint("From your calendar, with the guide for that class when "
                   "one has been built.")
            + "</h2>%s</section>" % "".join(rows[:8]))


def _guides_card(cfg=None):
    """The class guides, openable from here.

    They are single files next to the page, so a plain relative link opens
    one in the same browser — which is the whole point of building them as
    HTML rather than as notes in a folder."""
    root = os.path.join(BRAIN, "school", "guides")
    if not os.path.isdir(root):
        return ""
    found = []
    for course in sorted(os.listdir(root)):
        # .data holds the cached content the guides are rendered from — a
        # sibling of the courses, not one of them.
        if course.startswith("."):
            continue
        cdir = os.path.join(root, course)
        if not os.path.isdir(cdir):
            continue
        for fn in sorted(os.listdir(cdir)):
            if not fn.endswith(".html"):
                continue
            full = os.path.join(cdir, fn)
            title = fn[:-5].replace("-", " ")
            try:
                with open(full, encoding="utf-8") as f:
                    head = f.read(3000)
                m = re.search(r"<title>(.*?)(?: &mdash; | — )", head, re.S)
                if m:
                    title = m.group(1).strip()
                mt = os.path.getmtime(full)
            except OSError:
                mt = 0
            found.append((mt, course, title,
                          "school/guides/%s/%s" % (course, fn)))
    if not found:
        return ""
    found.sort(reverse=True)
    # The whole-course guide leads its course: in December that is the one
    # she opens, and a session guide is what she opens the week of the class.
    found.sort(key=lambda r: (0 if r[3].endswith("_course.html") else 1))
    rows = "".join(
        '<div class="mtrow"><span class="mttask">'
        '<a href="%s" target="_blank" rel="noopener">%s</a>'
        "<i>%s</i></span></div>"
        % (e(href),
           e("%s \u2014 everything so far" % course.replace("-", " ").title()
             if href.endswith("_course.html") else title),
           e(course.replace("-", " ")))
        for _, course, title, href in found[:10])
    return ('<section class="mttray"><h2>Class guides'
            + hint("Built from the slides and your own notes on that class. "
                   "They open in a new tab and work offline.")
            + "</h2>%s</section>" % rows)


def _mailtasks_row(cfg, have_account=True):
    """Task suggestions from whitelisted mail. The whitelist is hers, the
    reader has no tools, and nothing moves without her Accept — the full
    boundary is in mail_tasks.py and decisions.md (2026-09-08)."""
    if not have_account:
        return ""
    try:
        import mail_tasks as _mt
        allowed = _mt.senders(cfg)
        pend = _mt.pending()
    except Exception:                                    # noqa: BLE001
        allowed, pend = [], []
    on = bool(allowed)
    # The suggestions themselves live on Today (_mailtasks_tray) — a queue
    # waiting on her is not a setting. Here, just how many are waiting.
    tray = (f'<span class="mrfound">{len(pend)} waiting on Today.</span>'
            if pend else "")
    chips = "".join(
        f'<span class="mtchip">{e(s)}<button class="mtx" data-mtrm="{e(s)}" '
        'title="Remove">&times;</button></span>' for s in allowed)
    adder = ('<input id="mt-add" placeholder="name@school.fr or @school.fr" '
             'size="22"><button class="mini" id="mt-addbtn">Allow</button>')
    if on:
        state = (chips + " " + adder
                 + ' <button class="mini" id="mt-check">Check for tasks</button>')
    else:
        state = ("Off &mdash; whitelist a sender and their emails can propose "
                 "tasks for you to accept. " + adder)
    return (
        '<div class="connrow needs-server"><i class="cdot'
        + (" on" if on else "") + '"></i><b>Task mail</b><span>'
        + state
        + '<span class="mshelp" id="mt-help"></span>'
        + tray
        + '<details class="connhow"><summary>How this stays safe</summary>'
        "Only senders on your list are read, and only when your own mail "
        "server vouches for the message (DMARC) &mdash; a spoofed From gets "
        "dropped. The body goes to a small model with no tools and no access "
        "to your files; all it can do is propose up to three tasks here. "
        "Nothing enters your brain until you press Accept, which adds one "
        "line to your inbox for normal triage. Runs on your click only."
        "</details></span></div>")


def _calblock_row(cfg):
    """Where "Block time for it…" writes. A local calendar stays on the Mac;
    one belonging to an account is what puts blocks on her phone."""
    try:
        import calendar_write
        cals = calendar_write.calendars()
    except Exception:
        cals = []
    if not cals:
        return ""
    cur = (cfg.get("calendar_target") or "").strip()
    opts = ['<option value=""' + ("" if cur else " selected")
            + '>Brain (local to this Mac)</option>']
    for c in cals:
        opts.append(f'<option value="{e(c)}"'
                    + (" selected" if c == cur else "") + f">{e(c)}</option>")
    return ('<span class="msteps">Time blocks go to: '
            f'<select id="cal-target">{"".join(opts)}</select> '
            '<span id="cal-tnote"></span><br>'
            'Blocks only ever get ADDED &mdash; nothing else in that calendar '
            'is read, moved or deleted. Pick one that belongs to an account '
            '(your school/Outlook one, or iCloud) and the blocks appear on '
            'your phone; the local Brain calendar stays on this Mac. '
            '<b>Want a separate calendar that still syncs?</b> In the Calendar '
            'app: File &rarr; New Calendar &rarr; pick the account, name it '
            '&ldquo;Brain&rdquo;, then choose it here.</span>')


def draftcard(d, email_ready=False, from_addr=""):
    """One thing Claude prepared. The send affordance depends on channel AND
    on the person's circle — an Inner/Close draft gets copy only, by design."""
    kind = d["kind"]
    icon = {"email": "&#9993;", "message": "&#128172;", "form": "&#9999;",
            "note": "&#128196;"}.get(kind, "&#128196;")
    head = e(d["subject"] or d["to"] or d["person"] or d.get("title")
             or kind.title())
    to = []
    if d["to"]:
        to.append("to " + e(d["to"]))
    elif d["person"]:
        to.append("to " + e(d["person"])
                  + (f' <span class="v v-unk">{e(d["circle"])}</span>' if d["circle"] else ""))
    if d["task"]:
        to.append("for &ldquo;" + e(d["task"][:50]) + "&rdquo;")
    if d.get("stale"):
        to.append(f'<span class="dstale">{e(d.get("stale_why", ""))}</span>')
    meta = " &middot; ".join(to)

    # Actions, gated. Email always → open in the owner's own mail client.
    acts = []
    if kind == "email" and d["to"]:
        if email_ready and not d["personal"]:
            acts.append(f'<button class="act send" data-sendemail="{e(d["file"])}"'
                        f' data-to="{e(d["to"])}" data-subject="{e(d["subject"])}"'
                        f' data-from="{e(from_addr)}">Approve &amp; send</button>')
        acts.append(f'<button class="act{"" if email_ready else " send"}" '
                    f'data-mailto="{e(d["to"])}"'
                    f' data-subject="{e(d["subject"])}" data-file="{e(d["file"])}">'
                    "Open in email</button>")
    if kind == "message" and d["channel"] == "beeper":
        if d["personal"]:
            acts.append('<span class="draftnote">Inner/Close &mdash; copy and send it '
                        "yourself</span>")
        else:
            acts.append(f'<button class="act send" data-beeper="{e(d["file"])}"'
                        f' data-who="{e(d["person"])}">Review &amp; send via Beeper</button>')
    acts.append(f'<button class="act" data-copy="{e(d["file"])}">Copy</button>')
    acts.append(f'<button class="mini" data-draftsent="{e(d["file"])}">Mark done</button>')
    acts.append(f'<button class="mini" data-draftdiscard="{e(d["file"])}">Discard</button>')

    fn = e(d["file"])
    # The body is directly editable (free) and has a small revise box that
    # sends only this draft to Claude, not the whole brain.
    return (f'<details class="draft" data-file="{fn}"><summary>'
            f'<span class="dkind">{icon}</span>'
            f'<span class="dmain"><span class="dhead">{head}</span>'
            f'<span class="dmeta">{meta}</span></span>'
            '<span class="dedit">Edit</span></summary>'
            f'<div class="dbody" id="d-{fn}" contenteditable="false" '
            f'spellcheck="true">{e(d["body"])}</div>'
            '<div class="drevise needs-server">'
            f'<input class="drevin" placeholder="Tell Claude a change &mdash; '
            'e.g. warmer, shorter, drop the last line">'
            f'<button class="mini rev" data-revise="{fn}">Revise</button>'
            '<span class="revnote"></span></div>'
            f'<div class="acts needs-server">{"".join(acts)}'
            f'<button class="mini dsave" data-save="{fn}" hidden>Save edit</button>'
            "</div></details>")


def writingcard():
    """The voice guide, shown and editable on the page.

    Her rules for how anything a third party reads gets written. They were
    only ever visible by opening the file, which meant the one thing she was
    told to edit freely was the one thing she never saw. Rendered here, with
    the raw markdown behind an Edit toggle — the frontmatter is kept by the
    server, so she edits prose, not a header she has to preserve."""
    raw = read("writing-rules.md")
    if not raw.strip():
        return ""
    meta, body = MD.split_frontmatter(raw)
    updated = (meta or {}).get("updated", "")
    when = f'<span class="wrwhen">last changed {e(updated)}</span>' if updated else ""
    return ('<section id="writing"><h2>'
            '<img class="h2art" src="art/reading.png?v=1" alt="" width="34" height="34">'
            'How Claude writes for you'
            + hint("Your voice guide. Claude loads this before drafting anything "
                   "someone else will read, from an email to a job application. "
                   "It does not change how Claude talks to you here. Edit it and "
                   "the next draft follows the new version.")
            + "</h2>"
            '<details class="wrules"><summary><span class="wrsum">See the rules '
            'Claude is following</span>' + when + "</summary>"
            f'<div class="wrbody">{MD.render(body)}</div>'
            '<div class="acts needs-server">'
            '<button class="mini" id="wr-edit">Edit them</button></div>'
            '<form class="wredit needs-server" id="wr-form" hidden>'
            f'<textarea id="wr-text" spellcheck="true">{e(body.strip())}</textarea>'
            '<div class="acts"><button type="submit" class="act send">Save</button>'
            '<button type="button" class="mini" id="wr-cancel">Cancel</button>'
            '<span class="wrnote" id="wr-note"></span></div></form>'
            "</details></section>")


def dayword(n):
    """"1 day", "2 days". Every count on this page had `{n} days` hardcoded,
    so a horizon touched yesterday read "1 days untouched"."""
    n = abs(int(n or 0))
    return f"{n} day" + ("" if n == 1 else "s")


def ago(days):
    """A last-spoke gap in words a person actually uses. '157 days' is a number
    you have to decode; '5 months ago' you just feel."""
    if days is None:
        return ""
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days}d ago"
    if days < 61:
        w = round(days / 7)
        return f"{w} week{'s' if w != 1 else ''} ago"
    if days < 330:                    # 330+ says "a year", never "12 months"
        mo = round(days / 30)
        return f"{mo} month{'s' if mo != 1 else ''} ago"
    y = max(1, round(days / 365))
    return f"{y} year{'s' if y != 1 else ''} ago"


def _avatar(name, drag=False):
    """The real face when the Beeper sync has cached one (brain/avatars/,
    local copies of Beeper's own media cache); otherwise the initial on a
    hue that is stable per person, so the eye learns 'the green M is Maman'
    and scanning replaces reading.

    `drag=True` makes the face itself the handle for moving that person to
    another group. Rows ask for it; shelf faces do not, because there the
    whole button is the handle and a draggable inside a draggable is a
    coin-toss over which one the browser picks up.
    """
    import unicodedata
    import zlib
    # An <img> is natively draggable and would otherwise drag its own file
    # URL, so the attribute is spelled out either way — off for shelf faces.
    dr = (f' draggable="true" data-dragname="{e(name)}"' if drag
          else ' draggable="false"')
    # Slug must stay identical to beeper.avatar_slug — same person, same file.
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower() or "x"
    for ext in (".jpg", ".png", ".webp", ".gif"):
        if os.path.exists(os.path.join(BRAIN, "avatars", slug + ext)):
            return (f'<img class="pav pavimg{" pavdrag" if drag else ""}"'
                    f' src="avatars/{slug}{ext}" alt=""'
                    f' width="30" height="30" loading="lazy"{dr}>')
    hue = zlib.crc32(name.encode("utf-8")) % 360
    init = next((ch for ch in name if ch.isalpha()), "?").upper()
    return (f'<span class="pav{" pavdrag" if drag else ""}"'
            f' style="--pavh:{hue}"{dr}>{e(init)}</span>')


def shelf(group):
    """A circle as a shelf of faces — the design's glance layer. Steady on
    the left, slipping on the right, so who needs you is a shape rather
    than a paragraph. It sits ABOVE the rows rather than replacing them:
    the rows carry every control (spoke, hold, rhythm, merge) and a face
    the size of a thumbnail is a place to look, not a place to work.

    One deliberate departure from the mock: the lapsed do NOT fade. Fading
    them would hide the answer to the only question this page asks; they
    keep the state colour instead, which is the language everywhere else.
    """
    if len(group) < 3:
        return ""                     # three faces is a row, not a shelf
    def rank(p):
        return (2 if p["owed"] else 1 if p["overdue"] else 0,
                p.get("lapse_ratio") or 0, p["name"].lower())
    faces = []
    for p in sorted(group, key=rank):
        # The caption has to explain the ORDER, or the shelf looks broken:
        # someone four days into a quarterly rhythm is steadier than someone
        # two days into a weekly one, and "spoke 4d ago" next to "spoke 2d
        # ago" reads as a sorting bug unless the rhythm is on show.
        rhy = p.get("every_label") or ""
        rhy = "" if rhy in ("no rhythm set", "no set rhythm") else rhy
        if p.get("held"):
            st, why = "held", f'on hold until {p.get("hold", "")}'
        elif p["owed"]:
            st, why = "owed", "owes you a reply"
        elif p["overdue"]:
            gap = ago(p["days_since"]).replace(" ago", "")
            st, why = "late", (f"{gap} vs {rhy}" if rhy else f"{gap} quiet")
        elif p["days_since"] is None:
            st, why = "ok", "never logged"
        else:
            gap = ("today" if p["days_since"] == 0
                   else ago(p["days_since"]).replace(" ago", ""))
            st, why = "ok", (f"{gap} · {rhy}" if rhy else f"spoke {gap}")
        # A face with its name and where it stands — the design's shelf reads
        # as people, not as beads. Beyond a dozen the shelf folds, because a
        # 164-strong circle is a wall, not a glance.
        slipping = "1" if (p["owed"] or p["overdue"]) else "0"
        faces.append(
            f'<button class="shface sh-{st}" data-shjump="{e(p["name"])}"'
            f' data-slip="{slipping}" draggable="true"'
            f' title="{e(p["name"])} &mdash; {e(why)}. '
            'Drag onto another group to move them.">'
            + _avatar(p["name"])
            + f'<span class="shname">{e(p["name"])}</span>'
            + f'<span class="shwhy">{e(why)}</span>'
            + "</button>")
    n_need = len([p for p in group if p["owed"] or p["overdue"]])
    shown, rest = faces[:12], faces[12:]
    more = (f'<button class="shmore" data-shmore>+{len(rest)} more</button>'
            if rest else "")
    hidden = (f'<span class="shrest" hidden>{"".join(rest)}</span>' if rest else "")
    note = (f"{n_need} of {len(group)} need you" if n_need else "all steady")
    return (f'<div class="shelf" data-need="{n_need}">'
            f'<div class="shrow">{"".join(shown)}{hidden}{more}</div>'
            f'<p class="shnote">{note}'
            '<button class="shlist" data-shlist>read as a list</button>'
            "</p></div>")


def personrow(p, ledger=False):
    """One person. Two registers, one grammar:

    ledger=True (Today's five, Focus) — the debt view: what is owed, how far
    past their own rhythm, a lapse bar you can see without reading, and the
    action to close it right on the row.

    ledger=False (the directory) — a neutral address book: name, when you
    spoke, who they are. It is for FINDING people, so it stays flat —
    the urgency lives in the ledger above."""
    bits = []
    if p.get("held"):
        bits.append(f'<span class="heldnote">together &mdash; on hold until {e(p["hold"])}</span>')
    if p["owed"]:
        # "owe a reply · spoke today" reads like a contradiction until you know
        # what the flag means: the last word is THEIRS. Say that when the two
        # collide. (The sync clears this flag by itself once you answer.)
        txt = ("you owe them a reply"
               + (" &mdash; theirs is the last word"
                  if p["days_since"] is not None and p["days_since"] <= 1 else ""))
        bits.append(f"<b>{txt}</b>" if ledger else txt)
    if p["overdue"]:
        g = ago(p["days_since"]).replace(" ago", "")
        bits.append(f"{g} since you spoke &middot; you wanted {e(p['every_label'])}")
    elif p["never"]:
        bits.append("never logged yet"
                    + (f" &middot; you wanted {e(p['every_label'])}" if ledger else ""))
    elif p["days_since"] is not None:
        d = p["days_since"]
        bits.append("spoke today" if d == 0 else
                    "spoke yesterday" if d == 1 else f"spoke {ago(d)}")
    if p.get("bday_soon"):
        d = p["bday_in"]
        bits.append("<b>birthday " + ("today" if d == 0 else
                    "tomorrow" if d == 1 else f"in {d} days") + "</b>")
    if p.get("promised"):
        n = len(p["open_promises"])
        bits.append(f"{n} promise{'s' if n != 1 else ''} open")
    why = f'<p class="matters">{e(p["why"])}</p>' if p["why"] else ""
    # Professional block: role at company, a clickable LinkedIn, how/where you
    # met. The networking half of the relationship, when it exists.
    prof = []
    rc = " at ".join(x for x in [p.get("role"), p.get("company")] if x)
    if rc:
        prof.append(f"<b>{e(rc)}</b>")
    if p.get("how"):
        prof.append(e(p["how"]))
    if p.get("met"):
        prof.append("met " + e(p["met"]))
    if MD.safe_href(p.get("linkedin")):
        prof.append(f'<a class="lilink" href="{e(MD.safe_href(p["linkedin"]))}" target="_blank" '
                    f'rel="noopener">LinkedIn &#8599;</a>')
    profline = (f'<p class="prof">{" &middot; ".join(prof)}</p>' if prof else "")
    facts = []
    if p.get("pronouns"):
        facts.append(e(p["pronouns"]))
    for tg in p.get("tags", []):
        facts.append(f'<span class="ptag">{e(tg)}</span>')
    if p.get("where"):
        facts.append(e(p["where"]))
    if p.get("reach"):
        facts.append(f'reach via {e(p["reach"])}')
    if p.get("birthday"):
        facts.append(f"birthday {e(p['birthday'])}")
    factline = (f'<p class="meta">{" &middot; ".join(facts)}</p>' if facts else "")
    # The chat names folded into this person. Without this a merged WhatsApp
    # contact simply vanishes: not in the unsorted list, not findable by the
    # name you knew them under.
    if p.get("also"):
        factline += ('<p class="palso">also answers to '
                     + ", ".join(f"<b>{e(a)}</b>" for a in p["also"])
                     + " &mdash; merged into this person</p>")
    promises = ""
    if p.get("promises"):
        promises = ('<ul class="tasks">'
                    + "".join(taskrow(t_, src="people.md") for t_ in p["promises"])
                    + "</ul>")
    # Open tasks elsewhere that name this person — the other half of linking.
    if p.get("mentions"):
        lis = "".join(f'<li>{e(txt)} <span class="mws">&mdash; {e(wsn)}</span></li>'
                      for wsn, txt in p["mentions"])
        promises += (f'<div class="pmentions"><p class="meta">Comes up in</p>'
                     f"<ul>{lis}</ul></div>")
    notes = (f'<div class="notes">{MD.render(chr(10).join(p["notes"]))}</div>'
             if p["notes"] else "")
    focus = '<span class="pstar" title="Focus — you are investing here">&#9733;</span>' if p["focus"] else ""
    # The tier as a small grey word — only in the ledger, where rows from
    # different circles mix; the directory's rows sit under their own heading.
    tier = (f'<span class="ptier">{e(p["circle"].lower())}</span>'
            if ledger and p["circle"] and p["circle"] != "Everyone else" else "")
    # An owed reply needs attention, but nothing about it is late in the way
    # a passed date is late — it warns, it does not block. sev-cold still
    # carries "gone quiet", which is the same blue everywhere else.
    sev = ("sev-wait" if p["owed"] else
           ("sev-cold" if p["overdue"] or p["never"] else "")) if ledger else ""
    # The lapse in a channel you can see without reading: a thin bar that
    # fills as the debt grows past their own rhythm (full = 3x over).
    pbar = ""
    if ledger and p.get("lapse_ratio"):
        pct = round(min(p["lapse_ratio"], 3.0) / 3.0 * 100)
        pbar = f'<span class="bar pbar"><i style="width:{pct}%"></i></span>'
    # The action, not a label, on the right rail: close the debt from the row.
    act = ""
    if p["owed"]:
        act = (f'<button class="mini prepl needs-server" data-replied="{e(p["name"])}"'
               f' title="You answered them &mdash; clears the debt, stamps today">'
               "&#10003; Replied</button>")
    elif ledger and (p["overdue"] or p["never"]):
        act = (f'<button class="mini prepl needs-server" data-spoke="{e(p["name"])}"'
               f' title="You reached them &mdash; stamps today, resets their rhythm">'
               "&#10003; Spoke</button>")
    # Role at company sits under the name so the People page reads as a
    # directory for professional contacts, not just a warmth tracker.
    rowsub = f'<span class="rowsub">{e(rc)}</span>' if rc else ""
    return (f'<details class="row person {sev}" data-name="{e(p["name"])}"'
            f' data-flags="{" ".join(p["flags"])}" data-ball="{p["ball"]}"'
            f' data-focus="{"1" if p["focus"] else "0"}"'
            f' data-places="{e(" | ".join(([p["where"]] if p.get("where") else []) + p.get("tags", [])))}"'
            f' data-also="{e(" | ".join(p.get("also", [])))}">'
            "<summary>"
            + _avatar(p["name"], drag=True) +
            '<span class="rowmain">'
            f'<span class="rowname">{e(p["name"])}{focus}{tier}</span>'
            f'<span class="rowwhy">{" &middot; ".join(bits)}</span>'
            f'{rowsub}'
            "</span>"
            f"{act}{pbar}"
            f'<button class="pmenu needs-server" data-pmenu="{e(p["name"])}"'
            ' aria-label="Rename, merge, archive or delete">&#8943;</button>'
            "</summary>"
            f'<div class="rowbody">{why}{profline}{factline}{promises}{notes}'
            '<div class="acts needs-server">'
            f'<button class="act" data-openchat="{e(p["name"])}" title="Opens Beeper '
            'Desktop on your chat with them &mdash; nothing is sent">Open the chat &#8599;</button>'
            f'<button class="act" data-spoke="{e(p["name"])}">Spoke today</button>'
            + (f'<button class="act" data-unhold="{e(p["name"])}" title="You&rsquo;re '
               'apart again — rhythms and replies resume">End hold</button>'
               if p.get("held") else
               f'<button class="act" data-hold="{e(p["name"])}" title="You&rsquo;re '
               'together (living with them, travelling with them) — no owed replies, '
               'no rhythm, until the date you pick">Together / hold&hellip;</button>')
            + f'<button class="act" data-detail="{e(p["name"])}"><b>+</b> Details</button>'
            f'<button class="act" data-claudetalkperson="{e(p["name"])}"'
            ' title="A live conversation that opens already knowing them &mdash;'
            ' what to plan, what to say, what they&rsquo;d enjoy">Talk it through</button>'
            f'<button class="act" data-promise="{e(p["name"])}"><b>+</b> Promise</button>'
            f'<label class="pcircle">Circle '
            f'<select data-pcircle="{e(p["name"])}">{circleopts_for(p["circle"])}</select>'
            "</label>"
            + f'<button class="act" data-pevery="{e(p["name"])}"'
            f' data-cur="{e("" if p["every_from_circle"] else p["every_label"])}"'
            ' title="This person&rsquo;s own rhythm (&ldquo;3 days&rdquo;, &ldquo;weekly&rdquo;) '
            '&mdash; beats the group&rsquo;s. Empty hands them back to the group.">'
            + ("Rhythm: " + e(p["every_label"])
               + ('<span class="rfrom">from ' + e(p["circle"]) + '</span>'
                  if p["every_from_circle"] else
                  ('<span class="rfrom own">set for them</span>'
                   if p["every_label"] != "no rhythm set" else "")))
            + "</button>"
            + (f'<button class="mini pfocus on" data-pfocus="{e(p["name"])}"'
               ' title="You are deliberately investing in them — they surface sooner '
               'when quiet. Click to stop.">&#9733; Focus</button>' if p["focus"] else
               f'<button class="mini pfocus" data-pfocus="{e(p["name"])}"'
               ' title="Growing closer? Focus makes them surface sooner when quiet '
               '— an intention, without pretending the circle is closer than it is.">'
               "&#9734; Focus</button>")
            + '<span class="ballgroup" role="group" aria-label="Who owes a message">'
            '<span class="balllabel" title="Who owes whom a reply right now">Reply owed by</span>'
            f'<button class="ball{" on" if p["ball"]=="me" else ""}"'
            f' data-pball="me" data-name="{e(p["name"])}">me</button>'
            f'<button class="ball{" on" if p["ball"]=="them" else ""}"'
            f' data-pball="them" data-name="{e(p["name"])}">them</button>'
            f'<button class="ball{" on" if p["ball"]=="nobody" else ""}"'
            f' data-pball="nobody" data-name="{e(p["name"])}">no one</button>'
            "</span>"
            f'<button class="act right" data-ask="{e(p["name"])}">Tell Claude</button>'
            "</div></div></details>")


def circleopts_for(current):
    """Circle <option>s for a person row, from config, current one selected."""
    opts = []
    for c in M.circles().values():
        sel = " selected" if c["name"].lower() == (current or "").lower() else ""
        opts.append(f'<option{sel}>{e(c["name"])}</option>')
    if current and current.lower() not in M.circles():
        opts.insert(0, f'<option selected>{e(current)}</option>')
    return "".join(opts)




_STOP = {"with", "from", "that", "this", "your", "into", "about", "them",
         "then", "when", "have", "will", "what", "pour", "dans", "avec",
         "the", "and", "for", "her", "him", "une", "les", "des"}


def _sig_tokens(s):
    """The words that carry a task's identity — lowercase, punctuation off,
    stopwords out. Used to tell whether the hero and the plan agree."""
    return {t for t in re.findall(r"[a-zà-ÿ0-9€]+", (s or "").lower())
            if len(t) >= 4 and t not in _STOP}


def _same_thing(a, b):
    """Do two strings name the same piece of work? Two shared significant
    words, or one long one. Deliberately loose: "Book train Burgundy → Paris →
    Angoulême" and "Decide Thursday or Friday, then book the train" are the
    same errand to a person, and the page should not print both."""
    shared = _sig_tokens(a) & (b if isinstance(b, set) else _sig_tokens(b))
    return len(shared) >= 2 or any(len(x) >= 7 for x in shared)


def plan_tokens(today_md):
    """Today's plan, as one token-set per task line. Parsed once per build."""
    out = []
    for ln in (today_md or "").split("\n"):
        m = re.match(r"^\s*[-*]\s+\[[ xX]\]\s+(.*)$", ln)
        if m:
            toks = _sig_tokens(MD.plain(m.group(1)))
            if toks:
                out.append(toks)
    return out


def plan_ws_lookup(items, cfg):
    """Which project a plan task belongs to. Exact text first (the plan quotes
    workstream tasks verbatim — that is the tick-mirror rule), then the same
    loose token match `_same_thing` uses, then the workstream's own name
    appearing in the task's words. Gives "Do these three" rows their chip."""
    rlab = room_labels(cfg)
    exact, loose, names = {}, [], []
    for w in items:
        if not w.get("live"):
            continue
        ntoks = _sig_tokens(w["name"])
        if ntoks:
            names.append((ntoks, w["name"]))
        for t in w.get("tasks", []):
            if t["done"] or t.get("dropped"):
                continue
            exact[MD.plain(t["text"]).strip().lower()] = w["name"]
            toks = _sig_tokens(t["text"])
            if toks:
                loose.append((toks, w["name"]))

    def look(text):
        name = exact.get((text or "").strip().lower())
        toks = _sig_tokens(text)
        if not name:
            for ptoks, nm in loose:
                shared = toks & ptoks
                if len(shared) >= 2 or any(len(x) >= 7 for x in shared):
                    name = nm
                    break
        if not name:
            name = next((nm for ntoks, nm in names if ntoks <= toks), None)
        return (name, rlab.get(name, "")) if name else None

    return look


def plan_estimates(today_md):
    """Today's open plan tasks as {label, min} for the forecast — the `~30m`
    when the task carries one, None when it doesn't, so the forecast can fall
    back to the configured default and still count the task."""
    out = []
    for ln in (today_md or "").split("\n"):
        m = re.match(r"^\s*[-*]\s+\[ \]\s+(.*)$", ln)
        if not m:
            continue
        raw = m.group(1)
        if MD.DROPPED.search(raw) or MD.UNTIL.search(raw):
            continue
        est = M.EST.search(raw)
        txt = re.sub(r"\s*\(urgent\)", "", M.EST.sub("", raw), flags=re.I)
        out.append({"label": MD.plain(MD.CARRYING.sub("", txt)).strip(),
                    "min": M.est_to_minutes(est.group(1)) if est else None})
    return out


def next_line(w):
    """The one sentence a workstream would show as its next move. Every block
    that names a workstream ends up printing this, which is why they all have
    to agree about who said it first."""
    return w.get("next_action") or next(
        (t["text"] for t in w.get("tasks", []) if not t["done"]), "")


def in_plan(text, toks):
    """Is this already on today's list? The one rule that keeps a task from
    appearing in five blocks at once.

    This existed for a year as a closure inside "Off your plate in minutes",
    which is why that block alone was clean while the hero, the horizons and
    the offer card printed the same train journey six times between them.
    """
    return any(_same_thing(text, p) for p in (toks or []))


def hero_plan_link(w, today_md):
    """One honest chip: is the hero the plan's task one, elsewhere in the
    plan, or has the day moved since the plan was written? Nothing when
    there is no written plan to disagree with."""
    tasks = re.findall(r"^\s*-\s+\[([ xX])\]\s+(.*)$", today_md or "", re.M)
    if not tasks:
        return ""
    mine = _sig_tokens(w["name"]) | _sig_tokens(w.get("next_action", ""))
    for t in w.get("tasks", []):
        if not t["done"]:
            mine |= _sig_tokens(t["text"])
            break
    hit, hit_done = None, False
    for i, (mark, text) in enumerate(tasks):
        shared = mine & _sig_tokens(text)
        if len(shared) >= 2 or any(len(x) >= 6 for x in shared):
            hit, hit_done = i, mark.lower() == "x"
            break
    if hit is None:
        return ('<a class="heroplan off" href="#today">not in the written plan '
                '&mdash; the day may have moved; &#8635; refresh it &darr;</a>')
    if hit_done:
        return '<a class="heroplan" href="#today">already ticked in today&rsquo;s plan &#10003;</a>'
    if hit == 0:
        return '<a class="heroplan" href="#today">task one in today&rsquo;s plan &darr;</a>'
    # Naming the POSITION is what "also in the plan" never did. The hero is a
    # workstream and the plan is a list of tasks, so "Book train from Burgundy
    # to Paris" up here and "Decide Thursday or Friday? Then book the train"
    # as item three down there read as two separate jobs unless the page says
    # they are one. Ordinals, because "task 3" is something you can look for.
    ORD = ("one", "two", "three", "four", "five", "six", "seven", "eight")
    where = ORD[hit] if hit < len(ORD) else str(hit + 1)
    return (f'<a class="heroplan" href="#today">task {where} in today&rsquo;s '
            "plan &darr;</a>")


def _legend_html(b):
    """The Field Manual header legend: the five states with live counts.
    Hidden furniture (.skinx) until a skin shows it."""
    moving = len([w for w in b["live"]
                  if not (w["overdue"] or w["chase"] or w["cold"]
                          or w["never_touched"] or w["due_soon"])])
    bits = [("red", "past due", len(b["overdue"])),
            ("amber", "they quiet", len(b["chase"])),
            ("blue", "you quiet", len(b["cold"])),
            ("terra", "due soon", len(b["soon"])),
            ("ok", "moving", moving)]
    return "".join(
        f'<span class="lgch"><i class="lg-{k}"></i>{lbl} {n}</span>'
        for k, lbl, n in bits)


def _greeting(today_md):
    """"Friday evening. One thing left." — the day's name, its phase, and the
    honest count of the plan. The Soft Brutalism skin's headline; computed
    for every build because it is four string operations."""
    now = datetime.now()
    day = now.strftime("%A")
    phase = ("morning" if now.hour < 12 else
             "afternoon" if now.hour < 17 else "evening")
    m = re.search(r"##\s*Do these three\n(.*?)(?=\n##|\Z)", today_md or "", re.S)
    block = m.group(1) if m else ""
    total = len(re.findall(r"^\s*-\s*\[[ xX]\]", block, re.M))
    done = len(re.findall(r"^\s*-\s*\[[xX]\]", block, re.M))
    left = total - done
    if not total:
        return f"{day} {phase}." if phase != "morning" else f"{day}."
    if phase == "morning":
        return f"{day}. " + ({3: "Three things.", 2: "Two things.",
                              1: "One thing."}.get(total, f"{total} things."))
    if left <= 0:
        return f"{day} {phase}. All {total} are done."
    if phase == "evening":
        # Never a count after dark. "3 things left" at 21:00 is a scoreboard
        # she can no longer change, and it read as an accusation on a day
        # that simply went somewhere else (packing day, 31 Aug — her words:
        # "stresses me out"). The evening asks; the review below listens.
        return f"{day} evening. How did it go?"
    if left == 1:
        return f"{day} {phase}. One thing left."
    return f"{day} {phase}. {left} things left."


def _plan_time():
    """When today's plan was last written, as HH:MM — or ""."""
    try:
        ts = os.path.getmtime(os.path.join(BRAIN, "today.md"))
        return datetime.fromtimestamp(ts).strftime("%H:%M")
    except OSError:
        return ""


def _days_ago(datestr):
    try:
        n = (date.today() - date.fromisoformat(datestr)).days
    except (TypeError, ValueError):
        return ""
    return "today" if n == 0 else ("yesterday" if n == 1 else f"{n} days ago")


def hero(w, cfg, today_md="", ntotal=0):
    """The single most expensive thing to keep ignoring, given the whole top
    of the page. One item, huge, with its reason and its next move."""
    pct = round(decay(w, cfg) * 100)
    # What "Do this" is about to say, so the reason above it doesn't say the
    # same sentence again four lines earlier.
    nextline = next_line(w)
    reason = why_line(w, hero=True, skip_task=nextline)
    h = [f'<section class="hero {sevclass(w)}" data-name="{e(w["name"])}"'
         f' data-flags="{" ".join(w["flags"])} {w["ball"]}">']
    # Being late on something still winnable is the one hero state that was
    # never drawn. It is also the one she most needs to feel.
    art = artvid("hurrying", 72) if w.get("pressed_late") else ""
    h.append(heroline(f'<p class="eyebrow">{hero_eyebrow()}</p>'
                      '<span class="wav"></span>', art))
    # Skin furniture (hidden unless the active skin asks for it): the
    # provenance line the print-flavoured skins stamp under the eyebrow.
    prov = []
    pt = _plan_time()
    if pt:
        prov.append("chosen " + pt)
    if ntotal:
        prov.append(f"rank 1 of {ntotal}")
    if w.get("area"):
        prov.append(e(w["area"]))
    if prov:
        h.append('<p class="skinx skinx-prov">' + " &middot; ".join(prov) + "</p>")
    h.append(f'<h1>{e(w["name"])}</h1>')
    if reason:
        h.append(f'<p class="hero-why">{reason}</p>')
    if nextline:
        # "Done" lives on the line itself. "Worked on it today" only resets
        # the clock, and the ✓ in the … menu retires the whole workstream —
        # neither says "this next move is finished". If the line is a real
        # checkbox it ticks like any other; if it is the Next: field, the
        # field clears, the touch clock resets, and the next open task
        # inherits the slot on rebuild.
        tk = next((t for t in w.get("tasks", [])
                   if not t.get("done") and not t.get("parked")
                   and not t.get("dropped") and t.get("text") == nextline
                   and t.get("key")), None)
        if tk:
            tickbtn = ('<button class="box tick needs-server" aria-pressed="false"'
                       f' data-src="workstreams.md" data-key="{tk["key"]}"'
                       ' title="Done — tick it off"></button>')
        else:
            tickbtn = ('<button class="box tick needs-server" aria-pressed="false"'
                       f' data-nextdone="{e(w["name"])}"'
                       ' title="Done — this next move clears and the clock '
                       'resets"></button>')
        h.append(f'<p class="hero-next"><span>Do this</span>{tickbtn}'
                 f'{e(nextline)}</p>')
    # No ball chip here. The "Next move: mine / theirs" toggle sits in the same
    # band a few pixels below, showing the same fact AND able to change it — so
    # the chip was a read-only echo of the control right next to it. It stays
    # on the plate rows, where the toggle is folded away inside the row.
    meta = []
    link = hero_plan_link(w, today_md)
    if link:
        meta.append(link)
    if w["why"]:
        meta.append(f'<span class="hero-matters">{e(w["why"])}</span>')
    h.append('<div class="hero-meta">' + " ".join(meta) + "</div>")
    # No "Claude prepared this" here. The hero's job is the ONE next move; a
    # numbered account of what was filed, ticked and reworded is a record, and
    # a record belongs where you go to look one up — it is still on the
    # workstream's row and in its details panel. Anything actually needing her
    # hand arrives as a draft under "Ready for you".
    # The spec rows the Field Manual skin renders as its ruled table; other
    # skins leave them hidden. Same facts the hero already implies, made flat.
    opens = [t for t in (w.get("tasks") or []) if not t.get("done")]
    spec = [("Owner", "You" if w["ball"] == "me"
             else ("Nobody's" if w["ball"] == "nobody" else "Them"))]
    if w.get("touched"):
        spec.append(("Last touch", _days_ago(w["touched"]) or e(w["touched"])))
    if w.get("due"):
        spec.append(("Deadline", e(w.get("due_label") or w["due"])))
    if w.get("tasks"):
        spec.append(("Open tasks", f"{len(opens)} of {len(w['tasks'])}"))
    h.append('<dl class="skinx skinx-spec">'
             + "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in spec)
             + "</dl>")
    h.append(f'<div class="bar"><i style="width:{pct}%"></i></div>')
    h.append(actions(w, labelled=True))
    h.append("</section>")
    return "".join(h)


_DUMP_CUES = """<ol class="dumpcuelist" id="dumpcuelist">
        <li data-cue><b>Start with you</b> &mdash; where you are in life, where you live, what you're studying or building</li>
        <li data-cue><b>What fills your days</b> &mdash; the projects, work or study taking your time right now</li>
        <li data-cue><b>The people</b> &mdash; family, close friends, the ones far away you don't want to drift from</li>
        <li data-cue><b>What's weighing on you</b> &mdash; a deadline, something you're dreading, a decision you keep putting off</li>
        <li data-cue><b>Loose threads</b> &mdash; what you owe someone, who owes you, a reply you've been meaning to send</li>
        <li data-cue><b>What you're trying to build in yourself</b> &mdash; habits or routines, and honestly how often</li>
        <li data-cue><b>Anything else</b> &mdash; the small nagging things, or something that doesn't fit a box but matters</li>
      </ol>"""


# The step before the dump, on a brand-new brain: which subscription is
# paying for this, and what that means the brain may do on its own. It comes
# FIRST because the build run it leads into is the biggest single spend of
# the first day — asking afterwards would be asking after the money is gone.
# One tap is enough; the rest folds away for whoever wants it.
_AI_SETUP = """<div class="aiset" id="aiset" hidden>
      <p class="eyebrow">First, one question</p>
      <h2 class="dumph">How much Claude?</h2>
      <p class="dumplead">This brain runs on your own Claude subscription.
        Most of it &mdash; the pages, the reminders, the syncing &mdash; is
        plain code that costs nothing. The thinking parts draw on the same
        allowance as everything else you do with Claude, so it matters which
        plan you&rsquo;re on.</p>
      <div class="aipick">
        <button class="aicard" data-plan="pro">
          <b>I&rsquo;m on Pro</b>
          <span>Nothing runs unless you ask. Haiku by default. A $2-a-day
            ceiling that asks twice before a big run.</span>
        </button>
        <button class="aicard" data-plan="max">
          <b>I&rsquo;m on Max</b>
          <span>Tomorrow&rsquo;s plan writes itself at 7am, Sonnet by
            default, and the day&rsquo;s tasks get prepared ahead of you.</span>
        </button>
      </div>
      <p class="aihint" id="aihint">Not sure? Pick Pro &mdash; it&rsquo;s the
        careful one, and you can change any of this later on the Claude tab
        under Usage.</p>
      <details class="aimore">
        <summary>Set each one myself</summary>
        <div class="airows" id="airows">
          <div class="airow" data-key="morning">
            <span class="ail"><b>The 7am plan</b>
              <em>Writes today&rsquo;s plan before you&rsquo;re up. The steady
                spender &mdash; one run a day.</em></span>
            <span class="aiseg" data-seg="morning">
              <button data-v="auto">Follow the plan</button>
              <button data-v="on">On</button><button data-v="off">Off</button>
            </span>
          </div>
          <div class="airow" data-key="model">
            <span class="ail"><b>Default model</b>
              <em>What a run uses when you don&rsquo;t pick. Haiku costs about
                a tenth of Sonnet; Opus drains a small allowance fastest.
                Fable writes the best prose and costs the most &mdash; pick it
                for drafting, not for thinking.</em></span>
            <span class="aiseg" data-seg="model">
              <button data-v="auto">Follow the plan</button>
              <button data-v="haiku">Haiku</button>
              <button data-v="sonnet">Sonnet</button>
              <button data-v="opus">Opus</button>
              <button data-v="fable">Fable</button>
            </span>
          </div>
          <div class="airow" data-key="openers">
            <span class="ail"><b>Openers</b>
              <em>The morning run also preps the day &mdash; looks up the
                number, drafts the first message. It never sends
                anything.</em></span>
            <span class="aiseg" data-seg="openers">
              <button data-v="auto">Follow the plan</button>
              <button data-v="on">On</button><button data-v="off">Off</button>
            </span>
          </div>
          <div class="airow" data-key="news">
            <span class="ail"><b>News breakdowns</b>
              <em>A plain-language explainer once a day on the subjects
                you&rsquo;re learning. Pennies-scale.</em></span>
            <span class="aiseg" data-seg="news">
              <button data-v="auto">Follow the plan</button>
              <button data-v="on">On</button><button data-v="off">Off</button>
            </span>
          </div>
          <div class="airow" data-key="daily_cap">
            <span class="ail"><b>Daily ceiling</b>
              <em>Once a day costs this much, a run you start asks twice
                before going ahead. Scheduled work is never blocked.</em></span>
            <span class="aiseg aicap">
              <button data-cap="">No ceiling</button><button data-cap="1">$1</button>
              <button data-cap="2">$2</button><button data-cap="5">$5</button>
            </span>
          </div>
          <div class="airow" data-key="night">
            <span class="ail"><b>Night shift</b>
              <em>The heavy jobs run at 1am, in a usage window your own day
                never wanted. The best trick on a small plan &mdash; it needs
                one setup command in a terminal first.</em></span>
            <span class="aiseg ainight">
              <button data-night="on">On</button><button data-night="off">Off</button>
            </span>
          </div>
          <div class="airow" data-key="privacy">
            <span class="ail"><b>Keep the journal private</b>
              <em>Runs that happen while nobody is watching can&rsquo;t open
                your journal. The trade: the morning plan starts without
                yesterday&rsquo;s entry.</em></span>
            <span class="aiseg aipriv">
              <button data-privacy="on">On</button><button data-privacy="off">Off</button>
            </span>
          </div>
        </div>
      </details>
      <div class="aistyle">
        <p class="eyebrow">And how should it look?</p>
        <p class="dumplead">Tap one and this whole page changes with it.
          The &#8943; menu up top holds these plus the colours, anytime.</p>
        <div class="aprow styles" id="ai-style">__AISTYLECHIPS__</div>
      </div>
      <div class="aifoot">
        <button class="primary" id="aigo">Now let&rsquo;s fill your brain</button>
        <span class="aisaved" id="aisaved"></span>
      </div>
    </div>"""


def _dumpcopy(sheet, fresh, cfg=None):
    """The dump overlay speaks differently to an empty brain and a full one.
    First time it's an interview; after that it's an update that MERGES —
    same engine, different promise."""
    if fresh:
        return (sheet
                .replace("__DUMPH__", "Tell the brain about you")
                .replace("__DUMPLEAD__",
                         "Say whatever feels relevant &mdash; who you are, what's "
                         "going on, what's on your mind. There's no right order and "
                         "no form to fill. The prompts below are just nudges if you "
                         "dry up; skip any, or wander off them entirely. Claude "
                         "sorts all of it and checks with you before writing "
                         "anything down.")
                .replace("__DUMPCUES__", _DUMP_CUES)
                .replace("__AISETUP__",
                         _AI_SETUP.replace("__AISTYLECHIPS__",
                                           style_chips(cfg or {})))
                .replace("__DUMPBTN__", "Build my brain"))
    return (sheet
            .replace("__AISETUP__", "")
            .replace("__DUMPH__", "Add to your brain")
            .replace("__DUMPLEAD__",
                     "New projects, new people, updates, worries &mdash; say it "
                     "all in any order. Claude merges it into what's already "
                     "here (nothing duplicates &mdash; a person or project you've "
                     "mentioned before is recognised and updated), and puts "
                     "anything it needs from you in the questions list on Today.")
            .replace("__DUMPCUES__", "")
            .replace("__DUMPBTN__", "Add to my brain"))


def forecastcard(fc):
    """Motion's 'will I make it', in the brain's voice. Whether today fits the
    time you have, and which deadlines this week the work outruns."""
    d = M.fmt_dur
    if not fc["has_data"]:
        return ('<section class="forecast"><p class="eyebrow">The week ahead</p>'
                '<span class="wav"></span>'
                '<div class="empty">Give a task a rough time and a date &mdash; '
                '<em>- [ ] draft the deck ~2h (due 2026-09-20)</em> &mdash; and each '
                'morning I&rsquo;ll tell you whether the week actually fits the hours '
                'you have, and which deadline is going to bite first.</div></section>')
    out = ['<section class="forecast"><p class="eyebrow">The week ahead</p>'
           '<span class="wav"></span>']
    td = fc["today"]
    # Three states, not two. Past 22:00 the honest sentence is not "it fits"
    # — the hours it was counting on are gone — and it is not "you are over"
    # either, which reads as a scolding for a day that is simply finished.
    if td.get("day_over"):
        if td["min"] == 0:
            out.append('<p class="fc-today ok">The day is done, and nothing '
                       "fell due in it.</p>")
        else:
            out.append('<p class="fc-today done">The day is done. About '
                       f'<b>{d(td["min"])}</b> was due. Whatever didn&rsquo;t '
                       "land needs carrying or dropping above.</p>")
    elif td["min"] == 0:
        line = "Nothing falls due today."
        if fc["pull"]:
            p = fc["pull"]
            line += (f' You have room, so get a jump on <b>{e(p["label"])}</b> '
                     f'(~{d(p["min"])}, due in {p["days"]}d).')
        out.append(f'<p class="fc-today ok">{line}</p>')
    elif td["fits"]:
        out.append(f'<p class="fc-today ok">Today needs about <b>{d(td["min"])}</b> '
                   f'and you have ~{d(td["left"])}. It fits.</p>')
    else:
        out.append(f'<p class="fc-today over">Today needs about <b>{d(td["min"])}</b> '
                   f'and you have ~{d(td["left"])}, so move one thing to tomorrow.</p>')
    # The sentence above already spent today's three numbers. Repeating them as
    # a row underneath is the same fact twice, so today only earns a row when
    # the sentence never mentioned it.
    at_risk = fc["at_risk"]
    if not td.get("day_over") and td["min"]:
        at_risk = [dl for dl in at_risk if dl["days"] != 0]
    if at_risk:
        rows = []
        for dl in at_risk:
            when = ("today" if dl["days"] == 0 else "tomorrow" if dl["days"] == 1
                    else f"in {dl['days']}d")
            rows.append(f'<li class="risk"><span class="fc-dot"></span>'
                        f'<span class="fc-lbl">{e(dl["label"])}</span>'
                        f'<span class="fc-when">{when}</span>'
                        f'<span class="fc-gap"><b>{d(dl["short"])} short</b> '
                        f'&middot; needs ~{d(dl["need"])}, room for ~{d(dl["cap"])}'
                        "</span></li>")
        out.append('<ul class="fc-list">' + "".join(rows) + "</ul>")
    # "everything fits" is judged on the real list, never the filtered one:
    # dropping today's row for being a repeat must not turn an over day calm.
    elif not fc["at_risk"] and any(dl["days"] >= 0 for dl in fc["deadlines"]):
        out.append(f'<p class="fc-clear">Everything due in the next '
                   f'{fc["cap"]["horizon_days"]} days fits the time you have.</p>')
    out.append("</section>")
    return "".join(out)


def moneycard(cfg=None):
    """The bank feed's rail card: what you have, the month so far, the burn,
    and how fresh each bank's numbers are. Reads only the aggregate file —
    the raw transactions never reach the page."""
    # Hidden for now at her word (24 Sep): `finance.on_page: false` in
    # config. The feed keeps pulling; only the card is off.
    if not ((cfg or {}).get("finance") or {}).get("on_page", True):
        return ""
    try:
        with open(os.path.join(BRAIN, "finance", "summary.json")) as f:
            s = json.load(f)
    except Exception:
        return ""
    if not s.get("balances"):
        return ""
    eur = sum(float(b["amount"]) for b in s["balances"]
              if b.get("amount") and (b.get("currency") or "") == "EUR")
    banks = sorted({b["bank"] for b in s["balances"]})
    day = lambda iso: (lambda d: f'{d.day} {d.strftime("%b")}')(date(*map(int, iso.split("-"))))
    h = ['<section class="railcard money"><h3 class="area">Money</h3>',
         f'<p class="mo-total"><b>{eur:,.0f}&nbsp;&euro;</b>'
         f'<span class="mo-across"> across {e(" + ".join(banks))}</span></p>']
    ym = date.today().isoformat()[:7]
    m = (s.get("months") or {}).get(ym)
    if m:
        h.append(f'<p class="mo-line">{date.today().strftime("%B")} so far: '
                 f'in {m["in"]:,.0f}&nbsp;&euro;, out {m["out"]:,.0f}&nbsp;&euro;</p>')
    burn = s.get("monthly_burn_estimate")
    if burn is not None:
        h.append(f'<p class="mo-line">Roughly {burn:,.0f}&nbsp;&euro;/month going out, '
                 "averaged over the last three months</p>"
                 if burn > 0 else
                 '<p class="mo-line">More coming in than going out, averaged '
                 "over the last three months</p>")
    inv = s.get("investments") or []
    if inv:
        parts = " + ".join(f'{e(i["name"])} {(i.get("eur") or 0):,.0f}' for i in inv)
        asof = max((i.get("as_of") or "") for i in inv)
        h.append(f'<p class="mo-line">Invested: <b>{(s.get("investments_total_eur") or 0):,.0f}'
                 f'&nbsp;&euro;</b> &mdash; {parts}'
                 + (f' <span class="mo-across">as of {day(asof)}</span>' if asof else "")
                 + "</p>")
    bits = []
    for bank, info in sorted((s.get("banks") or {}).items()):
        fd, cd = (info.get("fetched") or "")[:10], (info.get("consent_until") or "")[:10]
        bit = f"{e(bank)}: fresh today" if fd == date.today().isoformat() \
            else f"{e(bank)}: numbers from {day(fd)}" if fd else f"{e(bank)}: nothing pulled yet"
        if cd and cd < date.today().isoformat():
            bit += " &mdash; renew to refresh"
        elif cd and (date(*map(int, cd.split("-"))) - date.today()).days <= 14:
            bit += f" &mdash; <b>re-approve by {day(cd)}</b>"
        bits.append(bit)
    if bits:
        h.append('<p class="mo-fresh">' + " &middot; ".join(bits) + "</p>")
    h.append("</section>")
    return "".join(h)


def stackrow(w, rank, cfg):
    """One row of the priority stack: rank, name, the next move, why it is
    ranked here, details behind a click so the list stays scannable.

    The next action used to live inside the fold, which meant the one line she
    could act on was the one line she had to click for, while the row face
    showed the reason twice over — once as the reason, once as the task
    fragment `why_line` tacks on. Now the move is the face and the reason is
    the small print under it; `skip_task` stops it being said twice.

    No "on you" chip here. Under a heading that says "Needs you" it is on
    every row, and a badge that never varies is width spent on nothing — the
    same argument that took the urgent flag out of the digest. "with them
    &middot; Bexley" still earns its place: that one tells you not to bother.
    """
    pct = round(decay(w, cfg) * 100)
    h = [f'<details class="row {sevclass(w)}" data-name="{e(w["name"])}"'
         f' data-flags="{" ".join(w["flags"])} {w["ball"]}">']
    tchip = (f'<span class="tcount" title="Open tasks inside &mdash; click to see them">'
             f'{w["open_tasks"]} task{"s" if w["open_tasks"] != 1 else ""} &#9662;</span>'
             if w["open_tasks"] else "")
    nxt = w["next_action"]
    why = why_line(w, skip_task=nxt or "", plain_urgent=True)
    h.append('<summary>'
             f'<span class="rank">{rank}</span>'
             '<span class="rowmain">'
             f'<span class="rowname">{e(w["name"])}</span>'
             + (f'<span class="rownext">{e(nxt)}</span>' if nxt else "")
             + (f'<span class="rowwhy">{why}</span>' if why else "")
             + "</span>"
             f'{tchip}{"" if w["ball"] == "me" else ballchip(w)}'
             f'<span class="bar"><i style="width:{pct}%"></i></span>'
             "</summary>")
    inner = []
    if w["why"]:
        inner.append(f'<p class="matters">{e(w["why"])}</p>')
    meta = []
    if w["due"]:
        meta.append("Due " + (w.get("due_label") or w["due"]))
    if w["touched"]:
        meta.append(f"Last touched {w['touched']}")
    if w["ball"] == "them" and w["since"]:
        meta.append(f"Waiting since {w['since']}")
    if meta:
        inner.append('<p class="meta">' + " &middot; ".join(e(m) for m in meta) + "</p>")
    inner.append(tasklist(w))
    if w["notes"]:
        inner.append(f'<div class="notes">{MD.render(chr(10).join(w["notes"]))}</div>')
    inner.append(prepared_fold(w["name"]))
    inner.append(actions(w))
    h.append(f'<div class="rowbody">{"".join(inner)}</div>')
    h.append("</details>")
    return "".join(h)


def fronts_block(live, cfg, plan_toks=None, seen=None, claim=None):
    """Every front of her life, each with its own short ranked list of next
    moves. This replaced the hero (2026-09-10, her call): one giant top item
    read as a monument, and on a school-prep day the monument was a
    renovation she could do nothing about. The question a morning actually
    asks is per-front — given School, given Dad, given the apps, what moves
    next? Order inside a front is the same score the whole page agrees on;
    the fronts themselves lead with their loudest member."""
    if not live:
        return ""
    fronts = {}
    for w in live:
        fronts.setdefault(w["area"], []).append(w)
    order = sorted(fronts, key=lambda a: -max(x["score"] for x in fronts[a]))
    rlab = room_labels(cfg)
    out = ['<section class="frontswrap" id="fronts">'
           '<p class="eyebrow">Front by front</p><span class="wav"></span>']
    for area in order:
        group = sorted(fronts[area], key=lambda x: -x["score"])
        out.append(f'<div class="front"><h3 class="area">{e(area)}</h3>')
        for w in group[:3]:
            # No tickbox here (24 Sep, her call: "too many different check
            # boxes"). This block is a map of her fronts; ticking happens on
            # the plan above or in the project's drawer.
            nxt = next_line(w)
            toks = plan_toks or []
            planned = bool(nxt) and in_plan(nxt, toks)
            shown = planned or bool(nxt and seen and seen(nxt))
            if shown:
                # Its first move is already on the page, so name the one
                # after it. A bare "ABOVE" in green capitals read as a stray
                # heading (her words, 25 Sep).
                nxt = next((t["text"] for t in sorted(
                    (t for t in w.get("tasks", [])
                     if not (t.get("done") or t.get("parked")
                             or t.get("dropped") or t.get("expired"))),
                    key=lambda t: -(t.get("pressure") or 0))
                    if t["text"] != nxt and not in_plan(t["text"], toks)
                    and not (seen and seen(t["text"]))), "")
            if nxt and claim:
                claim(nxt)
            # "(class)" is a marker for the tracker, not words to read.
            face_txt = re.sub(r"\s*\(class\)", "", nxt or "")
            if face_txt:
                face = '<span class="fnext">' + e(face_txt) + "</span>"
            elif shown:
                face = ('<span class="fnext fnote">'
                        + ("already in today&rsquo;s plan" if planned
                           else "already further up the page") + "</span>")
            else:
                face = '<span class="fnext fnote">nothing queued</span>'
            out.append(
                f'<div class="frow {sevclass(w)}">'
                f'<button class="tws" data-wsopen="{e(w["name"])}"'
                f' title="{e(w["name"])} &mdash; open the project">'
                + e(rlab.get(w["name"], w["name"])) + "</button>"
                + face + "</div>")
        if len(group) > 3:
            _n = len(group) - 3
            out.append(f'<p class="fmore">and {_n} more {e(area)} '
                       f'workstream{"s" if _n != 1 else ""} on the plate</p>')
        out.append("</div>")
    out.append("</section>")
    return "".join(out)


def _probablydone_tray(live):
    """Tasks whose moment has passed: a same-day errand seen days later, a
    booking verb after its date. model.py already dropped them from every
    ranking; here the page asks instead of nagging. Nothing is marked done
    without her click — done still means she said so — but one click IS her
    saying so, eight at a time."""
    rows, extra = [], 0
    for w in live:
        for t in w.get("tasks", []):
            if not t.get("expired") or t.get("done") or t.get("dropped") \
                    or t.get("parked"):
                continue
            if len(rows) >= 8:
                extra += 1
                continue
            key = t.get("key") or MD.taskkey(t["text"])
            rows.append(
                '<div class="pdrow">'
                f'<span class="pdtext">{e(t["text"])}'
                f'<i>{e(w["name"])}</i></span>'
                f'<button class="mini" data-pdact="done" data-pdkey="{key}">'
                "Done &#10003;</button>"
                f'<button class="mini" data-pdact="revive" data-pdkey="{key}">'
                "Still open</button></div>")
    if not rows:
        return ""
    allbtn = ('<button class="mini" id="pdall">All of these happened</button>'
              if len(rows) > 1 else "")
    more = f'<p class="mtmore">and {extra} more behind these</p>' if extra else ""
    return ('<section class="pdtray needs-server"><h2>Probably done?'
            + hint("The moment on these has passed, so they stopped counting "
                   "in the rankings. Done closes one for real; Still open "
                   "strips the dead date so it ranks honestly again.")
            + f'</h2>{"".join(rows)}{allbtn}{more}'
            '<span class="mshelp" id="pd-help"></span></section>')


def calmrow(w, cfg):
    """A quiet one-liner. These are fine; they must not compete for contrast
    with the stack above — that is the whole hierarchy of the page."""
    h = [f'<details class="row calm" data-name="{e(w["name"])}"'
         f' data-flags="{" ".join(w["flags"])} {w["ball"]}">']
    bits = []
    if w["next_action"]:
        bits.append(e(w["next_action"]))
    if w["open_tasks"]:
        bits.append(f"{w['open_tasks']} open")
    if w["due"]:
        bits.append("due " + (w.get("due_label") or w["due"]))
    h.append('<summary>'
             '<span class="dot"></span>'
             '<span class="rowmain">'
             f'<span class="rowname">{e(w["name"])}</span>'
             f'<span class="rowwhy">{" &middot; ".join(bits)}</span>'
             "</span>"
             f'{ballchip(w)}'
             "</summary>")
    inner = [tasklist(w)]
    if w["why"]:
        inner.append(f'<p class="matters">{e(w["why"])}</p>')
    if w["notes"]:
        inner.append(f'<div class="notes">{MD.render(chr(10).join(w["notes"]))}</div>')
    inner.append(actions(w))
    h.append(f'<div class="rowbody">{"".join(inner)}</div>')
    h.append("</details>")
    return "".join(h)


def _src_for(w, sources):
    """Which configured project folder belongs to this workstream — best token
    overlap between the workstream name and the source name, singular/plural
    tolerated ('Renovations' finds 'House renovation')."""
    def toks(s):
        return {t.lower().rstrip("s") for t in re.findall(r"[A-Za-zà-ÿ]+", s or "")
                if len(t) >= 4}
    wt = toks(w["name"])
    best, score = None, 0
    for s in sources or []:
        n = len(wt & toks(s.get("name", "")))
        if n > score:
            best, score = s, n
    return best


def wsdetail(w, sources):
    """One workstream as a whole little screen: status, the dated tasks as a
    timeline, every task tickable, the people inside it, notes, and the folder
    on disk — with the read-my-computer trigger right there."""
    n = e(w["name"])
    out = [f'<div class="wsdetail" data-for="{n}" hidden>']
    out.append(f'<p class="eyebrow">{e(w.get("area") or "Workstream")}</p>')
    out.append(f"<h2>{n}</h2>")
    reason = why_line(w)
    if reason:
        out.append(f'<p class="rowwhy wsd-why">{reason}</p>')
    meta = []
    if w["due"]:
        meta.append("Due " + (w.get("due_label") or w["due"]))
    if w["touched"]:
        meta.append(f"Last touched {w['touched']}")
    if w["ball"] == "them" and w["since"]:
        meta.append(f"Waiting since {w['since']}")
    if meta:
        out.append('<p class="meta">' + " &middot; ".join(e(m) for m in meta) + "</p>")
    if w["why"]:
        out.append(f'<p class="matters">{e(w["why"])}</p>')
    dated = sorted((t for t in w["tasks"]
                    if not t["done"] and not t.get("dropped")
                    and t.get("due_days") is not None),
                   key=lambda t: t["due_days"])
    if dated:
        out.append('<h3 class="wsd-h">Coming up</h3><ul class="wsd-when">')
        for t in dated[:8]:
            dd = t["due_days"]
            lab = ("today" if dd == 0 else
                   f"{abs(dd)}d overdue" if dd < 0 else f"in {dd}d")
            out.append(f'<li><span class="wsd-date{" bad" if dd < 0 else ""}">{lab}</span>'
                       f"{linknames(e(t['text']))}</li>")
        out.append("</ul>")
    hay = " ".join([w["name"], w.get("next_action") or "", w.get("why") or "",
                    w.get("ball_who") or "",
                    " ".join(t["text"] for t in w["tasks"])] + w["notes"])
    found = list(w.get("linked_people", []))          # hand-made links first
    found += [nm for nm in PERSON_NAMES if nm not in found and M.name_in(nm, hay)]
    out.append('<h3 class="wsd-h">People in this</h3><p class="wsd-people">'
               + " ".join(f'<a class="plink" href="#people" data-plink="{e(nm)}">{e(nm)}</a>'
                          for nm in found[:10])
               + f' <button class="mini wsaddp needs-server" data-wsaddp="{n}">'
               "+ link a person</button></p>")
    prep = prepared_fold(w["name"])
    if prep:
        out.append('<h3 class="wsd-h">Claude prepared</h3>' + prep)
    _rsl = _ws_room_slug(n)
    if _rsl:
        out.append(f'<p class="meta"><a href="rooms.html#room/{_rsl}">'
                   'Open its room &rarr;</a></p>')
    out.append('<h3 class="wsd-h">Tasks</h3>'
               + (tasklist(w) or '<p class="meta">None open.</p>'))
    if w["notes"]:
        out.append('<h3 class="wsd-h">Notes</h3><div class="notes">'
                   + MD.render(chr(10).join(w["notes"])) + "</div>")
    src = _src_for(w, sources)
    out.append('<h3 class="wsd-h">On your computer</h3>')
    if src:
        out.append('<p class="meta">Syncs from '
                   f'<button class="flink needs-server" data-reveal="{e(src.get("path", ""))}"'
                   f' title="Open the folder">{e(src.get("path", ""))} &#8599;</button></p>'
                   f'<button class="mini wssearch needs-server" data-wssearch="{n}"'
                   f' data-wspath="{e(src.get("path", ""))}">Read the folder &amp; update this</button> '
                   f'<button class="mini wsrun needs-server" data-wsrun="{n}"'
                   f' data-wspath="{e(src.get("path", ""))}" title="One Claude Code run '
                   'inside that repo, steered by its own CLAUDE.md — watched from the bar here">'
                   "Quick run in this repo&hellip;</button>")
    else:
        out.append('<p class="meta">No folder linked yet.</p>'
                   f'<button class="mini wssearch needs-server" data-wssearch="{n}">'
                   "Search my computer for this</button>")
    out.append(actions(w))
    out.append("</div>")
    return "".join(out)


def _nightline(cfg):
    """The night-shift row under the budget control.

    It says the one thing that decides whether to bother: heavy jobs run while
    you sleep so they are not competing with your day for the same allowance.
    When it has never been set up, the row explains the one-time command rather
    than offering a switch that would silently do nothing.
    """
    n = cfg.get("night") or {}
    at = n.get("at") or "01:00"
    jobs = ", ".join("/" + j for j in (n.get("jobs") or ["queue"]))
    on = bool(n.get("enabled"))
    return ('<p class="aimodesub nightline"><b>Night shift</b>: '
            + ('runs ' + jobs + ' at ' + at + ', while you are asleep, '
               'so it is not competing with your day for the same '
               'five-hour allowance.' if on
               else 'off. It would run ' + jobs + ' at ' + at + ' so the heavy '
                    'work is done before you wake.')
            + ' <button class="mini needs-server" id="nighttoggle" '
              'data-on="' + ('1' if on else '0') + '">'
            + ('Turn off' if on else 'Turn on') + '</button></p>')


def build():
    cfg = M.load_config()
    ws = M.load(cfg=cfg)
    b = M.briefing(ws, cfg)
    q = queue_items()
    pending = [x for x in q if x["status"] in ("pending", "working")]
    today = date.today()

    urgent = [w for w in b["live"] if w["flags"]]
    calm = [w for w in b["live"] if not w["flags"]]
    closed = b["closed"]

    people = M.load_people(today=today)
    warm = [pp for pp in people if pp["flags"]]
    rest = [pp for pp in people if not pp["flags"]]
    # Task text can now point at people: longest names first so "Emery Chang"
    # wins over "Emery". Skip very short names — too many false hits.
    global PERSON_NAMES, PERSON_ALIAS
    # The names she actually writes. "Call Mum" should reach Maman, whose
    # entry lists Mum as an alias — matching only the filed name meant the
    # word she uses every day linked to nothing.
    PERSON_ALIAS = {}
    for pp in people:
        for al in pp.get("also", []):
            if len(al) >= 3 and al.lower() != pp["name"].lower():
                PERSON_ALIAS.setdefault(al, pp["name"])
    PERSON_NAMES = sorted((pp["name"] for pp in people if len(pp["name"]) >= 3),
                          key=len, reverse=True)
    global WS_NAMES
    WS_NAMES = sorted((w2["name"] for w2 in b["live"] if len(w2["name"]) >= 4),
                      key=len, reverse=True)

    # What Claude prepared, attached to the thing it belongs to. A finished
    # queue outcome names its workstream explicitly ('in the workstream "X"')
    # and also mentions the people and words of the work — match both ways,
    # so the train options surface on the Ellis hero, not only in the
    # Claude tab's archive.
    global WS_OUTCOMES
    WS_OUTCOMES = {}
    _cut = (today - __import__("datetime").timedelta(days=7)).isoformat()
    for _it in q:
        if _it["status"] != "done" or not _it["outcome"]:
            continue
        if (_it["created"] or "")[:10] < _cut:
            continue
        blob = ((_it["title"] or "") + " " + (_it["body"] or "")
                + " " + (_it["outcome"] or "")[:2000])
        explicit = set()
        for m_ in re.finditer(r'workstream\s+[“"]([^”"]+)[”"]', blob):
            explicit.add(m_.group(1).strip().lower())
        btoks = _sig_tokens(blob)
        tokhits = []
        for w2 in b["live"]:
            if w2["name"].lower() in explicit:
                continue
            shared = _sig_tokens(w2["name"]) & btoks
            if len(shared) >= 2 or any(len(x) >= 6 for x in shared):
                tokhits.append(w2["name"].lower())
        # Explicit mentions ALWAYS attach; token guesses fill what's left.
        # (A set sliced unsorted here once dropped the hero at random.)
        for h_ in (sorted(explicit) + sorted(tokhits))[:4]:
            WS_OUTCOMES.setdefault(h_, []).append(_it)
    for _v in WS_OUTCOMES.values():
        _v.sort(key=lambda x: x["created"], reverse=True)
    # And the reverse: which open tasks mention each person, so their row can
    # answer "what's happening that involves them" without a hunt.
    mention_map = {}
    for w2 in ws:
        if not w2["live"]:
            continue
        for t2 in w2["tasks"]:
            if t2["done"] or t2.get("parked") or t2.get("dropped"):
                continue
            for nm in PERSON_NAMES:
                if re.search(r"\b" + re.escape(nm) + r"\b", t2["text"]):
                    mention_map.setdefault(nm, []).append((w2["name"], t2["text"]))
                    break                      # longest name wins; one credit per task
    for pp in people:
        pp["mentions"] = mention_map.get(pp["name"], [])[:5]

    # Four views, one file. Tabs are the architecture now: Today is the
    # morning ritual, Plate is the work ledger, People is the relationships
    # ledger, Claude is the delegation console.
    # "todayrail" is Today's right column in the 2026 redesign: everything
    # that is awareness rather than action — habits, forecast, questions,
    # the digest, interests. The wide left column stays the work itself, so
    # the hero never competes with status for attention.
    V = {"today": [], "todayrail": [], "school": [], "plate": [], "people": [],
         "peoplerail": [], "claude": [], "clauderail": [], "season": [],
         "news": []}

    # ================= TODAY =================
    today_md = read("today.md")
    # Today's plan, tokenised once. Every block below that could restate a
    # task the plan already carries checks itself against this. The hero is
    # the one exception: it is allowed to be the plan's task, because being
    # the most pressed thing is its entire job — so it publishes what it took
    # and the others avoid THAT too.
    PLAN_TOKS = plan_tokens(today_md)

    # ONE OWNER PER FACT. Every block below that can name a task registers what
    # it printed, and checks the register before printing. Filtering each block
    # against the plan alone was not enough: two blocks that both avoided the
    # plan could still land on each other, which is how the same recording
    # upload reached the horizons, the quick wins and the digest at once.
    #
    # Order of claim is the order of the page, so the block a reader meets
    # first keeps the sentence and the ones below it move on to something else.
    SHOWN = list(PLAN_TOKS)

    def shown_already(text):
        return bool(text) and any(_same_thing(text, s) for s in SHOWN)

    def claim(text):
        toks = _sig_tokens(text)
        if toks:
            SHOWN.append(toks)
        return text

    # Where the "Today, so far" card landed in the rail, if it rendered —
    # the fronts radar splices itself into that card instead of standing
    # beside it as a near-twin (her ask, 31 Aug: "can these be combined?").
    daycard_ix = None

    # The hero is gone (2026-09-10, her call): one giant "next hour" block
    # read as a monument and demotivated. The plan leads the page now, and
    # fronts_block below it shows every area of her life with its own short
    # ranked list. hero() stays defined above in case a skin wants it back.
    # The greeting headline (skin furniture, hidden unless a skin shows it):
    # the day and what's left of the plan, said like a person would.
    V["today"].append('<h2 class="skinx skinx-greet">'
                      + e(_greeting(today_md)) + "</h2>")
    if not b["live"]:
        # A fresh brain teaches the first thing to do rather than showing a
        # blank hero. This is what a friend sees on their own new install.
        cues = [
            ("Start with you", "where you are in life, where you live, what you're studying or building"),
            ("What fills your days", "the projects, work or study taking your time"),
            ("The people", "family, close friends, the ones far away you don't want to drift from"),
            ("What's weighing on you", "a deadline, something you're dreading, a decision you keep putting off"),
            ("Loose threads", "what you owe someone, who owes you, a reply you've been meaning to send"),
            ("What you're building in yourself", "habits or routines, and honestly how often"),
            ("Anything else", "small nagging things, or something that doesn't fit a box but matters"),
        ]
        cuelist = "".join(f'<li><b>{c}</b> &mdash; {d}</li>' for c, d in cues)
        V["today"].append(
            '<section class="hero sev-none">'
            + heroline('<p class="eyebrow">Welcome</p>',
                       '<video class="artvid cardart" autoplay muted loop playsinline poster="art/waving.png?v=2" width="72" height="72" aria-hidden="true"><source src="art/waving.mp4?v=2" type="video/mp4"></video>')
            + "<h1>Let's fill your brain</h1>"
            '<p class="hero-why hero-calmnote">Just talk &mdash; who you are, what\'s '
            "going on, what's on your mind, in whatever order it arrives. These are "
            "only nudges "
            "if you get stuck; wander off them freely. Claude sorts all of it and "
            "checks with you before writing anything down.</p>"
            f'<ol class="onboard-cues">{cuelist}</ol>'
            '<button class="dumpstart needs-server" id="startdump">'
            "Start talking</button>"
            '<p class="meta" style="margin-top:12px">Prefer the terminal? Open Claude '
            "Code here and run <code>/onboard</code>.</p></section>")

    # ORDER OF THE PAGE (her ask: clear, uncluttered, action-first):
    # hero → the plan (act) → questions (answer) → offers → forecast → digest.
    # Status never sits above action.

    # The assistant offers before being asked: upcoming dated tasks Claude can
    # get ahead of, one tap each. This is the difference between a brain that
    # presents and one that assists — the offer is visible, the boundary is
    # unchanged (research and drafts yes; booking, paying, sending never).
    # Built lazily, because it renders BELOW the plan and the horizons and so
    # must claim its tasks after them. Constructing it here but printing it
    # there would let it grab a sentence the blocks above were about to use.
    def build_offers():
        sec_offers = []
        if not b["live"]:
            return sec_offers
        soon_tasks = []
        for w2 in b["live"]:
            for t2 in w2["tasks"]:
                if (not t2["done"] and not t2.get("parked") and not t2.get("dropped")
                        and t2.get("due_days") is not None
                        and 0 <= t2["due_days"] <= 35):
                    verb = _offer_verb(t2["text"])
                    if verb:
                        soon_tasks.append((t2["due_days"], t2["text"],
                                           w2["name"], verb))

        def _prepped(txt, wn):
            return any(len(_sig_tokens(txt) & _sig_tokens(i2["title"] or "")) >= 2
                       for i2 in WS_OUTCOMES.get(wn.lower(), []))

        # Filter BEFORE the slice, never after. The three soonest-due tasks
        # are by construction the ones the plan already chose, so taking the
        # top three and then dropping the duplicates leaves an empty card on
        # exactly the days there was something to offer. Filtering first lets
        # this surface the NEXT three — which is the card's actual job.
        dupes = [s2 for s2 in soon_tasks if shown_already(s2[1])]
        soon_tasks = [s2 for s2 in soon_tasks if s2 not in dupes]
        soon_tasks.sort(key=lambda x: x[0])
        # A task already on today's list keeps its ✦ button on its own row, so
        # nothing is lost by dropping it from here — except the one thing the
        # row cannot say, which is that Claude ALREADY did the legwork. That
        # gets a line naming no task, so it restores the pointer without
        # reprinting the errand.
        n_prep = sum(1 for _, txt, wn, _ in dupes if _prepped(txt, wn))
        if not soon_tasks and n_prep:
            sec_offers.append(
                '<section class="offercard slim">'
                '<a class="offersee" href="#/claude">&#10022; Claude has already '
                f'found options for {"something" if n_prep == 1 else f"{n_prep} things"} '
                'on today&rsquo;s list &mdash; open the '
                + ("card" if n_prep == 1 else "cards") + "</a></section>")
        if soon_tasks:
            rows3 = []
            for dd, txt, wn, verb in soon_tasks[:3]:
                when = "today" if dd == 0 else f"in {dd}d"
                seen_prep = _prepped(txt, wn)     # work already landed?
                claim(txt)
                rows3.append(
                    f'<div class="offer"><span class="offerwhen">{when}</span>'
                    f'<span class="offertext">{e(txt)}'
                    + ('<a class="offersee" href="#/claude">&#10022; Claude found '
                       "options &mdash; open the card</a>"
                       if seen_prep else f'<span class="offerwould">{verb}</span>')
                    + "</span>"
                    f'<button class="mini offerbtn needs-server" data-claudestart="{e(txt)}"'
                    f' data-claudews="{e(wn)}">'
                    + ("Run it again" if seen_prep else "Start it for me")
                    + "</button></div>")
            sec_offers.append(
                '<section class="offercard"><p class="eyebrow">Claude can get ahead '
                'of these</p><span class="wav"></span>'
                + "".join(rows3)
                + '<p class="meta">It never sends anything &mdash; that stays '
                "yours.</p>"
                "</section>")
        return sec_offers

    # Open questions from the brain — the second half of any dump's interview.
    # Claude writes them to questions.md when there's nobody to ask; answering
    # one hands it back to Claude, who files the answer and ticks the box.
    qtext = read("questions.md")
    open_qs, parked_qs = [], []
    for line in qtext.split("\n"):
        mq = re.match(r"^\s*-\s+\[ \]\s+(.*)$", line)
        if not (mq and mq.group(1).strip()):
            continue
        raw = mq.group(1).strip()
        # A question you cannot answer yet is not a question you are
        # failing to answer. Parked ones wait for their date.
        mu = MD.UNTIL.search(raw)
        if mu and mu.group(1) > today.isoformat():
            parked_qs.append((raw, mu.group(1)))
        else:
            open_qs.append(raw)
    actqs = ""
    sec_questions = []

    def _qkey(raw):
        """Same stripping the server does, or the key will not match."""
        return MD.taskkey(re.sub(r"\s*\(urgent\)", "",
                                 MD.UNTIL.sub("", MD.DROPPED.sub(
                                     "", MD.CARRYING.sub("", raw))), flags=re.I))

    if open_qs or parked_qs:
        rows = []
        for raw in open_qs:
            qtxt = MD.plain(MD.UNTIL.sub("", raw))
            key = _qkey(raw)
            rows.append(
                '<li class="qrow">'
                f'<span class="qq"><span class="ttext">{e(qtxt)}</span>'
                f'<span class="qinline needs-server">'
                f'<input class="qin" data-q="{e(qtxt)}" autocomplete="off"'
                ' placeholder="Type the answer&hellip;">'
                f'<button class="mini qgo" data-qkey="{key}">file it</button>'
                f'<button class="mini qlater" data-qlater="{key}"'
                ' title="Cannot answer this yet — park it until it can be'
                ' answered">not yet&hellip;</button>'
                # Was a checkbox in front of every question (24 Sep: "too
                # many different check boxes"). Typing the answer is the
                # action; this is the rarer "already settled elsewhere".
                '<button class="mini tick qdone" aria-pressed="false"'
                f' data-src="questions.md" data-key="{key}"'
                ' title="Answered elsewhere &mdash; tick it off">already '
                'answered</button></span>'
                '<span class="qwhen needs-server" hidden>'
                f'<button class="mini" data-qdefer="{key}" data-days="7">next week</button>'
                f'<button class="mini" data-qdefer="{key}" data-days="30">in a month</button>'
                f'<button class="mini" data-qdefer="{key}" data-days="90">in three months</button>'
                f'<input type="date" class="qdate" data-qdate="{key}">'
                "</span></span></li>")
        # Parked questions are never deleted — they wait in a fold with the
        # date they come back, and can be pulled forward again.
        prows = "".join(
            f'<li class="qparked"><span>{e(MD.plain(MD.UNTIL.sub("", praw)))}</span>'
            f'<b>{e(when)}</b>'
            f'<button class="mini needs-server" data-qwake="{_qkey(praw)}">'
            "bring it back</button></li>"
            for praw, when in sorted(parked_qs, key=lambda x: x[1]))
        parked_html = (
            f'<details class="ghost qparkfold"><summary>{len(parked_qs)} parked '
            "&mdash; waiting for a date you cannot pick yet</summary>"
            f'<ul class="qparklist">{prows}</ul></details>' if parked_qs else "")
        if open_qs:
            sec_questions.append(
                '<section class="qcard"><p class="eyebrow">The brain needs '
                f'{len(open_qs)} answer{"s" if len(open_qs) != 1 else ""}</p>'
                '<p class="qlead">Each answer sharpens a task or a date. Park anything '
                "you cannot answer yet.</p>"
                f'<ul class="tasks qslist">{"".join(rows)}</ul>'
                + parked_html + "</section>")
        elif parked_qs:
            sec_questions.append(
                '<section class="qcard"><p class="eyebrow">Nothing to answer'
                "</p><p class=\"qlead\">Every open question is parked until it "
                "can actually be answered.</p>" + parked_html + "</section>")
        # The same questions ride in the activity drawer, answerable from any
        # tab — a follow-up should never require going to find it.
        if open_qs:
            actqs = ('<div class="actqs"><p class="eyebrow">The brain needs '
                     f'{len(open_qs)} answer{"s" if len(open_qs) != 1 else ""}</p>'
                     f'<ul class="tasks qslist">{"".join(rows)}</ul></div>')

    # The runbar pill says "1 waiting for Claude"; the drawer must SHOW the
    # one. A count whose item cannot be seen reads as a mystery, not a
    # status — so each pending ask gets a row: its name, a line of the ask
    # itself, and when it arrived.
    actpend = ""
    if pending:
        _mode_words = {"dump": "a dump to sort", "chat": "a shared chat",
                       "journal": "a journal entry",
                       "just-do-it": "a ramble from the page"}
        _one_day = __import__("datetime").timedelta(days=1)

        def _asked(created):
            d = (created or "")[:10]
            if d == today.isoformat():
                return "asked today"
            if d == (today - _one_day).isoformat():
                return "asked yesterday"
            return "asked " + d if d else "asked a while ago"

        def _wordcut(s, n):
            if len(s) <= n:
                return s
            cut = s[:n]
            return (cut[:cut.rfind(" ")] if " " in cut else cut) + "…"

        prows = []
        for it in pending:
            title = (it["title"] or "").strip() or "Untitled ask"
            raw = (it["body"] or "").strip()
            paras = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
            # The ramble button prefixes every ask with the same instruction
            # paragraph, so leading with it says nothing — her own words
            # start after it. The instructions stay out of the expanded
            # view too: she wrote the notes, not the wrapper.
            if len(paras) > 1 and paras[0].lower().startswith(
                    "i rambled these notes"):
                paras = paras[1:]
            full = "\n\n".join(MD.plain(p) for p in paras).strip()
            head = _wordcut(re.sub(r"\s+", " ", full).strip() or title, 110)
            more = full
            if len(more) > 1500:
                more = _wordcut(more, 1500) + "\n\n(the rest is on the Claude tab)"
            bits = [_asked(it["created"])]
            bits.append(_mode_words.get(it["mode"], "asked from the page"))
            if it["status"] == "working":
                bits.append("left mid-work by the last run")
            prows.append(
                '<li><details class="actqd"><summary>'
                f'<b>{e(head)}</b>'
                f'<span class="meta">{e(" · ".join(bits))}'
                ' <span class="actmore"></span></span></summary>'
                f'<div class="actqfull">{e(more)}</div>'
                '<p class="meta actqgo"><a href="#/claude">Open it on the '
                'Claude tab &rarr;</a></p></details></li>')
        actpend = ('<div class="actpend"><p class="eyebrow">Waiting to run</p>'
                   f'<ul class="actplist">{"".join(prows)}</ul></div>')

    # ---- Today's shape: the fixed skeleton of the day, so the plan is read
    # against real hours. Calendar events (local read, titles and times only)
    # plus the weekday's standing blocks from config "week". Silent when
    # there is nothing fixed — an empty strip would be furniture.
    V["todayrail"].append(routine_card(today))
    V["todayrail"].append(dayshape(cfg, today, today_md))
    V["todayrail"].append(countdown_card(today))
    # A reply you owe a friend is the loudest small thing there is — her ask
    # (19 Aug 2026): don't make her find it under People. Personal circles
    # only, high on the rail; the digest at the bottom skips whoever is
    # already named here.
    # Freshest first: the card exists to catch a reply BEFORE it ages, so a
    # message from 4 days ago outranks a debt from a month back (which the
    # People tab and the digest still carry).
    _owed_close = sorted((pp for pp in people
                          if pp.get("owed") and pp.get("personal")
                          and not pp.get("held")),
                         key=lambda pp: pp.get("days_since")
                         if pp.get("days_since") is not None else 999)
    _owed_shown = {pp["name"] for pp in _owed_close[:7]}
    if _owed_close:
        _orows = []
        for pp in _owed_close[:7]:
            d = pp.get("days_since")
            when = ("wrote today" if d == 0 else f"wrote {d}d ago"
                    if d is not None else "waiting on you")
            # The arrow opens Beeper on their chat rather than walking her to
            # the People tab to find the same person again. Her Reach says
            # which app that is, so the tooltip promises the right one; a
            # person she phones or emails has no chat to open, and the row
            # keeps the old jump instead of failing at her.
            reach = (pp.get("reach") or "").strip()
            chatty = reach.lower() not in ("email", "call", "phone", "in person")
            if chatty:
                where = f" on {e(reach)}" if reach else ""
                arrow = ('<span class="darrow opench" role="button" tabindex="0"'
                         f' data-openchat="{e(pp["name"])}"'
                         f' title="Opens Beeper{where} on your chat with them'
                         ' — nothing is sent"'
                         ' aria-label="Open the chat">&rarr;</span>')
            else:
                arrow = ('<span class="darrow" aria-hidden="true"'
                         f' title="You reach {e(pp["name"])} by {e(reach)}">'
                         "&rarr;</span>")
            _orows.append(f'<a class="drow owed" href="#/people">'
                          f'<span class="dname">{e(pp["name"])}</span>'
                          f'<span class="dwhy">{when}</span>'
                          f"{arrow}</a>")
        extra = len(_owed_close) - 7
        if extra > 0:
            _orows.append(f'<a class="drow" href="#/people">'
                          f'<span class="dname">&hellip;and {extra} more</span>'
                          f'<span class="dwhy">older debts, on the People tab</span>'
                          '<span class="darrow" aria-hidden="true">&rarr;</span></a>')
        V["todayrail"].append(
            '<section class="railcard"><h3 class="area">Answer them</h3>'
            + "".join(_orows) + "</section>")

    habits = M.load_habits(today=today)
    if not today_md.strip() and not habits:
        # An empty state that teaches: what this space becomes, and the one
        # action that fills it. Blank is the state that loses trust fastest.
        V["today"].append(
            '<section class="firstrun"><p class="eyebrow">Nothing here yet</p>'
            '<span class="wav"></span>'
            '<p class="coach">This is where the three things worth your day '
            'land each morning. It fills itself once the brain knows what '
            'you have on.</p>'
            '<div class="frdo"><button class="btnp needs-server" id="frdump">'
            'Empty your head into it</button>'
            '<button class="mini needs-server" data-job="today">'
            'or write today&rsquo;s plan from what it already knows</button>'
            "</div></section>")
    if today_md.strip() or habits:
        # A fresh plan edit leaves its snapshot behind; while it is recent,
        # the undo sits right where the change happened.
        _undo = ""
        _upath = os.path.join(BRAIN, ".plan-undo.json")
        try:
            if (os.path.exists(_upath)
                    and datetime.now().timestamp() - os.path.getmtime(_upath) < 7200):
                _undo = ('<button class="mini planundo needs-server" id="planundo"'
                         ' title="Reverse the last plan edit">&#8617; Undo</button>')
        except Exception:
            pass
        # Two kicks or more and the day has visibly drifted from the plan \u2014
        # offer the re-rank, never run it unasked.
        _resug = ""
        if len(re.findall(r"^\s*-\s+\d\d:\d\d kicked ", today_md or "", re.M)) >= 2:
            _resug = ('<button class="mini planresug needs-server" data-job="today"'
                      ' title="The day has drifted from this morning&rsquo;s plan '
                      '&mdash; have Claude re-rank what is left">'
                      "Resuggest the rest of today</button>")
        # The weather, above the plan, with the place named in it. She moves
        # between four houses across the year, and a forecast for the one she
        # left on Tuesday looks exactly like a forecast for the one she is in
        # — naming the place is the only thing that stops this quietly lying.
        _wline, _wfull = "", ""
        try:
            import weather as WX
            _wline = WX.words()
            _wfull = (WX.place() or {}).get("place", "")
        except Exception:
            _wline = ""
        if _wline:
            # The sub-stats the print-flavoured skins show under the weather
            # sentence. Only what the cache truly holds; nothing invented.
            _wx = ""
            try:
                _wd = (WX.fetch() or {}).get("today") or {}
                _bits = []
                if _wd.get("sunset"):
                    _bits.append("sunset " + _wd["sunset"])
                if _wd.get("wind") is not None:
                    _bits.append(f'wind {round(_wd["wind"])} km/h')
                _tm = (WX.fetch() or {}).get("tomorrow") or {}
                if _tm.get("high") is not None:
                    _bits.append(f'tomorrow {round(_tm["high"])}&deg;')
                if _bits:
                    _wx = ('<span class="skinx skinx-wx">'
                           + " &middot; ".join(_bits) + "</span>")
            except Exception:
                pass
            # The declared season of work rides on the same line as the
            # place: both are the brain's beliefs about "right now", and a
            # stale one must be visible to be corrected.
            _nowc = cfg.get("now") or {}
            _nowbit = ""
            if _nowc.get("phase"):
                _nu = M.parse_date(_nowc.get("until"))
                _nowbit = (' <span class="nowphase">&middot; '
                           + e(_nowc["phase"])
                           + (" until " + _nu.strftime("%a %d %b")
                              if _nu else "") + "</span>")
            V["today"].append(
                '<p class="wxline" title="' + e(_wfull)
                + ' &mdash; the place follows config&rsquo;s &quot;now&quot;; '
                'just tell Claude you moved">' + e(_wline) + _nowbit + _wx
                + "</p>")
        # Tasks proposed from her whitelisted mail, waiting on a yes/no. This
        # belongs on Today, not in the settings panel where the whitelist
        # lives: it is a thing asking for her attention, not a setting.
        V["today"].append(_mailtasks_tray(cfg))
        # School on Today is one thin strip: classes today and what is due in
        # three days. The tray, the tracker, the guides and each front moved
        # to the School tab, where there is room for them.
        V["today"].append(school_strip(cfg, shown_already, claim))
        V["school"].append(school_view(cfg))
        # Tasks whose moment has passed, asking to be closed — never closed
        # by the machine on its own.
        V["today"].append(_probablydone_tray(b["live"]))
        _pstamp = _plan_time()
        V["today"].append('<section id="today" class="todaywrap">'
                     + ('<span class="skinx skinx-planstamp">plan updated '
                        + _pstamp + "</span>" if _pstamp else "")
                     + '<button class="mini planrefresh needs-server" id="planrefresh"'
                     ' title="Have Claude rewrite today&rsquo;s plan from the brain as it'
                     ' stands right now \u2014 runs on your subscription">'
                     "&#8635; Refresh plan</button>" + _undo + _resug)
        if today_md.strip():
            # People and workstreams named in the plan are doors: Cody opens
            # her People row, TapGate opens its drawer.
            # The daily update (her priority, 24 Sep): the brain sees the
            # laptop and nothing else. Gone once today's update is in —
            # counted from the queue, so the phone and the page agree.
            _upd_in = date.today() in M.update_days(since_days=1)
            V["today"].append(
                '<div class="updnudge" id="updnudge" hidden'
                + (' data-done="1"' if _upd_in else '') + '><span><b>Daily '
                'update.</b> Tell the brain what happened today and what&rsquo;s '
                'next &mdash; above all what happened away from the laptop. '
                'Voice works.</span>'
                '<button class="mini" id="updgo">Tell the brain</button>'
                '<button class="mini" id="updlater">Later</button></div>')
            # The evening check — the accountability half of the loop. After
            # 17:00 (JS gates it) the plan turns into a mirror: what landed,
            # and a spoken decision for everything that didn't. Carry rolls it
            # into tomorrow deliberately; Drop retires it out loud. Nothing
            # silently vanishes, nothing silently piles up.
            #
            # The decisions are NOT a second copy of the list. They ship as
            # templates keyed by the same MD.taskkey the plan's own rows
            # already carry, and the JS grafts them onto those rows at 17:00 —
            # one list, two modes. Printing today's four tasks again directly
            # under the plan is what made the evening page read as a stutter,
            # and a done/carrying/dropped row needs nothing here at all: the
            # plan's own row says so already.
            ev_tpl, ev_done, ev_open = [], 0, 0
            for ln in today_md.split("\n"):
                mt = re.match(r"^\s*[-*]\s+\[([ xX])\]\s+(.*)$", ln)
                if not mt:
                    continue
                raw = mt.group(2)
                if MD.DROPPED.search(raw) or MD.CARRYING.search(raw) \
                        or MD.UNTIL.search(raw):
                    continue
                if mt.group(1).lower() == "x":
                    ev_done += 1
                    continue
                key = MD.taskkey(MD.bare(raw))
                ev_open += 1
                ev_tpl.append(
                    f'<template class="evtpl" data-evkey="{key}">'
                    f'<button class="mini evact" data-evact="carry" data-evkey="{key}"'
                    ' title="Still matters &mdash; roll it into tomorrow&rsquo;s plan deliberately">Carry &#8594;</button>'
                    f'<button class="mini evact" data-evact="drop" data-evkey="{key}"'
                    ' title="Turned out not to be yours &mdash; retire it, on the record">Drop</button>'
                    "</template>")
            if ev_done or ev_open:
                # Say WHERE the decision happens. "The open ones need a
                # decision" left her asking what to do with the box (31 Aug)
                # — the buttons this section grafts live on the plan's own
                # rows below, and the copy has to point there.
                if not ev_open:
                    head = "All of it landed &mdash; clean close."
                elif not ev_done:
                    head = ("The plan didn&rsquo;t happen &mdash; some days go "
                            "somewhere else, and that is worth recording, not "
                            "grading. Close each line below: <b>Carry &#8594;</b> "
                            "moves it into tomorrow, <b>Drop</b> retires it.")
                else:
                    head = (f"{ev_done} of {ev_done + ev_open} landed. Close "
                            "the rest on their lines below: <b>Carry &#8594;</b> "
                            "moves one into tomorrow, <b>Drop</b> retires it.")
                # Above the list, not below it: the count is a frame for the
                # rows it describes, and putting it under them was half of why
                # the page looked like it started the day over.
                V["today"].append(
                    '<section class="evwrap" id="evening" hidden>'
                    '<h3 class="area">How did today actually go?</h3>'
                    f'<p class="evhead">{head}</p>'
                    + "".join(ev_tpl) + "</section>")
            V["today"].append('<div class="todaydoc doc">'
                         + linkify_html(MD.render(today_md, task_source="today.md",
                                                  ws_lookup=plan_ws_lookup(ws, cfg)))
                         + "</div>")
            V["today"].append(week_strip(cfg, today, today_md))
        # Below the plan: every front of her life, short ranked lists.
        V["today"].append(fronts_block(b["live"], cfg, PLAN_TOKS,
                                       shown_already, claim))
        # The small, pressed tasks worth clearing now — quick wins pulled out
        # of the plate so they stop hiding there. Weekend-aware: office-hours
        # errands wait under a fold instead of nagging on a Saturday.
        # Anything already in today's three (or its chases) must not appear
        # again below — the TapGate demo showing up in four places at once is
        # what makes the page feel like it is repeating itself.
        qw = [_q for _q in M.quick_wins(ws, today=today)
              if not shown_already(_q["t"]["text"])]
        # Cheapest first, so the top of this card is the fastest thing on the
        # page. It was in workstream order, which meant the two-minute job
        # could be sixth and a reader with five spare minutes had to price the
        # whole list themselves. Anything unestimated sorts as the default
        # rather than as free.
        _dflt = M.capacity_cfg(cfg)["default_task_minutes"]
        qw.sort(key=lambda _q: _q["t"].get("est") or _dflt)
        for _q in qw:
            claim(_q["t"]["text"])
        if qw:
            rlab = room_labels(cfg)
            def _qw_row(q):
                return taskrow(q["t"], "workstreams.md", q["w"]["name"],
                               show_ws=True,
                               ws_label=rlab.get(q["w"]["name"], ""))
            # By area of her life, cheapest first inside each — so the
            # fastest win in every part of her life is visible, not just the
            # fastest overall (her rule, 16 Sep 2026).
            _cost = lambda q: (q["t"].get("est") or _dflt, q["t"]["text"])  # noqa: E731
            now_rows = area_groups([q for q in qw if not q["monday"]],
                                   lambda q: q["w"].get("area"), _cost,
                                   _qw_row)
            mon_rows = area_groups([q for q in qw if q["monday"]],
                                   lambda q: q["w"].get("area"), _cost,
                                   _qw_row)
            frag = [cardhead('<h3 class="area">Off your plate in minutes</h3>',
                             artvid("sweeping", 46)),
                    '<div class="qwins">']
            if now_rows:
                frag.append(now_rows)
            if mon_rows:
                frag.append(
                    '<details class="ghost"><summary>Waits for Monday '
                    '&mdash; needs offices open</summary>'
                    f'{mon_rows}</details>')
            if not now_rows and mon_rows:
                frag.insert(2, '<p class="meta">Nothing quick needs a '
                            'weekend hour &mdash; the rest waits for Monday.</p>')
            # The ✦ is the most useful control on the page and the only one
            # that is a bare glyph, so it gets named once, here, rather than
            # on every row — a label repeated forty times is furniture.
            frag.append('<p class="meta qwlegend"><b>&#10022;</b> hands a task '
                        "to Claude: options researched, numbers looked up, "
                        "anything to send drafted for you.</p>")
            frag.append("</div>")
            V["today"].append("".join(frag))
        # What the day actually held, from the marks it left: commits in the
        # project folders, ticks, Touched dates, drafts. Evening only — at
        # nine in the morning it is a card about nothing, and the plan is
        # what matters then. It reports and does not grade: the plan already
        # says what is undone, and saying it twice is nagging with a second
        # voice.
        if datetime.now().hour >= 16:
            try:
                import day as DAY
                dd = DAY.gather(today)
            except Exception:
                dd = None
            if dd and (dd["projects"] or dd["ticked"] or dd["touched"]
                       or dd["drafts"] or dd.get("answered")
                       or dd.get("files")):
                rows = []
                if dd["projects"]:
                    rows.append("<dt>Worked on</dt><dd>" + e(", ".join(
                        f'{p["project"]} ({len(p["commits"])})'
                        for p in dd["projects"][:4])) + "</dd>")
                # Files changed on disk — the half of a working day that
                # never reaches a commit. Three of her folders are not
                # repositories at all, so an afternoon on the champagne
                # dossier used to leave no trace anywhere in the brain.
                ch = [p for p in (dd.get("files") or [])
                      if p["kind"] == "changed"]
                un = [p for p in (dd.get("files") or [])
                      if p["kind"] == "uncommitted"]
                if ch:
                    rows.append("<dt>Files</dt><dd>" + e(", ".join(
                        f'{p["place"]} ({p["n"]})' for p in ch[:4]))
                        + "</dd>")
                if un:
                    rows.append("<dt>Uncommitted</dt><dd>" + e(", ".join(
                        f'{p["place"]} ({p["n"]})' for p in un[:3]))
                        + "</dd>")
                if dd["ticked"]:
                    items = "".join(
                        "<li>" + e(t["text"][:70]
                                   + ("…" if len(t["text"]) > 70 else ""))
                        + "</li>" for t in dd["ticked"][:5])
                    more = (f'<li class="dmore">+{len(dd["ticked"]) - 5} more</li>'
                            if len(dd["ticked"]) > 5 else "")
                    rows.append("<dt>Closed</dt><dd><ul class='dayl'>"
                                + items + more + "</ul></dd>")
                if dd.get("answered"):
                    n_a = dd["answered"]
                    rows.append("<dt>Answered</dt><dd>"
                                f"{n_a} open question{'s' if n_a > 1 else ''}"
                                "</dd>")
                other = [w for w in dd["touched"]
                         if not any(w == p["project"] for p in dd["projects"])]
                if other:
                    rows.append("<dt>Also moved</dt><dd>"
                                + e(", ".join(other[:5])) + "</dd>")
                if dd["drafts"]:
                    rows.append("<dt>Wrote</dt><dd>"
                                + e("; ".join(dd["drafts"][:3])) + "</dd>")
                daycard_ix = len(V["todayrail"])
                V["todayrail"].append(
                    '<section class="railcard daycard">'
                    '<h3 class="area">Today, so far</h3>'
                    '<dl class="dayd">' + "".join(rows) + "</dl>"
                    '<p class="meta">From what the day left behind &mdash; '
                    'commits, files changed, ticks, dates touched. Anything '
                    'off the keyboard, tell it.</p>'
                    "</section>")
        if habits:
            # Habits are a rail card, not the headline — the plan is the point
            # of this page. One pill per habit; the deep history lives one
            # fold away instead of occupying half the screen.
            V["todayrail"].append('<section class="railcard"><h3 class="area">Habits</h3>'
                                  '<div class="habits2">')
            for hb in habits:
                cls = ("done" if hb["done_today"]
                       else ("late" if not hb["on_track"] else ""))
                # An auto habit counts itself (a journal entry for the day is
                # the tick), so it gets a mark, not a button — nothing to
                # press, nothing to forget.
                if hb.get("auto"):
                    tickel = (
                        '<span class="h2tick auto" title="Counts itself — '
                        'an entry for the day is the tick">'
                        f'{"&#10003;" if hb["done_today"] else ""}</span>')
                else:
                    tickel = (
                        f'<button class="h2tick needs-server" data-habit="{e(hb["name"])}"'
                        f' aria-pressed="{"true" if hb["done_today"] else "false"}"'
                        f' title="{"Done today" if hb["done_today"] else "Did it today"}">'
                        f'{"&#10003;" if hb["done_today"] else ""}</button>')
                # A routine wears its steps as the reminder they are. Two
                # missed days running and it shows the FLOOR instead: the
                # short version that survives a hotel or a morning on campus.
                # Standing there at full size after a bad week is how a
                # routine turns into a thing you have already failed.
                steps = hb.get("steps") or []
                floor = hb.get("floor") or []
                l14 = hb.get("last14") or []
                # Slipping means it WAS running and stopped. A routine you
                # have never done once is not slipping, it is new — and a new
                # routine that introduces itself at its smallest has already
                # talked you down before you tried it.
                slipping = (hb.get("dates_list") and len(l14) >= 3
                            and not l14[-2] and not l14[-3]
                            and not hb["done_today"])
                stepline = ""
                if steps:
                    show = floor if (slipping and floor) else steps
                    stepline = (
                        f'<span class="h2steps{" floor" if show is floor else ""}"'
                        + (' title="The short version — just get these done">'
                           if show is floor else '>')
                        + e(" · ".join(show)) + "</span>")
                V["todayrail"].append(
                    f'<div class="habit2 {cls}">' + tickel +
                    f'<span class="h2name">{e(hb["name"])}</span>'
                    f'<span class="h2count">{hb["week_count"]}/{hb["target"]}</span>'
                    f'<button class="hmenu needs-server" data-habittarget="{e(hb["name"])}"'
                    f' data-target="{hb["target"]}" aria-label="Change the weekly target">'
                    "&#8943;</button>" + stepline + "</div>")
            V["todayrail"].append("</div>")
            hist = []
            for hb in habits:
                grid = "".join(
                    '<span class="hgrow">' + "".join(
                        '<i class="' + ("on" if c["on"] else "")
                        + (" today" if c["today"] else "")
                        + (" future" if c["future"] else "")
                        + f'" title="{c["date"]}"></i>'
                        for c in wk) + "</span>"
                    for wk in hb["grid"])
                pills = "".join(
                    f'<span class="wpill {"ok" if wk["count"] >= hb["target"] else "low"}'
                    f'{" cur" if wk["current"] else ""}"'
                    f' title="week of {wk["start"]}">{wk["count"]}</span>'
                    for wk in hb["weeks"])
                hist.append(f'<div class="hhrow"><b>{e(hb["name"])}</b>'
                            f'<div class="hgrid">{grid}</div>'
                            f'<div class="wpills">{pills}</div></div>')
            V["todayrail"].append(
                '<details class="ghost"><summary>History &mdash; the last month, '
                "and the weeks before</summary>"
                + "".join(hist)
                + '<p class="hnote">Each row is a week, Monday to Sunday, this '
                "week last; the numbers are days per week, oldest left.</p>"
                "</details></section>")
        V["today"].append("</section>")

    # The fronts: each area of her life by the last time anything in it
    # moved, longest-quiet on top. Productive procrastination starves a
    # front silently — this card is where the starving shows.
    if b["live"]:
        fronts = {}
        for w in b["live"]:
            t = M.parse_date(w.get("touched") or "")
            prev = fronts.get(w["area"])
            if t and (prev is None or t > prev):
                fronts[w["area"]] = t
            else:
                fronts.setdefault(w["area"], None)
        frows = []
        for name, t in sorted(fronts.items(),
                              key=lambda kv: kv[1] or date.min):
            days = (today - t).days if t else None
            sev = ("f-never" if days is None else
                   "f-fresh" if days <= 2 else
                   "f-ok" if days <= 7 else
                   "f-warm" if days <= 14 else "f-cold")
            lab = "never" if days is None else ago(days)
            frows.append(f'<div class="frow {sev}"><i class="fdot"></i>'
                         f'<span class="fname">{e(name)}</span>'
                         f'<span class="fago">{lab}</span></div>')
        fronts_html = (
            '<h3 class="area fr2">Where your attention went</h3>'
            + "".join(frows)
            + '<p class="hnote">Each front, by when anything in it last moved '
            "&mdash; longest quiet on top.</p>")
        if daycard_ix is not None:
            # Evening: ride inside "Today, so far" — one box about the day,
            # not two side by side saying overlapping things.
            card = V["todayrail"][daycard_ix]
            assert card.endswith("</section>")
            V["todayrail"][daycard_ix] = (card[:-len("</section>")]
                                          + fronts_html + "</section>")
        else:
            V["todayrail"].append(
                '<section class="railcard">' + fronts_html + "</section>")

    # The three horizons, directly under the plan.
    #
    # A deadline beats an ambition every single morning, so drawing the day's
    # work off one sorted stack means the ambition never gets a morning at
    # all. The pools are the fix, and they only work if she can SEE them —
    # which is also the only place "nothing is forcing this" can be said out
    # loud without it reading as nagging.
    if b["live"]:
        pools = {"now": [], "push": [], "slow": []}
        for w in b["live"]:
            if w.get("batched"):
                continue          # waits for its weekly hour, not a lane
            pools.get(w.get("horizon") or "slow", pools["slow"]).append(w)
        HZ = (("now", "A clock is on it",
               "these have dates, and the dates are doing the choosing"),
              ("push", "You chose this",
               "you set a focus or a finish line &mdash; before the week eats it"),
              ("slow", "Nothing is forcing it",
               "no date, so it can only ever reach you by going stale"))
        hrows = []
        for kind, title, note in HZ:
            pool = pools[kind]
            n = len(pool)
            # The "now" lane sorts exactly the way the hero does, so pool[0]
            # was structurally incapable of showing anything but the hero —
            # the same errand, twice, a screen apart. Skip the hero and the
            # lane finally says something the top of the page didn't. Anything
            # whose next move is already on the page goes too: a lane exists to
            # add a name, and repeating one adds nothing.
            if kind == "now":
                fresh = [w for w in pool if not shown_already(next_line(w))]
                pool = fresh or pool
            if not pool:
                # An empty pool is information: say it, don't drop the lane.
                hrows.append(
                    f'<div class="hzrow hz-{kind} hz-empty">'
                    f'<span class="hzkind">{title}</span>'
                    '<span class="hznone">'
                    + ("everything with a date on it is already above"
                       if kind == "now" and n else
                       "nothing has a date on it right now"
                       if kind == "now" else
                       "nothing chosen &mdash; pick something and it gets a slot"
                       if kind == "push" else
                       "everything you have is spoken for")
                    + "</span></div>")
                continue
            n = len(pool)
            # Within a horizon, whoever has waited longest earns the slot —
            # except in "now", where the loudest does.
            pick = (pool[0] if kind == "now" else
                    max(pool, key=lambda w: (w.get("days_untouched") or 0,
                                             w.get("goal_pull") or 0)))
            nxt = pick.get("next_action") or pick.get("pressed_task") or ""
            if not nxt:
                open_t = [t for t in pick["tasks"]
                          if not t["done"] and not t.get("parked")
                          and not t.get("dropped")]
                nxt = open_t[0]["text"] if open_t else ""
            claim(nxt)
            claim(pick["name"])
            days = pick.get("days_untouched")
            since = (f"{dayword(days)} untouched" if days else "not started")
            if kind == "now":
                d = pick.get("pressed_act_days")
                if d is not None:
                    since = (f"{dayword(abs(d))} past the moment to act" if d < 0
                             else "act today" if d == 0
                             else f"act within {dayword(d)}")
            goal = ""
            if pick.get("goal_text") and pick.get("goal_days") is not None:
                goal = (f'<span class="hzgoal">{e(clip(pick["goal_text"], 56))} '
                        f'&mdash; {dayword(pick["goal_days"])}</span>')
            more = (f'<span class="hzmore">+{n - 1} more in this lane</span>'
                    if n > 1 else "")
            # EVERY lane gets a verb, not just the slow one. Naming three
            # starving things and offering a button on one of them is a list
            # of complaints with a single exit — and the two silent lanes were
            # the ones with a clock on them.
            #
            # The verb differs because the need does. A dated thing wants
            # doing, so it gets the ✦ that hands the legwork to Claude; the
            # one she already chose wants the same; the one nothing is forcing
            # wants promoting into the week before it can be worked on at all.
            if kind == "slow":
                act = ('<button class="mini hzpush needs-server" '
                       f'data-ws="{e(pick["name"])}">Push this week &rarr;</button>')
            elif nxt:
                act = ('<button class="mini hzstart needs-server" '
                       f'data-claudestart="{e(nxt)}" data-claudews="{e(pick["name"])}"'
                       ' title="Claude does the legwork on this now: options '
                       'researched, numbers looked up, anything to send drafted. '
                       'It never sends anything.">&#10022; Start it</button>')
            else:
                act = (f'<a class="mini hzopen" href="#/plate">Open it &rarr;</a>')
            hrows.append(
                f'<div class="hzrow hz-{kind}">'
                f'<span class="hzkind">{title}</span>'
                f'<a class="hzname" href="#/plate">{e(clip(pick["name"], 40))}</a>'
                f'<span class="hzsince">{since}</span>'
                # "Next" turns a description into an instruction. The line was
                # already the next action; nothing on the row said so, so it
                # read as a subtitle and got skipped.
                + (f'<span class="hznext"><b>Next</b>{e(clip(nxt, 70))}</span>'
                   if nxt else "")
                + goal
                + f'<span class="hzact">{act}{more}</span>'
                + "</div>")
        V["today"].append(
            '<section class="hzcard">'
            + cardhead('<div><p class="eyebrow">Your three '
                       'horizons</p><span class="wav"></span></div>',
                       artvid("kite", 46))
            + "".join(hrows)
            + '</section>')

    # Offers stay beside the plan (they are work); questions and the forecast
    # move to the awareness rail — status never outranks action.
    V["today"].extend(build_offers())

    # What the ranking cannot see. The scorer's failure is silent by nature: a
    # task whose deadline lives in its words rather than its marker does not
    # rank low with a warning, it ranks as though it had no deadline. Saying
    # so — with the fix one tap away — is the difference between a ranking she
    # can trust and one she has to second-guess.
    spots = M.blind_spots(ws, cfg=cfg, today=today)
    gaps = M.prep_gaps(ws, cfg=cfg, today=today)
    if spots or gaps:
        # A filing due next February does not belong on today's page. Near
        # gaps only — the far ones keep their weight and wait their turn.
        dates = [s for s in spots
                 if s["kind"] == "prose_date" and s["weight"] >= 70][:3]
        expired = [s for s in spots if s["kind"] == "expired"][:3]
        goalless = [s for s in spots if s["kind"] == "no_goal"]
        rows = []
        # Soonest first, and a commitment happening tomorrow with nothing
        # readying her for it outranks any missing marker.
        for g in gaps[:2]:
            when = "today" if g["days"] == 0 else (
                "tomorrow" if g["days"] == 1 else f'in {g["days"]} days')
            # The prep wants doing before the thing, so it is due the day
            # before — or right now if the thing is already tomorrow.
            due = max(today, date.fromisoformat(g["when"]) - timedelta(days=1))
            # This becomes a real line in her file, so it has to read like one
            # she wrote: the event's own words, first sentence only, no
            # parenthetical address and no trailing ellipsis.
            label = re.sub(r"\s*\([^)]*\)", "", g["event"])
            label = re.split(r"(?<=[a-z0-9])\.\s", label)[0]
            label = label.replace(":", "").strip(" .,-—")
            if len(label) > 58:
                label = label[:58].rsplit(",", 1)[0].rstrip(" ,")
            rows.append(
                '<div class="bspot"><div class="bstext">'
                f'<b>{e(clip(g["event"], 88))}</b>'
                f'<span class="bswhy">happens <i>{when}</i>, and nothing on '
                'your plate gets you ready for it &mdash; it is written in a '
                'note, which the ranking never reads</span></div>'
                '<div class="bsfix"><button class="mini bsprep needs-server" '
                f'data-ws="{e(g["ws"])}" data-due="{due.isoformat()}" '
                f'data-text="Prep: {e(label)}">'
                'Add the prep</button></div></div>')
        for s in dates:
            key = MD.taskkey(s["task"])
            guess = ""
            if s.get("days") is not None:
                g = today + timedelta(days=s["days"])
                guess = g.isoformat()
            rows.append(
                '<div class="bspot"><div class="bstext">'
                f'<b>{e(clip(s["task"], 88))}</b>'
                # "carries no date" read as a flat contradiction to a line
                # that plainly says "4–7 September". The date is THERE; it is
                # in the sentence, and the sorter only ever looks at the
                # deadline field. Say which of the two is missing.
                f'<span class="bswhy">the date is in the words '
                f'(<i>{e(s.get("saw", ""))}</i>) but not in its deadline, and '
                'the deadline is the only part that sorts &mdash; so this '
                'currently queues behind things due much later</span></div>'
                f'<div class="bsfix"><input type="date" class="bsdate" value="{guess}" '
                f'aria-label="date for {e(clip(s["task"], 40))}">'
                f'<button class="mini bsgo needs-server" data-bskey="{key}">'
                'Set it</button></div></div>')
        for s in expired:
            key = MD.taskkey(s["task"])
            rows.append(
                '<div class="bspot"><div class="bstext">'
                f'<b>{e(clip(s["task"], 88))}</b>'
                '<span class="bswhy">its date has passed, so this can no longer '
                'be done &mdash; it will sit open forever unless it goes</span></div>'
                f'<div class="bsfix"><button class="mini bsdrop needs-server" '
                f'data-bskey="{key}">Retire it</button></div></div>')
        if goalless:
            names = ", ".join(e(s.get("room") or clip(s["ws"], 26))
                              for s in goalless[:4])
            more = f" and {len(goalless) - 4} more" if len(goalless) > 4 else ""
            rows.append(
                '<div class="bspot"><div class="bstext">'
                f'<b>No finish line: {names}{more}</b>'
                '<span class="bswhy">nothing is pulling these forward, so they '
                'can only reach your day by going stale first. A goal with a '
                'date gives them a claim on the quiet weeks.</span></div>'
                '<div class="bsfix"><a class="mini" href="rooms.html">'
                'Set goals</a></div></div>')
        if rows:
            V["today"].append(
                '<section class="bscard">'
                + cardhead('<div><p class="eyebrow">What the ranking '
                           'can\'t see</p><span class="wav"></span></div>',
                           artvid("sleuthing", 46))
                + "".join(rows)
                + "</section>")

    if b["live"]:
        V["todayrail"].append(forecastcard(M.forecast(
            items=ws, people=people, cfg=cfg, today=today,
            now_minutes=now_minutes(), plan_tasks=plan_estimates(today_md))))
    _money = moneycard(cfg)
    if _money:
        V["todayrail"].append(_money)
    V["todayrail"].extend(sec_questions)

    # The cross-domain digest: what is burning in the other tabs, so one
    # glance at Today covers everything. Each row is a door, not a control.
    def drow(sev, name, why, dest):
        return (f'<a class="drow {sev}" href="#/{dest}">'
                f'<span class="dname">{e(name)}</span>'
                f'<span class="dwhy">{why}</span>'
                '<span class="darrow" aria-hidden="true">&rarr;</span></a>')
    digest = []
    # The digest is the LAST thing on Today that can name a workstream, so it
    # yields to every block above it. A row here that repeats the horizons is
    # pure cost: it is a door to another tab, and a door labelled with a
    # sentence you just read tells you nothing about where it goes.
    # Scans the whole urgent stack, not the top few: if the first five are all
    # already on Today, the honest sixth is still worth a door, and stopping
    # early would leave this empty while real work sat unnamed.
    for w in urgent[1:]:
        if shown_already(w["name"]) or shown_already(next_line(w)):
            continue
        claim(w["name"])
        claim(next_line(w))
        digest.append(drow(sevclass(w), w["name"],
                           why_line(w, plain_urgent=True), "plate"))
        if len(digest) >= 3:
            break
    # RANK, then cut. This took the first four in file order, and people.md is
    # alphabetical — so with 86 people qualifying it showed Wren, Lane,
    # Amy and Hollis every single day, and the only two she actually owed a
    # reply to sat at positions 49 and 83 and were never seen. One of them was
    # Ellis, whose trip the hero at the top of the page is about.
    #
    # The severity colours below (owed is loud, quiet is grey) could not fire
    # either, because an owed person never survived the slice.
    #
    # Order: a reply you owe, then a promise you made, then a dated birthday,
    # then how far past the rhythm SHE chose — over_by, not raw silence, so a
    # weekly friend at ten days outranks a quarterly one at ninety.
    def _person_rank(pp):
        bucket = (0 if pp["owed"] else 1 if pp.get("promised")
                  else 2 if pp.get("bday_soon") else 3)
        return (bucket,
                pp.get("bday_in") or 0 if pp.get("bday_soon") else 0,
                -(pp.get("over_by") or 0),
                -(pp.get("days_since") or 0))

    shown_people = sorted(
        (pp for pp in warm
         if (pp["owed"] or pp["overdue"] or pp.get("promised")
             or pp.get("bday_soon")) and pp["name"] not in _owed_shown),
        key=_person_rank)[:4]
    for pp in shown_people:
        bits = []
        if pp["owed"]:
            # One phrase carrying both facts. It used to append "12d quiet" as
            # a second clause, which is the same fact said twice and the part
            # that got cut when the row ran out of room.
            d = pp["days_since"]
            bits.append(
                "<b>you owe them a reply</b>"
                + (" &mdash; theirs is the last word" if d is not None and d <= 1
                   else f" &mdash; {d} days now" if d else ""))
        if pp.get("promised"):
            first = pp["open_promises"][0]["text"]
            bits.append("you promised: " + e(first[:60]))
        if pp.get("bday_soon"):
            d = pp["bday_in"]
            bits.append("<b>birthday " + ("today" if d == 0 else f"in {d} days") + "</b>")
        if pp["overdue"] and not pp["owed"]:
            bits.append(ago(pp["days_since"]).replace(" ago", "") + " quiet")
        # A promise you made and have not kept is the one thing here that is
        # genuinely late; an unanswered reply warns instead.
        sev = ("sev-bad" if pp.get("promised")
               else "sev-wait" if pp["owed"]
               else "sev-soon" if pp.get("bday_soon") else "sev-cold")
        if pp["days_since"] is not None and not pp["overdue"] and not pp["owed"]:
            bits.append(ago(pp["days_since"]).replace(" ago", "") + " quiet"
                        if pp["days_since"] > 1 else "")
        bits = [x for x in bits if x]
        # An owed reply is closable right here: one tap says "answered them".
        btn = (f'<button class="mini prepl needs-server" data-replied="{e(pp["name"])}"'
               f' title="You answered them &mdash; clears the debt, stamps today">'
               "&#10003; Replied</button>" if pp["owed"] else "")
        digest.append(f'<div class="drow {sev}">'
                      f'<span class="dname">{e(pp["name"])}</span>'
                      f'<span class="dwhy">{" &middot; ".join(bits)}</span>{btn}'
                      f'<a class="darrow" href="#people" data-plink="{e(pp["name"])}"'
                      f' aria-label="Open {e(pp["name"])} on People">&rarr;</a></div>')
    if digest:
        # Undated people rows read flat — no "6 weeks quiet", no severity. The
        # honest cause is an unsorted chat pile, so say that once, not per row.
        dnote = ""
        if any(pp["never"] for pp in shown_people):
            dnote = ('<p class="dnote">Rows without a date are chats you haven&rsquo;t '
                     'sorted yet &mdash; <a href="#people">sort your chats</a> and they '
                     'get real dates, and real urgency.</p>')
        # When most of the address book is overdue, the honest reading is that
        # the rhythms are wrong, not that she is failing eighty people. Say so
        # once, out loud, and leave the fix to her — a circle is her judgement
        # and this brain does not get to reassign one. Same logic the habits
        # page uses: a target missed every week is the wrong target.
        n_over = sum(1 for pp in warm if pp["overdue"] and not pp["owed"])
        if n_over >= 25:
            dnote += (f'<p class="dnote"><b>{n_over} people</b> are past the '
                      'rhythm you set for them. At that number it is the '
                      'rhythms that need the work: a quarterly circle spends '
                      'most of the year quiet, which is what quarterly means. '
                      '<a href="#people">Review who you actually want to keep '
                      "warm</a>.</p>")
        V["todayrail"].append('<section class="digestwrap railcard">'
                              '<h3 class="area">Also needs you</h3>'
                              '<div class="digest">' + "".join(digest) + "</div>"
                              + dnote + "</section>")

    # Interests — the life beyond the to-dos. Quiet by design: no decay, no
    # counts, just each interest and its next small spark.
    try:
        intr = M.parse(read("interests.md"))
    except Exception:
        intr = []
    intr = [i for i in intr if i["fields"].get("spark") or i["fields"].get("what")]
    if intr:
        irows = []
        for i in intr:
            spark = M._plain(i["fields"].get("spark", ""))
            irows.append('<div class="intr"><b>' + e(i["name"]) + "</b>"
                         + (f'<span class="intspark">{e(spark)}</span>' if spark else "")
                         + "</div>")
        V["todayrail"].append(
            '<details class="ghost intwrap"><summary>'
            '<img class="sumart" src="art/watering.png?v=2" alt="" width="26" height="26">'
            'Interests &mdash; the life '
            f'beyond the to-dos ({len(intr)})</summary>'
            '<div class="intgrid">' + "".join(irows) + "</div>"
            '<p class="meta">Kept in interests.md &mdash; sparks, not chores. '
            "Tell Claude when one comes alive and it becomes real work; "
            "nothing here ever goes &ldquo;overdue&rdquo;.</p></details>")

    # ================= PLATE =================
    if not b["live"]:
        V["plate"].append(
            '<section class="firstrun"><p class="eyebrow">Your plate</p>'
            '<span class="wav"></span>'
            '<p class="coach">Everything you have on lives here, ranked by '
            'what is rotting fastest. Nothing is on it yet.</p>'
            '<div class="frdo"><button class="btnp needs-server" data-job="discover">'
            'Find my projects on this Mac</button>'
            '<button class="mini needs-server" id="frcapture">'
            'or just tell it what you have on</button></div></section>')
    _TILE_TIPS = {"overdue": "Past a date you set",
                  "chase": "Waiting on someone who has gone quiet",
                  "cold": "Untouched by you for a while",
                  "me": "The next move is yours",
                  "them": "The next move is someone else's"}

    def tile(n, label, kind, f):
        if not n:
            return ""                    # a zero filter is noise, not a filter
        return (f'<button class="tile t-{kind}" data-filter="{f}"'
                f' title="{_TILE_TIPS.get(f, "")}">'
                f"<b>{n}</b><span>{label}</span></button>")
    # The plate opens by saying, in words, what shape the whole pile is in \u2014
    # the design's "18 moving \u00b7 3 waiting on others \u00b7 2 past their date",
    # then one coaching sentence naming the genuinely worrying part.
    _mv = len([w for w in b["live"] if w["ball"] != "them"])
    _tr = [f"{_mv} moving"]
    if b["theirs"]:
        _tr.append(f'{len(b["theirs"])} waiting on others')
    if b["overdue"]:
        _tr.append(f'{len(b["overdue"])} past their date')
    _worry = ""
    if b["cold"]:
        _worry = (f'{len(b["cold"])} of these ' +
                  ("has" if len(b["cold"]) == 1 else "have") +
                  " not been touched in a fortnight. ")
    _worry += ("Nothing else here is in trouble." if not b["overdue"]
               else "The dated ones are the only real trouble.")
    V["plate"].append(
        '<section class="platehead"><p class="eyebrow">Your plate</p>'
        '<span class="wav"></span>'
        f'<p class="triage">{e(" · ".join(_tr))}.</p>'
        f'<p class="coach">{_worry}</p></section>')
    V["plate"].append(
        '<input class="psearch" id="tsearch" type="search" autocomplete="off" '
        'placeholder="Search every task and workstream \u2014 done ones too\u2026" '
        'aria-label="Search tasks">')
    V["plate"].append('<div class="tiles">'
                 + tile(len(b["overdue"]), "overdue", "bad", "overdue")
                 + tile(len(b["chase"]), "to chase", "wait", "chase")
                 + tile(len(b["cold"]), "going cold", "cold", "cold")
                 + tile(len(b["yours"]), "on you", "mine", "me")
                 + tile(len(b["theirs"]), "on others", "unk", "them")
                 + '<button class="tile clearf" data-filter="" hidden>'
                   "<b>&times;</b><span>show all</span></button>"
                 + "</div>")

    if urgent:
        # Grouped by front (her call, 2026-09-10): one flat global stack made
        # "rank 7" read as a scold. The rank numbers stay global, so the order
        # inside a front is the same order the whole page agrees on.
        V["plate"].append('<section id="attention"><h2>Needs you</h2>')
        _gidx = {w["name"]: i + 1 for i, w in enumerate(urgent)}
        _fr = {}
        for w in urgent:
            _fr.setdefault(w["area"], []).append(w)
        for _area in sorted(_fr, key=lambda a: min(_gidx[w["name"]]
                                                   for w in _fr[a])):
            V["plate"].append(f'<h3 class="area">{e(_area)}</h3>'
                              '<div class="stack">')
            V["plate"].extend(stackrow(w, _gidx[w["name"]], cfg)
                              for w in _fr[_area])
            V["plate"].append("</div>")
        V["plate"].append("</section>")

    if calm:
        V["plate"].append('<section id="all"><h2>Ticking over'
                     '<button class="addbutton needs-server" data-addkind="workstream">'
                     '+ New workstream</button></h2><div class="stack quiet">')
        areas = {}
        for w in calm:
            areas.setdefault(w["area"], []).append(w)
        for area in sorted(areas, key=str.lower):
            V["plate"].append(f'<h3 class="area">{e(area)}</h3>')
            V["plate"].extend(calmrow(w, cfg) for w in areas[area])
        V["plate"].append("</div></section>")

    snoozed = b.get("snoozed", [])
    if snoozed:
        # Asleep on purpose — parked with a wake date, out of every list until
        # then. One fold so the clutter is gone but nothing is hidden for real.
        V["plate"].append(f'<section id="asleep"><details class="ghost"><summary>'
                     f"Asleep &mdash; snoozed on purpose ({len(snoozed)})</summary>")
        for w in snoozed:
            when = (f'wakes {e(w["snooze"])}'
                    + (f' &middot; in {w["snooze_days"]}d'
                       if w.get("snooze_days") is not None else ""))
            V["plate"].append(
                f'<div class="asleeprow"><span class="rowname">{e(w["name"])}</span>'
                f'<span class="meta">{when}</span>'
                f'<button class="mini needs-server" data-wake="{e(w["name"])}">'
                "Wake now</button></div>")
        V["plate"].append("</details></section>")

    if closed:
        V["plate"].append(f'<section id="closed"><details class="ghost"><summary>Finished '
                     f"and dropped ({len(closed)})</summary><div class=\"stack quiet\">")
        V["plate"].extend(calmrow(w, cfg) for w in closed)
        V["plate"].append("</div></details></section>")

    for name, tid, add in (("waiting.md", "waiting",
                            '<button class="addbutton needs-server" data-addkind="waiting">'
                            "+ Add someone</button>"),
                           ("inbox.md", "inbox", "")):
        text = read(name)
        if tid == "inbox":
            # The inbox always renders. Its own drop line used to sit here and
            # was the slowest capture on the page: it is below the stack, the
            # quiet list, the sleeping fold and the finished fold, so catching
            # a passing thought meant scrolling past everything you were
            # avoiding. The + button is fixed to the corner of every tab and
            # never moves. This section is now the reading end of the inbox.
            body = (MD.render(text, task_source=name) if text.strip()
                    else '<p class="empty">Empty &mdash; exactly how an inbox '
                         "should feel. Anything you drop with the <b>+</b> "
                         "button lands here until Claude files it.</p>")
            V["plate"].append(f'<section id="{tid}" class="doc">{body}</section>')
            continue
        if text.strip():
            V["plate"].append(f'<section id="{tid}" class="doc">'
                         + MD.render(text, task_source=name) + add + "</section>")

    def _fresh(name):
        try:
            mt = os.path.getmtime(os.path.join(BRAIN, name))
            d = (datetime.now() - datetime.fromtimestamp(mt)).days
            return "today" if d == 0 else "yesterday" if d == 1 else f"{d}d ago"
        except Exception:
            return ""

    ref = []
    for name, tid, label in (("next.md", "next", "Claude's ranking, and why"),
                             ("synced.md", "synced", "What your project folders say"),
                             ("decisions.md", "decisions", "Decisions you have made")):
        text = read(name)
        if text.strip():
            fr = _fresh(name)
            ref.append(f'<details class="refblock" id="{tid}"><summary>{label}'
                       + (f'<span class="reffresh">updated {fr}</span>' if fr else "")
                       + f'</summary><div class="doc">{MD.render(text, task_source=name)}</div>'
                       "</details>")
    if ref:
        V["plate"].append('<section class="refwrap"><h2>'
                          '<img class="h2art" src="art/reading.png?v=2" alt="" width="34" height="34">Reference</h2>' + "".join(ref)
                          + "</section>")

    # ================= PEOPLE =================
    # The triage lives ON the page, not behind a button: the newest unsorted
    # chats render inline from the cache the syncs keep fresh, a few at a
    # time, so sorting is a daily nibble instead of a chore you go find.
    review = {}
    try:
        with open(os.path.join(BRAIN, ".beeper-review.json"), encoding="utf-8") as f:
            review = json.load(f)
    except Exception:
        pass
    unsorted_chats = (review.get("unmatched") or [])
    # Belt and braces: never render a chat she has hidden, even if the cache
    # predates the hide.
    try:
        with open(os.path.join(BRAIN, "people-ignored.json"), encoding="utf-8") as f:
            _ign = {x.lower() for x in json.load(f)}
        unsorted_chats = [u for u in unsorted_chats
                          if (u.get("name") or "").strip().lower() not in _ign]
    except Exception:
        pass
    # Chats whose whole name is a phone number. beeper.py stops adding them at
    # the source, but the cached queue on disk predates that, so the filter
    # runs here too and the count comes from what was ACTUALLY dropped rather
    # than from a field that could be stale. Guarded import: build.py has to
    # work on a machine where Beeper was never set up.
    try:
        from beeper import is_bare_number as _bare_number
    except Exception:
        def _bare_number(_n):
            return False
    _keep = [u for u in unsorted_chats if not _bare_number(u.get("name"))]
    n_numeric = len(unsorted_chats) - len(_keep)
    unsorted_chats = _keep

    circle_list = [c for c in M.circles(cfg).values()
                   if c["name"].lower() not in ("one-off", "oneoff")]

    _known_people = {pp["name"].lower() for pp in people}

    def _rvmembers(u):
        """A group's members, as chips: known ones marked, unknown ones one
        tap from becoming contacts."""
        mem = u.get("members") or []
        if not u.get("group") or not mem:
            return ""
        chips = []
        for m in mem[:8]:
            if m.lower() in _known_people:
                chips.append(f'<span class="rvmem known" title="Already in your '
                             f'people">{e(m)} &#10003;</span>')
            else:
                chips.append(f'<button class="rvmem" data-mem="{e(m)}" '
                             f'data-memgroup="{e(u.get("name", ""))}" '
                             f'title="Add them as a contact">{e(m)} +</button>')
        more = f'<span class="rvmem dim">+{len(mem) - 8}</span>' if len(mem) > 8 else ""
        return f'<div class="rvmembers">{"".join(chips)}{more}</div>'

    def rvrow(u):
        chips = "".join(
            f'<button class="cchip" data-circle="{e(c["name"])}"'
            f' title="{e(c["every"] or "no set rhythm")}">{e(c["name"])}</button>'
            for c in circle_list) + (
            '<button class="cchip cchipnew" data-newcircle'
            ' title="Create a new group right here">+ new</button>')
        name = e(u.get("name", ""))
        return ('<div class="rv" data-chat="' + name.replace("'", "&#39;") + '">'
                '<div class="rvtop"><span class="rvname">' + name
                + (' <span class="rvgroup">group</span>' if u.get("group") else "")
                + '</span><span class="rvmeta">'
                + e(u.get("network", "")) + f' &middot; {u.get("days", "?")}d ago</span></div>'
                + _rvmembers(u)
                + '<div class="rvacts"><span class="cchips">' + chips + '</span>'
                '<span class="rvminor">'
                '<input data-rv="link" class="rvlink" list="peopledl" '
                'placeholder="same as&hellip; type a name">'
                '<button data-rv="oneoff">one-off</button>'
                '<button data-rv="ignore">hide</button></span></div></div>')

    if people:
        V["people"].append('<datalist id="peopledl">'
                     + "".join(f'<option value="{e(pp["name"])}"></option>' for pp in people)
                     + "</datalist>")
        # Last-synced time rides ON the sync pill — "does this run itself?"
        # should never need a hunt. (It does: every morning at 7.)
        try:
            _bmt = os.path.getmtime(os.path.join(BRAIN, ".beeper-review.json"))
            _bd = datetime.now() - datetime.fromtimestamp(_bmt)
            _bago = ("just now" if _bd.total_seconds() < 3600 else
                     f"{int(_bd.total_seconds() // 3600)}h ago" if _bd.days == 0 else
                     f"{_bd.days}d ago")
        except Exception:
            _bago = ""
        _me = ""
        for _ext in (".jpg", ".png", ".webp", ".gif"):
            if os.path.exists(os.path.join(BRAIN, "avatars", "me" + _ext)):
                _me = "avatars/me" + _ext
                break
        V["people"].append('<section id="people">'
                     '<img class="artpng h2art" src="art/waiting.png?v=2" alt=""'
                     ' width="34" height="34" aria-hidden="true">'
                     '<h2>People'
                     '<button class="addbutton needs-server" data-addkind="person">'
                     "+ Add someone</button>"
                     '<a class="addbutton circleslink" href="map.html#circles"'
                     ' title="You at the centre, your people on rings, colour = who '
                     'needs you">&#9678; Circles view</a>'
                     '<button class="addbutton needs-server" id="syncppl">'
                     "Sync from Beeper"
                     + (f' <span class="csub">{e(_bago)}</span>' if _bago else "")
                     + "</button>"
                     '<details class="hmore"><summary aria-label="More">&#8943;</summary>'
                     '<div class="hmorepanel">'
                     '<button class="addbutton needs-server" id="shotbtn">'
                     "From a screenshot</button>"
                     '<button class="addbutton needs-server" id="newgroup">'
                     "+ New group</button>"
                     '<button class="addbutton needs-server" id="mephoto"'
                     ' title="Your face for the centre of the Circles view">'
                     + (f'<img class="mepill" src="{_me}?v=1" alt=""> Change photo'
                        if _me else "Your photo")
                     + "</button></div></details>"
                     '<input type="file" id="mephotofile" accept="image/*" hidden>'
                     + hint("Beeper fills in the dates each morning at 7 &mdash; chat "
                            "names and dates, never messages. Sort the chats below "
                            "into your circles.")
                     + "</h2>"
                     '<p class="sub" id="pplnote" hidden></p>')
        # A one-line orientation. Deliberately NOT "250 need you" — a number
        # that big is unactionable and the eye slides off it. The page
        # surfaces five a day; the rest wait their turn silently.
        n_un = len(unsorted_chats)
        # The headcount belongs to the big sentence below, which already says
        # it with the circles attached — repeating it here made the top of the
        # page say "343" twice in two lines. This line keeps only what the
        # sentence cannot: what there is to DO.
        tally = []
        if warm:
            tally.append(f"{min(5, len(warm))} for today")
        if n_un:
            tally.append('<a href="#sortnow" class="pcountgo">'
                         f'{n_un} chats to sort</a>')
        if tally:
            V["people"].append('<p class="pcount">' + " &middot; ".join(tally) + "</p>")
        # The design's opening line for this page: the state of the whole
        # ledger in one honest sentence, so the shelves below don't have to
        # shout it. Calm on purpose — 237 lapsed people is a fact, not an
        # emergency, and reading it as guilt is what killed the old page.
        _circ = len({p["circle"] for p in people if p.get("circle")})
        _owed = len([p for p in people if p.get("owed")])
        _lapsed = len([p for p in people if p.get("overdue") and not p.get("held")])
        _held = len([p for p in people if p.get("held")])
        _bits = []
        if _owed:
            _bits.append(f"{_owed} owe you a reply")
        if _lapsed:
            _bits.append(f"{_lapsed} are past their rhythm")
        if _held:
            _bits.append(f"{_held} are on hold")
        V["people"].append(
            f'<p class="psub">{len(people)} kept, across {_circ} circles.</p>'
            + (f'<p class="coach pledger">{e(" · ".join(_bits))}.</p>'
               if _bits else ""))
        # The Dunbar reality check: what all the rhythms ADD UP to, per day.
        # Research (Dunbar's layers) puts stable circles near 5 intimate /
        # 15 close / 50 friends / 150 meaningful names — and real capacity at
        # a handful of deliberate touches a day. This line converts her own
        # settings into that currency, so over-commitment is visible as a
        # number instead of a vague guilt.
        _load = sum(1.0 / pp["every_days"] for pp in people
                    if pp.get("every_days") and not pp.get("oneoff")
                    and not pp.get("held"))
        if _load:
            _n_rhythm = sum(1 for pp in people
                            if pp.get("every_days") and not pp.get("oneoff")
                            and not pp.get("held"))
            _msg = (f"Your rhythms ask for <b>~{_load:.1f} reach-outs a day</b> "
                    f"across {_n_rhythm} people. ")
            if _load > 6:
                _msg += ("That's more than anyone sustains &mdash; research puts "
                         "stable circles near <b>5 / 15 / 50 / 150</b> and real "
                         "capacity at a few touches a day. Loosen a big group's "
                         "rhythm (the pill on its heading) or set it to none.")
            elif _load > 3:
                _msg += ("Ambitious but possible &mdash; the 5/15/50/150 layers "
                         "suggest keeping the tight rhythms for the inner few.")
            else:
                _msg += "That's a sustainable pace &mdash; the layers agree."
            V["people"].append(
                '<div class="pintro" id="pintro" hidden>'
                '<button class="pintro-x" id="pintrox" title="Got it — hide this">'
                '&times;</button>'
                f'<p class="dunbar">{_msg}</p>')
        # What you DID, before what you owe: a ledger that only shows debts
        # becomes a page you feel bad opening, and then you stop opening it.
        recent = sorted((pp for pp in people
                         if pp["days_since"] is not None and pp["days_since"] <= 6
                         and not pp.get("oneoff")),
                        key=lambda pp: pp["days_since"])
        if recent:
            names = [pp["name"] for pp in recent[:3]]
            extra = len(recent) - len(names)
            lst = (", ".join(names) if extra > 0        # "A, B, C and 38 more"
                   else names[0] if len(names) == 1
                   else " and ".join([", ".join(names[:-1]), names[-1]]))
            V["people"].append(
                '<p class="weekline">This week you reached '
                f'<b>{len(recent)}</b> {"person" if len(recent) == 1 else "people"}'
                f' &mdash; {e(lst)}{f" and {extra} more" if extra > 0 else ""}.</p>')
        # When Beeper last brought dates in, and when it will again — the sync
        # should never be a mystery.
        try:
            bmt = os.path.getmtime(os.path.join(BRAIN, ".beeper-review.json"))
            bd = (datetime.now() - datetime.fromtimestamp(bmt))
            bago = ("just now" if bd.total_seconds() < 3600 else
                    f"{int(bd.total_seconds() // 3600)}h ago" if bd.days == 0 else
                    f"{bd.days}d ago")
            V["people"].append(
                f'<p class="beepnote">Beeper last synced {bago} &mdash; runs itself '
                "every morning at 7, or tap <b>Sync from Beeper</b> above for now. "
                "Chat names and dates only, never messages.</p>")
        except Exception:
            pass
        V["people"].append("</div>")     # closes the dismissible intro

        # The sort queue is real work but it should not bury the people you have
        # already sorted — it lives behind a toggle, open only when it is short.
        if unsorted_chats:
            V["people"].append(
                f'<details class="ghost sortwrap"{" open" if n_un <= 6 else ""}>'
                f'<summary>Sort {n_un} new contact{"s" if n_un != 1 else ""} from Beeper</summary>'
                '<div class="rvlist" id="sortstrip">'
                + "".join(rvrow(u) for u in unsorted_chats[:6])
                + "</div>"
                + (f'<button class="addbutton needs-server" id="reviewmore">'
                   f"Open the sorter &mdash; search, filters, multi-select ({n_un})</button>" if n_un > 6 else "")
                + "</details>")

        # Possible duplicate people: close spellings that survived the dump
        # (dictation invents variants). Conservative on purpose — Cody and
        # Ember are different people; Brittany and Robin are not.
        def _lev(a, b):
            if abs(len(a) - len(b)) > 2:
                return 9
            prev = list(range(len(b) + 1))
            for i, ca in enumerate(a):
                cur = [i + 1]
                for j, cb in enumerate(b):
                    cur.append(min(prev[j + 1] + 1, cur[j] + 1,
                                   prev[j] + (ca != cb)))
                prev = cur
            return prev[-1]

        # Edit distance alone flags Bellamy/Cody and Perry/Shay — real distinct
        # people one letter apart. Dictation variants of ONE name keep their
        # consonants (Brittany/Robin -> brtn); different names don't
        # (cody/bellamy -> lx/lc). So: close spelling AND same consonant skeleton.
        # Short names are too ambiguous for skeletons (Lea/Leo both -> l) —
        # under five letters only accent/case variants (Ines/Tobin) qualify.
        import unicodedata as _ud

        def _deaccent(s):
            s = _ud.normalize("NFKD", s)
            return "".join(ch for ch in s if not _ud.combining(ch))

        def _skel(s):
            out = []
            for ch in _deaccent(s):
                if ch.isalpha() and ch not in "aeiouy":
                    if not out or out[-1] != ch:
                        out.append(ch)
            return "".join(out)

        dup_pairs = []
        _names = [pp["name"] for pp in people if not pp.get("oneoff")]
        for i2 in range(len(_names)):
            for j2 in range(i2 + 1, len(_names)):
                a2, b2 = _names[i2].lower(), _names[j2].lower()
                d2 = _lev(a2, b2)
                if min(len(a2), len(b2)) < 5:
                    close = a2 != b2 and _deaccent(a2) == _deaccent(b2)
                else:
                    close = ((d2 == 1 or (d2 == 2 and min(len(a2), len(b2)) >= 7))
                             and _skel(a2) == _skel(b2))
                if close:
                    dup_pairs.append((_names[i2], _names[j2]))
        if dup_pairs:
            rows2 = []
            for a3, b3 in dup_pairs[:6]:
                key3 = e(a3) + "|" + e(b3)
                rows2.append(
                    f'<div class="duprow" data-dupkey="{key3}">'
                    f'<span class="duplbl">{e(a3)} &harr; {e(b3)}</span>'
                    f'<button class="mini dupmerge needs-server" data-dupa="{e(a3)}"'
                    f' data-dupb="{e(b3)}">Merge &rarr; {e(b3)}</button>'
                    f'<button class="mini dupmerge needs-server" data-dupa="{e(b3)}"'
                    f' data-dupb="{e(a3)}">Merge &rarr; {e(a3)}</button>'
                    f'<button class="mini dupdismiss" data-dupkey="{key3}">Not the same</button>'
                    "</div>")
            V["people"].append(
                '<div class="dupcard" id="dupcard"><p class="eyebrow">Possible '
                "duplicates</p>" + "".join(rows2) + "</div>")

        # A quick filter across every section at once: who owes whom, who has
        # drifted. Clears back to everyone.
        V["people"].append(
            '<input class="psearch" id="psearch" type="search" autocomplete="off" '
            'placeholder="Search people by name…" aria-label="Search people">'
            '<div class="pfilters" role="group" aria-label="Filter people">'
            '<button class="pfilter active" data-pfilter="">Everyone</button>'
            '<button class="pfilter" data-pfilter="owe-them">I owe them</button>'
            '<button class="pfilter" data-pfilter="owe-me">They owe me</button>'
            '<button class="pfilter" data-pfilter="quiet">Gone quiet</button>'
            '<button class="pfilter" data-pfilter="focus">Focus</button>'
            "</div>")
        # The trip-planning question ("I'm in Madrid next week — who should I
        # see?") as one control, not a taxonomy of overlapping chips.
        placecount = {}
        for pp in people:
            for v in ([pp["where"]] if pp.get("where") else []) + pp.get("tags", []):
                placecount[v] = placecount.get(v, 0) + 1
        if placecount:
            popts = "".join(
                f'<option value="{e(v)}">{e(v)} ({c2})</option>'
                for v, c2 in sorted(placecount.items(), key=lambda x: -x[1]))
            V["people"].append(
                '<div class="pfilters pwhererow" role="group" aria-label="Filter by place">'
                '<label class="pwhere">I&rsquo;m in&hellip; '
                '<select id="pplacesel"><option value="">anywhere</option>'
                + popts + "</select></label>"
                '<span class="pwherenote">pick a place and the directory shows '
                "everyone there</span></div>")

        # 1) Focus — the handful of relationships being deliberately invested
        #    in right now. Always visible, always first: this block is the
        #    definition of the star.
        focus_people = [pp for pp in people if pp["focus"] and not pp.get("oneoff")]
        if focus_people:
            V["people"].append(
                '<div class="pgroup" id="pfocus"><h3 class="area">Focus</h3>'
                '<p class="phint">They surface sooner when quiet. The &#9733; on any '
                "person adds them.</p>"
                '<div class="stack">'
                + "".join(personrow(pp, ledger=True) for pp in focus_people)
                + "</div></div>")

        # 2) Today's five — the whole daily ask, finishable on purpose. Ranked
        #    by lapse relative to each person's own rhythm, weighted by
        #    closeness (family and inner rings outrank acquaintances).
        #    A RATION, not a live query: the names lock at the first build of
        #    the day, so clearing one is progress, not a summons for the next
        #    — and clearing all five is a real finish line.
        import json as _j5
        ffocus = {pp["name"] for pp in focus_people}
        cand = [pp for pp in warm
                if not pp.get("oneoff") and pp["name"] not in ffocus]
        by_name = {pp["name"]: pp for pp in people}
        five_fp = os.path.join(BRAIN, ".today-five.json")
        five_names = None
        try:
            with open(five_fp, encoding="utf-8") as f5:
                st5 = _j5.load(f5)
            if st5.get("date") == today.isoformat():
                five_names = [n for n in st5.get("names", []) if n in by_name]
        except Exception:
            pass
        if five_names is None:
            five_names = [pp["name"] for pp in cand[:5]]
            try:
                with open(five_fp, "w", encoding="utf-8") as f5:
                    _j5.dump({"date": today.isoformat(), "names": five_names}, f5)
            except OSError:
                pass
        five = [by_name[n] for n in five_names]
        open_five = [pp for pp in five if pp["flags"]]
        done_five = [pp for pp in five if not pp["flags"]]
        waiting = len([pp for pp in cand if pp["name"] not in set(five_names)])

        def _reachedrow(pp):
            return ('<div class="row pdone">' + _avatar(pp["name"])
                    + f'<span class="rowname">{e(pp["name"])}</span>'
                    '<span class="pdonewhy">&#10003; reached today</span></div>')

        if five and not open_five:
            # The finish line: all five closed. Celebrate and fold — done
            # should FEEL done, or the page never gives anything back.
            names5 = ", ".join(pp["name"] for pp in five)
            V["people"].append(
                '<div class="pgroup" id="pneeds"><h3 class="area">Today&rsquo;s five</h3>'
                '<div class="fivedone">'
                '<video class="artvid" autoplay muted loop playsinline'
                ' poster="art/celebrating.png?v=2" width="110" height="110"'
                ' aria-hidden="true"><source src="art/celebrating.mp4?v=2"'
                ' type="video/mp4"></video>'
                '<p class="fivedone-h">That&rsquo;s the five &#10003;</p>'
                f'<p class="meta">{e(names5)} &mdash; all reached. This page is '
                "done for today; tomorrow brings the next five.</p>"
                "</div></div>")
        elif five:
            V["people"].append(
                '<div class="pgroup" id="pneeds"><h3 class="area">Today&rsquo;s five'
                + (f' <span class="csub">{len(done_five)} of {len(five)} done</span>'
                   if done_five else "")
                + "</h3>"
                '<p class="phint">Reach these and the page is done for the day. '
                "Longest past their own rhythm first, closest circles weighted "
                "heaviest.</p>"
                '<div class="stack">'
                + "".join(_reachedrow(pp) for pp in done_five)
                + "".join(personrow(pp, ledger=True) for pp in open_five)
                + "</div>"
                + (f'<p class="pwait">{waiting} more wait their turn &mdash; '
                   "tomorrow brings the next five. They&rsquo;re all in the "
                   "directory below, without the red.</p>" if waiting > 0 else "")
                + "</div>")
        else:
            V["people"].append('<div class="pgroup" id="pneeds">'
                         '<h3 class="area">Today&rsquo;s five</h3>'
                         '<p class="empty art"><img src="art/sleeping.png?v=2" alt="" width="64" height="64"> '
                         "Nobody is owed a reply and nobody has "
                         "gone quiet past the rhythm you set.</p></div>")

        # 2c) Up next — the dated people-moments, on a 30-day horizon. Today's
        #     five answers "who do I reach today"; this answers "what is
        #     coming that I cannot do late". A birthday can only be wished on
        #     the day, so seeing it three weeks out is the whole point.
        #     Silent when there is nothing dated: an empty block on a page
        #     with 400 people is clutter, not a prompt.
        upnext = []
        for pp in people:
            if pp.get("oneoff"):
                continue
            bi = pp.get("bday_in")
            if bi is not None and bi <= 30:
                upnext.append((bi, pp["name"], "sev-soon",
                               "birthday " + ("today" if bi == 0 else
                                              "tomorrow" if bi == 1 else
                                              f"in {bi} days")))
            if pp.get("held") and pp.get("hold"):
                try:
                    hd = (date.fromisoformat(pp["hold"]) - today).days
                except ValueError:
                    hd = None
                if hd is not None and hd <= 30:
                    upnext.append((hd, pp["name"], "sev-cold",
                                   "together until then &middot; the rhythm "
                                   "restarts " + ("tomorrow" if hd <= 1
                                                  else f"in {hd} days")))
        if upnext:
            upnext.sort(key=lambda x: (x[0], x[1].lower()))
            shown_up, rest_up = upnext[:8], upnext[8:]
            V["people"].append(
                '<div class="pgroup" id="pnext"><h3 class="area">Up next</h3>'
                '<p class="phint">Dated in the next 30 days.</p>'
                '<div class="digest">'
                + "".join(
                    f'<div class="drow {sev}"><span class="dname">{e(nm)}</span>'
                    f'<span class="dwhy">{why}</span>'
                    f'<a class="darrow" href="#people" data-plink="{e(nm)}"'
                    f' aria-label="Open {e(nm)} on People">&rarr;</a></div>'
                    for _d, nm, sev, why in shown_up)
                + "</div>"
                + (f'<p class="pwait">{len(rest_up)} more further out.</p>'
                   if rest_up else "")
                + "</div>")

        # 2b) The sort queue, up here where it can be seen. It used to live
        #     collapsed at the bottom behind "Sort 358 new contacts", which is
        #     a chore you have to go and find — and 358 is a number you bounce
        #     off rather than start. This is the opposite end: the handful
        #     that messaged you most recently, by name, one click from the
        #     sorter. On a wide screen it is a sticky rail beside the page.
        if unsorted_chats:
            # People first, groups after — and only people get listed.
            #
            # A group of two hundred MBAT volunteers is not a relationship to
            # keep warm (people.md counts a group only as itself, never spread
            # across its members), so leading with groups buries the actual
            # names. It also has to be said plainly that nothing here is NEW:
            # the cache carries last-activity and no first-seen date, and
            # anyone she has spoken to lately is already sorted — so what is
            # left is a tail, and calling it "new" would be a promise the list
            # cannot keep.
            solo = [u for u in unsorted_chats if not u.get("group")]
            n_grp = n_un - len(solo)
            fresh = sorted(solo, key=lambda u: (u.get("days") or 9999))[:7]
            srows = []
            for u in fresh:
                d = u.get("days")
                net = u.get("network") or ""
                bits = [ago(d) if d is not None else "no date"]
                if net:
                    bits.append(net)
                nm = u.get("name") or "?"
                # The row DOES the thing. A list of names over a button that
                # sends you somewhere else to act is a signpost, not a tool —
                # which is exactly what she said about the first version.
                opts = "".join(
                    f'<option value="{e(c["name"])}">{e(c["name"])}</option>'
                    for c in circle_list)
                srows.append(
                    '<li class="snrow">'
                    '<span class="snwho">'
                    f'<span class="snname">{e(clip(nm, 28))}</span>'
                    '<span class="snmeta">'
                    + " &middot; ".join(e(x) for x in bits)
                    + '</span></span>'
                    '<span class="snacts needs-server">'
                    f'<select class="sncircle" data-snchat="{e(nm)}"'
                    f' aria-label="Which circle for {e(nm)}">'
                    '<option value="">circle&hellip;</option>'
                    + opts +
                    "</select>"
                    f'<input class="snlink" data-snlink="{e(nm)}" list="peopledl"'
                    ' placeholder="same as&hellip;"'
                    f' aria-label="Merge {e(nm)} into someone already in your people">'
                    f'<button class="snhide" data-snhide="{e(nm)}"'
                    ' title="Stop offering this chat. Nothing is deleted.">'
                    "hide</button>"
                    "</span></li>")
            note = []
            if solo:
                note.append(f'<b>{len(solo)} people</b>')
            if n_grp:
                note.append(f"{n_grp} group chats")
            V["peoplerail"].append(
                '<aside class="railcard" id="sortnow">'
                + cardhead('<h3 class="area">Waiting to be sorted</h3>',
                           artimg("waiting", 46))
                + '<p class="railnote">'
                + " and ".join(note)
                + " Beeper knows about that are not in a circle yet. "
                + ("Put these in one right here &mdash; the circle carries its "
                   "own rhythm, so that is the whole decision."
                   if solo else "All of them are group chats.")
                + "</p>"
                + (f'<ul class="snlist">{"".join(srows)}</ul>' if srows else "")
                + '<button class="addbutton needs-server" id="sortnowgo">'
                + (f"The other {len(solo) - len(fresh)} and the groups"
                   if len(solo) > len(fresh)
                   else f"Open the full sorter ({n_un})")
                + "</button>"
                # Filtered, not vanished. A count she can see is the
                # difference between a queue that got shorter and a queue
                # that is lying to her.
                + (('<p class="snfoot">'
                    + ("Groups sort in there too. " if n_grp and solo else "")
                    + (f"{n_numeric} bare phone numbers are left out "
                       "&mdash; nothing in them says who it is."
                       if n_numeric else "")
                    + "</p>") if (n_grp and solo) or n_numeric else "")
                + "</aside>")

        # 3) The directory: EVERYONE, once, in circle folds — a neutral address
        #    book for finding people, not a second debt list. The circles
        #    appear exactly here and nowhere else; the shouting stays above.
        # The shelves' own header: what the ordering means, and the one
        # filter that matters on a page this size — show me only who is
        # slipping. (The old Directory heading became this.)
        V["people"].append(
            '<div class="shelvesbar" id="shelvesbar">'
            '<p class="eyebrow">The shelves</p>'
            '<span class="shelvesnote">ordered by how far through each '
            "person&rsquo;s own rhythm you are &mdash; steadiest first</span>"
            '<span class="shelvestoggle">'
            '<button class="pill on" data-shfilter="all">All circles</button>'
            '<button class="pill" data-shfilter="slip">Only slipping</button>'
            '<button class="pill" id="shopen" data-open="1"'
            ' title="Whether circles start open. Remembered on this device.">'
            "Collapse all</button>"
            "</span></div>")
        order = [c["name"] for c in M.circles(cfg).values()]
        oneoff = [pp for pp in people if pp.get("oneoff")]
        sorted_rest = [pp for pp in people if not pp.get("oneoff")]
        groups = {}
        for pp in sorted_rest:
            key = next((cn for cn in order if cn.lower() == pp["circle"].lower()),
                       pp["circle"])
            groups.setdefault(key, []).append(pp)
        seq = [cn for cn in order if cn.lower() not in ("one-off", "oneoff")]
        seq += [cn for cn in groups if cn not in seq]     # any custom circle
        for cn in seq:
            grp = groups.get(cn)
            if not grp:
                continue
            grp.sort(key=lambda p: (-(p["days_since"] or 0), p["name"].lower()))
            # The group's rhythm, visible and clickable right on the heading —
            # "how often do I want to reach these people" is a live dial, not
            # a decision buried at group creation.
            cev = M.circle_meta(cn).get("every") or ""
            faces = shelf(grp)
            # A circle is normally its shelf of faces, with the rows a click
            # away. But `shelf()` draws nothing under three people — so a
            # group of one rendered a shelf that wasn't there over rows that
            # CSS was hiding, and opening it showed an empty box. Too small
            # for a shelf means the rows ARE the group.
            V["people"].append(
                f'<details class="csection pgroup{"" if faces else " aslist"}"'
                f' data-circle="{e(cn)}">'
                f'<summary class="area circlehead">{e(cn)} '
                f'<span class="csub">{len(grp)}</span>'
                f'<button class="crhythm needs-server" data-crhythm="{e(cn)}"'
                f' data-every="{e(cev)}" title="The default rhythm for everyone here '
                f'&mdash; click to change it">{e(cev or "no rhythm")}</button>'
                f'<button class="crename needs-server" data-crename="{e(cn)}"'
                ' title="Rename this group &mdash; everyone in it moves with it">'
                'rename</button></summary>'
                + faces
                + '<div class="stack">' + "".join(personrow(pp) for pp in grp) + "</div></details>")
        if oneoff:
            oneoff.sort(key=lambda p: (-(p["days_since"] or 0), p["name"].lower()))
            V["people"].append(
                f'<details class="ghost"><summary>One-off &amp; archived '
                f"({len(oneoff)})</summary><div class=\"stack quiet\">"
                + "".join(personrow(pp) for pp in oneoff) + "</div></details>")
        V["people"].append("</section>")

    # ================= CLAUDE =================
    ai = "careful" if cfg.get("ai") in ("low", "careful", "pro") else "full"
    drafts = M.load_drafts(today=today)
    email_default = (cfg.get("email") or {}).get("default", "")
    if drafts:
        V["clauderail"].append('<section id="drafts"><h2>'
                     '<img class="h2art" src="art/envelope.png?v=2" alt="" width="34" height="34">Ready for you'
                     + hint("Things Claude wrote for you to send or submit. You "
                            "always press the button yourself &mdash; Claude drafts, "
                            "you act. People in your Inner or Close circle are "
                            "draft-only: no send button appears for them, ever.")
                     + "</h2><div class=\"draftlist\">")
        email_ready = bool(email_default)
        # Two stakes, told apart: messages that leave the house on her click,
        # and prepared notes/forms that never send anything. Only worth the
        # subheads when both kinds are present.
        fresh = [d for d in drafts if not d.get("stale")]
        sends = [d for d in fresh if d.get("kind") in ("email", "message")]
        prep = [d for d in fresh if d.get("kind") not in ("email", "message")]
        if sends and prep:
            V["clauderail"].append('<p class="draftsub">To send &mdash; your '
                                   'call, one by one</p>')
            for d in sends:
                V["clauderail"].append(draftcard(d, email_ready, email_default))
            V["clauderail"].append('<p class="draftsub">Notes &amp; forms '
                                   '&mdash; nothing here sends</p>')
            for d in prep:
                V["clauderail"].append(draftcard(d, email_ready, email_default))
        else:
            for d in fresh:
                V["clauderail"].append(draftcard(d, email_ready, email_default))
        oldies = [d for d in drafts if d.get("stale")]
        if oldies:
            n = len(oldies)
            V["clauderail"].append(
                '<details class="oldrafts"><summary>'
                + f'{n} older draft{"s" if n != 1 else ""} &mdash; probably '
                'overtaken. Discard what you no longer need.</summary>')
            for d in oldies:
                V["clauderail"].append(draftcard(d, email_ready, email_default))
            V["clauderail"].append("</details>")
        if not email_ready and any(d["kind"] == "email" for d in drafts):
            V["clauderail"].append(
                '<div class="connectmail needs-server"><b>Send email straight from here?</b>'
                ' Connect Gmail or Yahoo with an app password (kept in your Keychain).'
                ' <button class="mini" id="mailsetup-open">Connect an account</button>'
                '<form id="mailsetup" class="mailsetup" hidden>'
                '<input id="ms-addr" placeholder="you@gmail.com" autocomplete="off">'
                '<select id="ms-prov"><option value="gmail">Gmail</option>'
                '<option value="yahoo">Yahoo</option><option value="icloud">iCloud</option>'
                '<option value="outlook">Outlook (sending only)</option></select>'
                '<input id="ms-pw" type="password" placeholder="app password" autocomplete="off">'
                '<button type="submit" class="primary">Connect</button>'
                '<span class="mshelp" id="ms-help"></span></form></div>')
        V["clauderail"].append("</div></section>")

    # The voice guide sits under the drafts on purpose: it is the setting that
    # explains what every card above it sounds like.
    V["clauderail"].append(writingcard())

    V["claude"].append('<section id="queue"><h2>Talk to Claude'
                 + hint("Answers, updates, requests, whole brain-dumps. Queued "
                        "locally until you press <i>Work the queue</i> or run "
                        "<code>/queue</code>.")
                 + '<span class="aimode" role="group" aria-label="AI budget">'
                 f'<button class="aopt{" on" if ai == "careful" else ""}" data-ai="careful"'
                 ' title="Fits a Pro plan: cheapest model unless you pick one">Careful</button>'
                 f'<button class="aopt{" on" if ai == "full" else ""}" data-ai="full"'
                 ' title="Fits a Max plan: balanced model by default">Full</button>'
                 "</span></h2>"
                 '<p class="aimodesub"><b>Careful</b>: nothing runs or spends unasked. '
                 "<b>Full</b>: the morning plan writes itself, and openers get prepared "
                 "&mdash; on your subscription either way. "
                 '<a href="usage.html">Each piece has its own switch on the '
                 "Usage page&nbsp;&rarr;</a></p>"
                 + _nightline(cfg))
    # The four verbs ARE the page: a blank box asking you to invent a request
    # is harder to face than buttons that already know what you want.
    # And each button answers the question every button row invites — "am I
    # supposed to press this every day?" — with when it last ran and whether
    # it ran itself. From the ledger, not the run history: the history only
    # keeps the last 20 page runs, and the 7am/night runs never land there.
    def _job_runs():
        last = {}
        try:
            for r in USAGE.load(days=365):
                if not r.get("ok") or r.get("kind") not in ("run", "morning",
                                                           "night"):
                    continue
                lbl = (r.get("label") or "").strip()
                auto = r.get("kind") in ("morning", "night")
                base = lbl.rsplit("/", 1)[-1].strip() if auto else lbl
                last[base] = (r.get("at") or "", auto)
        except Exception:
            pass
        return last

    _runs_by_job = _job_runs()

    def _ranline(job):
        at, auto = _runs_by_job.get(job, ("", False))
        if not at:
            return "not run yet"
        d, tm = at[:10], at[11:16]
        if d == today.isoformat():
            when = "today at " + tm
        elif d == (today - timedelta(days=1)).isoformat():
            when = "yesterday"
        else:
            when = d
        return ("ran itself " if auto else "you ran it ") + when

    _ov_morning = (cfg.get("ai_features") or {}).get("morning")
    _morning_on = _ov_morning if isinstance(_ov_morning, bool) else ai == "full"
    _night_on = bool((cfg.get("night") or {}).get("enabled"))
    _sync_min = cfg.get("auto_sync_minutes") or 20
    if _morning_on or _night_on:
        _auto_bits = []
        if _morning_on:
            _auto_bits.append("the plan writes itself each morning at 7")
        if _night_on:
            _auto_bits.append("the night shift works the queue while you sleep")
        _auto_bits.append(f"folders sync every {_sync_min} minutes")
        jobs_lead = ("You don&rsquo;t have to run these yourself &mdash; "
                     + ", ".join(_auto_bits)
                     + ". The buttons are for when you don&rsquo;t want to wait.")
    else:
        jobs_lead = ("In Careful mode nothing runs unasked &mdash; these "
                     "buttons are how work starts. Folders still sync on "
                     f"their own every {_sync_min} minutes.")

    n_pending = len(pending)
    qcount_label = (f"&middot; {n_pending} waiting" if n_pending else "nothing waiting")
    V["claude"].append(f"""
<div class="asker needs-server">
  <p class="jobslead">{jobs_lead}</p>
  <div class="jobrow jobrow2">
    <button class="jobbtn" data-job="brief" title="Good after a few days away.">Catch me up<span>the whole brain, in plain language</span><span class="jobwhen">{_ranline("brief")}</span></button>
    <button class="jobbtn" data-job="today" title="Runs itself every morning at 7; use this after big mid-day changes.">Refresh today&rsquo;s plan<span>rewrite the three from the brain as it stands</span><span class="jobwhen">{_ranline("today")}</span></button>
    <button class="jobbtn" data-job="wrap" title="The night shift also runs this when it is on.">Tidy the brain<span>file strays, catch stale or contradictory entries</span><span class="jobwhen">{_ranline("wrap")}</span></button>
    <button class="jobbtn" data-job="discover" title="Read-only; safe anytime.">Scan my project folders<span>find new work on this Mac</span><span class="jobwhen">{_ranline("discover")}</span></button>
    <button class="jobbtn" data-job="scout" title="Searches the web for what is on where you are. Runs weekly on its own; nothing is ever booked.">Find things to do<span>concerts, shows and nights out that match your taste</span><span class="jobwhen">{_ranline("scout")}</span></button>
    <button class="jobbtn" data-job="audit" title="Claude hunts the missing facts that make ranking wrong and asks for them.">Ask me what&rsquo;s missing<span>gaps become questions with answer boxes on Today</span><span class="jobwhen">{_ranline("audit")}</span></button>
    <button id="askrun" class="jobbtn jobqueue" title="Start Claude Code here and work through everything waiting">Work the queue<span id="qcount">{qcount_label}</span><span class="jobwhen">{_ranline("queue")}</span></button>
  </div>
  <textarea id="askbox" rows="2" data-mic placeholder="Or type anything: a request, an update, a brain-dump &mdash; or a change to the brain itself (&ldquo;this number looks wrong&rdquo;). Claude can rebuild its own page. Paste a screenshot straight in and it comes along."></textarea>
  <div class="askrow">
    <select id="askmode">
      <option value="just-do-it">Just do it</option>
      <option value="dump">Organize a brain-dump</option>
      <option value="journal">Journal my day</option>
      <option value="investigate">Look into it first</option>
      <option value="draft">Draft something for me</option>
      <option value="question">Just answer the question</option>
      <option value="critic">Tear it apart &mdash; no mercy</option>
      <option value="consult">Run the frameworks on it</option>
      <option value="tidy">Tidy up the brain</option>
    </select>
    <button id="asksend" class="primary">Add to the queue</button>
  </div>
  <div id="agentfeed" class="feed" hidden></div>
  <div id="runhistory" class="runs"></div>
</div>""")

    _qlabel = ask_label

    def _qcard(item):
        # Done cards lead with the payload: the Outcome in full size, the
        # original ask folded away, and no status chip — "done" on every
        # card carries no information. Anything not-done keeps its chip.
        label = _qlabel(item)
        chip = ("" if item["status"] == "done" else
                f'<span class="v v-{"wait" if item["status"] == "pending" else "mine" if item["status"] == "working" else "unk"}">{e(item["status"])}</span> ')
        out = [f'<div class="qitem q-{e(item["status"])}"'
               f' data-qfile="{e(item["file"])}">'
               f'<div class="qhead">{chip}<b>{e(label)}</b>'
               f'<span class="qdate">{e(item["created"])}</span></div>']
        if item["outcome"]:
            out.append('<div class="qout qoutfirst">'
                       + linkify_html(MD.render(item["outcome"])) + "</div>")
        if item["body"]:
            out.append('<details class="qask"><summary>what you asked</summary>'
                       f'<div class="qbody">{MD.render(item["body"])}</div></details>')
        if item["status"] == "done" and item["outcome"].strip():
            # An Outcome is the end of a thread that often has more in it.
            # This opens a conversation already holding the ask and the answer.
            out.append('<button class="qcont" data-qcont='
                       f'"{e(item["file"])}">Carry on in a conversation '
                       "&#8594;</button>")
        out.append("</div>")
        return "".join(out)

    # The asker's section ends here: what Claude PRODUCED lives in the
    # right-hand column, so asking and watching sit side by side instead of
    # scrolling past each other.
    V["claude"].append("</section>")
    V["clauderail"].append('<section class="qwrap">')
    if pending:
        # The queue the buttons talk about, visible — not a black box.
        V["clauderail"].append(
                           cardhead(f'<h3 class="area">In the queue '
                                    f'<span class="csub">{n_pending}</span></h3>',
                                    artimg("waiting", 46))
                           + '<div class="qlist">'
                           + "".join(_qcard(item) for item in pending)
                           + "</div>")
    finished = [x for x in q if x["status"] in ("done", "dropped")]
    if finished:
        # Newest first: the recent Outcome is what she comes here to read.
        # By created date, not filename — the earliest queue files predate
        # the timestamp naming and would otherwise float to the top.
        finished.sort(key=lambda x: (x["created"] or "", x["file"]),
                      reverse=True)

        def _isq(item):
            return (item["status"] == "done"
                    and (item["title"] or "").lower().startswith("answer"))
        cards = []          # (html, how many items it represents)
        i3 = 0
        while i3 < len(finished):
            item = finished[i3]
            if _isq(item):
                j3 = i3
                while (j3 < len(finished) and _isq(finished[j3])
                       and finished[j3]["created"][:10] == item["created"][:10]):
                    j3 += 1
                grp = finished[i3:j3]
                if len(grp) >= 3:
                    # A run of identical events is one fact, not eight cards.
                    cards.append((
                        f'<details class="ghost qgroup"><summary>{len(grp)} questions '
                        f'answered <span class="qdate">{e(item["created"][:10])}</span>'
                        "</summary>" + "".join(_qcard(x) for x in grp) + "</details>",
                        len(grp)))
                    i3 = j3
                    continue
            cards.append((_qcard(item), 1))
            i3 += 1
        # Three most recent stay in view; the pile folds away. A long trail
        # of finished cards was burying everything under it. The newest card
        # shows its whole Outcome — it is the report of the last run — while
        # the two under it clamp to a few lines until asked.
        head, rest = cards[:3], cards[3:]
        n_rest = sum(n for _, n in rest)
        head_html = "".join(
            h if k3 == 0 else
            f'<div class="qclamp">{h}<button class="qmore">read the rest</button></div>'
            for k3, (h, _) in enumerate(head))
        V["clauderail"].append(
            f'<h3 class="area">Done <span class="csub">{len(finished)}</span></h3>'
            '<div class="qlist">' + head_html)
        if rest:
            V["clauderail"].append(
                f'<details class="ghost qgroup"><summary>{n_rest} older &mdash; '
                'show</summary>' + "".join(h for h, _ in rest) + "</details>")
        V["clauderail"].append("</div>")
    V["clauderail"].append("</section>")

    # ---- Connections: every channel the brain has, with its live state and
    # the way in. These existed but hid behind conditions (mail setup only
    # appeared when a draft was stuck); a channel you can't find is a channel
    # that doesn't exist.
    tg = {}
    try:
        with open(os.path.join(BRAIN, ".telegram.json"), encoding="utf-8") as f:
            tg = json.load(f)
    except Exception:
        pass
    try:
        import email_send as _es
        mail_accts = _es.accounts()
    except Exception:
        mail_accts = []
    cal_on = bool(cfg.get("calendar"))
    conn = ['<section id="connections"><h2>Connections'
            + hint("The brain's senses. Beeper brings chat dates in, Telegram "
                   "makes the brain a contact, mail lets drafts send for real, "
                   "calendar lets the plan see your actual day.")
            + '</h2><div class="connlist">']
    # Beeper — runs itself; state is just the stamp.
    try:
        _bm = os.path.getmtime(os.path.join(BRAIN, ".beeper-review.json"))
        _bd2 = datetime.now() - datetime.fromtimestamp(_bm)
        _bs = ("just now" if _bd2.total_seconds() < 3600 else
               f"{int(_bd2.total_seconds() // 3600)}h ago" if _bd2.days == 0 else
               f"{_bd2.days}d ago")
        conn.append('<div class="connrow"><i class="cdot on"></i><b>Beeper</b>'
                    f'<span>Synced {_bs} &mdash; chat names and dates only, '
                    'runs itself every morning.</span></div>')
    except Exception:
        conn.append('<div class="connrow"><i class="cdot"></i><b>Beeper</b>'
                    '<span>Never synced &mdash; tap <b>Sync from Beeper</b> on '
                    'the People page.</span></div>')
    # Telegram — three states: paired, token-awaiting-first-message, nothing.
    if tg.get("chat_id"):
        conn.append('<div class="connrow"><i class="cdot on"></i><b>Telegram</b>'
                    '<span>Paired &mdash; anything you message the bot gets '
                    'filed; the plan arrives mornings, the check evenings.</span></div>')
    elif tg.get("token"):
        _pc = tg.get("pair_code") or ""
        conn.append('<div class="connrow"><i class="cdot wait"></i><b>Telegram</b>'
                    '<span>Token saved. To pair, message '
                    + (f'the code <b class="paircode">{e(_pc)}</b>' if _pc
                       else 'the pairing code (appears here within a minute '
                            '&mdash; refresh)')
                    + ' to your bot in Telegram. Only the chat that sends the '
                    'exact code is ever listened to &mdash; anyone else who '
                    'finds the bot gets silence, forever. Once paired, the '
                    'whole surface is two things: file a note, and read the plan '
                    'back. A message can never start a job or spend '
                    'anything.</span></div>')
    else:
        conn.append(
            '<div class="connrow needs-server"><i class="cdot"></i><b>Telegram</b>'
            '<span>Message the brain from your phone &mdash; captures file '
            'themselves, the plan arrives as a message. Two minutes: in '
            'Telegram message <b>@BotFather</b>, send <code>/newbot</code>, '
            'pick any name, paste the token here.'
            '<span class="connform"><input id="tg-token" autocomplete="off"'
            ' placeholder="123456789:AAF...">'
            '<button class="mini" id="tg-connect">Connect</button>'
            '<span class="mshelp" id="tg-help"></span></span></span></div>')
    # Mail — accounts listed; the add form always reachable, not draft-gated.
    # The flow is written as numbered steps with the provider's own settings
    # page one click away, because "app password" is jargon until the page
    # that mints one is in front of you.
    mrows = " ".join(f'<code>{e(a["address"])}</code>' for a in mail_accts)
    conn.append(
        '<div class="connrow needs-server"><i class="cdot'
        + (" on" if mail_accts else "") + '"></i><b>Mail</b><span>'
        + (f"Connected: {mrows} &mdash; drafts can send for real. "
           if mail_accts else
           "Not connected &mdash; email drafts stay copy-paste until this is "
           "set up. ")
        + '<button class="mini" id="ms2-open">'
        + ("Add another account" if mail_accts else "Set up sending")
        + '</button>'
        '<span id="ms2wrap" hidden>'
        '<span class="msteps"><b>What this needs is an app password &mdash; '
        'never your real one.</b> It&rsquo;s a separate throwaway code your '
        'provider mints just for this: it can only send mail, it can&rsquo;t '
        'open your account, and you can revoke it any time.<br>'
        '<b>Step 1</b> &mdash; create one (takes two minutes): '
        '<a href="https://myaccount.google.com/apppasswords" target="_blank" '
        'rel="noopener">Gmail: create an app password &#8599;</a> &nbsp;&middot;&nbsp; '
        '<a href="https://login.yahoo.com/myaccount/security" target="_blank" '
        'rel="noopener">Yahoo: Account Security &#8599;</a> (look for '
        '&ldquo;Generate app password&rdquo;). If the page asks you to turn '
        'on 2-Step Verification first, do that and come back.<br>'
        '<b>Step 2</b> &mdash; back here: pick the provider, your address, '
        'paste the code it gave you.</span>'
        '<form id="ms2" class="mailsetup">'
        '<select id="ms2-prov"><option value="gmail">Gmail</option>'
        '<option value="yahoo">Yahoo</option><option value="icloud">iCloud</option>'
        '<option value="outlook">Outlook (sending only)</option></select>'
        '<input id="ms2-addr" placeholder="you@gmail.com" autocomplete="off">'
        '<input id="ms2-pw" type="password" placeholder="paste the app password" autocomplete="off">'
        '<button type="submit" class="primary">Connect</button>'
        '<span class="mshelp" id="ms2-help">The code lands in your '
        'Mac&rsquo;s Keychain, never in a file.</span></form></span>'
        '</span></div>')
    # Mail, the other direction. Off until she turns it on, headers only, and
    # only ever on a button — see email_read.py for why bodies stay out. Shown
    # even with no account connected: a capability nobody can see is one she
    # can't decide about.
    conn.append(_mailread_row(cfg, bool(mail_accts)))
    # Task suggestions from whitelisted mail — the amended boundary of
    # 2026-09-08 (decisions.md): bodies for HER list only, read by a no-tools
    # model, nothing lands without her Accept.
    conn.append(_mailtasks_row(cfg, bool(mail_accts)))
    # Calendar — local read of the Mac's Calendar app; Google and Outlook
    # ride in through Internet Accounts, no OAuth anywhere.
    conn.append(
        '<div class="connrow needs-server"><i class="cdot'
        + (" on" if cal_on else "") + '"></i><b>Calendar</b><span>'
        + ("On &mdash; the morning plan reads the Mac&rsquo;s Calendar app, "
           "titles and times only. "
           '<button class="mini" id="cal-test">Test read</button> '
           '<button class="mini" id="cal-off">Turn off</button>'
           if cal_on else
           "Off &mdash; the plan can&rsquo;t see your real day. "
           '<button class="mini" id="cal-on">Turn on</button>')
        + '<span class="mshelp" id="cal-help"></span>'
        + (_calblock_row(cfg) if cal_on else "")
        + '<details class="connhow"><summary>How Google Calendar and Outlook '
        'get in</summary>System Settings &rarr; Internet Accounts &rarr; add '
        '<b>Google</b> and <b>Microsoft Exchange</b>, tick Calendars on each. '
        'The Mac&rsquo;s Calendar app then carries both, and the brain reads '
        'it locally, so nothing about your calendar leaves this Mac. '
        'The first read pops one macOS permission dialog; allow it once.'
        '</details></span></div>')
    # The way back into the walkthrough. The ? in the corner always starts
    # this page's tour; this re-arms the whole thing — for a new tester on
    # this brain, or for her own second look.
    conn.append(
        '<div class="connrow needs-server"><i class="cdot"></i>'
        '<b>Show me around</b><span>'
        'The ? in the corner walks through whichever page you are on. '
        '<button class="mini" id="tour-again">Start the full tour</button>'
        '<span class="mshelp" id="tour-help"></span></span></div>')
    conn.append("</div></section>")
    V["clauderail"].append("".join(conn))

    # ---- New files in her folders. A session in a project repo can write a
    # 75-item task menu and a walkthrough log, and none of it reaches the
    # brain: sync mirrors CHECKBOXES, and those files have none. This lists
    # what changed and hands it to Claude to file.
    try:
        import serve as _srv
        newf = _srv.recent_source_files()
    except Exception:
        newf = []
    if newf:
        rows = []
        for fdesc in newf[:12]:
            rows.append('<div class="recrow"><span class="recname">'
                        f'{e(fdesc["name"])}</span>'
                        f'<span class="recmeta">{e(fdesc["source"])} &middot; '
                        f'{fdesc["kb"]}kb &middot; {e(fdesc["when"])}</span></div>')
        V["clauderail"].append(
            '<section id="newfiles"><h2>New in your folders'
            + hint("Markdown that changed in your project folders in the last "
                   "few days. Sync only mirrors checkboxes, so files like a "
                   "task menu or a walkthrough log never reach the brain "
                   "until someone reads them.")
            + '</h2><div class="recwrap needs-server">'
            + "".join(rows)
            + (f'<p class="meta">and {len(newf) - 12} more</p>'
               if len(newf) > 12 else "")
            + '<div class="recopts" style="margin-top:12px">'
            '<button class="btnp" id="filenew">Have Claude read and file these</button>'
            "</div>"
            '<p class="meta">Marked &ldquo;confirm&rdquo; so you can prune.'
            "</p></div></section>")

    # ---- Recordings: the loop from "I recorded the kitchen conversation" to
    # "the project's task lists moved" without a shell script in between.
    try:
        import transcribe as TR
        recs = TR.recordings()[:6]
        haves = TR.existing_transcripts()
    except Exception:
        recs, haves = [], []
    if recs or haves:
        rooms_opts = ['<option value="">which project?</option>']
        for wing in ((cfg.get("rooms") or {}).get("wings") or []):
            for room in (wing.get("rooms") or []):
                nm = room.get("name", "")
                sl = room.get("slug") or M.room_slug(nm)
                rooms_opts.append(f'<option value="{e(sl)}">{e(nm)}</option>')
        rows = []
        for r in recs:
            mins = f'{r["minutes"]:g} min' if r["minutes"] else ""
            state = ('<span class="recdone">transcribed &#10003;</span>'
                     if r["done"] else
                     f'<button class="mini needs-server" data-rec="{e(r["path"])}">'
                     "Transcribe &amp; file</button>")
            rows.append('<div class="recrow"><span class="recname">'
                        f'{e(r["name"])}</span>'
                        f'<span class="recmeta">{e(mins)} &middot; {e(r["when"])}</span>'
                        f"{state}</div>")
        # Transcripts she already produced herself — the cheap path: file it
        # and go straight to the tasks, no second twenty-minute run.
        hrows = []
        for t in haves:
            hrows.append(
                '<div class="recrow"><span class="recname">'
                f'{e(t.get("label") or t["name"])}</span>'
                f'<span class="recmeta">{t["kb"]}KB &middot; {e(t["when"])}</span>'
                f'<button class="mini needs-server" data-adopt="{e(t["path"])}">'
                "Use this transcript</button></div>")
        if hrows:
            rows.append('<p class="recsub">Already transcribed &mdash; file '
                        "one straight into a project</p>" + "".join(hrows))
        V["clauderail"].append(
            '<section id="recordings"><h2>Recordings'
            + hint("Voice notes become project movement: transcribed on this "
                   "Mac (nothing is uploaded), then Claude turns what was "
                   "said into your task list and the other person's.")
            + '</h2><div class="recwrap needs-server">'
            '<div class="recopts"><select id="rec-room">'
            + "".join(rooms_opts) + '</select>'
            '<select id="rec-lang"><option value="fr">French</option>'
            '<option value="en">English</option></select>'
            '<input id="rec-prompt" placeholder="names and jargon to expect '
            '(Kit, moquette, évacuation…)" autocomplete="off"></div>'
            + "".join(rows)
            + '<p class="recnote" id="recnote" hidden></p>'
            '<p class="meta">Transcripts land in brain/transcripts/. A '
            'recording of an hour takes roughly twenty minutes to do, and '
            'the page can be closed while it runs.</p></div></section>')

    # ================= SEASON =================
    V["season"].append(seasonview(cfg, date.today()))
    try:
        season_ics()
    except Exception:
        pass          # the feed is a bonus; it must never sink the page

    # ================= NEWS =================
    V["news"].append(newsview(cfg))

    parts = []
    for vname in ("today", "school", "plate", "people", "season", "news", "claude"):
        inner = "".join(V[vname])
        if vname == "today" and V["todayrail"]:
            # wide work column + the awareness rail beside it
            inner = ('<div class="todaygrid"><div class="todaymain">' + inner
                     + '</div><aside class="todayrail">'
                     + "".join(V["todayrail"]) + "</aside></div>")
        if vname in ("plate", "people"):
            # 60/40: the ranked list keeps a readable measure, and an opened
            # row's detail docks beside it instead of shoving the ranking
            # down the page. The dock is filled by moving the row's own body
            # into it, so every control inside keeps working.
            eyebrow = "Open row" if vname == "plate" else "Who this is"
            inner = (f'<div class="dockgrid"><div class="dockmain">' + inner
                     + f'</div><aside class="dockside" id="{vname}dock" hidden'
                     f' data-dockfor="{vname}">'
                     f'<div class="pdtop"><p class="eyebrow">{eyebrow}</p>'
                     '<button class="mini dockclose">Close</button></div>'
                     '<span class="wav"></span>'
                     '<h2 class="dockname"></h2>'
                     '<p class="coach dockwhy"></p>'
                     '<div class="pdstats dockstats"></div>'
                     '<div class="dockbody"></div></aside>'
                     # The dock column is 40% of a 1420px page and stands
                     # EMPTY until a row is opened. Anything permanently
                     # useful belongs in it — otherwise the width is reserved
                     # for a maybe and the list is squeezed for nothing.
                     + "".join(V.get(vname + "rail") or [])
                     + "</div>")
        if vname == "claude" and V["clauderail"]:
            # asking on the left, everything Claude produced on the right
            inner = ('<div class="claudegrid"><div class="claudemain">' + inner
                     + '</div><div class="clauderail">'
                     + "".join(V["clauderail"]) + "</div></div>")
        if vname == "claude":
            # Sessions and Usage left the top bar; this row is how the three
            # Claude pages reach each other.
            inner = CHROME.claude_subnav("jobs", in_app=True) + inner
        parts.append(f'<div class="view" data-view="{vname}">' + inner + "</div>")

    # Answers, grafted back onto the rows that asked for them. Outside the tab
    # views because one task row appears on the plan, the plate and in a
    # drawer, and all three deserve the pill.
    parts.append(ready_templates(ready_marks(drafts, q, ws, today_md)))

    # The workstream drawer: every live project as a little side screen,
    # opened by any Details button. Lives outside the tab views so it works
    # from Today's hero and the Plate alike.
    _sources = cfg.get("sources", []) or []
    # The speed reader lives outside the tab views: any page text can call
    # window.rsvpRead(text, title) — News uses it today, others can later.
    parts.append(
        '<div id="rsvp" class="rsvp" role="dialog" aria-modal="true"'
        ' aria-label="Speed reader" hidden><div class="rsvpinner">'
        '<p class="rsvptitle meta" id="rsvptitle"></p>'
        '<div class="rsvpword"><span class="rpre"></span>'
        '<span class="rpiv"></span><span class="rpost"></span></div>'
        '<div class="rsvpbar"><i></i></div>'
        '<div class="rsvpctl">'
        '<button class="mini" id="rsvpprev" hidden>&lsaquo; previous</button>'
        '<button class="mini" id="rsvpslow" title="Slower">&minus;</button>'
        '<button class="mini" id="rsvpplay">Pause</button>'
        '<button class="mini" id="rsvpfast" title="Faster">+</button>'
        '<span class="meta" id="rsvpwpm"></span>'
        '<button class="mini" id="rsvpnext" hidden>next &rsaquo;</button>'
        '<button class="mini" id="rsvpclose">Close</button></div>'
        '<p class="rsvphint">space pauses &middot; &larr; &rarr; step words '
        "&middot; &uarr; &darr; previous / next article &middot; esc "
        "closes</p></div></div>")
    parts.append('<aside id="wsdrawer" class="wsdrawer" hidden'
                 ' aria-label="Workstream details">'
                 '<button class="mini wsdclose" id="wsdclose">&times; close</button>'
                 + "".join(wsdetail(w, _sources) for w in b["live"])
                 + "</aside>")

    # One nav for the whole app — see chrome.py. Rooms, Map and Sessions used
    # to sit in the action pills beside "Brain dump", so half that row
    # navigated and half opened a dialog with nothing to tell them apart.
    nav = CHROME.nav_html(current="today", in_app=True, cls="topnav appnav")

    owner = cfg.get("owner", "My")
    ap_cur = cfg.get("appearance", {}) or {}
    ap_accent = ap_cur.get("accent", "olive")
    ap_base = ap_cur.get("base", "warm")
    ap_font = ap_cur.get("font", "editorial")
    ap_style = ap_cur.get("style", "workroom")
    _circles = list(M.circles(cfg).values())
    circleopts = "".join(
        f'<option{" selected" if c["name"]=="Friends" else ""}>{e(c["name"])}</option>'
        for c in _circles)
    circlesjs = MD.json_for_script([[c["name"], (c["every"] or "no set rhythm")]
                                    for c in _circles if c["name"].lower() not in ("one-off","oneoff")])
    page = (HEAD.replace("__TITLE__", e(f"{owner} brain"))
                .replace("__FONT__", ap_font)
                .replace("__STYLE__", ap_style)
                .replace("__PALETTE__", palette_css(cfg)) + f"""
<header class="top">
  <div class="brand"><img class="logo" src="logo-96.png?v=5" alt="" width="24" height="24"><span class="wordmark">{e(owner)} <b>brain</b></span>
    <button class="syncstate" id="syncstate" title="Syncs itself on a timer &mdash; click to sync right now"><i></i><span class="skinx skinx-stamp">{datetime.now().strftime("%a %d %b").upper()} &middot;</span><span id="synctext">{today.isoformat()}</span></button>
  </div>
  {nav}
  <div class="findwrap needs-server">
    <span class="findicon" aria-hidden="true"><svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5 21 21"/></svg></span>
    <input id="findq" type="search" placeholder="Find anything, or + to jot" autocomplete="off"
           aria-label="Find anything in your brain" spellcheck="false">
    <div id="findout" class="findout" hidden></div>
  </div>
  <div class="hacts">
    <span class="skinx skinx-legend">{_legend_html(b)}</span>
    {CHROME.ask_button_html()}
    <button id="updbtn" class="ghostbtn needs-server" title="Looking BACK: say what already happened and Claude ticks it off, re-ranks what is left and corrects the files. Use it at the end of a day.">What happened?</button>
    <div class="apwrap" data-accent="{ap_accent}" data-base="{ap_base}" data-font="{ap_font}">
      <button id="apbtn" class="ghostbtn" title="Connections &amp; appearance" aria-label="Connections and appearance">&#8943;</button>
      <div id="appanel" class="appanel" hidden>
        <p class="aplabel">Connections</p>
        <div id="cxlist" class="cxlist"><p class="cxwait">Checking&hellip;</p></div>
        <a class="cxall" href="#/claude" id="cxall">Set these up on the Claude tab &rarr;</a>
        <p class="aplabel">Style</p>
        <div class="aprow styles" id="ap-style">{style_chips(cfg)}</div>
        <p class="aplabel">Palette</p>
        <div class="aprow palettes" id="ap-palette">{palette_chips(cfg)}</div>
        <p class="aplabel">Theme</p>
        <div class="aprow" id="ap-theme">
          <button data-theme-set="light">Light</button>
          <button data-theme-set="dark">Dark</button>
          <button data-theme-set="auto">Auto</button>
        </div>
        <p class="aplabel">Accent</p>
        <div class="aprow swatches" id="ap-accent">
          <button data-accent="olive" style="--sw:oklch(48% .11 135)" title="Olive"></button>
          <button data-accent="forest" style="--sw:oklch(48% .11 150)" title="Forest"></button>
          <button data-accent="teal" style="--sw:oklch(52% .11 185)" title="Teal"></button>
          <button data-accent="ocean" style="--sw:oklch(52% .12 245)" title="Ocean"></button>
          <button data-accent="indigo" style="--sw:oklch(50% .13 280)" title="Indigo"></button>
          <button data-accent="plum" style="--sw:oklch(50% .13 325)" title="Plum"></button>
          <button data-accent="rose" style="--sw:oklch(55% .14 12)" title="Rose"></button>
          <button data-accent="amber" style="--sw:oklch(60% .12 70)" title="Amber"></button>
        </div>
        <p class="aplabel">Paper</p>
        <div class="aprow" id="ap-base">
          <button data-base="warm">Warm</button>
          <button data-base="cool">Cool</button>
          <button data-base="rose">Blush</button>
          <button data-base="mono">Neutral</button>
        </div>
        <p class="aplabel">Type</p>
        <div class="aprow" id="ap-font">
          <button data-font="editorial">Editorial</button>
          <button data-font="clean">Clean</button>
          <button data-font="playful">Playful</button>
        </div>
      </div>
    </div>
  </div>
</header>
<div class="banner" id="filebanner" hidden>
  Read-only: this is the page opened as a file. Double-click <b>Open Brain</b>
  for the live version.
</div>
<main>
{''.join(parts)}
</main>
<footer>Generated {today.isoformat()} from the markdown in <code>brain/</code>
&mdash; edits go there.</footer>
<div id="runbar" class="runbar needs-server" data-pending="{len(pending)}"{"" if pending else " hidden"}
     title="Tap to open the activity drawer">
  <img src="logo-96.png?v=5" width="20" height="20" alt="">
  <span class="rbspin" id="rb-spin" hidden aria-hidden="true"></span>
  <span id="rb-txt">{len(pending)} waiting for Claude</span>
  <button class="rb-go" id="rb-run">Run now</button>
</div>
<aside id="actdrawer" class="actdrawer" hidden aria-label="Claude activity">
  <div class="acthead"><b id="act-title">Claude</b>
    <button class="mini" id="act-close">&times; close</button></div>
  <p class="meta actstatus" id="act-status"></p>
  <div id="act-feed" class="feed actfeed" hidden></div>
  {actpend}
  {actqs}
  <div class="actacts">
    <button class="mini" id="act-run">Work the queue</button>
    <a class="mini actlink" href="#/claude">Open the Claude tab</a>
  </div>
</aside>
""" + _dumpcopy(SHEET, fresh=not b["live"] and not people, cfg=cfg) + SCRIPT + PEOPLE_SCRIPT
            + TALKCHAT + CHROME.ask_block()
            + TOUR.brain_block() + TALK.block() + _PINTRO_JS + "\n</body></html>")
    page = page.replace("__CIRCLEOPTS__", circleopts).replace("__CIRCLESJS__", circlesjs)
    # The calendar-block button exists only where calendar_write can work.
    page = page.replace("__SZCAL__", "1" if sys.platform == "darwin" else "0")

    # A page with broken script is worse than a stale page: it renders blank
    # AND kills the auto-refresh that would have rescued it. So the inline
    # script must parse before the old page is replaced. Node does the check
    # when present; without node the write proceeds as before.
    import shutil as _sh
    import subprocess as _sp
    import tempfile as _tf
    node = _sh.which("node")
    if node:
        # EVERY script block, not just the first — the People script is its own
        # <script> precisely so it survives the main one, and a gate that only
        # checks script #1 would let a broken script #2 ship silently.
        for js in re.findall(r"<script>(.*?)</script>", page, re.S):
            with _tf.NamedTemporaryFile("w", suffix=".js", delete=False,
                                        encoding="utf-8") as tmp:
                tmp.write(js)
            try:
                r = _sp.run([node, "--check", tmp.name], capture_output=True,
                            text=True, timeout=20)
                if r.returncode != 0:
                    raise SystemExit("REFUSING to write index.html — a page "
                                     "script does not parse:\n"
                                     + r.stderr.strip()[:600])
            finally:
                os.unlink(tmp.name)

    # The shared look for pages this script does not render (sessions.html):
    # the same font faces and the same :root tokens, regenerated on every
    # build so the appearance panel reaches them too.
    faces = "\n".join(re.findall(r"@font-face\{[^}]+\}", HEAD))
    faces += ("\n@font-face{font-family:'Petrona';"
              "src:url('fonts/petrona-i.woff2') format('woff2');"
              "font-weight:400 600;font-style:italic;font-display:swap}")
    with open(os.path.join(BRAIN, "appearance.css"), "w", encoding="utf-8") as f:
        f.write(faces + "\n" + palette_css(cfg))

    # sessions.html is hand-written, but its Claude sub-row must be the same
    # strip chrome.py renders on the Claude tab and usage.html — a pasted
    # copy drifted apart once already, which read as three different bars.
    # Re-stamp it every build; the fresh markup matches the pattern again,
    # so this stays idempotent.
    spath = os.path.join(BRAIN, "sessions.html")
    try:
        with open(spath, encoding="utf-8") as f:
            sh = f.read()
        fresh = CHROME.claude_subnav("sessions")
        new = re.sub(r"<style>\s*\.clsub\{.*?</nav>", lambda m: fresh, sh,
                     count=1, flags=re.S)
        new = new.replace(
            '<div style="padding:4px 24px 8px;border-bottom:1px solid '
            'var(--rule);background:var(--card)">' + fresh,
            '<div style="padding:10px 24px 0">' + fresh)
        # The style attribute rides the same re-stamp: sessions.html links
        # appearance.css, so the attribute is all it needs to wear the style.
        new = re.sub(r'<html lang="en"[^>]*>',
                     '<html lang="en" data-style="%s">' % ap_style,
                     new, count=1)
        if "brain-style" not in new:
            new = new.replace(
                '<link rel="stylesheet" href="appearance.css">',
                '<link rel="stylesheet" href="appearance.css">'
                "<script>try{var _bs=localStorage.getItem('brain-style');"
                "if(_bs)document.documentElement.setAttribute('data-style',_bs);}"
                "catch(e){}</script>", 1)
        # The Ask panel rides the same re-stamp: sessions.html carried a
        # pasted copy that had already fallen behind chrome.py's (no chats
        # list, no model picker, no full screen). The block is the last
        # thing before </body>, so the greedy match ends at its own script.
        # ask_block() brings its own <style> in front of the panel, so the
        # match takes any earlier copies of that style with it. Matching from
        # the panel alone left the old style behind on every build, and 460
        # builds later the page carried 460 copies of it (5 MB).
        new = re.sub(r'(?:<style>\s*\.askopen\{.*?</style>\s*)*'
                     r'<div class="askscrim".*</script>',
                     lambda m: CHROME.ask_block(), new, count=1, flags=re.S)
        if new != sh:
            with open(spath, "w", encoding="utf-8") as f:
                f.write(new)
    except Exception:
        pass          # a missing sessions.html must not sink the build

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(page)

    # The usage page rides every build: it links appearance.css (written just
    # above) and shares the chrome, so building them together is what keeps
    # them from drifting apart.
    import usage_page
    usage_page.build(cfg)

    # The kitchen page rides along too — same chrome, same palette. A
    # missing recipe library must never sink the main build.
    try:
        import cook as _cook
        _cook.build(cfg)
    except Exception:
        pass

    return OUT, len(ws), len(pending)


# The page's stylesheet and main script live as real files in page/ beside
# this one, so they can be read, highlighted and checked as CSS and
# JavaScript rather than as Python strings. They are inlined here, byte for
# byte, so the built page stays one self-contained file.
PAGE_DIR = os.path.join(HERE, "page")


def _page_file(name):
    with open(os.path.join(PAGE_DIR, name), encoding="utf-8") as f:
        return f.read()


HEAD = """<!doctype html>
<html lang="en" data-font="__FONT__" data-style="__STYLE__"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>__TITLE__</title>
<link rel="manifest" href="manifest.webmanifest">
<link rel="icon" href="logo-192.png?v=5" type="image/png">
<link rel="apple-touch-icon" href="logo-180.png?v=5">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Brain">
<meta name="theme-color" content="#f4efe6" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#1c1b16" media="(prefers-color-scheme: dark)">
<script>if("serviceWorker" in navigator)navigator.serviceWorker.register("sw.js")</script>
<style>
""" + _page_file("page.css") + """</style>
</head><body>
"""

# The quick-capture sheet. Everything about it is thumb-first: the button sits
# in the bottom-right thumb arc, the sheet rises from the bottom edge, and the
# send button stays low rather than above the keyboard. It exists because the
# alternative was scrolling the whole page to reach the box, which is exactly
# the friction that kills a capture habit.
SHEET = """
<nav class="tabbar" aria-label="Sections">
  <a href="#/today" data-nav="today">
    <svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke-width="1.8"
         stroke-linecap="round" aria-hidden="true">
      <circle cx="12" cy="12" r="4"/>
      <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6L17 7M7 17l-1.4 1.4"/>
    </svg>Today</a>
  <a href="#/school" data-nav="school">
    <svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke-width="1.8"
         stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M2.5 9L12 4.5 21.5 9 12 13.5z"/>
      <path d="M6.5 11v4.5c0 1.4 2.5 2.8 5.5 2.8s5.5-1.4 5.5-2.8V11"/>
    </svg>School</a>
  <a href="#/plate" data-nav="plate">
    <svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke-width="1.8"
         stroke-linecap="round" aria-hidden="true">
      <circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="5"/>
    </svg>Plate</a>
  <a href="#/people" data-nav="people">
    <svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke-width="1.8"
         stroke-linecap="round" aria-hidden="true">
      <circle cx="9" cy="8.5" r="3.2"/><path d="M3.5 19c.8-3.2 3-5 5.5-5s4.7 1.8 5.5 5"/>
      <circle cx="16.8" cy="9.5" r="2.4"/><path d="M15.6 14.2c2.3.2 4.2 1.8 4.9 4.8"/>
    </svg>People</a>
  <a href="#/claude" data-nav="claude">
    <svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke-width="1.8"
         stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>
      <path d="M18.5 15.5l.9 2.6 2.6.9-2.6.9-.9 2.6-.9-2.6-2.6-.9 2.6-.9z"/>
    </svg>Claude</a>
  <button class="tabmore" id="tabmore" aria-expanded="false" aria-label="More pages">
    <svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke-width="1.8"
         stroke-linecap="round" aria-hidden="true">
      <circle cx="5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/>
      <circle cx="19" cy="12" r="1.4"/>
    </svg>More</button>
</nav>
<div id="morepop" class="morepop" hidden>
  <a href="#/season" data-nav="season">Season</a>
  <a href="#/news" data-nav="news">News</a>
  <a href="rooms.html">Rooms</a>
  <a href="map.html">Map</a>
  <a class="needs-server" href="sessions.html">Sessions</a>
  <button id="moreconn" class="needs-server">Connections</button>
</div>
<div id="tscrim" class="scrim" hidden></div>
<div id="wscrim" class="scrim" hidden></div>
<div id="weekdlg" class="taskdlg" role="dialog" aria-modal="true" hidden>
  <p class="tdtitle" id="wdtitle"></p>
  <div class="tdopts" id="wdopts"></div>
</div>
<div id="taskdlg" class="taskdlg" role="dialog" aria-modal="true" hidden>
  <p class="tdtitle" id="tdtitle"></p>
  <p class="tdsub" id="tdsub" hidden></p>
  <div class="tdopts">
    <button class="tdopt" id="td-done" data-ta="done">
      <span class="tdico ok">&#10003;</span>Mark it done</button>
    <button class="tdopt" id="td-undone" data-ta="undone" hidden>
      <span class="tdico">&#8634;</span>Put it back</button>
    <button class="tdopt" id="td-next">
      <span class="tdico ok">&#10003;</span>Done &mdash; and the next step
      is&hellip;</button>
    <div class="parkrow prow" id="nextrow" hidden>
      <label class="plab"><b>Follow-up</b>
        <input type="text" id="nextline" maxlength="500"
               placeholder="what the task becomes now"></label>
      <span class="plab"><b>Surfaces</b>
        <input type="date" id="nextdate"></span>
      <span class="plab"><b></b>
        <button class="primary" id="nextgo">Tick &amp; file it</button></span>
      <span class="mshelp">Ticks this one and files the follow-up in the same
        project. Leave the date empty and it is live right away; set one and
        it stays parked until then.</span>
    </div>
    <button class="tdopt needs-server" id="td-ans">
      <span class="tdico ok">&#9998;</span>The answer came back&hellip;</button>
    <div class="parkrow prow" id="ansrow" hidden>
      <label class="plab"><b>What you heard</b>
        <input type="text" id="ansline" maxlength="600"
               placeholder="what came back"></label>
      <span class="plab"><b></b>
        <button class="primary" id="ansgo">File it</button></span>
      <span class="mshelp">Writes it onto the task now, then hands it to
        Claude to put where it belongs &mdash; the project, a person, the
        class file. It ticks the task only if your answer finishes it.</span>
    </div>
    <button class="tdopt needs-server" id="td-prog">
      <span class="tdico wait">&#8594;</span>I did my part &mdash; someone else
      has it now&hellip;</button>
    <div class="parkrow prow" id="progrow" hidden>
      <label class="plab"><b>Waiting on</b>
        <input type="text" id="progwho" maxlength="60" placeholder="who"></label>
      <label class="plab"><b>What&rsquo;s left</b>
        <input type="text" id="progwhat" maxlength="500"
               placeholder="the half that is still open"></label>
      <span class="plab"><b>Chase in</b>
        <button class="preset progdays" data-days="3">3 days</button>
        <button class="preset progdays on" data-days="7">a week</button>
        <button class="preset progdays" data-days="14">two weeks</button></span>
      <span class="plab"><b></b>
        <button class="primary" id="proggo">Record it</button></span>
      <span class="mshelp">Parks the task until then, and moves this
        project&rsquo;s next move onto them so the chase reminder knows who to
        chase.</span>
    </div>
    <div class="tdsep" role="separator"></div>
    <button class="tdopt" id="td-due">
      <span class="tdico soon">&#9200;</span>Set a deadline&hellip;</button>
    <div class="parkrow" id="duerow" hidden>
      <button class="preset" data-duedays="1">Tomorrow</button>
      <button class="preset" data-duephrase="this week">This week</button>
      <button class="preset" data-duephrase="this month">This month</button>
      <input type="date" id="duedate">
      <button class="primary" id="duego">Set</button>
    </div>
    <button class="tdopt" id="td-est">
      <span class="tdico">&#8987;</span>How long will it take&hellip;</button>
    <div class="parkrow" id="estrow" hidden>
      <button class="estpreset" data-estmin="15">15m</button>
      <button class="estpreset" data-estmin="30">30m</button>
      <button class="estpreset" data-estmin="60">1h</button>
      <button class="estpreset" data-estmin="120">2h</button>
      <button class="estpreset" data-estmin="240">4h</button>
      <button class="mini" id="estclear">clear</button>
    </div>
    <div class="tdsep" id="plansep" role="separator" hidden></div>
    <button class="tdopt needs-server" id="td-kick" hidden>
      <span class="tdico">&#10005;</span>Kick it &mdash; next best slides in</button>
    <button class="tdopt needs-server" id="td-swap" hidden>
      <span class="tdico">&#8644;</span>Swap it for&hellip;</button>
    <div class="parkrow" id="swaprow" hidden></div>
    <button class="tdopt needs-server" id="td-planday" hidden>
      <span class="tdico">&#8594;</span>Not today &mdash; pick a day&hellip;</button>
    <div class="parkrow" id="dayrow" hidden></div>
    <div class="planmove" id="planmove" hidden>
      <button class="preset" id="td-up">&#8593; Move up</button>
      <button class="preset" id="td-down">&#8595; Move down</button>
    </div>
    <button class="tdopt" id="td-unpark" hidden>
      <span class="tdico ok">&#8617;</span>Un-park &mdash; put it back on the list</button>
    <button class="tdopt" id="td-park">
      <span class="tdico wait">&#10073;&#10073;</span>Park until&hellip;</button>
    <div class="parkrow" id="parkrow" hidden>
      <button class="preset" data-days="7">Next week</button>
      <button class="preset" data-days="30">In a month</button>
      <input type="date" id="parkdate">
      <button class="primary" id="parkgo">Park</button>
    </div>
    <button class="tdopt needs-server" id="td-block">
      <span class="tdico">&#128197;</span>Block time for it&hellip;</button>
    <div class="parkrow" id="blockrow" hidden>
      <input type="date" id="blockday">
      <input type="time" id="blocktime" step="900">
      <select id="blockmin"><option value="30">30m</option>
        <option value="60" selected>1h</option><option value="90">1h30</option>
        <option value="120">2h</option><option value="180">3h</option></select>
      <button class="primary" id="blockgo">Block it</button>
      <span class="mshelp">Goes into its own &ldquo;Brain&rdquo; calendar &mdash;
        your other calendars are never touched.</span>
    </div>
    <div class="tdsep" role="separator"></div>
    <button class="tdopt" id="td-edit">
      <span class="tdico">&#9998;</span>Edit the wording&hellip;</button>
    <div class="parkrow" id="editrow" hidden>
      <input type="text" id="editline" maxlength="500" placeholder="New wording">
      <button class="primary" id="editgo">Save</button>
    </div>
    <button class="tdopt" id="td-drop" data-ta="drop">
      <span class="tdico bad">&times;</span>Drop it &mdash; not mine to do</button>
  </div>
  <button class="ghostbtn tdcancel" id="td-cancel">Cancel</button>
</div>
<div id="persondlg" class="taskdlg" role="dialog" aria-modal="true" hidden>
  <p class="tdtitle" id="pdtitle"></p>
  <div class="tdopts">
    <button class="tdopt" id="pd-rename">
      <span class="tdico">&#9998;</span>Rename&hellip;</button>
    <div class="parkrow" id="renamerow" hidden>
      <input type="text" id="renameline" maxlength="80" placeholder="New name">
      <button class="primary" id="renamego">Save</button>
    </div>
    <button class="tdopt" id="pd-merge">
      <span class="tdico">&#8646;</span>Merge into another person&hellip;</button>
    <div class="parkrow" id="mergerow" hidden>
      <input id="mergesel" list="peopledl" placeholder="type their name&hellip;">
      <button class="primary" id="mergego">Merge</button>
    </div>
    <button class="tdopt" id="pd-archive">
      <span class="tdico wait">&#10073;&#10073;</span>Archive &mdash; keep them, drop the rhythm</button>
    <button class="tdopt" id="pd-delete">
      <span class="tdico bad">&times;</span>Delete from your people</button>
  </div>
  <button class="ghostbtn tdcancel" id="pd-cancel">Cancel</button>
</div>
<div id="promisedlg" class="taskdlg" role="dialog" aria-modal="true" hidden>
  <p class="tdtitle" id="prtitle"></p>
  <p class="prhint">Something you said you'd do for them &mdash; it sits under their
    name and chases you until it's ticked.</p>
  <div class="parkrow">
    <input type="text" id="prline" maxlength="200"
           placeholder="e.g. send the flat details to the agency">
    <button class="primary" id="prgo">Save</button>
  </div>
  <button class="ghostbtn tdcancel" id="pr-cancel">Cancel</button>
</div>
<div id="askdlg2" class="taskdlg" role="dialog" aria-modal="true" hidden>
  <p class="tdtitle" id="ad-title"></p>
  <p class="prhint" id="ad-hint" hidden></p>
  <div class="adfield" id="ad-f1"><label id="ad-l1" for="ad-i1"></label>
    <input type="text" id="ad-i1" maxlength="200"></div>
  <div class="adfield" id="ad-f2" hidden><label id="ad-l2" for="ad-i2"></label>
    <input type="text" id="ad-i2" maxlength="200"></div>
  <div class="adfield" id="ad-fsel" hidden><label id="ad-lsel" for="ad-sel"></label>
    <select id="ad-sel"></select></div>
  <label class="adcheck" id="ad-fchk" hidden>
    <input type="checkbox" id="ad-chk"><span id="ad-chkl"></span></label>
  <div class="adrow">
    <button class="primary" id="ad-go">Save</button>
    <button class="ghostbtn" id="ad-cancel">Cancel</button>
  </div>
</div>
<div id="dumpover" class="dumpover" hidden role="dialog" aria-modal="true" aria-label="Brain dump">
  <div class="dumpwrap">
    <button class="dumpx" id="dumpclose" aria-label="Close">&times;</button>
    __AISETUP__
    <div class="dumpcues">
      <p class="eyebrow">Just talk</p>
      <h2 class="dumph">__DUMPH__</h2>
      <p class="dumplead">__DUMPLEAD__</p>
      __DUMPCUES__
    </div>
    <div class="dumpwrite">
      <textarea id="dumpbox" placeholder="Start wherever. &ldquo;So I&rsquo;m finishing a course in December, and there&rsquo;s an app I keep meaning to work on, but honestly the thing on my mind is&hellip;&rdquo; &mdash; and just keep going."></textarea>
      <div class="dumpfoot">
        <button id="dumpmic" class="micbtn" aria-label="Dictate" aria-pressed="false">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"
               stroke-width="2" stroke-linecap="round" aria-hidden="true">
            <rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v4"/>
          </svg>
        </button>
        <label class="dumpsearch"><input type="checkbox" id="dumpfiles-cb" checked>
          Let Claude search my computer for context on what I mention</label>
        <span id="dumpnote" class="sheetnote"></span>
        <button id="dumpbuild" class="primary">__DUMPBTN__</button>
      </div>
    </div>
    <div id="dumpprog" class="dumpprog" hidden>
      <div class="dp-holder" aria-hidden="true"><video class="artvid " autoplay muted loop playsinline poster="art/thinking.png?v=2" width="120" height="120" aria-hidden="true"><source src="art/thinking.mp4?v=2" type="video/mp4"></video></div>
      <h2 class="dumph" id="dp-stage">Claude is reading&hellip;</h2>
      <p class="dumplead" id="dp-sub">Your words are being sorted into workstreams,
        people, dates and habits. This usually takes a few minutes &mdash; you can
        close this and it keeps working (watch it live on the Claude tab).</p>
      <pre class="dp-tail" id="dp-tail"></pre>
      <p class="dp-elapsed" id="dp-elapsed"></p>
      <div id="dp-done" hidden>
        <div class="dp-holder"><video class="artvid " autoplay muted loop playsinline poster="art/celebrating.png?v=2" width="130" height="130" aria-hidden="true"><source src="art/celebrating.mp4?v=2" type="video/mp4"></video></div>
        <h2 class="dumph" id="dp-donehead">Your brain is built</h2>
        <p class="dumplead" id="dp-summary"></p>
        <p class="dumplead" id="dp-questions" hidden></p>
        <button class="primary" id="dp-tour">Show me around</button>
        <button class="ghostbtn" id="dp-sort">Sort your chat contacts</button>
        <button class="ghostbtn" id="dp-open">Open your brain</button>
      </div>
    </div>
  </div>
</div>
<button id="fab" class="fab needs-server" aria-label="Capture something">
  <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor"
       stroke-width="2" stroke-linecap="round" aria-hidden="true">
    <path d="M12 5v14M5 12h14"/>
  </svg>
</button>
<button id="ramblefab" class="ramblefab needs-server" aria-expanded="false"
        title="A running note that follows you around the brain">&#9998; ramble</button>
<div id="ramblewrap" class="ramblewrap" hidden>
  <button class="ramblex" id="ramblex" aria-label="Close notes">&times;</button>
  <p class="ramblehead">Notes as you go</p>
  <p class="ramblehint">Wander the brain and ramble &mdash; what&rsquo;s stale, what&rsquo;s
    wrong, what&rsquo;s new. It piles up here and goes to Claude in one batch; broken
    things about the brain itself count too. Your keyboard&rsquo;s mic works for talking.
    Safe across refreshes.</p>
  <textarea id="rambleta" rows="5" placeholder="the cleaners are paid&#10;Bexley is really monthly, not quarterly&#10;the map still shows X wrong&hellip;"></textarea>
  <div class="rambleacts">
    <button id="ramblemic" class="micbtn" aria-label="Dictate" aria-pressed="false">
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
           stroke-width="2" stroke-linecap="round" aria-hidden="true">
        <rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v4"/>
      </svg>
    </button>
    <span id="ramblen" class="meta"></span>
    <button class="mini" id="rambleclear">clear</button>
    <button class="mini ramblesend" id="ramblesend">Send to Claude &amp; run</button>
  </div>
</div>
<div id="scrim" class="scrim" hidden></div>
<div id="sheet" class="sheet" hidden role="dialog" aria-modal="true" aria-label="Capture">
  <div class="grab"></div>
  <div class="seg" role="tablist">
    <button class="segbtn on" data-dest="claude" role="tab" aria-selected="true">Tell Claude</button>
    <button class="segbtn" data-dest="save" role="tab" aria-selected="false">Just save it</button>
  </div>
  <p class="segnote" id="segnote" hidden></p>
  <p class="segwhat" id="segwhat">Saved word for word to your inbox. Nothing happens
    to it until Claude tidies up later. Use it when you just need it out of your head.</p>

  <div id="addform" class="addform" hidden>
    <div class="addseg">
      <button class="addbtn on" data-kind="note">Note</button>
      <button class="addbtn" data-kind="task">Task</button>
      <button class="addbtn" data-kind="waiting">Waiting on someone</button>
      <button class="addbtn" data-kind="workstream">New workstream</button>
      <button class="addbtn" data-kind="person">Person</button>
    </div>
    <div data-form="task">
      <select id="f-task-ws"></select>
      <input id="f-task-text" placeholder="What needs doing?">
      <input id="f-task-due" placeholder="Due (optional) &mdash; a date, &ldquo;friday&rdquo;, &ldquo;this week&rdquo;&hellip;">
    </div>
    <div data-form="waiting" hidden>
      <input id="f-wait-what" placeholder="What are you waiting for?">
      <input id="f-wait-who" placeholder="From who?">
      <input id="f-wait-chase" placeholder="Chase when? (e.g. no reply by Friday)">
    </div>
    <div data-form="workstream" hidden>
      <input id="f-ws-name" placeholder="Name it">
      <select id="f-ws-area">
        <option value="Dad">Dad</option>
        <option value="School">School</option>
        <option value="Business">Business</option>
        <option value="Personal" selected>Personal</option>
      </select>
      <select id="f-ws-ball">
        <option value="me">Ball is with me</option>
        <option value="them">Waiting on someone else</option>
        <option value="nobody">Nobody / not started</option>
      </select>
      <input id="f-ws-next" placeholder="Next physical step (optional)">
      <input id="f-ws-due" type="date">
    </div>
    <div data-form="person" hidden>
      <input id="f-p-name" placeholder="Who?">
      <select id="f-p-every">
        <option value="3 days">Every few days</option>
        <option value="weekly">Weekly</option>
        <option value="2 weeks">Every couple of weeks</option>
        <option value="monthly" selected>Monthly</option>
        <option value="quarterly">Every few months</option>
      </select>
      <select id="f-p-circle">__CIRCLEOPTS__</select>
      <select id="f-p-ball">
        <option value="nobody" selected>We are even</option>
        <option value="me">I owe them a reply</option>
        <option value="them">They owe me one</option>
      </select>
      <input id="f-p-where" placeholder="Where do they live? (optional)">
      <input id="f-p-bday" placeholder="Birthday, MM-DD (optional)">
      <input id="f-p-how" placeholder="How do you know them? (optional)">
      <label class="chk"><input type="checkbox" id="f-p-focus">
        Someone I want to invest in this season</label>
    </div>
  </div>

  <div id="chatform" class="addform" hidden>
    <select id="f-chat-person"></select>
    <p class="segwhat">Paste the chat text (or attach a screenshot below). Claude reads
      it, pulls out anything you promised, and files it on that person. Message
      content is never stored &mdash; only the promises you keep.</p>
  </div>
  <textarea id="sheetbox" rows="4"
    placeholder="What's on your mind? Tap the mic and just say it."></textarea>
  <div id="sheetmode" class="sheetmode" hidden>
    <select id="sheetmodesel">
      <option value="just-do-it">Just do it</option>
      <option value="update">Daily update &mdash; tick off what happened</option>
      <option value="dump">Organize a brain-dump</option>
      <option value="journal">Journal my day</option>
      <option value="investigate">Look into it first</option>
      <option value="draft">Draft something for me</option>
      <option value="question">Just answer the question</option>
      <option value="critic">Tear it apart &mdash; no mercy</option>
      <option value="consult">Run the frameworks on it</option>
      <option value="chat">From a chat &mdash; file what I promised</option>
    </select>
    <select id="sheetmodel" title="Bigger models think harder and use more of your plan">
      <option value="haiku">Haiku &mdash; fastest: filing, tidying, simple asks</option>
      <option value="sonnet">Sonnet &mdash; balanced: most things</option>
      <option value="opus">Opus &mdash; deepest: hard thinking</option>
      <option value="fable">Fable &mdash; the writer: drafts and prose, costs most</option>
    </select>
    <div class="attachrow">
      <label class="attachbtn">
        <input type="file" id="sheetfiles" multiple hidden
               accept=".pdf,.png,.jpg,.jpeg,.webp,.gif,.txt,.md,.csv,.docx,.xlsx,.ics">
        Attach documents
      </label>
      <span id="filelist" class="filelist"></span>
    </div>
  </div>
  <div class="sheetrow">
    <button id="mic" class="micbtn" aria-label="Dictate" aria-pressed="false">
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"
           stroke-width="2" stroke-linecap="round" aria-hidden="true">
        <rect x="9" y="2" width="6" height="12" rx="3"/>
        <path d="M5 11a7 7 0 0 0 14 0M12 18v4"/>
      </svg>
    </button>
    <span id="sheetnote" class="sheetnote"></span>
    <button id="sheetrun" class="ghostbtn" hidden>Run now</button>
    <button id="sheetsend" class="primary">Save</button>
    <button id="sheetclose" class="ghostbtn">Close <kbd>esc</kbd></button>
  </div>
</div>
"""

# ── "Talk it through": a live conversation about one task or person ────────
# The speech-bubble button on a task row (and "Talk it through" on a person)
# opens this drawer: a real, resumable Sessions conversation in the brain's
# own folder, opened with the context pack context.py builds — the task, its
# workstream, the people it names. The drawer remembers which conversation
# belongs to which task (localStorage), so reopening resumes it; the same
# conversation is on the Sessions page under "The brain".
TALKCHAT = """
<style>
.ttalk{border:0;background:transparent;color:var(--faint);padding:2px 4px;line-height:1;cursor:pointer}
.ttalk svg{width:14px;height:14px;vertical-align:-2px}
.ttalk:hover{color:var(--terra)}
.talkdrawer{position:fixed;right:14px;bottom:calc(18px + env(safe-area-inset-bottom));
  z-index:78;width:min(480px,calc(100vw - 28px));max-height:74vh;display:flex;
  flex-direction:column;background:var(--surface);border:1px solid var(--line);
  border-radius:var(--r-lg);box-shadow:var(--shadow-lift);padding:14px 16px}
.talkdrawer[hidden]{display:none}
/* the floating buttons (capture +, tour ?, ramble) share this corner — they
   duck while the conversation is open, exactly as they do while scrolling */
body.talk-open .fab,body.talk-open .ramblefab,body.talk-open .btour-btn{
  transform:translateY(160%);opacity:0;pointer-events:none}
.talkhead{display:flex;align-items:baseline;gap:10px}
.talkhead b{flex:1;font:700 var(--t-sm)/1.35 var(--sans)}
.talkfeed{flex:1;overflow-y:auto;margin:6px 0;min-height:0}
.tkb{margin:8px 0;padding:9px 12px;border-radius:var(--r-md);max-width:92%;
  font-size:var(--t-sm);line-height:1.5;white-space:pre-wrap;overflow-wrap:anywhere}
.tkb.her{background:var(--bg);border:1px solid var(--line);margin-left:auto;width:fit-content}
.tkb.claude{background:transparent;border:1px solid var(--line);border-left:3px solid var(--terra)}
.tkb.note{color:var(--dim);font-size:var(--t-xs);background:transparent;padding:4px 0;margin:4px 0}
.tksteps{color:var(--faint);font-size:var(--t-xs);margin:6px 0}
.talkrow{display:flex;gap:8px;align-items:flex-end}
.talkrow textarea{flex:1;resize:none;min-height:44px;max-height:130px;
  font:inherit;font-size:var(--t-sm);padding:10px 12px;border-radius:var(--r-md);
  border:1px solid var(--line);background:var(--bg);color:var(--text)}
.talkfoot{display:flex;gap:10px;align-items:baseline;margin-top:8px}
.talkfoot .meta{flex:1}
.talkfoot a{font-size:var(--t-xs);color:var(--dim)}
@media(max-width:760px){
  .talkdrawer{bottom:calc(132px + env(safe-area-inset-bottom));max-height:66vh}}
</style>
<aside id="talkdrawer" class="talkdrawer" hidden aria-label="Talk it through with Claude">
  <div class="talkhead"><b id="talk-title"></b>
    <button class="mini" id="talk-close">&times; close</button></div>
  <div id="talk-feed" class="talkfeed" aria-live="polite"></div>
  <div class="talkrow">
    <textarea id="talk-box" data-mic rows="2"
      placeholder="Ask, think out loud, decide&hellip;"></textarea>
    <button class="primary" id="talk-send">Send</button>
  </div>
  <div class="talkfoot"><span class="meta" id="talk-status"></span>
    <a href="sessions.html">Open on the Sessions page</a></div>
</aside>
<script>
(function(){
  var drawer = document.getElementById('talkdrawer');
  if(!drawer) return;
  var feed = document.getElementById('talk-feed');
  var box = document.getElementById('talk-box');
  var send = document.getElementById('talk-send');
  var title = document.getElementById('talk-title');
  var status = document.getElementById('talk-status');
  var cur = null, timer = null, lastRunning = false;
  var map = {};
  try { map = JSON.parse(localStorage.getItem('talk-convos') || '{}'); } catch(e){}
  function remember(){
    try { localStorage.setItem('talk-convos', JSON.stringify(map)); } catch(e){}
  }
  function jpost(path, body){
    return fetch(path, {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body || {})})
      .then(function(r){
        return r.json().catch(function(){ return {}; }).then(function(j){
          if(!r.ok || j.error) throw new Error(j.error || ('HTTP ' + r.status));
          return j;
        });
      });
  }
  function jget(path){
    return fetch(path).then(function(r){ return r.json(); });
  }
  function bubble(cls, text){
    var d = document.createElement('div');
    d.className = 'tkb ' + cls;
    d.textContent = text;
    feed.appendChild(d);
  }
  function render(events){
    feed.innerHTML = '';
    if(!events.length)
      bubble('note', 'Say what you are wondering. This conversation opens '
        + 'already knowing the task, its project and the people in it.');
    events.forEach(function(ev){
      if(ev.k === 'her') bubble('her', ev.t);
      else if(ev.k === 'claude') bubble('claude', ev.t);
      else if(ev.k === 'note') bubble('note', ev.t);
      else if(ev.k === 'work'){
        var d = document.createElement('div');
        d.className = 'tksteps';
        d.textContent = ev.label || 'worked';
        feed.appendChild(d);
      }
    });
    feed.scrollTop = feed.scrollHeight;
  }
  function refresh(){
    if(!cur) return;
    if(!cur.id){ render([]); return; }
    jget('/api/sessions/transcript?id=' + encodeURIComponent(cur.id))
      .then(function(j){ render(j.events || []); })
      .catch(function(){});
  }
  function poll(){
    if(!cur || !cur.id || drawer.hidden) return;
    clearTimeout(timer);
    jget('/api/sessions/feed?id=' + encodeURIComponent(cur.id))
      .then(function(f){
        var wait = 5000;
        if(f.running){
          var last = (f.steps && f.steps.length)
            ? ' \\u00b7 ' + f.steps[f.steps.length - 1].s : '';
          status.textContent = 'Thinking\\u2026 ' + (f.stepcount || 0)
            + ' steps' + last;
          lastRunning = true;
          wait = 1500;
        } else {
          if(lastRunning){ status.textContent = ''; refresh(); }
          lastRunning = false;
        }
        timer = setTimeout(poll, wait);
      })
      .catch(function(){ timer = setTimeout(poll, 6000); });
  }
  function open(kind, mapkey, ws, label){
    cur = {kind: kind, mapkey: mapkey, ws: ws || '', label: label,
           id: map[mapkey] || null};
    title.textContent = label;
    status.textContent = '';
    drawer.hidden = false;
    document.body.classList.add('talk-open');
    lastRunning = false;
    refresh();
    clearTimeout(timer);
    timer = setTimeout(poll, 800);
    box.focus();
  }
  function sending(on){
    send.disabled = on;
    send.textContent = on ? '\\u2026' : 'Send';
  }
  function speak(){
    var text = box.value.trim();
    if(!cur || !text) return;
    sending(true);
    var p;
    if(cur.id)
      p = jpost('/api/sessions/say', {id: cur.id, text: text});
    else if(cur.kind === 'person')
      p = jpost('/api/sessions/new', {kind: 'person', name: cur.label, text: text});
    else
      p = jpost('/api/sessions/new', {kind: 'task', ws: cur.ws,
                                      task: cur.label, text: text});
    p.then(function(j){
      if(j.id){ cur.id = j.id; map[cur.mapkey] = j.id; remember(); }
      box.value = '';
      sending(false);
      bubble('her', text);
      feed.scrollTop = feed.scrollHeight;
      status.textContent = 'Thinking\\u2026';
      lastRunning = true;
      clearTimeout(timer);
      timer = setTimeout(poll, 1200);
    }).catch(function(e){
      sending(false);
      status.textContent = e.message;
    });
  }
  send.onclick = speak;
  box.addEventListener('keydown', function(ev){
    if(ev.key === 'Enter' && !ev.shiftKey){ ev.preventDefault(); speak(); }
  });
  document.getElementById('talk-close').onclick = function(){
    drawer.hidden = true;
    document.body.classList.remove('talk-open');
    clearTimeout(timer);
  };
  document.addEventListener('click', function(ev){
    if(!ev.target.closest) return;
    var b = ev.target.closest('[data-claudetalk]');
    if(b){
      ev.preventDefault(); ev.stopPropagation();
      var t = b.dataset.claudetalk;
      open('task', 'task:' + (b.dataset.claudews || '') + '|' + t.slice(0, 80),
           b.dataset.claudews || '', t);
      return;
    }
    var pb = ev.target.closest('[data-claudetalkperson]');
    if(pb){
      ev.preventDefault(); ev.stopPropagation();
      var n = pb.dataset.claudetalkperson;
      open('person', 'person:' + n, '', n);
    }
  }, true);
})();
</script>
"""

# The page's one big script — the tab router and every button on the page.
# It lives in page/page.js so an editor can read it as JavaScript.
SCRIPT = "\n<script>\n" + _page_file("page.js") + "</script>\n"


# A deliberately separate, self-contained script. The People page's filter and
# remembered-collapse must keep working even if the big main script throws
# somewhere upstream, so they live here with no dependency on its scope.
PEOPLE_SCRIPT = """
<script>
(function(){
  function lg(k){ try { return localStorage.getItem(k); } catch(e){ return null; } }
  function ls(k, v){ try { localStorage.setItem(k, v); } catch(e){} }
  var pf = '', pq = '', pplace = '', chipLabel = '';

  // Circles start OPEN — the people are the page, and having to click into
  // every band to see anyone was the complaint. One preference sets the
  // default; each circle still remembers being opened or shut by hand.
  var circDefault = lg('circles-default') !== '0';
  document.querySelectorAll('.csection').forEach(function(d){
    var key = 'ppl-open:' + d.dataset.circle, s = lg(key);
    d.open = (s === '0') ? false : (s === '1') ? true : circDefault;
    // A filter opens circles by itself; persisting THAT would quietly undo
    // every circle she collapsed by hand. Only her own clicks are saved.
    d.addEventListener('toggle', function(){
      if(!pf && !pq && !pplace) ls(key, d.open ? '1' : '0'); });
  });
  (function(){
    var btn = document.getElementById('shopen');
    if(!btn) return;
    function label(){ btn.textContent = circDefault ? 'Collapse all' : 'Open all'; }
    label();
    btn.onclick = function(){
      circDefault = !circDefault;
      ls('circles-default', circDefault ? '1' : '0');
      document.querySelectorAll('.csection').forEach(function(d){
        ls('ppl-open:' + d.dataset.circle, circDefault ? '1' : '0');
        d.open = circDefault;
      });
      label();
      // This runs inside the People script, which is deliberately isolated
      // from the main one \u2014 so it cannot reach the main script's toast().
      btn.title = circDefault ? 'Circles start open. Click to collapse them.'
                              : 'Circles start collapsed. Click to open them.';
    };
  })();

  function match(r){
    if(pf){
      var fl = (r.dataset.flags || '').split(/\\s+/);
      if(pf === 'owe-them'){ if(fl.indexOf('owed') < 0) return false; }
      else if(pf === 'owe-me'){ if(r.dataset.ball !== 'them') return false; }
      else if(pf === 'quiet'){ if(fl.indexOf('overdue') < 0 && fl.indexOf('never') < 0) return false; }
      else if(pf === 'focus'){ if(r.dataset.focus !== '1') return false; }
    }
    // Search matches the names a person ANSWERS to, not just the one you
    // filed them under — otherwise a merged chat name is unfindable.
    if(pq && ((r.dataset.name || '') + ' ' + (r.dataset.also || ''))
              .toLowerCase().indexOf(pq) < 0) return false;
    if(pplace && (r.dataset.places || '').toLowerCase().indexOf(pplace) < 0) return false;
    return true;
  }
  function apply(){
    var filtering = !!pf || !!pq || !!pplace;
    // rows carry the match; faces cannot show why they matched
    var pw = document.getElementById('people');
    if(pw) pw.classList.toggle('filtering', filtering);
    document.querySelectorAll('#people .row.person').forEach(function(r){
      r.classList.toggle('phide', !match(r)); });
    document.querySelectorAll('#people .pgroup').forEach(function(g){
      var vis = g.querySelectorAll('.row.person:not(.phide)').length;
      g.classList.toggle('phide', filtering && vis === 0);
      if(g.classList.contains('csection')){
        if(filtering){ if(vis > 0) g.open = true; }
        else { g.open = lg('ppl-open:' + g.dataset.circle) !== '0'; }
      }
    });
    var shown = document.querySelectorAll('#people .row.person:not(.phide)').length;
    var msg = document.getElementById('pfilterempty');
    if(!msg){
      var anchor = document.querySelector('#people .pfilters');
      if(anchor){ msg = document.createElement('p'); msg.id = 'pfilterempty';
        msg.className = 'empty'; anchor.insertAdjacentElement('afterend', msg); }
    }
    if(msg){
      if(filtering && shown === 0){
        msg.textContent = pq ? ('No one matching \\u201c' + pq + '\\u201d.')
                             : ('No one under \\u201c' + (chipLabel || 'that filter') + '\\u201d right now.');
        msg.style.display = '';
      } else { msg.style.display = 'none'; }
    }
  }
  document.addEventListener('click', function(e){
    var b = e.target.closest ? e.target.closest('.pfilter') : null;
    if(!b) return;
    if(b.classList.contains('pplace')){
      // place/context chips toggle, independent of the who-owes-whom chips
      var was = b.classList.contains('active');
      document.querySelectorAll('.pplace').forEach(function(x){ x.classList.remove('active'); });
      pplace = was ? '' : (b.dataset.pplace || '').toLowerCase();
      if(!was) b.classList.add('active');
      chipLabel = b.dataset.pplace || '';
      apply();
      return;
    }
    pf = b.dataset.pfilter || '';
    chipLabel = b.textContent.toLowerCase();
    document.querySelectorAll('.pfilter:not(.pplace)').forEach(function(x){
      x.classList.toggle('active', x === b); });
    apply();
  });
  var box = document.getElementById('psearch');
  if(box) box.addEventListener('input', function(){
    pq = box.value.trim().toLowerCase(); apply(); });
  // "I'm in…" — the trip question as one control: pick a place, the
  // directory folds open on everyone there.
  var psel = document.getElementById('pplacesel');
  if(psel) psel.addEventListener('change', function(){
    pplace = (psel.value || '').toLowerCase();
    chipLabel = psel.value || '';
    apply();
  });

  // ---- circle drag-to-reorder (persists the closeness order) ----------------
  // Each circle section carries a small handle; drop reorders the sections and
  // POSTs the new order so it sticks everywhere circles are used. Server-only —
  // on the read-only file view the handles simply do nothing.
  var wrap = document.getElementById('people');
  var dragging = null;
  function sections(){ return Array.prototype.slice.call(document.querySelectorAll('#people .csection')); }
  function afterElement(y){
    var els = sections().filter(function(s){ return s !== dragging; });
    var closest = null, cd = -Infinity;
    els.forEach(function(s){ var box = s.getBoundingClientRect();
      var off = y - box.top - box.height / 2;
      if(off < 0 && off > cd){ cd = off; closest = s; } });
    return closest;
  }
  function adjSection(sec, dir){
    var s = dir < 0 ? sec.previousElementSibling : sec.nextElementSibling;
    while(s && !s.classList.contains('csection'))
      s = dir < 0 ? s.previousElementSibling : s.nextElementSibling;
    return s;
  }
  document.querySelectorAll('#people .csection').forEach(function(sec){
    var h = sec.querySelector('summary');
    if(!h) return;
    var grip = document.createElement('span');
    grip.className = 'cgrip'; grip.title = 'Drag to reorder'; grip.draggable = true;
    grip.textContent = '\\u2261';
    h.insertBefore(grip, h.firstChild);
    // Clicking the grip must not fold the section — only dragging should act.
    grip.addEventListener('click', function(e){ e.preventDefault(); e.stopPropagation(); });
    grip.addEventListener('dragstart', function(e){ dragging = sec; sec.classList.add('cdrag');
      try { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', sec.dataset.circle); } catch(x){} });
    grip.addEventListener('dragend', function(){ sec.classList.remove('cdrag'); dragging = null; persistOrder(); });
    // Touch has no drag-and-drop, so give every section up/down arrows too.
    var moves = document.createElement('span');
    moves.className = 'cmove';
    [['\\u2191', -1, 'Move up'], ['\\u2193', 1, 'Move down']].forEach(function(m){
      var btn = document.createElement('button');
      btn.className = 'cmovebtn'; btn.type = 'button'; btn.textContent = m[0];
      btn.setAttribute('aria-label', m[2]);
      btn.addEventListener('click', function(e){
        e.preventDefault(); e.stopPropagation();
        var t = adjSection(sec, m[1]);
        if(!t) return;
        if(m[1] < 0) wrap.insertBefore(sec, t); else wrap.insertBefore(t, sec);
        persistOrder();
      });
      moves.appendChild(btn);
    });
    h.appendChild(moves);
  });
  if(wrap) wrap.addEventListener('dragover', function(e){
    if(!dragging) return; e.preventDefault();
    var after = afterElement(e.clientY);
    if(after){ wrap.insertBefore(dragging, after); }
    else {                                   // dropped below all — keep it inside the circle block
      var others = sections().filter(function(s){ return s !== dragging; });
      var last = others[others.length - 1];
      if(last) wrap.insertBefore(dragging, last.nextSibling);
    }
  });
  function persistOrder(){
    var order = sections().map(function(s){ return s.dataset.circle; });
    try {
      fetch('/api/circles/reorder', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({order: order})}).catch(function(){});
    } catch(x){}
  }

  // ---- person links in task text: jump to them on the People tab -----------
  document.addEventListener('click', function(e){
    var a = e.target.closest ? e.target.closest('.plink,.darrow[data-plink]') : null;
    if(!a) return;
    e.preventDefault(); e.stopPropagation();
    location.hash = '#/people';
    setTimeout(function(){
      var rows = document.querySelectorAll('#people .row.person');
      for(var i = 0; i < rows.length; i++){
        if(rows[i].dataset.name === a.dataset.plink){
          rows[i].open = true;
          rows[i].scrollIntoView({behavior:'smooth', block:'center'});
          rows[i].classList.add('rowflash');
          (function(r){ setTimeout(function(){ r.classList.remove('rowflash'); }, 1800); })(rows[i]);
          break;
        }
      }
    }, 150);
  });

  // ---- the tour: six stops through what the brain built --------------------
  var TOUR = [
    {hash:'#/today',  sel:'.hero',     t:'Your next hour', d:'The one thing most worth doing right now, chosen from everything the brain knows. It changes as life does.'},
    {hash:'#/today',  sel:'.forecast', t:'The week ahead', d:'Whether what is due actually fits the hours you have \\u2014 honestly, before it bites.'},
    {hash:'#/today',  sel:'.qcard',    t:'Questions for you', d:'What Claude could not know from your dump. Each answer sharpens a task, a date, or a person.'},
    {hash:'#/plate',  sel:'.tiles',    t:'Your plate', d:'Every project and responsibility, ranked by what is rotting \\u2014 overdue, waiting, going cold.'},
    {hash:'#/people', sel:'.pfilters', t:'Your people', d:'Everyone you decided to keep warm, by circle, with how long it has been. Owed replies surface on Today.'},
    {hash:'#/today',  sel:null,        t:'That\\u2019s the loop', d:'Mornings on Today, work from the Plate, people kept warm. Three more pages when you need them: Rooms gives each project a workspace, the Map draws everything as one picture, and Sessions holds live Claude conversations. The ? button retakes this tour anytime. Welcome home.'}
  ];
  var tcard = null, tstep = 0, tlit = null;
  function tourCard(){
    if(tcard) return tcard;
    tcard = document.createElement('div');
    tcard.className = 'tourcard';
    tcard.innerHTML = '<p class="tour-t"></p><p class="tour-d"></p>'
      + '<div class="tour-b"><span class="tour-n"></span>'
      + '<button class="mini" id="tour-skip">Skip</button>'
      + '<button class="primary" id="tour-next">Next</button></div>';
    document.body.appendChild(tcard);
    tcard.querySelector('#tour-skip').onclick = tourEnd;
    tcard.querySelector('#tour-next').onclick = function(){ tourStep(tstep + 1); };
    return tcard;
  }
  function tourLight(el){
    if(tlit) tlit.classList.remove('tourlit');
    tlit = el;
    if(el){ el.classList.add('tourlit'); el.scrollIntoView({behavior:'smooth', block:'center'}); }
  }
  function tourEnd(){
    tourLight(null);
    if(tcard){ tcard.remove(); tcard = null; }
    try { localStorage.removeItem('tour-pending'); } catch(e){}
  }
  function tourStep(i){
    var s = TOUR[i];
    while(s && s.sel && !document.querySelector(s.sel)){ i++; s = TOUR[i]; }
    if(!s){ tourEnd(); return; }
    tstep = i;
    if(location.hash !== s.hash) location.hash = s.hash;
    setTimeout(function(){
      var el = s.sel ? document.querySelector(s.sel) : null;
      tourLight(el);
      var c = tourCard();
      c.querySelector('.tour-t').textContent = s.t;
      c.querySelector('.tour-d').textContent = s.d;
      c.querySelector('.tour-n').textContent = (i + 1) + ' / ' + TOUR.length;
      c.querySelector('#tour-next').textContent = i === TOUR.length - 1 ? 'Done' : 'Next';
    }, 200);
  }
  var wantTour = false;
  try { wantTour = localStorage.getItem('tour-pending') === '1'; } catch(e){}
  if(wantTour || location.hash === '#tour'){ setTimeout(function(){ tourStep(0); }, 400); }

  // Search every task ever written — the answer to "I know I wrote it down,
  // where is it?". Matches row names and task text, done tasks included;
  // matching rows open with the hits highlighted.
  var ts = document.getElementById('tsearch');
  if(ts) ts.addEventListener('input', function(){
    var q = ts.value.trim().toLowerCase();
    document.querySelectorAll('.view[data-view="plate"] details.row').forEach(function(r){
      if(!q){ r.classList.remove('phide'); r.open = false; return; }
      var hit = (r.dataset.name || '').toLowerCase().indexOf(q) >= 0;
      r.querySelectorAll('.ttext').forEach(function(el){
        var m = el.textContent.toLowerCase().indexOf(q) >= 0;
        el.classList.toggle('tsearchhit', m && !!q);
        if(m) hit = true;
      });
      r.classList.toggle('phide', !hit);
      r.open = hit && !!q;
    });
    // ghosts (closed / quiet folds) open themselves when they hold a match
    document.querySelectorAll('.view[data-view="plate"] details.ghost').forEach(function(g){
      if(!q) return;
      if(g.querySelector('details.row:not(.phide)')) g.open = true;
    });
    // area headings with nothing visible under them step aside too
    document.querySelectorAll('.view[data-view="plate"] h3.area').forEach(function(h){
      var any = false, n2 = h.nextElementSibling;
      while(n2 && n2.classList && n2.classList.contains('row')){
        if(!n2.classList.contains('phide')) any = true;
        n2 = n2.nextElementSibling;
      }
      h.classList.toggle('phide', !!q && !any);
    });
  });

  // Anyone asking for reduced motion gets the still drawings, not the films.
  try {
    if(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches){
      document.querySelectorAll('video.artvid').forEach(function(v){
        var img = document.createElement('img');
        img.className = v.className; img.src = v.poster;
        img.width = v.width; img.height = v.height; img.alt = '';
        v.parentNode.replaceChild(img, v);
      });
    }
  } catch(e){}
})();
</script>
"""


def repetition_report(path=None):
    """How many times does the Today tab say the same thing?

    Every point fix in this file is one block taught to check itself. Nothing
    stops the NEXT block from printing the plan again, and that is exactly how
    one train journey came to be on screen six times. So the build counts.

    It warns and never fails: a genuine double is occasionally right (the hero
    IS allowed to be the plan's task), and a build that refuses to run is
    worse than a page that repeats.
    """
    try:
        with open(path or OUT, encoding="utf-8") as f:
            doc = f.read()
    except OSError:
        return []
    m = re.search(r'<div class="view" data-view="today">(.*?)(?=<div class="view" '
                  r'data-view=|</main>)', doc, re.S)
    seg = m.group(1) if m else ""
    if not seg:
        return []
    # Visible text only — an attribute the hand never reads is not a repeat.
    seg = re.sub(r"<(script|style)\b.*?</\1>", " ", seg, flags=re.S | re.I)
    seg = re.sub(r"<template\b.*?</template>", " ", seg, flags=re.S | re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "\n", seg))
    # Cluster by MEANING, not by matching strings. Every block phrases the
    # same errand its own way — "Book train Burgundy → Paris → Angoulême" and
    # "…Thursday or Friday? Then book the train" are one job to a person — so
    # exact-signature counting sails straight past the thing it exists to
    # catch.
    #
    # The threshold is STRICTER than in_plan's, on purpose, and it is a RATIO
    # rather than a count. in_plan compares a task against a known plan line
    # and can afford to be eager. Here every line meets every other, including
    # narration — and two paragraphs about the same afternoon share "Bexley"
    # and "the country house" without being a repeat of anything. Counting shared
    # words flagged those; asking what FRACTION of the two lines is shared
    # does not, while still catching the same errand worded three ways.
    def _guard_match(toks, seed):
        shared = toks & seed
        if len(shared) < 3:
            return False
        return len(shared) / len(toks | seed) >= 0.5

    clusters = []
    for line in text.split("\n"):
        line = " ".join(line.split())
        if len(line) < 18:
            continue
        toks = _sig_tokens(line)
        if len(toks) < 3:
            continue
        for c in clusters:
            if _guard_match(toks, c["toks"]):
                c["hits"].append(line)
                break
        else:
            clusters.append({"toks": toks, "hits": [line]})
    return [(c["hits"][0], c["hits"]) for c in clusters if len(c["hits"]) > 2]


if __name__ == "__main__":
    path, n, pend = build()
    extra = f", {pend} queued ask{'s' if pend != 1 else ''}" if pend else ""
    print(f"Built {path} — {n} workstream{'s' if n != 1 else ''}{extra}")
    for key, hits in repetition_report(path):
        print(f'  ⚠ "{clip(hits[0], 58)}" appears {len(hits)}× on Today')
    # The linter: mechanical integrity checks on the files just rendered.
    # A crash in it must never block the page build.
    try:
        import check
        for prob in check.check():
            print(f"  ⚠ {prob}")
    except Exception as ex:
        print(f"  (check.py failed: {ex})")
