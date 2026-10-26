"""Compatibility entrypoint for authenticated protected-main fixture verification."""

from pathlib import Path
import runpy

from lava.builds.fixture_toolchain import BUILDKIT_VERSION as BUILDKIT_VERSION
from lava.builds.fixture_toolchain import FIXTURE_SHA256 as FIXTURE_SHA256
from lava.builds.fixture_toolchain import RAILPACK_VERSION as RAILPACK_VERSION
from lava.builds.fixture_toolchain import fixture_digest as fixture_digest


def main() -> None:
    runpy.run_path(
        str(Path(__file__).with_name("verify_executor_fixture_builds.py")),
        run_name="__main__",
    )


if __name__ == "__main__":
    main()
