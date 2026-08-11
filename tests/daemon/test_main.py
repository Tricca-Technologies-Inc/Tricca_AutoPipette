"""Unit tests for the ``tapd`` entry point, ``daemon/main.py``.

Covers argument parsing, config-path resolution/validation wiring, and
``main()``'s exit-code handling for each caught exception type. ``_serve``
builds a real ``AutoPipetteService``/``ControlServer`` pair, so its tests
monkeypatch both classes with tiny in-process fakes rather than doing real
Moonraker/network I/O -- consistent with how the rest of this module's
callers (``AutoPipetteService`` gap-fill in ``test_service_*.py``) fake only
at the Moonraker boundary, here pushed one layer further out.

``_serve`` blocks on a ``asyncio.Event`` set by a SIGINT/SIGTERM handler it
registers on the running loop -- the same shutdown path a real ``tapd``
process uses. Tests exercise that real path (rather than reaching into
``_serve``'s internals) by having the fake ``ControlServer.start()`` schedule
a self-``SIGTERM`` shortly after "starting", simulating an operator
Ctrl-C. The signal handler is registered before ``start()`` runs, so there is
no race with the default disposition.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import logging
import os
import signal
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, cast

import pytest

from tricca_autopipette.core.pipette_constants import DefaultFilenames, DefaultPaths
from tricca_autopipette.daemon import main as main_module
from tricca_autopipette.daemon.control_server import DEFAULT_HOST, DEFAULT_PORT


def _base_args(**overrides: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {
        "config": None,
        "config_gantry": None,
        "config_pipette": None,
        "config_liquids": None,
        "config_locations": None,
        "log_file": "tapd.log",
        "log_level": "INFO",
        "no_connect": True,
        "local_connect": False,
        "host": DEFAULT_HOST,
        "port": DEFAULT_PORT,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestParseArguments:
    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.argv", ["tapd"])

        args = main_module.parse_arguments()

        assert args.config is None
        assert args.config_gantry is None
        assert args.config_pipette is None
        assert args.config_locations is None
        assert args.config_liquids is None
        assert args.log_file == main_module.DEFAULT_LOG_FILE
        assert args.log_level == "INFO"
        assert args.no_connect is False
        assert args.local_connect is False
        assert args.host == DEFAULT_HOST
        assert args.port == DEFAULT_PORT

    def test_config_flags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "sys.argv",
            [
                "tapd",
                "--config",
                "sys.json",
                "--config-gantry",
                "gantry.json",
                "--config-pipette",
                "pipette.json",
                "--config-locations",
                "locations.json",
                "--config-liquids",
                "liquids.json",
            ],
        )

        args = main_module.parse_arguments()

        assert args.config == "sys.json"
        assert args.config_gantry == "gantry.json"
        assert args.config_pipette == "pipette.json"
        assert args.config_locations == "locations.json"
        assert args.config_liquids == "liquids.json"

    def test_no_connect_and_local_connect_flags(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.argv", ["tapd", "--no-connect", "--local-connect"])

        args = main_module.parse_arguments()

        assert args.no_connect is True
        assert args.local_connect is True

    def test_host_port_and_log_level(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "sys.argv",
            [
                "tapd",
                "--host",
                "0.0.0.0",
                "--port",
                "9999",
                "--log-level",
                "DEBUG",
                "--log-file",
                "custom.log",
            ],
        )

        args = main_module.parse_arguments()

        assert args.host == "0.0.0.0"
        assert args.port == 9999
        assert args.log_level == "DEBUG"
        assert args.log_file == "custom.log"

    def test_rejects_an_invalid_log_level(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.argv", ["tapd", "--log-level", "NOPE"])

        with pytest.raises(SystemExit):
            main_module.parse_arguments()


class TestSetupLogging:
    def test_configures_a_file_and_stream_handler_at_the_given_level(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        captured: dict[str, Any] = {}

        def _fake_basic_config(**kwargs: Any) -> None:
            captured.update(kwargs)

        monkeypatch.setattr(logging, "basicConfig", _fake_basic_config)
        sentinel_stdout = io.StringIO()
        monkeypatch.setattr(main_module.sys, "stdout", sentinel_stdout)
        log_file = tmp_path / "tapd.log"

        main_module.setup_logging(str(log_file), logging.DEBUG)

        assert captured["level"] == logging.DEBUG
        handlers = cast("list[logging.Handler]", captured["handlers"])
        assert len(handlers) == 2
        file_handler, stream_handler = handlers
        # Rotating, not a plain FileHandler -- issue #52 meaningfully
        # increases log volume, so unbounded growth needs a cap.
        assert isinstance(file_handler, RotatingFileHandler)
        assert file_handler.baseFilename == str(log_file)
        assert file_handler.maxBytes == main_module.DEFAULT_LOG_MAX_BYTES
        assert file_handler.backupCount == main_module.DEFAULT_LOG_BACKUP_COUNT
        assert (
            cast("logging.StreamHandler[Any]", stream_handler).stream is sentinel_stdout
        )


class TestServe:
    def _drive(
        self, monkeypatch: pytest.MonkeyPatch, args: argparse.Namespace
    ) -> dict[str, Any]:
        """Run ``_serve(args)`` to completion against fakes, self-terminating.

        Returns:
            A dict with the constructed fake ``"service"`` and ``"server"``
            instances, once ``_serve`` has returned.
        """
        created: dict[str, Any] = {}

        class _FakeControlServer:
            def __init__(self, service: Any, host: str, port: int) -> None:
                self.service = service
                self.host = host
                self.port = port
                self.started = False
                self.stopped = False
                created["server"] = self

            async def start(self) -> None:
                self.started = True
                # Simulate an operator hitting Ctrl-C shortly after the
                # daemon comes up -- scheduled on the same running loop, so
                # there's no cross-thread race with the signal handlers
                # `_serve` registers before calling `start()`.
                asyncio.get_running_loop().call_later(
                    0.02, os.kill, os.getpid(), signal.SIGTERM
                )

            async def stop(self) -> None:
                self.stopped = True

        class _FakeAutoPipetteService:
            def __init__(self, **kwargs: Any) -> None:
                self.kwargs = kwargs
                created["service"] = self

        monkeypatch.setattr(main_module, "ControlServer", _FakeControlServer)
        monkeypatch.setattr(main_module, "AutoPipetteService", _FakeAutoPipetteService)

        asyncio.run(main_module._serve(args))
        return created

    def test_starts_and_cleanly_stops_the_control_server(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        created = self._drive(monkeypatch, _base_args())

        assert created["server"].started is True
        assert created["server"].stopped is True

    def test_binds_the_requested_host_and_port(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        created = self._drive(monkeypatch, _base_args(host="0.0.0.0", port=1234))

        assert created["server"].host == "0.0.0.0"
        assert created["server"].port == 1234

    def test_default_config_paths_resolve_to_default_filenames(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        created = self._drive(monkeypatch, _base_args())

        kwargs = created["service"].kwargs
        assert kwargs["config_system"] == (
            DefaultPaths.DIR_CONFIG_SYSTEM / DefaultFilenames.CONFIG_SYSTEM
        )
        assert kwargs["config_gantry"] is None
        assert kwargs["config_pipette"] is None
        assert kwargs["config_locations"] is None
        assert kwargs["config_liquids"] is None

    def test_explicit_config_paths_resolve_under_their_config_dirs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        created = self._drive(
            monkeypatch,
            _base_args(
                config="sys.json",
                config_gantry="gantry.json",
                config_pipette="pipette.json",
                config_locations="locations.json",
                config_liquids="liquids.json",
            ),
        )

        kwargs = created["service"].kwargs
        assert kwargs["config_system"] == DefaultPaths.DIR_CONFIG_SYSTEM / "sys.json"
        assert kwargs["config_gantry"] == DefaultPaths.DIR_CONFIG_GANTRY / "gantry.json"
        assert (
            kwargs["config_pipette"] == DefaultPaths.DIR_CONFIG_PIPETTE / "pipette.json"
        )
        assert (
            kwargs["config_locations"]
            == DefaultPaths.DIR_CONFIG_LOCATIONS / "locations.json"
        )
        assert (
            kwargs["config_liquids"] == DefaultPaths.DIR_CONFIG_LIQUIDS / "liquids.json"
        )

    def test_no_connect_flag_disables_the_websocket_connection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        created = self._drive(monkeypatch, _base_args(no_connect=True))

        assert created["service"].kwargs["connect_websocket"] is False

    def test_omitting_no_connect_enables_the_websocket_connection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        created = self._drive(monkeypatch, _base_args(no_connect=False))

        assert created["service"].kwargs["connect_websocket"] is True

    def test_local_connect_flag_is_forwarded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        created = self._drive(monkeypatch, _base_args(local_connect=True))

        assert created["service"].kwargs["connect_local_websocket"] is True


class TestMain:
    def _patch_common(
        self,
        monkeypatch: pytest.MonkeyPatch,
        args: argparse.Namespace,
        *,
        validate_error: Exception | None = None,
        serve_error: BaseException | None = None,
    ) -> dict[str, Any]:
        calls: dict[str, Any] = {}

        monkeypatch.setattr(main_module, "parse_arguments", lambda: args)

        def _fake_setup_logging(log_file: str, level: int) -> None:
            calls["setup_logging"] = (log_file, level)

        monkeypatch.setattr(main_module, "setup_logging", _fake_setup_logging)

        def _fake_validate(**kwargs: Any) -> None:
            calls["validate_config_files"] = kwargs
            if validate_error is not None:
                raise validate_error

        monkeypatch.setattr(main_module, "validate_config_files", _fake_validate)

        def _fake_asyncio_run(coro: Any) -> None:
            coro.close()  # avoid an "never awaited" warning
            calls["asyncio_run_called"] = True
            if serve_error is not None:
                raise serve_error

        monkeypatch.setattr(main_module.asyncio, "run", _fake_asyncio_run)
        return calls

    def test_success_path_returns_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        args = _base_args()
        calls = self._patch_common(monkeypatch, args)

        result = main_module.main()

        assert result == 0
        assert calls["asyncio_run_called"] is True
        assert calls["setup_logging"] == (args.log_file, logging.INFO)
        assert calls["validate_config_files"] == {
            "config_system": args.config,
            "config_gantry": args.config_gantry,
            "config_pipette": args.config_pipette,
            "config_locations": args.config_locations,
            "config_liquids": args.config_liquids,
        }

    def test_file_not_found_error_returns_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        args = _base_args()
        self._patch_common(
            monkeypatch, args, validate_error=FileNotFoundError("missing.json")
        )

        assert main_module.main() == 1

    def test_value_error_returns_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        args = _base_args()
        self._patch_common(monkeypatch, args, validate_error=ValueError("bad file"))

        assert main_module.main() == 1

    def test_keyboard_interrupt_returns_130(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        args = _base_args()
        self._patch_common(monkeypatch, args, serve_error=KeyboardInterrupt())

        assert main_module.main() == 130

    def test_unexpected_exception_returns_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        args = _base_args()
        self._patch_common(monkeypatch, args, serve_error=RuntimeError("boom"))

        assert main_module.main() == 1

    def test_log_level_string_is_uppercased_before_lookup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        args = _base_args(log_level="debug")
        calls = self._patch_common(monkeypatch, args)

        assert main_module.main() == 0

        assert calls["setup_logging"] == (args.log_file, logging.DEBUG)
