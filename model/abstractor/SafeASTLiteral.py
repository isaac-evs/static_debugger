"""
This module contains a safe deserializer for `ast.dump()` output.

Bug/fix patterns are stored as the text produced by `ast.dump(node)`
(e.g. "If(Compare(Name('x'), [Lt()], [Constant(0)]), [...], [...])") and
were previously reconstructed with `eval(dump_src, vars(ast), {})`.
Because `vars(ast)` doesn't already contain `__builtins__`, Python
silently injects the real `__builtins__` into it for `eval`, so a
crafted dump string (e.g. from a pattern mined off an untrusted public
repo via `--mine`) could call `__import__`/`open`/etc. and execute
arbitrary code.

`safe_ast_literal_eval` never calls `eval`/`exec`. It parses the dump
text with `ast.parse()` (pure syntax, nothing is executed) and walks
the resulting tree, reconstructing only calls to `ast.AST` subclasses
and plain literals/lists/tuples -- anything else (attribute access,
subscripts, comprehensions, calls to non-AST names, ...) raises a
ValueError instead of running.
"""
import ast
from typing import Any


_UNARY_OPS = {
    ast.USub: lambda value: -value,
    ast.UAdd: lambda value: +value,
}


def safe_ast_literal_eval(dump_src: str) -> ast.AST:
    """ Safely reconstructs an `ast.AST` node from `ast.dump()` output.

    :param dump_src: The output of `ast.dump(node)`, with or without
        `annotate_fields=False`.
    :type  dump_src: str
    :rtype: ast.AST
    """
    try:
        expression = ast.parse(dump_src, mode='eval').body
    except SyntaxError as exc:
        raise ValueError(f"Invalid AST dump: {dump_src!r}") from exc
    return _reconstruct(expression)


def _reconstruct(node: ast.AST) -> Any:
    """ Recursively reconstructs the value described by a parsed dump
    expression, restricted to the grammar `ast.dump()` produces. """
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple)):
        elements = [_reconstruct(elt) for elt in node.elts]
        return elements if isinstance(node, ast.List) else tuple(elements)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_reconstruct(node.operand))
    if isinstance(node, ast.Call):
        return _reconstruct_call(node)
    raise ValueError(f"Unsupported node in AST dump: {ast.dump(node)}")


def _reconstruct_call(node: ast.Call) -> ast.AST:
    """ Reconstructs a single `ast.AST` node from a `Cls(...)` call,
    refusing anything that doesn't resolve to an `ast.AST` subclass. """
    if not isinstance(node.func, ast.Name):
        raise ValueError(f"Unsupported callee in AST dump: {ast.dump(node.func)}")
    node_cls = getattr(ast, node.func.id, None)
    if not (isinstance(node_cls, type) and issubclass(node_cls, ast.AST)):
        raise ValueError(f"Refusing to construct non-AST type: {node.func.id!r}")
    args = [_reconstruct(arg) for arg in node.args]
    kwargs = {kw.arg: _reconstruct(kw.value) for kw in node.keywords}
    return node_cls(*args, **kwargs)
