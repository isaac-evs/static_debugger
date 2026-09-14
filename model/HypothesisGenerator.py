"""
This module contains the HypothesisGenerator class.
This class is in charge of generating new hypotheses to repair a defect.
Also,it is one of the core modules used in the methodology.
"""
import ast
from copy import deepcopy
from typing import Callable, List, Iterator, Tuple, Union, Type, Optional
from types import TracebackType
from model.abstractor.NodeAbstractor import NodeAbstractor, NodeAbstraction
from model.abstractor.PythonLLOC import PythonLLOC
from model.abstractor.HypothesisAbductor import HypothesisAbductor
from model.abstractor.NodeMapper import ASTNode, IDTokens
from model.abstractor.SymbolTable import SymbolTable
from model.abstractor.SubExpressionVisitor import get_boolop_operands
import logger as AbinLogging
import config as DebugController
import re
MatchingPattern = NodeAbstraction
MatchingPatterns = Iterator[MatchingPattern]
Hypothesis = Tuple[str, int, float]
Hypotheses = List[Hypothesis]
class HypothesisGenerator():
    """ The class is utilized to generate the hypotheses set,
    which the hypotheses that may repair the bug. """
    abduction_breadth: int
    complexity: int
    candidate: int
    bug_candidates: Iterator
    hypotheses_set_position: int
    hypotheses_set_complexity: int
    abductor: HypothesisAbductor
    node_abstractor: NodeAbstractor
    bugged_LOC: PythonLLOC
    matching_patterns: MatchingPatterns
    hypotheses_set: Iterator[Hypotheses]
    max_complexity: int
    nested_node: str

    def __init__(self, influence_path: list,
        model_src: Union[List[str], str], max_complexity: int = 3) -> None:
        """ Constructor Method """
        AbinLogging.debugging_logger.debug('Init HypothesisGenerator')
        self.abduction_breadth = 0
        self.max_complexity = max_complexity
        self.candidate = 0
        self.bug_candidates = map(lambda candidate: candidate[1], influence_path)
        self.model_src = model_src
        self.matching_patterns = iter([])
        self.hypotheses_set = iter([])
        self.hypotheses_set_complexity = 0
        self.hypotheses_set_position = 0
        self.LogicalLOC = PythonLLOC
        self.abductor = HypothesisAbductor
        self.node_abstractor = NodeAbstractor
        self.nested_node = None
        # Set alongside self.matching_patterns: which AST node the active
        # patterns were matched against (the whole LOC statement, or a
        # specific sub-expression within it -- see get_boolop_operands),
        # and how to splice a sub-expression fix back into a standalone
        # header line. None/None means "whole statement" (the default).
        self.active_bug_node: Optional[ASTNode] = None
        self.active_rebuild: Optional[Callable[[ASTNode], ASTNode]] = None

    def get_bug_candidate(self) -> int:
        """ This method returns the next bug candidate in the iterator.
        :rtype: int
        """
        return next(self.bug_candidates)

    def abstract_bug_candidate(self, ast_bug_candidate: ASTNode) -> str:
        """ This method returns the hex digest of the abstracted node.
        :rtype: str
        """
        bugged_node_abstract = self.node_abstractor(ast_bug_candidate)
        hexdigest = bugged_node_abstract.ast_hexdigest
        return hexdigest

    def get_matching_patterns(self, ast_node_hexdigest: str) -> Tuple[MatchingPatterns, int]:
        """ This method queries the database to obtain a list of MatchingPatterns.

        The hex digest of the abstracted node is needed in the query to obtain
        all identical patterns in the database. Additionally, the query is an aggregator-type query.

        :param ast_node_hexdigest: the hexdigest of the abstracted node.
        :type  ast_node_hexdigest: str
        :rtype: Tuple[MatchingPatterns, int]
        """
        config = DebugController.APP_SETTINGS
        import sqlite3
        import json
        db_path = config.get('SQLITE_DB_PATH', 'patterns.db')
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT data FROM BugPatterns")
            
            matching_patterns_dict = {}
            for row in cursor.fetchall():
                data = json.loads(row[0])
                if data.get('bug_metadata', {}).get('hexdigest') == ast_node_hexdigest:
                    fix_hexdigest = data.get('fix_metadata', {}).get('hexdigest')
                    map_ids = data.get('fix_metadata', {}).get('map_ids', {})
                    complexity = len(map_ids)
                    
                    if complexity <= self.max_complexity:
                        if fix_hexdigest not in matching_patterns_dict:
                            matching_patterns_dict[fix_hexdigest] = {
                                '_id': fix_hexdigest,
                                'fix_metadata': data.get('fix_metadata'),
                                'bug_metadata': data.get('bug_metadata'),
                                'available_identifiers': data.get('available_identifiers'),
                                'commit_sha': data.get('commit_sha'),
                                'complexity': complexity,
                                'count_similar': 1
                            }
                        else:
                            matching_patterns_dict[fix_hexdigest]['count_similar'] += 1
                            
            matching_patterns_list = list(matching_patterns_dict.values())
            matching_patterns_list.sort(key=lambda x: x['complexity'])
            
            matching_patterns_count = len(matching_patterns_list)
            self.matching_patterns = iter(matching_patterns_list)
            return (iter(matching_patterns_list), matching_patterns_count)
        except sqlite3.OperationalError:
            self.matching_patterns = iter([])
            return (iter([]), 0)
    
    def localize_bug_candidate(self, logical_loc: PythonLLOC) -> Tuple[MatchingPatterns, int]:
        """ Finds matching patterns for the current bug candidate line.

        Spectrum-based localization only identifies a suspicious *line*,
        but a compound line (e.g. `if check(u) and authorize(p):`) may
        only be buggy in one sub-expression, and the whole-line AST won't
        match any DB pattern unless the entire line's shape does. This
        tries the whole statement first (unchanged default behavior) and,
        if that finds nothing, falls back to each boolean operand of an
        `if`/`while` test individually, so a fix pattern only has to match
        the specific sub-expression that's actually broken.

        Sets self.active_bug_node/self.active_rebuild as a side effect,
        to whichever granularity produced a match.

        :param logical_loc: The current bug candidate's logical line.
        :type  logical_loc: PythonLLOC
        :rtype: Tuple[MatchingPatterns, int]
        """
        whole_statement = deepcopy(logical_loc.ast_node)
        localization_candidates: List[Tuple[ASTNode, Optional[Callable]]] = [(whole_statement, None)]
        for sub_candidate in get_boolop_operands(deepcopy(logical_loc.ast_node)):
            localization_candidates.append((sub_candidate.node, sub_candidate.rebuild))

        patterns: MatchingPatterns = iter([])
        count = 0
        for bug_node, rebuild in localization_candidates:
            ast_hexdigest = self.abstract_bug_candidate(deepcopy(bug_node))
            (patterns, count) = self.get_matching_patterns(ast_hexdigest)
            if count:
                self.active_bug_node = bug_node
                self.active_rebuild = rebuild
                return (patterns, count)

        # Nothing matched at any granularity; keep the whole-statement
        # node as the default so downstream logging/state stays sane.
        self.active_bug_node = whole_statement
        self.active_rebuild = None
        return (patterns, count)

    def apply_bugfix_pattern(self,
        bugged_node: NodeAbstractor,
        pattern: MatchingPattern,
        available_identifiers: IDTokens,
        symbol_table: Optional[SymbolTable] = None) -> Iterator[Hypotheses]:
        """ This method applies the fix-pattern to the abstracted node.

        This method returns an iterator of hypotheses generated
        due to the application of the fix-pattern.

        :param bugged_node: The abstracted node object.
        :type  bugged_node: NodeAbstractor
        :param pattern: The fix pattern.
        :type  pattern: MatchingPattern
        :param available_identifiers: the hexdigest of the abstracted node.
        :type  available_identifiers: IDTokens
        :param symbol_table: Usage evidence for the local vocabulary, used
            to filter out-of-role candidate identifiers up front.
        :type  symbol_table: Optional[SymbolTable]
        :rtype: Iterator[Hypotheses]
        """
        hypotheses = HypothesisAbductor(bugged_node, pattern, available_identifiers, symbol_table)
        return iter(hypotheses)

    def __iter__(self) -> None:
        """ Class Iterator Constructor """
        return self

    def __next__(self) -> str:
        """ Class Iterator Next Constructor

        This method will iterate over all bug candidates and generate
        a hypothesis until the iterator `self.bug_candidates` is exhausted.
        
        :rtype: str
        """
        hypothesis: Hypothesis = None
        while hypothesis is None:
            try:
                hypothesis = next(self.hypotheses_set)
                if self.active_rebuild is not None:
                    # The abducted fix is only a sub-expression (e.g. one
                    # operand of a compound `if`); splice it back into a
                    # standalone header line before it's used as a hypothesis.
                    rebuilt = self.active_rebuild(self.hypotheses_set.abducted_fix)
                    hypothesis = ast.unparse(rebuilt)
                if self.nested_node == 'elif' and re.search('if.*', hypothesis):
                    # Check if the hypothesis is part of an elif nested structure
                    hypothesis = 'el' + hypothesis
            except StopIteration:
                pattern: Union[MatchingPattern, None] = None
                while pattern is None:
                    try:
                        pattern = next(self.matching_patterns)
                    except StopIteration:
                        try:
                            self.candidate = self.get_bug_candidate()
                        except StopIteration:
                            msg_ = 'No more bug candidates to abstract in the current model.'
                            AbinLogging.debugging_logger.info(msg_)
                            raise StopIteration(msg_)
                        else:
                            model = self.model_src
                            logical_loc = self.LogicalLOC(self.candidate, '\n'.join(model))
                            self.nested_node = logical_loc.get_nested_node()
                            available_identifiers = logical_loc.get_available_identifiers()
                            (self.matching_patterns, count) = self.localize_bug_candidate(logical_loc)
                            AbinLogging.debugging_logger.info(f"""
                            Current Candidate: {self.candidate}. Patterns Found: {count}
                            """
                            )

                model = self.model_src
                logical_loc = self.LogicalLOC(self.candidate, '\n'.join(model))
                self.nested_node = logical_loc.get_nested_node()
                available_identifiers = logical_loc.get_available_identifiers()
                symbol_table = SymbolTable.from_source('\n'.join(model))
                self.hypotheses_set = self.apply_bugfix_pattern(
                    self.active_bug_node, pattern, available_identifiers, symbol_table)
                self.hypotheses_set_complexity = pattern['complexity']
                self.hypotheses_set_position = self.candidate

        self.abduction_breadth += 1
        # The explanatory power is set to 0 for untested hypotheses.
        return (hypothesis, self.hypotheses_set_position, 0)

    def __enter__(self):
        """ Context manager method. """
        AbinLogging.debugging_logger.debug('Entering HypothesisGenerator')
        return self

    def __exit__(self, exc_tp: Type, exc_value: BaseException,
                 exc_traceback: TracebackType) -> Optional[bool]:
        """ Context manager method is used to ignore/consume all the exceptions.
        
        This method is used to void a raising exception that occurred
        during the execution of the class methods.

        :param exc_tp: Type of the raised exception.
        :type  exc_tp: Type
        :param exc_value: The raised exception object.
        :type  exc_value: BaseException
        :param exc_traceback: The trace-back object of the exception.
        :type  exc_traceback: TracebackType
        :rtype: bool
        """
        AbinLogging.debugging_logger.debug('Exiting HypothesisGenerator')
        AbinLogging.debugging_logger.info(f"""
            <=== Hypothesis Generator Process Summary ===>
            Current Candidate: {self.candidate}
            Remaining Candidates: {list(self.bug_candidates)}
            Abduction Maximum Complexity: {self.hypotheses_set_complexity}
            Total Number of Hypotheses Generated: {self.abduction_breadth}
            """
        )
        if exc_tp is not None:
            from traceback import format_exc
            AbinLogging.debugging_logger.warning(f"""
                An error ocurred during the hypotheses generation.
                {exc_tp}: {exc_value}
                Unable to continue the hypotheses generation process.
                """
            )
            AbinLogging.debugging_logger.debug(f"""
                <== Exception Traceback ==>
                """
            )
            AbinLogging.debugging_logger.debug(f"{format_exc()}")
        return True  # Ignore exception, if any

