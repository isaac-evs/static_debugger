"""
This module contains the HypothesisTester, ModelConstructor and Behaviour classes.
The HypothesisTester class is in charge of testing
the generated hypotheses. This class is one of the core
modules used to automatically repair a defect.
The ModelConstructor class is in charge of constructing
a proper model for an hypothesis.
The Behaviour class is an enumeration of the available behaviors.
"""
from model.core.ModelTester import ModelTester, TestSuite, Observation, PassedTest, FailedTest, Behavior
from model.HypothesisGenerator import Hypothesis
from typing import Union, List
import logger as AbinLogging
import ast
import re


# Compound statements only have their header (the part carrying the
# hypothesis' condition/target) replaced, so the original body/orelse
# nodes are preserved instead of being discarded.
_COMPOUND_HEADER_FIELDS = {
    ast.If: ('test',),
    ast.While: ('test',),
    ast.For: ('target', 'iter'),
    ast.AsyncFor: ('target', 'iter'),
}


class HypothesisNodeTransformer(ast.NodeTransformer):
   """ Splices a hypothesis snippet into a candidate AST in-memory.

   This replaces the previous approach of guessing indentation with a
   regex (`re.split('\\w', ...)`) and physically rewriting a line of
   source: the target statement is located by its original line number
   and swapped for the parsed hypothesis, using the AST's own notion of
   structure (rather than text/whitespace) to stay correct. """

   def __init__(self, target_lineno: int, replacement_src: str) -> None:
       super().__init__()
       self.target_lineno = target_lineno
       self.replacement_src = replacement_src
       self.applied = False

   def generic_visit(self, node: ast.AST) -> ast.AST:
       node = super().generic_visit(node)
       if (not self.applied and isinstance(node, ast.stmt)
               and getattr(node, 'lineno', None) == self.target_lineno):
           self.applied = True
           return self._splice(node)
       return node

   def _splice(self, original_node: ast.stmt) -> ast.stmt:
       header_fields = _COMPOUND_HEADER_FIELDS.get(type(original_node))
       if header_fields is None:
           replacement = ast.parse(self.replacement_src, mode='exec').body[0]
       else:
           # Header-only text (e.g. "if x > 0:"/"elif x > 0:") cannot be
           # parsed on its own; pad it with a dummy body just to make it
           # parseable, then only reuse the header field(s) so the
           # original body/orelse survive untouched.
           header_src = re.sub(r'^elif\b', 'if', self.replacement_src.strip())
           parsed = ast.parse(f"{header_src}\n    pass", mode='exec').body[0]
           replacement = original_node
           for field in header_fields:
               setattr(replacement, field, getattr(parsed, field))
       ast.copy_location(replacement, original_node)
       return replacement


class ModelConstructor():
   """ This class contains the methods needed to
   build a hypothesis model."""
   def build_hypothesis_model(self, hypothesis: Hypothesis,
       src_code: Union[List[str], str]) -> Union[str, None]:
       """ This method create a new model to test the given hypothesis.

       The mutation happens purely in-memory: the source is parsed into
       an AST, the candidate statement is swapped via NodeTransformer,
       and the resulting tree is unparsed back into source text. No
       temporary file is ever written to disk.

       :param hypothesis: The hypothesis that need a model.
       :type  hypothesis: Hypothesis
       :rtype: Union[str, None]
       """
       (hypothesis_str, position, *_) = hypothesis
       if isinstance(src_code, list):
           src_code = '\n'.join(src_code)

       tree = ast.parse(src_code)
       transformer = HypothesisNodeTransformer(position, hypothesis_str)
       new_tree = transformer.visit(tree)
       if not transformer.applied:
           AbinLogging.debugging_logger.exception(
               f"Unable to locate the target statement at line {position} to apply the hypothesis."
           )
           return None
       ast.fix_missing_locations(new_tree)
       return ast.unparse(new_tree)
class HypothesisTester(ModelTester, ModelConstructor):
   """ This class' goal is to test a hypothesis.
   It inherits from ModelTester and ModelConstructor. """
   prev_observation: Observation
   hypothesis: Hypothesis
   def __init__(self, prev_observation: Observation,
       src_code: Union[List[str], str], target_function: str,
       test_suite: TestSuite, hypothesis: Hypothesis) -> None:
       """ Constructor Method """
       AbinLogging.debugging_logger.debug('Init HypothesisTester')

       new_model_code = self.build_hypothesis_model(hypothesis, src_code)
       super().__init__(new_model_code, target_function, test_suite)
       self.hypothesis = hypothesis
       self.prev_observation = prev_observation

   def compare_observations(self) -> Behavior:
       """ This method compares two observations.

       The two observations are compared in order to obtain a behavior,
       the behavior indicates the degree of utility the new tested hypothesis have.
       Also, this method sets the explanatory power to the given hypothesis.

       :type: Behavior
       """
       if self.is_consistent:
           prev_explanatory_power = self.get_explanatory_power(self.prev_observation)
           AbinLogging.debugging_logger.info(f'Previous Explanatory Power: {prev_explanatory_power}')
           curr_explanatory_power = self.get_explanatory_power(self.observation)
           AbinLogging.debugging_logger.info(f'Current Explanatory Power: {curr_explanatory_power}')
           # The explanatory power is the third argument of a hypothesis.
           self.hypothesis = (*self.hypothesis[:2], curr_explanatory_power)
           if curr_explanatory_power == 1:
               return Behavior.Correct
           elif prev_explanatory_power < curr_explanatory_power:
               return Behavior.Improvement
           elif prev_explanatory_power == curr_explanatory_power:
               return Behavior.Same
       return Behavior.Worsened

   @staticmethod
   def get_explanatory_power(observation: Observation) -> float:
       """ This method calculates the explanatory power.

       The explanatory power is the ratio of no. paseed test cases
       and the total number of test cases.

       :param observation: The list of TestResults obtained
       from testing the hypothesis.
       :type  observation: Observation
       :rtype: float
       """
       explanatory_power = 0
       no_test_cases = len(observation)
       test_outcome = lambda x: True if x[1] == PassedTest else False
       no_passed_test_cases = sum(map(test_outcome, observation))
       try:
           explanatory_power = no_passed_test_cases/no_test_cases
       except ZeroDivisionError:
           AbinLogging.debugging_logger.exception(
               "The given observation do not have any test case."
           )
       finally:
           return round(explanatory_power, 4)

   def is_consistent(self) -> bool:
       """ This method checks the consistency of two observations.

       This method checks the consistency of the current observation
       agaist the previous observation.

       :rtype: bool
       """
       # Check if have the same number of test_cases?
       if len(self.prev_observation) != len(self.observation):
           return False

       for prev_test_result, curr_test_result in zip(self.prev_observation, self.observation):
           if (prev_test_result[1] == PassedTest
               and curr_test_result[1] == FailedTest):
               return False
       return True

   @staticmethod
   def get_complexity():
       """ Abstract Method """
       pass

   def __repr__(self) -> str:
       """ Abstract Method """
       pass
