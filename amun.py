"""Repository-local entrypoint for the AMUN CLI.

Use ``python amun.py ...`` without installing a package. Installed launchers can
point at ``cli.main:main`` and expose the shorter ``amun ...`` contract used by
AMUN Studio.
"""

from cli.main import main


if __name__ == "__main__":
    raise SystemExit(main())
