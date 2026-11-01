from __future__ import annotations

import re
import sys


print('(gdb)')
for line in sys.stdin:
    line = line.strip()
    match = re.match(r"(\d+)(.*)", line)
    if not match:
        continue
    token, command = match.groups()
    if "info os processes" in command:
        print('~"  42 Example Game\\n  7 Home Menu\\n"')
        print(f"{token}^done")
    elif command.startswith("-data-read-memory-bytes"):
        size = int(command.rsplit(" ", 1)[1])
        contents = bytes(range(1, size + 1)).hex()
        print(f'{token}^done,memory=[{{begin="0x08000000",offset="0x0",end="0x08000004",contents="{contents}"}}]')
    elif command.startswith("-gdb-exit"):
        print(f"{token}^exit")
        sys.stdout.flush()
        break
    else:
        print(f"{token}^done")
    sys.stdout.flush()

