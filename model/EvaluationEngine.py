"""
This module contains the EvaluationEngine class.

The EvaluationEngine executes a test suite against a single candidate
patch and returns a pure fitness result. It holds only immutable
configuration (the target function and test suite) and never mutates
any shared search state, decoupling runtime evaluation from the search
traversal that drives it.
"""
from typing import List, NamedTuple, Type, Union
from model.core.ModelTester import Behavior, Observation, TestSuite
from model.HypothesisTester import HypothesisTester
from model.HypothesisGenerator import Hypothesis
from model.SearchSchema import Candidate


class EvaluationResult(NamedTuple):
    """ The pure outcome of evaluating a single candidate patch. """
    model_src_code: Union[List[str], str]
    behavior: Behavior
    observation: Observation
    hypothesis: Hypothesis


class EvaluationEngine():
    """ Executes candidate patches against the test suite and reports
    their fitness, independently of how the search chose to visit them. """

    def __init__(self, target_function: str, test_suite: TestSuite,
        tester: Type[HypothesisTester] = HypothesisTester) -> None:
        """ Constructor Method """
        self.target_function = target_function
        self.test_suite = test_suite
        self.tester = tester

    def evaluate(self, prev_observation: Observation,
        src_code: Union[List[str], str], candidate: Candidate) -> EvaluationResult:
        """ Tests a single candidate patch and returns a pure fitness result.

        :param prev_observation: The previous observation to compare against.
        :type  prev_observation: Observation
        :param src_code: The source code the candidate patch is applied to.
        :type  src_code: Union[List[str], str]
        :param candidate: The pure candidate patch to evaluate.
        :type  candidate: Candidate
        :rtype: EvaluationResult
        """
        # Pre-initialized: the tester's __exit__ swallows any exception
        # raised inside the `with` block, so these are the fallback values
        # if an error interrupts the block before it reaches the end.
        behavior = Behavior.Undefined
        observation = []
        new_model_src_code = []
        hypothesis = candidate.hypothesis
        with self.tester(prev_observation, src_code, self.target_function,
            self.test_suite, candidate.hypothesis) as hypo_test:
            (observation, _influence_path) = hypo_test.model_testing(check_consistency=True)
            behavior = hypo_test.compare_observations()
            new_model_src_code = hypo_test.model_src
            hypothesis = hypo_test.hypothesis
        return EvaluationResult(new_model_src_code, behavior, observation, hypothesis)
