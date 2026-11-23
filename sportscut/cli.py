import argparse

from sportscut import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sportscut",
        description="Find highlights in sports videos and export clips.",
    )
    parser.add_argument("--version", action="version", version=f"sportscut {__version__}")

    parser.parse_args(argv)
    parser.print_help()
    return 0
