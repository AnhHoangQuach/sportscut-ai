import argparse

from sportscut import __version__


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

    parser.parse_args(argv)
    parser.print_help()
    return 0
