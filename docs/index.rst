Tricca AutoPipette
==================

Tricca AutoPipette controls an automated liquid handling system (ALHS) built
on the Voron 3D-printer/Klipper platform. A long-running control daemon
(``tapd``) owns the single connection to a Moonraker instance and exposes a
local control-plane WebSocket that two thin clients talk to: a ``cmd2``-based
interactive shell (``tap``) and a FastAPI "kiosk" touchscreen web UI.

This site is generated API reference, rendered straight from the docstrings
in ``src/``. For architecture, the command-line workflow, and how the pieces
fit together, start with the repository's ``CLAUDE.md`` -- it is the
authoritative system description and isn't duplicated here.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   api
