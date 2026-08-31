# Deploying the brain as a Portainer stack

The one thing to understand before you start: **the brain folder has to exist
on the server as a real directory, and it is not the same thing as the copy
Portainer clones.**

Nothing is copied into the image. The image is only a runtime — Python, git,
Node, Claude Code — and the brain itself is bind-mounted from the host at
`/brain`. So the markdown the page serves is the markdown in a folder you can
`cd` into, edit, and run `git log` on. That is deliberate: it is what makes the
host's git history the undo for everything the brain does.

Docker resolves a bind mount **on the host**. Portainer clones a git stack
into its own `/data/compose/<id>`, which normally lives in a Portainer-managed
volume with no host path at all. A relative `.` there points at nothing, and
Docker's response to a bind source that does not exist is to create an empty
directory and carry on. You would get a running page, backed by an empty
brain, with no error anywhere. Hence `BRAIN_DIR`, and hence: make it absolute.

## 1. Decide where the brain lives

You do not have to clone anything. Point `BRAIN_DIR` at a folder and the page
container sorts it out on first start:

| What is at `BRAIN_DIR` | What happens |
|---|---|
| Nothing, or an empty folder | It clones one in |
| An existing brain | It uses it, untouched |
| Anything else | It refuses to start, and lists what it found |

That last row is deliberate. A folder with your things in it is not ours to
write into, and a half-overwritten one would be worse than a failed deploy.

So all you need is the path:

```
sudo mkdir -p /srv/life-brain
```

Ownership sorts itself out: the container starts as root, takes the folder if
it is empty or root-owned, and drops to the unprivileged user before running
anything. A folder that belongs to a real user, or has things in it that are
not a brain, is refused rather than written into.

Any path works — `/srv/life-brain` is just a habit. What matters is that it is
yours to write to, and that it is somewhere you would think to back up, because
after this it holds your whole life-admin history.

Cloning it yourself still works if you prefer, and is the way to start from an
existing brain:

```
sudo git clone https://github.com/albertonoys/life-brain-starter /srv/life-brain
sudo chown -R $(id -u):$(id -g) /srv/life-brain
```

## 2. Add the stack

In Portainer: **Stacks → Add stack → Repository**.

| Field | Value |
|---|---|
| Repository URL | `https://github.com/albertonoys/life-brain-starter` |
| Reference | `refs/heads/master` |
| Compose path | `docker-compose.yml` |

Portainer will clone the repo itself, build the image from the `Dockerfile`,
and start both containers. Its clone is used only to read the compose file and
build the image — the running brain is the folder from step 1.

## 3. Environment variables

Add these under **Environment variables** on the same page. There is no `.env`
file in a Portainer stack; this is where those values go instead.

| Name | Example | Why |
|---|---|---|
| `BRAIN_DIR` | `/srv/life-brain` | The folder from step 1. **Absolute, and the one that must be right.** Left unset, the stack silently runs against an empty scratch directory inside Portainer's own `/data/compose/<id>`. |
| `BRAIN_REPO` | your fork's URL | Only used when cloning into an empty folder. Defaults to this repo. |
| `BRAIN_REF` | `master` | The branch to clone. |
| `BRAIN_ALLOWED_HOSTS` | `192.168.1.50,brainbox.local` | Every name you will open the page under. Anything else is refused. |
| `TZ` | `Europe/Madrid` | The 7am plan and the 1am night shift are local time. |
| `UID` | `1000` | Run `id -u` on the server. Files the brain writes are owned by this. |
| `GID` | `1000` | `id -g`. |
| `BRAIN_PORT` | `7718` | The port on the server. |
| `WITH_WHISPER` | `false` | `true` builds in voice transcription — about three times the image. |

`UID` and `GID` are the ones people skip. Get them wrong and every file the
brain writes belongs to the wrong user, and you can no longer edit your own
life from a normal shell.

**On `UID=0`.** If you read those numbers off a root shell you will get `0`,
and the build accepts it — root is a legitimate answer, and the image handles
it. But then the brain writes into `/srv/life-brain` as root, and editing your
own notes from an ordinary shell stops working. Prefer the numbers of the user
who owns that folder:

```
stat -c '%u %g' /srv/life-brain
```

## 4. Sign in to Claude, once

The containers come up before Claude Code has a login, so the page works and
the AI parts do not. Over SSH:

```
docker exec -it life-brain claude
```

Follow the prompt. The credentials land in the `claude-auth` volume and survive
restarts and redeploys — you do this once, not once per deploy.

Then the smoke test, which uses no network and no model:

```
docker exec life-brain python3 brain/tools/selftest.py
```

## What to expect afterwards

- **Two containers**, `life-brain` and `life-brain-cron`. The second one looks
  idle because it is: it wakes at 07:00 and 01:00. Both scripts write their own
  logs — `brain/.morning.log` and `brain/.night.log`, in the folder from step 1,
  not in Portainer's log view.
- **The night shift does nothing** until `night.enabled` is set in
  `brain/config.json`. That is the default and it is intentional.
- **The brain commits to itself.** The scheduled runs `git add -A && git commit`
  in `/srv/life-brain` before and after their work, and push if a remote is set.
  So that folder accumulates real history — treat it as a live repo, not a
  deployment artifact. Pull into it by hand, never with `git reset --hard`.
- **Redeploying the stack does not touch it.** Portainer re-clones its own copy
  and rebuilds the image; your brain folder is untouched, which is the whole
  point of keeping the two separate.

## If you would rather not let Portainer build

Build the image yourself over SSH and give Portainer a stack that only runs it:

```
cd /srv/life-brain
docker build -t life-brain:latest --build-arg UID=$(id -u) --build-arg GID=$(id -g) .
```

Then use **Add stack → Web editor**, paste `docker-compose.yml`, and delete the
`build:` block from the pasted copy — leaving `image: life-brain:latest`. Same
environment variables as above. The trade is that image updates become a manual
`docker build` instead of a redeploy.
