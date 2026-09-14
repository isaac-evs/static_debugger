"""
This module contains helpers to decompose a compound conditional into
its individually addressable boolean sub-expressions.

Spectrum-based localization (Ochiai) ranks suspiciousness strictly at
the Line-of-Code level. When a suspicious line is a compound condition
like `if check(u) and authorize(p):`, the abduction engine otherwise has
no way to target just `authorize(p)` -- the whole `if` statement gets
abstracted and hashed as a single unit, so a fix pattern only matches if
it happens to cover the *entire* line's structure. `get_boolop_operands`
extracts each operand of an `if`/`while` test's boolean chain as its own
addressable candidate, so localization can fall back to finer-grained
pattern matching when no pattern exists for the line as a whole.
"""
import ast
import copy
from typing import List, NamedTuple


class SubExpressionCandidate(NamedTuple):
    """ A single boolean operand within a larger `if`/`while` test, plus
    enough context to splice a replacement back into a standalone header
    statement (e.g. "if <replacement>:"). """
    node: ast.AST
    statement_type: type
    path: List[int]
    original_test: ast.AST

    def rebuild(self, replacement: ast.AST) -> ast.AST:
        """ Returns a new header-only statement (`if`/`while`, with a
        placeholder `pass` body) with this operand replaced.

        Only the header is reconstructed -- the caller only ever needs a
        single-line replacement, and the original statement's body is
        untouched by construction (it lives on separate source lines).

        :param replacement: The abducted fix for this sub-expression.
        :type  replacement: ast.AST
        :rtype: ast.AST
        """
        new_test = copy.deepcopy(self.original_test)
        target = new_test
        for idx in self.path[:-1]:
            target = target.values[idx]
        if self.path:
            target.values[self.path[-1]] = replacement
        else:
            new_test = replacement
        new_statement = self.statement_type(test=new_test, body=[ast.Pass()], orelse=[])
        ast.fix_missing_locations(new_statement)
        return new_statement


def get_boolop_operands(statement: ast.AST) -> List[SubExpressionCandidate]:
    """ Extracts each operand of an `if`/`while` test's boolean chain
    (recursively, through nested `and`/`or`) as its own candidate.

    :param statement: A logical LOC statement. Only If/While have a
        decomposable `test`; anything else yields no candidates.
    :type  statement: ast.AST
    :rtype: List[SubExpressionCandidate]
    """
    if not isinstance(statement, (ast.If, ast.While)):
        return []
    candidates: List[SubExpressionCandidate] = []

    def walk(node: ast.AST, path: List[int]) -> None:
        if isinstance(node, ast.BoolOp):
            for i, value in enumerate(node.values):
                walk(value, path + [i])
        elif path:
            # Only sub-expressions strictly nested under a BoolOp are
            # independently addressable; the bare test itself is already
            # covered by the whole-statement candidate.
            candidates.append(SubExpressionCandidate(
                node=node, statement_type=type(statement),
                path=path, original_test=statement.test))

    walk(statement.test, [])
    return candidates
