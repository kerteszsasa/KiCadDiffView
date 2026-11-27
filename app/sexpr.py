"""Small, iterative S-expression reader for KiCad documents.

Atoms (including numbers) remain strings. Only direct children are selected by
``children`` and ``first``; library definitions must not leak into placed parts.
"""

import re

_TOKEN = re.compile(r'\s+|;[^\r\n]*|\(|\)|"(?:[^"\\]|\\[\s\S])*"|[^\s()";]+')
_ESCAPE = re.compile(r'\\([\s\S])')
_ESCAPES = {'n': '\n', 'r': '\r', 't': '\t', '"': '"', '\\': '\\'}


def loads(text: str) -> list:
    """Read exactly one root expression, with useful syntax errors.

    Parsing uses an explicit stack and a streaming token iterator, so deeply
    nested expressions and large boards do not need Python recursion.
    """
    stack = []
    root = None
    position = 0
    for match in _TOKEN.finditer(text):
        if match.start() != position:
            raise ValueError(f'Invalid or unterminated string at offset {position}')
        position = match.end()
        token = match.group()
        if token.isspace() or token.startswith(';'):
            continue
        if token == '(':
            node = []
            if stack:
                stack[-1].append(node)
            elif root is not None:
                raise ValueError(f'Multiple root expressions at offset {match.start()}')
            else:
                root = node
            stack.append(node)
        elif token == ')':
            if not stack:
                raise ValueError(f'Unexpected closing parenthesis at offset {match.start()}')
            stack.pop()
        else:
            if not stack:
                raise ValueError(f'Expected root expression at offset {match.start()}')
            if token.startswith('"'):
                token = _ESCAPE.sub(lambda m: _ESCAPES.get(m[1], '\\' + m[1]), token[1:-1])
            stack[-1].append(token)
    if position != len(text):
        raise ValueError(f'Invalid or unterminated string at offset {position}')
    if stack:
        raise ValueError('Unclosed parenthesis at end of document')
    if root is None:
        raise ValueError('Expected root expression; document is empty')
    return root


def children(node, tag) -> list[list]:
    """Return direct list children beginning with ``tag``."""
    return [item for item in node if isinstance(item, list) and item and item[0] == tag]


def first(node, tag, default=None):
    """Return the first direct child beginning with ``tag``."""
    return next((item for item in node if isinstance(item, list) and item and item[0] == tag), default)
