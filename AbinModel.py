"""
This module is the model of the system.
This is the model representation of the MVC software pattern.
"""
import sys
from typing import List, NamedTuple, Optional, Type, Tuple, Union
from types import TracebackType
from model.core.ModelTester import TestCase, Observation, InfluencePath, Behavior
from model.HyphotesisTester import HyphotesisTester
from model.FaultLocalizator import FaultLocalizator
from model.HypothesisGenerator import Hypothesis, HypothesisGenerator
from model.HypothesisRefinement import AbductionSchema
from model.SearchSchema import SearchSchema, DFSSchema, BFSSchema, AStarSchema, Candidate
from model.EvaluationEngine import EvaluationEngine
import pandas as pd
import logger as AbinLogging
import config as DebugController


Localizator = FaultLocalizator
Tester = HyphotesisTester
Generator = HypothesisGenerator
Refinement = 'HypothesisRefinement'

# Maps each abduction schema to the (stateless) traversal strategy that
# decides when the search recurses into an improvement candidate.
SEARCH_SCHEMAS = {
    AbductionSchema.DFS: DFSSchema,
    AbductionSchema.BFS: BFSSchema,
    AbductionSchema.A_star: AStarSchema,
}


class SearchResult(NamedTuple):
    """ The pure result of a (possibly recursive) search traversal.

    Unlike the previous recursive implementation, this result carries the
    winning hypothesis/candidate explicitly instead of relying on the
    caller's local loop variables, so a successful repair found deep in
    the recursion can never be overwritten by a parent frame's own
    (unrelated) hypothesis while it backtracks. """
    model_src_code: Union[List[str], str]
    behavior: Behavior
    prev_observation: Observation
    new_observation: Observation
    hypothesis: Optional[Hypothesis]
    candidate: Optional[int]
    depth: int


class AbinModel():
    """ This class is the encapsulation of the model"""
    function_name: str
    bugged_file_path: str
    test_suite: List[TestCase]
    fault_localizator: Localizator
    hyphotesis_tester: Tester
    hypotheses_generator: Generator
    current_behavior: Behavior
    max_complexity: int
    candidate: int
    bugfixing_hyphotesis: str

    def __init__(self, function_name: str, bugged_file_path: str, test_suite: List[TestCase],
                max_complexity: int, abduction_schema: AbductionSchema = AbductionSchema.DFS,
                localizator: Localizator = FaultLocalizator,
                tester: Tester = HyphotesisTester,
                generator: Generator = HypothesisGenerator) -> None:
        """ Constructor Method """
        self.function_name = function_name
        self.bugged_file_path = bugged_file_path
        self.test_suite = test_suite
        self.max_complexity = max_complexity
        self.abduction_depth = 0
        self.abduction_breadth = 0
        self.abduction_schema = abduction_schema
        self.search_schema: Type[SearchSchema] = SEARCH_SCHEMAS[abduction_schema]
        self.candidate = None
        self.bugfixing_hyphotesis = None
        self.fault_localizator = localizator
        self.hyphotesis_tester = tester
        self.hypotheses_generator = generator
        self.evaluation_engine = EvaluationEngine(function_name, test_suite, tester)

    def start_auto_debugging(self, model_src_code = None,
        improvement_candidates_set = None) -> Tuple[str, Behavior, Observation, Observation]:
        """ This method encapsulates the whole debugging process.

        This is the public entry point: it delegates the actual search to
        `_search`, which is a pure recursive traversal that never mutates
        `self`. The winning hypothesis/candidate (if any) are only ever
        assigned here, once, from the final propagated result -- so a
        successful repair found deep in the recursion can't be clobbered
        by a parent frame's own hypothesis while DFS backtracks.

        :rtype: Tuple[str, Behavior, Observation, Observation]
        """
        result = self._search(model_src_code, improvement_candidates_set, depth=0)
        self.abduction_depth = result.depth
        self.candidate = result.candidate
        self.bugfixing_hyphotesis = result.hypothesis[0] if result.behavior == Behavior.Correct else None
        return (result.model_src_code, result.behavior, result.prev_observation, result.new_observation)

    def _search(self, model_src_code, improvement_candidates_set, depth: int) -> SearchResult:
        """ Recursively traverses the hypotheses search space.

        Search traversal (deciding *when* to recurse, via `self.search_schema`),
        database retrieval/hypothesis generation (`self.hypotheses_generation`),
        and runtime evaluation (`self.evaluation_engine`) are three separate,
        independently swappable collaborators; this method only orchestrates
        them and carries state through return values instead of instance
        attributes, so recursive calls can never corrupt a sibling/parent
        frame's state.

        :rtype: SearchResult
        """
        AbinLogging.debugging_logger.info(f"""
        Schema: {self.abduction_schema}
        Abduction Depth: {depth}
        Abduction Breadth: {self.abduction_breadth}""")
        localizator = self.fault_localization(model_src_code, improvement_candidates_set)
        behavior = Behavior.Undefined
        prev_observation = []
        influence_path = []
        with localizator:
            (prev_observation, influence_path) = localizator.model_testing(check_consistency=False)
            model_src_code = localizator.model_src
            if localizator.are_all_test_pass():
                behavior = Behavior.Valid
        AbinLogging.debugging_logger.info(f"""
                Observations:
                {prev_observation}
                Bug Candidates Set by Suspiciousness Ranking:
                {influence_path}
                """
        )
        if behavior == Behavior.Valid:
            AbinLogging.debugging_logger.info(f"AbinDebugger did not detect any defects in the program.")
            return SearchResult(model_src_code, behavior, prev_observation, [], None, None, depth)
        # We need to save the prev_observation in case of failed refinement
        prev_observation_holder = prev_observation[:]
        # Fixed once per localizator/model: every sibling hypothesis tried
        # below is compared against THIS SAME baseline. Without it, a
        # nested recursive dive triggered by one hypothesis (which
        # reassigns `prev_observation` to whatever it returned) would
        # silently become the comparison point for the *next* sibling
        # hypothesis, comparing it against an unrelated candidate instead
        # of the actual baseline.
        baseline_observation = prev_observation[:]
        imprv_candidates = []
        winning_hypothesis = None
        winning_candidate = None
        final_depth = depth
        while True:
            new_observation = []
            hypotheses_generator = self.hypotheses_generation(influence_path, model_src_code[:], self.max_complexity)

            with hypotheses_generator:
                for hypothesis in hypotheses_generator:
                    AbinLogging.debugging_logger.info(f"""
                        Testing Hypothesis {self.abduction_breadth}.
                        Hypothesis: {hypothesis}
                        """
                    )
                    self.abduction_breadth += 1
                    evaluation = self.evaluation_engine.evaluate(baseline_observation[:], model_src_code[:], Candidate(hypothesis))
                    (new_model_src_code, behavior, new_observation, hypothesis) = evaluation
                    AbinLogging.debugging_logger.info(f"""
                        New Observations:
                        {new_observation}
                        Behavior Type:
                        {behavior}
                        """
                    )
                    if behavior == Behavior.Improvement:
                        imprv_candidates.append(hypothesis)
                        if self.search_schema.recurse_per_improvement():
                            # DFS: dive into this improvement right away.
                            sub_result = self._search(model_src_code[:], imprv_candidates, depth + 1)
                            (new_model_src_code, behavior, prev_observation,
                                new_observation, winning_hypothesis, winning_candidate, final_depth) = sub_result
                            imprv_candidates.clear()

                    if behavior == Behavior.Correct:
                        break

            if behavior == Behavior.Correct:
                pass
            elif imprv_candidates and not self.search_schema.recurse_per_improvement():
                # BFS/A*: recurse only once the current depth is exhausted.
                sub_result = self._search(model_src_code[:], imprv_candidates, depth + 1)
                (new_model_src_code, behavior, prev_observation,
                    new_observation, winning_hypothesis, winning_candidate, final_depth) = sub_result
                imprv_candidates.clear()

            if behavior == Behavior.Correct:
                AbinLogging.debugging_logger.debug(f"""
                    Previous Observations:
                    {prev_observation}
                    New Observations:
                    {new_observation}
                    Abduction Depth: {final_depth}
                    Abduction Breadth: {self.abduction_breadth}
                    \nSUCCESSFUL REPAIR!
                    """
                )
                # A repair found via a recursive call already carries its own
                # winning hypothesis/candidate; only fall back to this
                # frame's own loop variables when the fix was found here.
                if winning_hypothesis is None:
                    winning_hypothesis = hypothesis
                    winning_candidate = hypotheses_generator.candidate
                return SearchResult(new_model_src_code, behavior, prev_observation,
                    new_observation, winning_hypothesis, winning_candidate, final_depth)

            elif localizator.is_refinement:
                AbinLogging.debugging_logger.info(f"\nImprovement Candidate Rejected...")
                depth -= 1
                has_imprv_cand = next(localizator)
                if not has_imprv_cand:
                    # We need to return the prev_observation that was saved
                    prev_observation = prev_observation_holder[:]
                    behavior = Behavior.Undefined
                    AbinLogging.debugging_logger.info(f"Failed Refinement...")
                    AbinLogging.debugging_logger.info(f"""
                    Schema: {self.abduction_schema}
                    Abduction Depth: {depth}
                    Abduction Breadth: {self.abduction_breadth}""")
                    return SearchResult('', behavior, prev_observation, new_observation, None, None, depth)
                behavior = Behavior.Undefined
                with localizator:
                    (prev_observation, influence_path) = localizator.model_testing(check_consistency=False)
                    model_src_code = localizator.model_src
                # A new localizator/starting point means a genuinely new
                # baseline to compare its own sibling hypotheses against.
                baseline_observation = prev_observation[:]
            else:
                break


        if depth == 0:
            AbinLogging.debugging_logger.debug(f"\nUNABLE TO REPAIR!")
        return SearchResult('', behavior, prev_observation, new_observation, None, None, depth)

    def fault_localization(self, model_src_code = None,
        improvement_candidates_set = None) -> Localizator:
        """ This method encapsulates the fault localization process.
        : rtype: Tuple[str, Behavior, Observation, InfluencePath]
        """
        if improvement_candidates_set is None:
            localizator = self.fault_localizator(model_path = self.bugged_file_path,
                target_function = self.function_name,
                test_suite = self.test_suite,
                schema=self.abduction_schema)
        else:
            AbinLogging.debugging_logger.debug(f"Improvement Candidates: {improvement_candidates_set}\n")
            AbinLogging.debugging_logger.debug(f"New Model: {model_src_code}")
            localizator = self.fault_localizator(src_code = model_src_code,
                improvement_candidates_set = improvement_candidates_set,
                target_function = self.function_name,
                test_suite = self.test_suite,
                schema=self.abduction_schema)
        return localizator

    def hypotheses_generation(self,
        influence_path: InfluencePath,
        src_code: Union[List[str], str],
        max_complexity: int = 3) -> Generator:
        """ This method encapsulates the hypotheses generation process.

        :param influence_path: The visited node
        :type  influence_path: InfluencePath
        :param max_complexity: The maximun hypothesis' complexity allowed.
        :type  max_complexity: int
        :rtype : Tuple[Behavior, Observation]
        """
        return self.hypotheses_generator(influence_path, src_code, max_complexity)

    def hyphotesis_testing(self,
        prev_observation: Observation,
        src_code: Union[List[str], str],
        hypothesis: Hypothesis) -> Tuple[Behavior, Observation]:
        """ This method encapsulates the hypothesis testing process.

        Kept for backward compatibility; delegates to `self.evaluation_engine`,
        the single source of truth for runtime evaluation (see `_search`).

        :param prev_observation: The previous observation.
        :type  prev_observation: Observation
        :param model_name: The model's name.
        :type  model_name: str
        :rtype : Tuple[Behavior, Observation]
        """
        return self.evaluation_engine.evaluate(prev_observation, src_code, Candidate(hypothesis))

    def hyphotesis_refinement(self):
        pass

    def __enter__(self):
        """ Context manager method """
        return self

    def __exit__(self, exc_tp: Type, exc_value: BaseException,
                 exc_traceback: TracebackType) -> Optional[bool]:
        """ Context manager method to re-raise exceptions that happened during the process.

        :param exc_tp: Type of the raised exception.
        :type  exc_tp: Type
        :param exc_value: The raised exception object.
        :type  exc_value: BaseException
        :param exc_traceback: The trace-back object of the exception.
        :type  exc_traceback: TracebackType
        :rtype: bool
        """
        if exc_tp is not None:
            AbinLogging.debugging_logger.warning(f"""
                An error ocurred during in the model execution.
                {exc_tp}: {exc_value}
                Unable to debug.
                """
            )
        #return True  # Ignore exception, if any



def parse_csv_data(data):
  from json import loads
  import builtins
  parsed_data = pd.DataFrame()
  parsed_types = []
  columnsNames = list(data.columns)
  parsed_data[columnsNames[0]] = data[columnsNames[0]] # test_cases
  parsed_data[columnsNames[1]] = data[columnsNames[1]] # expected_output
  columnsNames = columnsNames[2:] # skip test_cases and expected_output columns
  for colName in columnsNames:
    newColName, castType = map(str.strip, colName.split(':'))
    parsed_types.append({ 'input_args': newColName, 'type': castType })
    if castType in ['int', 'float', 'str']:
      parsed_data[newColName] = data[colName].map(getattr(builtins, castType))
    elif castType in ['dict', 'json']:
      parsed_data[newColName] = data[colName].apply(loads)
    elif castType.startswith('list'):
      parsed_data[newColName] = data[colName].apply(loads)
    elif castType.startswith('tuple'):
      parsed_data[newColName] = data[colName].apply(lambda x: tuple(loads(x)))
  return (parsed_data, pd.DataFrame(parsed_types))

def main():
    from pathlib import Path
    curr_dir = Path(__file__).parent.resolve()

    #path_bugged_file = curr_dir.joinpath("benchmarks", "benchmark0.py")
    #df = pd.read_csv(curr_dir.joinpath("benchmarks", "benchmark0.csv"), keep_default_na=False)
    #func_name = 'get_profit'

    #path_bugged_file = curr_dir.joinpath("benchmarks", "benchmark1.py")
    #df = pd.read_csv(curr_dir.joinpath("benchmarks", "benchmark1.csv"), keep_default_na=False)
    #func_name = 'remove_html_markup'

    #path_bugged_file = curr_dir.joinpath("benchmarks", "benchmark2.py")
    #df = pd.read_csv(curr_dir.joinpath("benchmarks", "benchmark2.csv"), keep_default_na=False)
    #func_name = 'middle'

    path_bugged_file = curr_dir.joinpath("benchmarks", "benchmark3.py")
    df = pd.read_csv(curr_dir.joinpath("benchmarks", "benchmark3.csv"), keep_default_na=False)
    func_name = 'check_password_strength'

    (parsed_data, parsed_types) = parse_csv_data(df)
    test_cases = parsed_data

    abin = AbinModel(func_name, path_bugged_file, test_cases)
    (model_name, behavior, prev_observation, new_observation) = abin.start_auto_debugging()

def debugger_is_active() -> bool:
    """ This method return if the debugger is currently active """
    gettrace = getattr(sys, 'gettrace', lambda : None)
    return gettrace() is not None

if __name__ == "__main__":

    if debugger_is_active():
        print('The program is currenly being execute in debug mode.')
    else:
        main()
