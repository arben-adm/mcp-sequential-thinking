"""Utility functions for the sequential thinking package.

This module contains common utilities used across the package.
"""

def to_camel_case(snake_str: str) -> str:
    """Convert a snake_case string to camelCase.

    Args:
        snake_str: A string in snake_case format

    Returns:
        The string converted to camelCase
    """
    components = snake_str.split('_')
    # Join with the first component lowercase and the rest with their first letter capitalized
    return components[0] + ''.join(x.title() for x in components[1:])