"""Holds the TAPCmdParsers data class."""
from cmd2 import Cmd2ArgumentParser


class TAPCmdParsers():
    """A data class containing all the parsers for TAP commands."""

    parser_home: Cmd2ArgumentParser = Cmd2ArgumentParser()
    parser_home.add_argument("motors", default=None, type=str)

    parser_set: Cmd2ArgumentParser = Cmd2ArgumentParser()
    parser_set.add_argument("pipvar", type=str)
    parser_set.add_argument("pipval", type=float)

    parser_coor: Cmd2ArgumentParser = Cmd2ArgumentParser()
    parser_coor.add_argument("name_loc", type=str)
    parser_coor.add_argument("x", type=float)
    parser_coor.add_argument("y", type=float)
    parser_coor.add_argument("z", type=float)

    parser_plate: Cmd2ArgumentParser = Cmd2ArgumentParser()
    parser_plate.add_argument("name_loc", type=str)
    parser_plate.add_argument("plate_type", type=str)
    parser_plate.add_argument("--row", default=None, type=int)
    parser_plate.add_argument("--col", default=None, type=int)

    parser_move: Cmd2ArgumentParser = Cmd2ArgumentParser()
    parser_move.add_argument("x", type=float)
    parser_move.add_argument("y", type=float)
    parser_move.add_argument("z", type=float)

    parser_move_loc: Cmd2ArgumentParser = Cmd2ArgumentParser()
    parser_move_loc.add_argument("name_loc", type=str)
    parser_move_loc.add_argument("--row", default=None, type=int)
    parser_move_loc.add_argument("--col", default=None, type=int)

    parser_move_rel: Cmd2ArgumentParser = Cmd2ArgumentParser()
    parser_move_rel.add_argument("--x", default=0, type=float)
    parser_move_rel.add_argument("--y", default=0, type=float)
    parser_move_rel.add_argument("--z", default=0, type=float)

    parser_pipette: Cmd2ArgumentParser = Cmd2ArgumentParser()
    parser_pipette.add_argument("vol_ul", type=float)
    parser_pipette.add_argument("src", type=str)
    parser_pipette.add_argument("dest", type=str)
    parser_pipette.add_argument("--prewet", action="store_true")
    parser_pipette.add_argument("--keep_tip", action="store_true")
    parser_pipette.add_argument("--wiggle", action="store_true")
    parser_pipette.add_argument("--src_row", default=None, type=int)
    parser_pipette.add_argument("--src_col", default=None, type=int)
    parser_pipette.add_argument("--dest_row", default=None, type=int)
    parser_pipette.add_argument("--dest_col", default=None, type=int)
    parser_pipette.add_argument(
    "--dispense_vol", "-d",
    dest="disp_vol_ul",
    default=None,
    type=float,
    )

    parser_run: Cmd2ArgumentParser = Cmd2ArgumentParser()
    parser_run.add_argument("filename", type=str)

    parser_reset_plate: Cmd2ArgumentParser = Cmd2ArgumentParser()
    parser_reset_plate.add_argument("plate", type=str)

    parser_vol_to_steps: Cmd2ArgumentParser = Cmd2ArgumentParser()
    parser_vol_to_steps.add_argument("vol", type=float)

    parser_ls: Cmd2ArgumentParser = Cmd2ArgumentParser()
    parser_ls.add_argument("var", default=None, type=str)

    parser_load_conf: Cmd2ArgumentParser = Cmd2ArgumentParser()
    parser_load_conf.add_argument("filename", default=None, type=str)

    parser_gcode_print: Cmd2ArgumentParser = Cmd2ArgumentParser()
    parser_gcode_print.add_argument("msg", default=None, type=str)

    parser_send: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Send a JSON-RPC request.")
    parser_send.add_argument("method", help="JSON-RPC method to call")
    parser_send.add_argument("params",
                             nargs="?",
                             help="JSON string of parameters")

    parser_notify: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Send a JSON-RPC notification.")
    parser_notify.add_argument("method", help="JSON-RPC method to notify")
    parser_notify.add_argument("params",
                               nargs="?",
                               help="JSON string of parameters")

    parser_upload: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Upload a G-code file to the pipette.")
    parser_upload.add_argument("file_name", help="Name to assign on the server")
    parser_upload.add_argument("file_path", help="Local path to G-code file")
