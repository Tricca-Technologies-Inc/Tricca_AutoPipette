"""Unit tests for ``core/gcode_buffer.py``'s ``GCodeBuffer``."""

from __future__ import annotations

from tricca_autopipette.core.gcode_buffer import GCodeBuffer


class TestAddAndGetCommands:
    def test_get_commands_returns_added_commands_in_order(self) -> None:
        buffer = GCodeBuffer()
        buffer.add("G28\n")
        buffer.add("G1 X10 Y10 F5000\n")

        assert buffer.get_commands() == ["G28\n", "G1 X10 Y10 F5000\n"]

    def test_get_commands_clears_the_buffer(self) -> None:
        buffer = GCodeBuffer()
        buffer.add("G28\n")
        buffer.get_commands()

        assert buffer.get_commands() == []

    def test_empty_buffer_returns_empty_list(self) -> None:
        assert GCodeBuffer().get_commands() == []


class TestHeader:
    def test_get_header_returns_added_lines_in_order(self) -> None:
        buffer = GCodeBuffer()
        buffer.add_header("; a\n")
        buffer.add_header("; b\n")

        assert buffer.get_header() == ["; a\n", "; b\n"]

    def test_get_header_does_not_clear(self) -> None:
        buffer = GCodeBuffer()
        buffer.add_header("; a\n")
        buffer.get_header()

        assert buffer.get_header() == ["; a\n"]


class TestClearing:
    def test_clear_commands_empties_only_commands(self) -> None:
        buffer = GCodeBuffer()
        buffer.add("G28\n")
        buffer.add_header("; a\n")

        buffer.clear_commands()

        assert buffer.peek_commands() == []
        assert buffer.get_header() == ["; a\n"]

    def test_clear_header_empties_only_header(self) -> None:
        buffer = GCodeBuffer()
        buffer.add("G28\n")
        buffer.add_header("; a\n")

        buffer.clear_header()

        assert buffer.get_header() == []
        assert buffer.peek_commands() == ["G28\n"]

    def test_clear_all_empties_both(self) -> None:
        buffer = GCodeBuffer()
        buffer.add("G28\n")
        buffer.add_header("; a\n")

        buffer.clear_all()

        assert buffer.get_header() == []
        assert buffer.peek_commands() == []


class TestHasCommandsAndCount:
    def test_has_commands_false_when_empty(self) -> None:
        assert GCodeBuffer().has_commands() is False

    def test_has_commands_true_after_add(self) -> None:
        buffer = GCodeBuffer()
        buffer.add("G28\n")
        assert buffer.has_commands() is True

    def test_command_count_reflects_buffer_size(self) -> None:
        buffer = GCodeBuffer()
        buffer.add("G28\n")
        buffer.add("G1 X10\n")
        assert buffer.command_count() == 2

    def test_command_count_zero_when_empty(self) -> None:
        assert GCodeBuffer().command_count() == 0


class TestPeekCommands:
    def test_peek_does_not_clear(self) -> None:
        buffer = GCodeBuffer()
        buffer.add("G28\n")

        peeked = buffer.peek_commands()

        assert peeked == ["G28\n"]
        assert buffer.get_commands() == ["G28\n"]

    def test_peek_returns_a_copy(self) -> None:
        buffer = GCodeBuffer()
        buffer.add("G28\n")

        peeked = buffer.peek_commands()
        peeked.append("G1 X10\n")

        assert buffer.peek_commands() == ["G28\n"]


class TestBuildHeaderFromConfig:
    def test_builds_a_formatted_header(self) -> None:
        buffer = GCodeBuffer()
        sections = {
            "SPEED": {"SPEED_XY": "5000", "SPEED_Z": "2000"},
            "SERVO": {"ANGLE_RETRACT": "160"},
        }

        buffer.build_header_from_config("auto.conf", sections)

        header = buffer.get_header()
        assert header[0] == "; Configuration: auto.conf\n"
        assert header[1] == "; Settings:\n"
        assert "; [SPEED]\n" in header
        assert ";\t SPEED_XY = 5000\n" in header
        assert ";\t SPEED_Z = 2000\n" in header
        assert "; [SERVO]\n" in header
        assert ";\t ANGLE_RETRACT = 160\n" in header

    def test_replaces_rather_than_appends_to_existing_header(self) -> None:
        buffer = GCodeBuffer()
        buffer.add_header("; stale\n")

        buffer.build_header_from_config("auto.conf", {})

        assert "; stale\n" not in buffer.get_header()

    def test_empty_sections_still_produces_the_preamble(self) -> None:
        buffer = GCodeBuffer()

        buffer.build_header_from_config("auto.conf", {})

        assert buffer.get_header() == [
            "; Configuration: auto.conf\n",
            "; Settings:\n",
        ]


class TestDunderMethods:
    def test_len_reflects_command_count(self) -> None:
        buffer = GCodeBuffer()
        buffer.add("G28\n")
        assert len(buffer) == 1

    def test_bool_false_when_empty(self) -> None:
        assert bool(GCodeBuffer()) is False

    def test_bool_true_when_commands_present(self) -> None:
        buffer = GCodeBuffer()
        buffer.add("G28\n")
        assert bool(buffer) is True

    def test_repr_shows_command_and_header_counts(self) -> None:
        buffer = GCodeBuffer()
        buffer.add("G28\n")
        buffer.add_header("; a\n")

        assert repr(buffer) == "GCodeBuffer(commands=1, header=1)"

    def test_repr_on_empty_buffer(self) -> None:
        assert repr(GCodeBuffer()) == "GCodeBuffer(commands=0, header=0)"
