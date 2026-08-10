"""``twin-runtime`` entrypoint — durable cognitive background process."""

from __future__ import annotations

import argparse
import logging
import sys


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="twin-runtime",
        description="Durable cognitive runtime (queue + workers + scheduler)",
    )
    parser.add_argument("--home", default=None)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--vault", default=None)
    parser.add_argument("--lease", type=int, default=60)
    parser.add_argument("--schedule-interval", type=float, default=30.0)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument(
        "--no-live", action="store_true",
        help="disable live processing panel (logs only)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    from twin.interfaces import ux
    from twin.interfaces.runtime.service import TwinRuntime
    from twin.workspace import Workspace

    ws = Workspace(args.home)
    rt = TwinRuntime(
        ws.store, ws.cfg, ws.embedder,
        workers=args.workers,
        vault_id=args.vault,
        lease_seconds=args.lease,
        schedule_interval=args.schedule_interval,
        offline=args.offline,
    )
    ux.run_runtime_with_live(rt, live=not args.no_live and not args.verbose)


if __name__ == "__main__":
    main(sys.argv[1:])
