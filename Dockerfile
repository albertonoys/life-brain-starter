# The brain, on a server.
#
# The image holds the RUNTIME only — no COPY of this repo. The brain is code
# and life in one git folder, so it is bind-mounted at /brain instead: the
# markdown you read on the page is the markdown on the host disk, and git on
# the host is still the undo for everything.
#
#   docker compose build
#   docker compose up -d
#
# Voice transcription is off by default because it roughly triples the image:
#
#   docker compose build --build-arg WITH_WHISPER=true
#
FROM node:22-bookworm-slim

# Node is the harder dependency (Claude Code is an npm package), so it is the
# base and Python comes from Debian. python3.11 is plenty: the brain's own
# tools are pure standard library.
#
# No zsh. morning.sh and night.sh are plain bash, which is the whole reason
# they were converted.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-venv git tzdata ca-certificates curl procps \
    && rm -rf /var/lib/apt/lists/*

# Claude Code itself. The queue button, the Sessions page and the 7am /today
# run all shell out to this.
RUN npm install -g @anthropic-ai/claude-code && npm cache clean --force

# supercronic runs the schedule as an ordinary user and logs to the container
# log, neither of which system cron does gracefully. Pinned by digest — the
# project publishes no checksum file, so this one was taken from the binary
# itself.
ARG SUPERCRONIC_VERSION=v0.2.49
ARG SUPERCRONIC_SHA256=a53ae236602c7338aba3fbaff40bda6300eae3b9fedb8261eb06cfe3724430c1
RUN curl -fsSL -o /usr/local/bin/supercronic \
        "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-amd64" \
    && echo "${SUPERCRONIC_SHA256}  /usr/local/bin/supercronic" | sha256sum -c - \
    && chmod +x /usr/local/bin/supercronic

# Debian marks its Python externally-managed, so anything pip installs goes in
# a venv. Putting it first on PATH means every plain `python3 brain/tools/...`
# in this repo — and there are many — finds it with no other change.
#
# keyring + keyrings.alt: a container has no D-Bus secret service, so without
# these email_send.py and news.py have nowhere to put a password. keyrings.alt
# gives them an encrypted file instead.
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
RUN python3 -m venv "$VIRTUAL_ENV" \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir keyring keyrings.alt

# Voice memos, transcribed on this machine and never uploaded anywhere. Off by
# default: faster-whisper and its model runtime are most of a gigabyte, and a
# brain that never gets a voice note should not carry them. ffmpeg is here for
# ffprobe, which reads how long a recording is.
ARG WITH_WHISPER=false
RUN if [ "$WITH_WHISPER" = "true" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends ffmpeg \
        && rm -rf /var/lib/apt/lists/* \
        && pip install --no-cache-dir faster-whisper ; \
    fi

# The container writes to the bind-mounted repo, so it must write as whoever
# owns it on the host — otherwise every file the brain touches turns up
# root-owned and the host user can no longer edit their own life.
#   docker compose build --build-arg UID=$(id -u) --build-arg GID=$(id -g)
ARG UID=1000
ARG GID=1000
RUN userdel -r node 2>/dev/null || true \
    && (getent group "$GID" > /dev/null || groupadd -g "$GID" brain) \
    && useradd -u "$UID" -g "$GID" -m -s /bin/bash brain
USER brain
ENV HOME=/home/brain

# git is the brain's undo, and both scheduled scripts commit. A bind-mount is
# owned by the host, which git treats as suspicious until told otherwise; the
# identity is here so an unattended 1am commit has an author.
RUN git config --global --add safe.directory /brain \
    && git config --global user.name "life-brain" \
    && git config --global user.email "brain@localhost"

WORKDIR /brain
EXPOSE 7718
CMD ["python3", "brain/tools/serve.py"]
