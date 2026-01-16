#!/usr/bin/env python3
"""Holds class and methods for running Tricca AutoPipette Shell."""

import logging
import sys

from cmd2 import Cmd2ArgumentParser
from tap_shell import TriccaAutoPipetteShell


def main() -> None:
    """Entry point for the program."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(module)s] %(levelname)s: %(message)s",
        handlers=[
            logging.FileHandler("app.log"),
        ],
    )
    argparser = Cmd2ArgumentParser()
    argparser.add_argument("--conf", type=str, help="optional config file")
    args = argparser.parse_args()
    # Remove other processed parser commands to avoid cmd2 from using them
    TriccaAutoPipetteShell(conf_autopipette=args.conf).cmdloop()
    sys.exit(0)


if __name__ == "__main__":
    main()
