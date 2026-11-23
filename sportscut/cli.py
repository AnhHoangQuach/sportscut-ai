import argparse
import json
import sys

from sportscut import __version__
from sportscut.detect import find_highlights
from sportscut.media import MediaError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sportscut",
        description="Find and export highlights from sports videos.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"sportscut {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")
    detect_parser = subparsers.add_parser("detect", help="detect highlight segments")
    detect_parser.add_argument("video")
    detect_parser.add_argument("--top", type=int, default=10)
    detect_parser.add_argument("--min-len", type=float, default=10)
    detect_parser.add_argument("--max-len", type=float, default=30)
    detect_parser.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    try:
        segments = find_highlights(
            args.video, top=args.top, min_len=args.min_len, max_len=args.max_len
        )
    except (MediaError, ValueError) as exc:
        print(f"sportscut: error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps([segment.to_dict() for segment in segments]))
    else:
        for segment in segments:
            print(
                f"{segment.start:.1f}\t{segment.end:.1f}\t"
                f"{segment.score:.2f}\t{segment.reason}"
            )
    return 0
