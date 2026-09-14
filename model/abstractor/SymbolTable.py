"""
This module contains the SymbolTable class.

Candidate hypotheses are synthesized by substituting abstract tokens
(e.g. "Name0", "arg1") with names pulled from the local vocabulary of
the bugged program, combined via a brute-force Cartesian product with
no notion of what each name is actually used for. That routinely
produces syntactically-valid-but-nonsensical code (e.g. calling an int
variable as a function), which then burns a full test-suite run just to
crash with a NameError/TypeError.

SymbolTable is a lightweight, best-effort classifier: it walks the
bugged program once and records, per identifier, evidence of how it is
used elsewhere in the source (ever called, ever subscripted, ...). It
does not do real type inference -- it only rules out combinations for
which there is no supporting evidence at all, cheaply, before a single
test case is executed.
"""
import ast
from typing import Set


CALLABLE_ROLE = 'callable'
SUBSCRIPTABLE_ROLE = 'subscriptable'
VALUE_ROLE = 'value'


class SymbolTable():
    """ A best-effort, source-derived classification of identifiers by
    how they are used (callable, subscriptable, ...), so candidate
    identifiers can be filtered by role before being substituted into a
    hypothesis. """

    def __init__(self) -> None:
        """ Constructor Method """
        self._callable_names: Set[str] = set()
        self._subscriptable_names: Set[str] = set()

    @classmethod
    def from_source(cls, source: str) -> 'SymbolTable':
        """ Builds a SymbolTable from the given program source.

        Parsing/traversal errors are treated as "no evidence available"
        rather than raised, since a SymbolTable is only ever used to
        narrow down candidates, never as the sole source of truth.

        :param source: The program source to analyze.
        :type  source: str
        :rtype: SymbolTable
        """
        table = cls()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return table
        for node in ast.walk(tree):
            table._record(node)
        return table

    def _record(self, node: ast.AST) -> None:
        """ Records the usage evidence a single AST node provides. """
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            self._callable_names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                self._callable_names.add(alias.asname or alias.name.split('.')[0])
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if isinstance(node.value, ast.Lambda):
                self._callable_names.update(names)
            if isinstance(node.value, (ast.List, ast.Dict, ast.Tuple, ast.Set,
                    ast.ListComp, ast.DictComp, ast.SetComp)):
                self._subscriptable_names.update(names)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            self._callable_names.add(node.func.id)
        elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            self._subscriptable_names.add(node.value.id)
        elif isinstance(node, ast.For) and isinstance(node.iter, ast.Name):
            self._subscriptable_names.add(node.iter.id)

    def is_callable(self, name: str) -> bool:
        """ Whether there's evidence `name` is ever used as a callable.
        :rtype: bool
        """
        return name in self._callable_names

    def is_subscriptable(self, name: str) -> bool:
        """ Whether there's evidence `name` is ever indexed/iterated.
        :rtype: bool
        """
        return name in self._subscriptable_names

    def compatible(self, token: str, role: str) -> bool:
        """ Whether `token` has supporting evidence for the given role.

        Unrecognized/unconstrained roles are always compatible: this
        table only ever narrows candidates down for roles it actually
        has an opinion about.

        :param token: The candidate identifier/token.
        :type  token: str
        :param role: The role the token would be substituted into.
        :type  role: str
        :rtype: bool
        """
        if role == CALLABLE_ROLE:
            return self.is_callable(token)
        if role == SUBSCRIPTABLE_ROLE:
            return self.is_subscriptable(token)
        return True
