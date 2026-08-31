#!/bin/sh
# Make sure /brain holds a brain, owned by the right user, before anything
# tries to run one.
#
# The brain is bind-mounted from the host rather than baked into the image,
# because code and life live in the same git folder here: your notes and
# serve.py are the same repo, and the commits the scheduled runs make around
# their work are the undo for everything. That only means something if the
# folder is somewhere you can reach — edit, git log, back up.
#
# The cost is that three things have to agree, set in three different places:
# the folder on the host, the UID the image was built with, and BRAIN_DIR in
# the stack. Nothing keeps them in step, and every way they can disagree used
# to fail obscurely — a bind mount pointed nowhere becomes an empty directory
# that everything starts happily against, and one owned by root becomes a git
# error about .git that names neither the user nor the folder.
#
# So this runs as root, settles all of it, and only then becomes the real user:
#
#   already a brain, ours       -> use it
#   already a brain, root's     -> take ownership, say so
#   already a brain, someone's  -> refuse
#   empty                       -> take ownership, clone into it
#   anything else               -> refuse, and list what is there
#
# Root is PID 1 for the few lines above the exec and not one line further.

set -eu

BRAIN=/brain
MARKER="$BRAIN/brain/tools/serve.py"
UID_T="${BRAIN_UID:-1000}"
GID_T="${BRAIN_GID:-1000}"
REPO="${BRAIN_REPO:-https://github.com/albertonoys/life-brain-starter}"
REF="${BRAIN_REF:-master}"

listing() {
    echo "  It currently holds:" >&2
    ls -A "$BRAIN" 2>/dev/null | head -10 | sed 's/^/    /' >&2
    echo "  Point BRAIN_DIR at an empty folder, or at a brain you own." >&2
}

# Two different problems, and being told the wrong one costs an afternoon.
refuse_owner() {
    echo "  /brain is a brain, but not one this container may write to." >&2
    echo "  It is owned by uid $1, and this container runs as $UID_T." >&2
    listing
    exit 1
}

refuse_content() {
    echo "  /brain has things in it, and none of them are a brain." >&2
    echo "  Refusing to write into it." >&2
    listing
    exit 1
}

mkdir -p "$BRAIN"
OWNER="$(stat -c '%u' "$BRAIN" 2>/dev/null || echo 0)"

if [ -f "$MARKER" ]; then
    if [ "$OWNER" != "$UID_T" ]; then
        # root-owned is what Docker leaves behind when it creates a missing
        # bind source, and what a container built as root writes. Adopting it
        # is right. Any other user is a person, and their folder is theirs.
        if [ "$OWNER" = "0" ]; then
            echo "  /brain is root-owned — taking ownership as $UID_T:$GID_T."
            chown -R "$UID_T:$GID_T" "$BRAIN"
        else
            refuse_owner "$OWNER"
        fi
    fi
elif [ -z "$(ls -A "$BRAIN" 2>/dev/null)" ]; then
    chown "$UID_T:$GID_T" "$BRAIN"
    # Both containers start at once, and two clones into one directory is a
    # race with no winner — so exactly one is allowed to do it, and the other
    # waits for the result.
    if [ "${BRAIN_BOOTSTRAP:-0}" = "1" ]; then
        echo "  /brain is empty — cloning $REPO ($REF) into it."
        gosu "$UID_T:$GID_T" git clone --branch "$REF" "$REPO" "$BRAIN"
        echo "  Cloned. It lives on the host, at whatever BRAIN_DIR points at."
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
    refuse_content
fi

exec gosu "$UID_T:$GID_T" "$@"
