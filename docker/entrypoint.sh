#!/bin/sh
# Make sure /brain actually holds a brain before anything tries to run one.
#
# The brain is bind-mounted from the host rather than baked into the image,
# because code and life live in the same git folder here: your notes and
# serve.py are the same repo, and the commits the scheduled runs make around
# their work are the undo for everything. That only means something if the
# folder is somewhere you can reach — edit, git log, back up.
#
# The cost used to be a manual clone before the first deploy, and a bind mount
# pointed at the wrong path fails in the worst possible way: Docker creates an
# empty directory and everything starts happily against nothing. So:
#
#   already a brain  -> use it, touch nothing
#   empty            -> clone one into it
#   something else   -> refuse, and say what is there
#
# The last case is the important one. Whatever is in that folder, it is not
# ours to write into.

set -eu

BRAIN=/brain
MARKER="$BRAIN/brain/tools/serve.py"
REPO="${BRAIN_REPO:-https://github.com/albertonoys/life-brain-starter}"
REF="${BRAIN_REF:-master}"

if [ -f "$MARKER" ]; then
    :                                   # a brain is already here
elif [ -z "$(ls -A "$BRAIN" 2>/dev/null)" ]; then
    # Empty. Only the service that was told to bootstrap does the cloning —
    # both containers start at once, and two clones into one directory is a
    # race with no winner. The other one waits for the result.
    if [ "${BRAIN_BOOTSTRAP:-0}" = "1" ]; then
        echo "  /brain is empty — cloning $REPO ($REF) into it."
        git clone --branch "$REF" "$REPO" "$BRAIN"
        echo "  Cloned. Your brain lives on the host at whatever BRAIN_DIR points to."
    else
        echo "  /brain is empty; waiting for the page container to clone it."
        i=0
        while [ ! -f "$MARKER" ] && [ "$i" -lt 120 ]; do
            sleep 2
            i=$((i + 2))
        done
        if [ ! -f "$MARKER" ]; then
            echo "  Gave up after two minutes. Check the 'brain' container's log." >&2
            exit 1
        fi
    fi
else
    echo "  BRAIN_DIR points at a folder that is not a brain and is not empty." >&2
    echo "  Refusing to write into it. It currently holds:" >&2
    ls -A "$BRAIN" | head -10 | sed 's/^/    /' >&2
    echo "  Point BRAIN_DIR at an empty folder, or at an existing brain." >&2
    exit 1
fi

exec "$@"
