"""Fixed fixture-only build entrypoint launched by the trusted executor."""

import argparse
from pathlib import Path

from lava.builds.fixture_toolchain import FIXTURE_SHA256, build_fixture


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--fixture", choices=tuple(FIXTURE_SHA256), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build_fixture(args.root, args.commit, args.fixture, args.output)


if __name__ == "__main__":
    main()
