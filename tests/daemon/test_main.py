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

from tricca_autopipette.core.pipette_constants import (
    DefaultFilenames,
    DefaultPaths,
    LocalConfigRoots,
)
from tricca_autopipette.daemon import main as main_module
from tricca_autopipette.daemon.control_server import DEFAULT_HOST, DEFAULT_PORT


def _base_args(**overrides: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {
        "config": None,
        "init_local_config": None,
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
        assert args.init_local_config is None
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

    def test_init_local_config_bare_flag_defaults_to_default_system(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.argv", ["tapd", "--init-local-config"])

        args = main_module.parse_arguments()

        assert args.init_local_config == "default_system"

    def test_init_local_config_with_a_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.argv", ["tapd", "--init-local-config", "murphy_100"])

        args = main_module.parse_arguments()

        assert args.init_local_config == "murphy_100"

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
        self,
        monkeypatch: pytest.MonkeyPatch,
        args: argparse.Namespace,
        system_filename: str = "default_system.json",
    ) -> dict[str, Any]:
        """Run ``_serve(args, system_filename)`` to completion against fakes.

        Self-terminating.

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

        asyncio.run(main_module._serve(args, system_filename))
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
        created = self._drive(
            monkeypatch, _base_args(), system_filename=DefaultFilenames.CONFIG_SYSTEM
        )

        kwargs = created["service"].kwargs
        assert kwargs["config_system"] == (
            DefaultPaths.DIR_LOCAL_SYSTEM / DefaultFilenames.CONFIG_SYSTEM
        )
        assert kwargs["config_gantry"] is None
        assert kwargs["config_pipette"] is None
        assert kwargs["config_locations"] is None
        assert kwargs["config_liquids"] is None

    def test_explicit_config_paths_resolve_under_their_config_dirs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # `system_filename` stands in for what `resolve_system_config` (a
        # separate, directly-tested function -- see `TestResolveSystemConfig`)
        # would have resolved `--config sys.json` to; `_serve` itself no
        # longer reads `args.config` at all.
        created = self._drive(
            monkeypatch,
            _base_args(
                config_gantry="gantry.json",
                config_pipette="pipette.json",
                config_locations="locations.json",
                config_liquids="liquids.json",
            ),
            system_filename="sys.json",
        )

        kwargs = created["service"].kwargs
        assert kwargs["config_system"] == DefaultPaths.DIR_LOCAL_SYSTEM / "sys.json"
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
        resolve_error: Exception | None = None,
        validate_error: Exception | None = None,
        serve_error: BaseException | None = None,
    ) -> dict[str, Any]:
        calls: dict[str, Any] = {}

        monkeypatch.setattr(main_module, "parse_arguments", lambda: args)

        def _fake_setup_logging(log_file: str, level: int) -> None:
            calls["setup_logging"] = (log_file, level)

        monkeypatch.setattr(main_module, "setup_logging", _fake_setup_logging)

        def _fake_resolve(explicit: str | None) -> str:
            calls["resolve_system_config"] = explicit
            if resolve_error is not None:
                raise resolve_error
            return "default_system.json"

        monkeypatch.setattr(main_module, "resolve_system_config", _fake_resolve)

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
        assert calls["resolve_system_config"] == args.config
        assert calls["validate_config_files"] == {
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

    def test_resolve_system_config_error_returns_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        args = _base_args()
        self._patch_common(
            monkeypatch, args, resolve_error=ValueError("ambiguous configs")
        )

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

    def test_init_local_config_flag_bypasses_serve_and_returns_zero(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        args = _base_args(init_local_config="murphy_100")
        calls = self._patch_common(monkeypatch, args)

        def _fake_init(name: str) -> Path:
            calls["init_local_config"] = name
            return tmp_path / f"{name}.json"

        monkeypatch.setattr(main_module, "init_local_config", _fake_init)

        assert main_module.main() == 0
        assert calls["init_local_config"] == "murphy_100"
        # The daemon never actually starts on this path.
        assert "resolve_system_config" not in calls
        assert "asyncio_run_called" not in calls

    def test_init_local_config_error_returns_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        args = _base_args(init_local_config="murphy_100")
        self._patch_common(monkeypatch, args)

        def _fake_init(name: str) -> Path:
            raise FileExistsError(f"{name}.json already exists")

        monkeypatch.setattr(main_module, "init_local_config", _fake_init)

        assert main_module.main() == 1


@pytest.fixture
def config_roots(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Path]:
    """Redirect the shared/local system-config dirs into an isolated tree.

    Returns:
        Mapping with ``"shared"`` and ``"local"`` directories, both already
        created and empty, plus a real ``default_system.json`` template
        already written into ``"shared"``.
    """
    shared = tmp_path / "shared_system"
    local = tmp_path / "local_system"
    shared.mkdir()
    local.mkdir()
    monkeypatch.setattr(DefaultPaths, "DIR_CONFIG_SYSTEM", shared)
    monkeypatch.setattr(DefaultPaths, "DIR_LOCAL_SYSTEM", local)
    (shared / DefaultFilenames.CONFIG_SYSTEM).write_text('{"system_name": "shared"}')
    return {"shared": shared, "local": local}


class TestCopySharedDefaultSystem:
    def test_copies_the_template_into_the_local_root(
        self, config_roots: dict[str, Path]
    ) -> None:
        dest = main_module._copy_shared_default_system()

        assert dest == config_roots["local"] / DefaultFilenames.CONFIG_SYSTEM
        assert dest.read_text() == '{"system_name": "shared"}'

    def test_missing_shared_template_raises(
        self, config_roots: dict[str, Path]
    ) -> None:
        (config_roots["shared"] / DefaultFilenames.CONFIG_SYSTEM).unlink()

        with pytest.raises(FileNotFoundError, match="template not found"):
            main_module._copy_shared_default_system()


class TestInitLocalConfig:
    def test_copies_shared_template_to_the_named_local_profile(
        self, config_roots: dict[str, Path]
    ) -> None:
        dest = main_module.init_local_config("murphy_100")

        assert dest == config_roots["local"] / "murphy_100.json"
        assert dest.read_text() == '{"system_name": "shared"}'

    def test_refuses_to_overwrite_an_existing_profile(
        self, config_roots: dict[str, Path]
    ) -> None:
        (config_roots["local"] / "murphy_100.json").write_text('{"real": "config"}')

        with pytest.raises(FileExistsError, match="already exists"):
            main_module.init_local_config("murphy_100")

        # Untouched -- the existing real config was not clobbered.
        assert (
            config_roots["local"] / "murphy_100.json"
        ).read_text() == '{"real": "config"}'

    def test_missing_shared_template_raises(
        self, config_roots: dict[str, Path]
    ) -> None:
        (config_roots["shared"] / DefaultFilenames.CONFIG_SYSTEM).unlink()

        with pytest.raises(FileNotFoundError, match="template not found"):
            main_module.init_local_config("murphy_100")


class TestResolveSystemConfig:
    def test_explicit_config_resolves_locally_and_sets_active_link(
        self, config_roots: dict[str, Path]
    ) -> None:
        (config_roots["local"] / "murphy_100.json").write_text("{}")

        result = main_module.resolve_system_config("murphy_100.json")

        assert result == "murphy_100.json"
        assert LocalConfigRoots.active_system_target() == (
            config_roots["local"] / "murphy_100.json"
        )

    def test_explicit_config_missing_locally_raises(
        self, config_roots: dict[str, Path]
    ) -> None:
        with pytest.raises(FileNotFoundError, match=r"does_not_exist\.json"):
            main_module.resolve_system_config("does_not_exist.json")

    def test_none_found_auto_copies_the_shared_template(
        self, config_roots: dict[str, Path], caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            result = main_module.resolve_system_config(None)

        assert result == DefaultFilenames.CONFIG_SYSTEM
        assert (config_roots["local"] / DefaultFilenames.CONFIG_SYSTEM).exists()
        assert any("No local system config found" in r.message for r in caplog.records)
        assert LocalConfigRoots.active_system_target() == (
            config_roots["local"] / DefaultFilenames.CONFIG_SYSTEM
        )

    def test_exactly_one_local_config_is_used_as_is(
        self, config_roots: dict[str, Path]
    ) -> None:
        (config_roots["local"] / "only_one.json").write_text("{}")

        result = main_module.resolve_system_config(None)

        assert result == "only_one.json"
        assert LocalConfigRoots.active_system_target() == (
            config_roots["local"] / "only_one.json"
        )

    def test_ambiguous_with_no_tty_hard_fails(
        self, config_roots: dict[str, Path]
    ) -> None:
        (config_roots["local"] / "murphy_100.json").write_text("{}")
        (config_roots["local"] / "murphy_1000.json").write_text("{}")

        with pytest.raises(ValueError, match="Multiple local system configs found"):
            main_module.resolve_system_config(None, interactive=False)

    def test_ambiguous_with_tty_prompts_and_uses_the_choice(
        self, config_roots: dict[str, Path]
    ) -> None:
        (config_roots["local"] / "murphy_100.json").write_text("{}")
        (config_roots["local"] / "murphy_1000.json").write_text("{}")
        prompted: dict[str, Any] = {}

        def _fake_prompt(names: list[str], default: str) -> str:
            prompted["names"] = names
            prompted["default"] = default
            return "murphy_1000.json"

        result = main_module.resolve_system_config(
            None, interactive=True, prompt=_fake_prompt
        )

        assert result == "murphy_1000.json"
        assert set(prompted["names"]) == {"murphy_100.json", "murphy_1000.json"}
        assert LocalConfigRoots.active_system_target() == (
            config_roots["local"] / "murphy_1000.json"
        )

    def test_ambiguous_prompt_defaults_to_last_loaded(
        self, config_roots: dict[str, Path]
    ) -> None:
        (config_roots["local"] / "murphy_100.json").write_text("{}")
        (config_roots["local"] / "murphy_1000.json").write_text("{}")
        LocalConfigRoots.set_active_system(config_roots["local"] / "murphy_100.json")
        prompted: dict[str, Any] = {}

        def _fake_prompt(names: list[str], default: str) -> str:
            prompted["default"] = default
            return default

        main_module.resolve_system_config(None, interactive=True, prompt=_fake_prompt)

        assert prompted["default"] == "murphy_100.json"

    def test_ambiguous_prompt_returning_an_unknown_name_raises(
        self, config_roots: dict[str, Path]
    ) -> None:
        (config_roots["local"] / "murphy_100.json").write_text("{}")
        (config_roots["local"] / "murphy_1000.json").write_text("{}")

        with pytest.raises(ValueError, match="not one of the available configs"):
            main_module.resolve_system_config(
                None, interactive=True, prompt=lambda names, default: "nonsense.json"
            )


class TestPromptForSystemConfig:
    def test_blank_input_returns_the_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fake_input(prompt: str) -> str:
            return ""

        monkeypatch.setattr("builtins.input", _fake_input)

        result = main_module._prompt_for_system_config(["a.json", "b.json"], "b.json")

        assert result == "b.json"

    def test_numeric_input_selects_by_index(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fake_input(prompt: str) -> str:
            return "2"

        monkeypatch.setattr("builtins.input", _fake_input)

        result = main_module._prompt_for_system_config(["a.json", "b.json"], "a.json")

        assert result == "b.json"

    def test_typed_filename_is_returned_verbatim(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fake_input(prompt: str) -> str:
            return "c.json"

        monkeypatch.setattr("builtins.input", _fake_input)

        result = main_module._prompt_for_system_config(["a.json", "b.json"], "a.json")

        assert result == "c.json"
