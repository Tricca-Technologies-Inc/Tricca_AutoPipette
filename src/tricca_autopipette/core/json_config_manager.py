#!/usr/bin/env python3
"""JSON-based configuration management for AutoPipette.

This module provides the JsonConfigManager class for loading, validating,
and building SystemConfig from JSON files with default value merging.
Supports both batch loading (for initialization) and dynamic loading
(for interactive shell operations).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pipette_constants import DefaultFilenames, DefaultPaths
from pipette_models import (
    GantryKinematics,
    LiquidProfile,
    PipetteModel,
    SystemConfig,
)

CONFIG_SYSTEM = DefaultFilenames.CONFIG_SYSTEM
CONFIG_GANTRY = DefaultFilenames.CONFIG_GANTRY
CONFIG_PIPETTE = DefaultFilenames.CONFIG_PIPETTE
CONFIG_LIQUIDS = DefaultFilenames.CONFIG_LIQUIDS


logger = logging.getLogger(__name__)


class JsonConfigManager:
    """Manages JSON-based configuration loading and merging.

    Loads defaults and user configurations, merges them according to
    override rules, and builds complete SystemConfig objects. Supports
    both complete system loading and dynamic component switching.

    Attributes:
        system_config: Currently loaded system configuration.

    Example:
        >>> # Batch loading (initialization)
        >>> manager = JsonConfigManager(Path("config"))
        >>> config = manager.load_system_config("system.json")

        >>> # Dynamic loading (interactive shell)
        >>> manager.switch_liquid("glycerol")
        >>> manager.switch_pipette("p200_horizontal.json")
    """

    def __init__(self) -> None:
        """Initialize configuration manager.

        Example:
            >>> manager = JsonConfigManager()
            >>> manager = JsonConfigManager(Path("/custom/config"))
        """
        self.system_config: SystemConfig | None = None

    def get_system_config(self) -> SystemConfig:
        """Get the currently loaded system configuration.

        Returns:
            The current SystemConfig object.

        Raises:
            RuntimeError: If no system configuration is loaded.

        Example:
            >>> manager = JsonConfigManager()
            >>> manager.load_system_config()
            >>> config = manager.get_system_config()
            >>> print(config.system_name)
            'AutoPipette'
        """
        if self.system_config is None:
            raise RuntimeError("No system configuration loaded.")
        return self.system_config

    # ========================================================================
    # BATCH LOADING - For initialization
    # ========================================================================
    def load_configs(
        self,
        fn_system: str = CONFIG_SYSTEM,
        fn_gantry: str = CONFIG_GANTRY,
        fn_pipette: str = CONFIG_PIPETTE,
        fn_liquids: str = CONFIG_LIQUIDS,
    ) -> SystemConfig:
        """Load all configuration files and return the system configuration.

        Args:
            fn_system: Filename of the system configuration. Defaults to CONFIG_SYSTEM.
            fn_gantry: Filename of the gantry configuration. Defaults to CONFIG_GANTRY.
            fn_pipette: Filename of the pipette configuration. Defaults to
                        CONFIG_PIPETTE.
            fn_liquids: Filename of the liquids configuration. Defaults to
                        CONFIG_LIQUIDS.

        Returns:
            The loaded system configuration.
        """
        system_config: SystemConfig = self.load_system_config(fn_system)
        if fn_gantry != CONFIG_GANTRY:
            self.load_gantry(fn_gantry)
        if fn_pipette != CONFIG_PIPETTE:
            self.load_pipette(fn_pipette)
        if fn_liquids != CONFIG_LIQUIDS:
            self.load_liquid(fn_liquids)
        return system_config

    def load_system_config(self, filename: str = CONFIG_SYSTEM) -> SystemConfig:
        """Load complete system configuration with defaults and overrides.

        Loads default configurations from defaults/ directory and merges
        with user configuration file to create complete SystemConfig.

        Args:
            filename: Filename of the system configuration file in
                           config/system/ directory. Defaults to "system.json".

        Returns:
            Complete SystemConfig with merged defaults and overrides.

        Raises:
            FileNotFoundError: If config file not found.
            ValueError: If configuration is invalid.

        Example:
            >>> config = manager.load_system_config()
            >>> # Loads config/system.json with config/defaults/*
            >>> print(config.system_name)
            'AutoPipette'
        """
        user_path = DefaultPaths.DIR_CONFIG_SYSTEM / filename

        if user_path.exists():
            path_system = user_path
        else:
            raise FileNotFoundError(
                f"System config not found: {filename} "
                f"(searched in {user_path.parent})"
            )

        # 1. Load defaults
        default_gantry = self._load_default_gantry()
        default_pipettes = self._load_default_pipettes()
        default_liquids = self._load_default_liquids()

        # 2. Load user config
        try:
            with path_system.open("r", encoding="utf-8") as f:
                user_data = json.load(f)
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON in system config: %s", path_system)
            raise ValueError(f"Invalid JSON in {path_system}: {e}") from e

        # 3. Merge gantry config (user overrides defaults)
        gantry_data = {**default_gantry.model_dump(), **user_data.get("gantry", {})}
        merged_gantry = GantryKinematics(**gantry_data)

        # 4. Resolve pipette (reference or full config)
        pipette_ref = user_data.get("pipette", "p100_vertical")
        if isinstance(pipette_ref, str):
            # Reference to default pipette
            if pipette_ref not in default_pipettes:
                available = list(default_pipettes.keys())
                raise ValueError(
                    f"Unknown pipette '{pipette_ref}'. " f"Available: {available}"
                )
            merged_pipette = default_pipettes[pipette_ref]
        else:
            # Full pipette config provided by user
            merged_pipette = PipetteModel(**pipette_ref)

        # 5. Merge liquid profiles (user overrides defaults)
        merged_liquids = {}

        # Start with all default liquids
        for liquid_name, default_liquid in default_liquids.items():
            user_override = user_data.get("liquids", {}).get(liquid_name, {})

            # Merge default with user override
            liquid_data = {**default_liquid.model_dump(), **user_override}
            merged_liquids[liquid_name] = LiquidProfile(**liquid_data)

        # Add any user-only liquids (not in defaults)
        user_liquids = user_data.get("liquids", {})
        for liquid_name, liquid_data in user_liquids.items():
            if liquid_name not in merged_liquids:
                merged_liquids[liquid_name] = LiquidProfile(**liquid_data)

        # 6. Build final SystemConfig
        self.system_config = SystemConfig(
            version=user_data.get("version", "1.0"),
            system_name=user_data.get("system_name", "AutoPipette"),
            gantry=merged_gantry,
            pipette=merged_pipette,
            liquids=merged_liquids,
            network=user_data.get("network", {"hostname": "localhost", "port": "7125"}),
        )

        logger.info("Loaded system config from %s", path_system)
        logger.info("  System: %s", self.system_config.system_name)
        logger.info("  Pipette: %s", self.system_config.pipette.name)
        logger.info("  Liquids:  %d profile(s)", len(self.system_config.liquids))

        return self.system_config

    # ========================================================================
    # DYNAMIC LOADING - For interactive shell
    # ========================================================================
    def load_gantry(self, filename: str = CONFIG_GANTRY) -> GantryKinematics:
        """Load and switch to new gantry configuration.

        Dynamically loads a gantry configuration and updates the current
        system config. Useful for switching between different gantry
        setups in the shell.

        Args:
            filename: Gantry config filename in config/ directory.

        Returns:
            Newly loaded GantryKinematics object.

        Raises:
            RuntimeError: If no system config loaded.
            FileNotFoundError: If config file not found.
            ValueError: If config validation fails.

        Example:
            >>> gantry = manager.load_gantry("fast_gantry.json")
            >>> print(gantry.speed_xy)
            8000.0
        """
        if self.system_config is None:
            raise RuntimeError(
                "No system config loaded. Call load_system_config() first."
            )

        user_path = DefaultPaths.DIR_CONFIG_GANTRY / filename

        if user_path.exists():
            path_gantry = user_path
        else:
            raise FileNotFoundError(
                f"Gantry config not found: {filename} "
                f"(searched in {user_path.parent})"
            )

        try:
            with path_gantry.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON in gantry config: %s", path_gantry)
            raise ValueError(f"Invalid JSON in {filename}: {e}") from e

        try:
            gantry = GantryKinematics(**data)
            self.system_config.gantry = gantry
            logger.info("Switched to gantry config: %s", filename)
            return gantry
        except Exception as e:
            logger.error("Failed to validate gantry config: %s", e)
            raise ValueError(f"Gantry config validation failed: {e}") from e

    def load_pipette(self, filename: str = CONFIG_PIPETTE) -> PipetteModel:
        """Load and switch to new pipette model.

        Dynamically loads a pipette configuration and updates the current
        system config. Useful for switching between different pipette
        models in the shell.

        Args:
            filename: Pipette config filename (looks in config/pipettes/).

        Returns:
            Newly loaded PipetteModel object.

        Raises:
            RuntimeError: If no system config loaded.
            FileNotFoundError: If config file not found.
            ValueError: If config validation fails.

        Example:
            >>> pipette = manager.load_pipette("p200_horizontal.json")
            >>> print(pipette.name)
            'P200_Horizontal'
        """
        if self.system_config is None:
            raise RuntimeError(
                "No system config loaded. Call load_system_config() first."
            )

        # Try user pipettes first, then defaults
        user_path = DefaultPaths.DIR_CONFIG_PIPETTE / filename

        if user_path.exists():
            path = user_path
        else:
            raise FileNotFoundError(
                f"Pipette config not found: {filename} "
                f"(searched in {user_path.parent})"
            )

        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON in pipette config: %s", path)
            raise ValueError(f"Invalid JSON in {filename}: {e}") from e

        try:
            pipette = PipetteModel(**data)
            self.system_config.pipette = pipette
            logger.info("Switched to pipette: %s", pipette.name)
            return pipette
        except Exception as e:
            logger.error("Failed to validate pipette config: %s", e)
            raise ValueError(f"Pipette config validation failed: {e}") from e

    def load_liquid(self, filename: str = CONFIG_LIQUIDS) -> LiquidProfile:
        """Load a new liquid profile into the system.

        Dynamically loads a liquid profile and adds it to the available
        liquids in the system config. Does not automatically make it active.

        Args:
            filename: Liquid config filename (looks in config/liquids/).

        Returns:
            Newly loaded LiquidProfile object.

        Raises:
            RuntimeError: If no system config loaded.
            FileNotFoundError: If config file not found.
            ValueError: If config validation fails.

        Example:
            >>> liquid = manager.load_liquid("acetone.json")
            >>> print(liquid.name)
            'acetone'
            >>> manager.switch_liquid("acetone")  # Now activate it
        """
        if self.system_config is None:
            raise RuntimeError(
                "No system config loaded. Call load_system_config() first."
            )

        # Try user liquids first, then defaults
        user_path = DefaultPaths.DIR_CONFIG_LIQUIDS / filename

        if user_path.exists():
            path = user_path
        else:
            raise FileNotFoundError(
                f"Liquid config not found: {filename} "
                f"(searched in {user_path.parent})"
            )

        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON in liquid config: %s", path)
            raise ValueError(f"Invalid JSON in {filename}: {e}") from e

        try:
            liquid = LiquidProfile(**data)
            self.system_config.liquids[liquid.name] = liquid
            logger.info("Loaded liquid profile: %s", liquid.name)
            return liquid
        except Exception as e:
            logger.error("Failed to validate liquid config: %s", e)
            raise ValueError(f"Liquid config validation failed: {e}") from e

    # ========================================================================
    # LIQUID SWITCHING - For multi-liquid protocols
    # ========================================================================

    def switch_liquid(self, liquid_name: str) -> LiquidProfile:
        """Switch to a different liquid profile.

        Changes the active liquid profile for subsequent pipetting operations.
        Essential for protocols that use multiple liquids (e.g., water and
        methanol).

        Args:
            liquid_name: Name of liquid profile to activate.

        Returns:
            The newly activated LiquidProfile.

        Raises:
            RuntimeError: If no system config loaded.
            ValueError: If liquid not found in loaded profiles.

        Example:
            >>> # In a protocol:
            >>> manager.switch_liquid("water")
            >>> # ... pipette water ...
            >>> manager.switch_liquid("methanol")
            >>> # ... pipette methanol ...
        """
        if self.system_config is None:
            raise RuntimeError(
                "No system config loaded. Call load_system_config() first."
            )

        if liquid_name not in self.system_config.liquids:
            available = list(self.system_config.liquids.keys())
            raise ValueError(
                f"Liquid '{liquid_name}' not loaded. " f"Available liquids: {available}"
            )

        logger.info("Switched active liquid to: %s", liquid_name)
        return self.system_config.liquids[liquid_name]

    def get_active_liquid_name(self) -> str:
        """Get name of currently active liquid (for tracking).

        Returns:
            Name of active liquid profile.

        Note:
            This is tracked separately from SystemConfig since the active
            liquid changes during protocol execution.

        Example:
            >>> current = manager.get_active_liquid_name()
            >>> print(f"Currently using: {current}")
            'water'
        """
        # This will be tracked in AutoPipette, not in SystemConfig
        # Just documenting the pattern here
        raise NotImplementedError(
            "Active liquid tracking should be done in AutoPipette class"
        )

    # ========================================================================
    # QUERY METHODS - For shell introspection
    # ========================================================================

    def list_available_pipettes(self) -> list[str]:
        """List all available pipette configurations.

        Returns:
            List of pipette configuration filenames (without .json).

        Example:
            >>> pipettes = manager.list_available_pipettes()
            >>> print(pipettes)
            ['p1000_vertical', 'p200_horizontal', 'p10_vertical']
        """
        pipettes = []

        # Check user pipettes
        user_pipettes_dir = DefaultPaths.DIR_CONFIG_PIPETTE
        if user_pipettes_dir.exists():
            user_pipettes = [f.stem for f in user_pipettes_dir.glob("*.json")]
            # Add user pipettes that aren't duplicates
            pipettes.extend([p for p in user_pipettes if p not in pipettes])

        return sorted(pipettes)

    def list_available_liquids(self) -> list[str]:
        """List all available liquid configurations.

        Returns:
            List of liquid profile names.

        Example:
            >>> liquids = manager.list_available_liquids()
            >>> print(liquids)
            ['water', 'dmso', 'glycerol', 'methanol']
        """
        if self.system_config is None:
            return []

        return sorted(self.system_config.liquids.keys())

    def has_liquid(self, liquid_name: str) -> bool:
        """Check if a liquid profile is loaded.

        Args:
            liquid_name: Name of liquid to check.

        Returns:
            True if liquid is loaded, False otherwise.

        Example:
            >>> if manager.has_liquid("glycerol"):
            ...     manager.switch_liquid("glycerol")
        """
        if self.system_config is None:
            return False

        return liquid_name in self.system_config.liquids

    def get_current_config(self) -> SystemConfig:
        """Get the current system configuration.

        Returns:
            Current SystemConfig object.

        Raises:
            RuntimeError: If no system config loaded.

        Example:
            >>> config = manager.get_current_config()
            >>> print(config.pipette.name)
            'P1000_Vertical'
        """
        if self.system_config is None:
            raise RuntimeError(
                "No system config loaded. Call load_system_config() first."
            )

        return self.system_config

    # ========================================================================
    # PARAMETER MERGING - For getting effective parameters
    # ========================================================================

    def get_merged_syringe_params(self, liquid_name: str) -> dict[str, Any]:
        """Get syringe parameters merged with specific liquid overrides.

        Returns liquid-specific parameters where specified, falling back
        to pipette defaults. This allows each liquid to have optimized
        pipetting parameters.

        Args:
            liquid_name: Name of liquid profile to use for overrides.

        Returns:
            Dictionary of effective syringe parameters.

        Raises:
            RuntimeError: If no system config loaded.
            ValueError: If liquid not found.

        Example:
            >>> # Get water parameters
            >>> water_params = manager.get_merged_syringe_params("water")
            >>> print(water_params["speed_aspirate"])
            200.0

            >>> # Get glycerol parameters (slower)
            >>> glycerol_params = manager.get_merged_syringe_params("glycerol")
            >>> print(glycerol_params["speed_aspirate"])
            50.0
        """
        if self.system_config is None:
            raise RuntimeError(
                "No system config loaded. Call load_system_config() first."
            )

        if liquid_name not in self.system_config.liquids:
            available = list(self.system_config.liquids.keys())
            raise ValueError(
                f"Liquid '{liquid_name}' not found. Available: {available}"
            )

        liquid = self.system_config.liquids[liquid_name]
        syringe = self.system_config.pipette.syringe

        return {
            # Speed parameters (liquid overrides syringe)
            "speed_aspirate": liquid.speed_aspirate or syringe.speed_aspirate,
            "speed_dispense": liquid.speed_dispense or syringe.speed_dispense,
            # Timing parameters (liquid overrides syringe)
            "wait_aspirate_ms": liquid.wait_aspirate_ms or syringe.wait_aspirate_ms,
            "wait_dispense_ms": liquid.wait_dispense_ms or syringe.wait_dispense_ms,
            # Calibration data (liquid overrides syringe)
            "calibration_volumes": (
                liquid.calibration_volumes
                if liquid.calibration_volumes is not None
                else syringe.calibration_volumes
            ),
            "calibration_steps": (
                liquid.calibration_steps
                if liquid.calibration_steps is not None
                else syringe.calibration_steps
            ),
            # Motor configuration (from syringe only, no liquid override)
            "stepper_name": syringe.stepper_name,
            "motor_orientation": syringe.motor_orientation,
            # Volume limits (from syringe only, no liquid override)
            "max_volume_ul": syringe.max_volume_ul,
            "min_volume_ul": syringe.min_volume_ul,
        }

    # ========================================================================
    # INTERNAL METHODS - For loading defaults
    # ========================================================================

    def _load_default_gantry(self) -> GantryKinematics:
        """Load default gantry configuration.

        Returns:
            Default GantryKinematics object.

        Raises:
            FileNotFoundError: If default gantry config not found.
        """
        path = DefaultPaths.DIR_CONFIG_GANTRY / CONFIG_GANTRY
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return GantryKinematics(**data)
        except FileNotFoundError as e:
            logger.error("Default gantry config not found: %s", path)
            raise FileNotFoundError(
                f"Default gantry configuration not found: {path}"
            ) from e

    def _load_default_pipettes(self) -> dict[str, PipetteModel]:
        """Load all default pipette configurations.

        Returns:
            Dictionary of PipetteModel objects keyed by file stem.
        """
        pipettes_dir = DefaultPaths.DIR_CONFIG_PIPETTE
        pipettes: dict[str, PipetteModel] = {}

        if not pipettes_dir.exists():
            logger.warning("Default pipettes directory not found: %s", pipettes_dir)
            return pipettes

        for json_file in pipettes_dir.glob("*.json"):
            try:
                with json_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                pipette = PipetteModel(**data)
                # Use file name (without .json) as key
                key = json_file.stem
                pipettes[key] = pipette
                logger.debug("Loaded default pipette: %s (%s)", key, pipette.name)
            except Exception as e:
                logger.error("Failed to load default pipette %s: %s", json_file.name, e)

        return pipettes

    def _load_default_liquids(self) -> dict[str, LiquidProfile]:
        """Load all default liquid profiles.

        Returns:
            Dictionary of LiquidProfile objects keyed by liquid name.
        """
        liquids_dir = DefaultPaths.DIR_CONFIG_LIQUIDS
        liquids: dict[str, LiquidProfile] = {}

        if not liquids_dir.exists():
            logger.warning("Default liquids directory not found: %s", liquids_dir)
            return liquids

        for json_file in liquids_dir.glob("*.json"):
            try:
                with json_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                liquid = LiquidProfile(**data)
                liquids[liquid.name] = liquid
                logger.debug("Loaded default liquid: %s", liquid.name)
            except Exception as e:
                logger.error("Failed to load default liquid %s: %s", json_file.name, e)

        return liquids

    def __repr__(self) -> str:
        """Return string representation of configuration manager.

        Returns:
            String showing loaded state.

        Example:
            >>> manager = JsonConfigManager()
            >>> repr(manager)
            'JsonConfigManager(system_loaded=False)'
        """
        return f"JsonConfigManager(system_loaded={self.system_config is not None})"
