"""Store a secret in the macOS Keychain without putting it on a command line.

`security add-generic-password -w SECRET` puts the secret in the process's
arguments, where any process on the Mac can read it with `ps` while it runs.
`security -i` reads its commands from stdin instead, so the secret only ever
travels through a pipe. One helper so every tool that stores a token does it
the same way.
"""

import subprocess


def _quote(s):
    # security's interactive parser takes double-quoted words with backslash
    # escapes; checked by round-trip on quotes, backslashes, $ and accents.
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def set_password(service, account, value):
    """Add or update (-U) a generic password. Raises CalledProcessError on
    failure, like the `check=True` calls it replaces."""
    value = str(value)
    if "\n" in value or "\r" in value or "\x00" in value:
        # a line break would end the command and run the rest as another one
        raise ValueError("a secret cannot contain a line break")
    cmd = (f"add-generic-password -U -s {_quote(service)} "
           f"-a {_quote(account)} -w {_quote(value)}\n")
    r = subprocess.run(["security", "-i"], input=cmd, text=True,
                       capture_output=True)
    # `security -i` exits 0 even when a command inside it fails, so its
    # complaint on stderr is the only signal.
    if r.returncode != 0 or r.stderr.strip():
        raise subprocess.CalledProcessError(
            r.returncode or 1, ["security", "-i", "add-generic-password"],
            output=r.stdout, stderr=r.stderr)
