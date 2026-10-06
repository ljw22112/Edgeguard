"""Answer Mobius' interactive secret prompts (tools/setup.js) without a terminal.

    python scripts/_mobius_seal.py <mobius_dir> --superuser
    python scripts/_mobius_seal.py <mobius_dir> --dbpass <password>

Mobius 3 keeps superUser and dbpass in a sealed file that can only be written
through its interactive setup; this runs it in a pseudo-terminal and types the answer.
"""
import os
import pty
import select
import sys
import time


def main():
    mdir, flag = sys.argv[1], sys.argv[2]
    answer = sys.argv[3] if len(sys.argv) > 3 else ""          # empty = keep current value
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(mdir)
        os.execvp("node", ["node", "tools/setup.js", flag])
    out, sent, end = b"", False, time.time() + 30
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.5)
        if not r:
            continue
        try:
            data = os.read(fd, 4096)
        except OSError:
            break
        if not data:
            break
        out += data
        if not sent and (b">" in data or b":" in data or b"?" in data):
            time.sleep(0.3)
            os.write(fd, answer.encode() + b"\r")
            sent = True
    _, status = os.waitpid(pid, 0)
    text = out.decode(errors="ignore")
    print(text.strip().splitlines()[-1] if text.strip() else "(no output)")
    sys.exit(0 if os.WEXITSTATUS(status) == 0 else 1)


if __name__ == "__main__":
    main()
