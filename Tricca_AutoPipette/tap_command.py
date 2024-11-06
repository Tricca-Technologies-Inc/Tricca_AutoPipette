#!/usr/bin/env python3
"""Holds the decorator to mark functions as Tricca AutoPipette commands."""
from cmd2 import Cmd2ArgumentParser, with_argparser
import inspect
from functools import wraps


def generate_parser_from_signature(func):
    """Generate an ArgumentParser based on the function's signature.

    Uses type hints for type enforcement in argparse.
    TODO Support nargs and other parser features.
    """
    parser = Cmd2ArgumentParser(description=func.__doc__)
    signature = inspect.signature(func)
    for name, param in signature.parameters.items():
        # Determine if the parameter has a type annotation
        if name == 'self':
            continue
        param_type = \
            param.annotation if param.annotation != inspect.Parameter.empty else str
        # Positional (required) arguments
        # TODO Implement someway to do nargs / handle *args and **kwargs
        if param.default == inspect.Parameter.empty:
            parser.add_argument(name, type=param_type)
        else:
            if param_type is bool:
                if param.default:
                    parser.add_argument(f'--{name}',
                                        default=param.default,
                                        action='store_false')
                else:
                    parser.add_argument(f'--{name}',
                                        default=param.default,
                                        action='store_true')
            else:
                # Keyword (optional) arguments
                parser.add_argument(f'--{name}',
                                    default=param.default,
                                    type=param_type)
    return parser


def tap_command(func=None, parser=None):
    """Decorate functions used as Tricca AutoPipette commands.

    Create a parser based on a function signature, use it, and unwrap it.

    Args:
        func: The function to be decorated.
        parser: Optional custom argument parser
    """
    # Allow decorator to be used without parentheses
    if func is None:
        return lambda f: tap_command(f, parser=parser)

    # Use provided parser or generate one based on function signature
    parser = parser or generate_parser_from_signature(func)

    # Decorator to apply cmd2.with_argparser and unpack args
    @with_argparser(parser)
    @wraps(func)
    def wrapper(self, args):
        # Unpack args and call the function with keyword arguments
        kwargs = vars(args)
        # This definitely won't have any consequences...
        kwargs.pop('cmd2_statement')
        kwargs.pop('cmd2_handler')
        return func(self, **kwargs)
    return wrapper
