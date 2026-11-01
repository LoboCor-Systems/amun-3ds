from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .server import HubPaths, HubServer


def main() -> int:
    parser = argparse.ArgumentParser(description="AMUN optional LAN Hub")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=43831)
    parser.add_argument("--data", type=Path, default=Path.home() / ".amun-hub")
    args = parser.parse_args()

    async def run() -> None:
        paths = HubPaths(args.data / "state.json", args.data / "events.jsonl", args.data / "backups")
        server = HubServer(paths, host=args.host, port=args.port)
        await server.start()
        print(f"AMUN Hub listening on {args.host}:{server.port}")
        try:
            await server.serve_forever()
        finally:
            await server.close()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

