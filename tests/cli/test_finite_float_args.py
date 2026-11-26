"""Numeric command arguments must be finite.

Python's ``float()`` accepts ``nan`` and ``inf``, and a NaN slips past every
``<``/``>`` bounds check downstream (``aspirate nan src`` would reach the
syringe). Every parser takes floats through ``finite_float`` instead.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator

import pytest

from tricca_autopipette.commands.tap_cmd_parsers import TAPCmdParsers, finite_float


def _parsers() -> Iterator[tuple[str, argparse.ArgumentParser]]:
    pending = [
        (name, value)
        for name, value in vars(TAPCmdParsers).items()
        if isinstance(value, argparse.ArgumentParser)
    ]
    while pending:
        name, parser = pending.pop()
        yield name, parser
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                pending.extend(
                    (f"{name} {sub}", p)
                    for sub, p in action.choices.items()  # type: ignore[union-attr]
                )


def test_no_parser_takes_a_bare_float() -> None:
    bare = [
        f"{name} {action.dest}"
        for name, parser in _parsers()
        for action in parser._actions
        if action.type is float
    ]

    assert bare == []


@pytest.mark.parametrize("text", ["nan", "NaN", "inf", "-inf", "infinity"])
def test_non_finite_is_refused(text: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        finite_float(text)


@pytest.mark.parametrize(("text", "value"), [("1.5", 1.5), ("-2", -2.0), ("0", 0.0)])
def test_finite_is_accepted(text: str, value: float) -> None:
    assert finite_float(text) == pytest.approx(value)


def test_aspirate_nan_does_not_parse() -> None:
    with pytest.raises(SystemExit):
        TAPCmdParsers.parser_aspirate.parse_args(["nan", "src"])
