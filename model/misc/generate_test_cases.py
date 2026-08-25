"""
This module generates AI-authored CSV test suites for a target Python
function, in the exact format `AbinModel.parse_csv_data` (and the
`benchmarks/*.csv` files) expect: a `test_cases`/`expected_output` pair
of columns plus one `paramName: type` column per function parameter.

The Claude API key is read from the ANTHROPIC_API_KEY environment
variable (see `.env`).

Design note: the LLM is asked to reason about what the function's name,
signature, and docstring say it *should* do, and to derive
`expected_output` from that intended behavior -- not by mentally
executing the (possibly buggy) implementation. That's the whole point of
a bug-repair test suite: it has to encode the correct behavior, not
whatever the current, potentially-defective code happens to produce.
"""
import argparse
import ast
import json
from pathlib import Path
from typing import Dict, List, Tuple

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv(override=True)  # .env's ANTHROPIC_API_KEY wins over a blank/stale shell var

import anthropic
import pandas as pd

# Kept in sync with the castType branches in AbinModel.parse_csv_data.
SUPPORTED_CAST_TYPES = {'int', 'float', 'str', 'list', 'dict'}

DEFAULT_MODEL = "claude-opus-5"


class GeneratedTestCase(BaseModel):
    """ One row of the generated suite, as returned by the model.

    `inputs`/`expected_output` are JSON-encoded literal strings (e.g.
    "42", "\\"hello\\"", "[1, 2, 3]", "true", "null") rather than typed
    fields, so the schema doesn't need to special-case every possible
    parameter type -- they're decoded with json.loads() once on our side.
    """
    test_id: str
    description: str
    inputs: List[str]
    expected_output: str


class TestCaseSuite(BaseModel):
    test_cases: List[GeneratedTestCase]


def get_function_source_and_params(source_path: Path, function_name: str) -> Tuple[str, List[str]]:
    """ Returns the target function's source text and parameter names,
    in declaration order.

    :param source_path: Path to the .py file containing the function.
    :type  source_path: Path
    :param function_name: The target function's name.
    :type  function_name: str
    :rtype: Tuple[str, List[str]]
    """
    tree = ast.parse(source_path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            params = [arg.arg for arg in node.args.args]
            return ast.unparse(node), params
    raise ValueError(f"Function '{function_name}' not found in {source_path}")


def build_prompt(function_source: str, function_name: str, params: List[str], num_cases: int) -> str:
    """ Builds the test-generation prompt for the given function.
    :rtype: str
    """
    return f"""You are a senior SDET designing a minimal-but-thorough unit test suite \
for the Python function `{function_name}` below.

SOURCE:
```python
{function_source}
```

IMPORTANT: The implementation above may be BUGGY -- that is the whole point \
of this exercise. Reason about what the function's name, parameters, and \
docstring say it SHOULD do, and derive `expected_output` from that intended \
behavior, NOT by mentally executing the code as written. If the current \
implementation looks wrong for a case, your expected_output should reflect \
the CORRECT behavior, not whatever this code would currently produce.

METHODOLOGY:
1. Equivalence partitioning: typical valid inputs, and distinct classes of \
invalid/edge inputs where they make sense for this function.
2. Boundary value analysis: minimums, maximums, empty collections, zero, \
values immediately at/around any comparison thresholds you can infer.
3. Condition coverage: for compound boolean logic, pick inputs that flip \
each individual condition's truth value independently (MC/DC).
4. Avoid redundant tests -- one test per distinct logical path/case.

OUTPUT REQUIREMENTS:
- Generate approximately {num_cases} test cases.
- The function's parameters, in order, are: {', '.join(params)}.
- For each test case, `inputs` must be a list of exactly {len(params)} \
strings, one per parameter in that order, each a JSON-encoded literal \
(e.g. "42", "3.14", "\\"hello\\"", "[1, 2, 3]", "true", "null").
- `expected_output` must likewise be a single JSON-encoded literal string.
- `test_id` values must be unique (e.g. T001, T002, ...).
- `description` is a short one-line rationale for what the case covers.
"""


def _to_csv_cell(value, cast_type: str) -> str:
    """ Renders a decoded JSON value as the raw text a CSV cell needs to
    hold for `parse_csv_data` to reconstruct it under `cast_type`.
    :rtype: str
    """
    if cast_type in ('dict', 'json') or cast_type.startswith('list') or cast_type.startswith('tuple'):
        return json.dumps(value)
    return str(value)


def build_dataframe(suite: TestCaseSuite, params: List[str], param_types: Dict[str, str]) -> pd.DataFrame:
    """ Converts a generated TestCaseSuite into the benchmarks/*.csv shape.
    :rtype: pd.DataFrame
    """
    rows = []
    for tc in suite.test_cases:
        if len(tc.inputs) != len(params):
            # Malformed row (wrong arity) -- skip rather than fail the whole suite.
            continue
        row = {
            'test_cases': tc.test_id,
            'expected_output': repr(json.loads(tc.expected_output)),
        }
        for name, raw in zip(params, tc.inputs):
            cast_type = param_types[name]
            row[f'{name}: {cast_type}'] = _to_csv_cell(json.loads(raw), cast_type)
        rows.append(row)
    columns = ['test_cases', 'expected_output'] + [f'{p}: {param_types[p]}' for p in params]
    return pd.DataFrame(rows, columns=columns)


def build_injectable_dataframe(suite: TestCaseSuite, params: List[str], param_types: Dict[str, str]) -> pd.DataFrame:
    """ Converts a generated TestCaseSuite into the *parsed* shape
    `AbinModel.inject_tests()` expects: bare parameter-name columns
    (no "name: type" suffix) holding real typed Python values -- what
    `AbinModel.parse_csv_data()` itself produces from a CSV file, not
    the raw cell-text shape `build_dataframe()` renders for `write_csv()`.
    :rtype: pd.DataFrame
    """
    rows = []
    for tc in suite.test_cases:
        if len(tc.inputs) != len(params):
            continue
        row = {'test_cases': tc.test_id, 'expected_output': json.loads(tc.expected_output)}
        for name, raw in zip(params, tc.inputs):
            row[name] = json.loads(raw)
        rows.append(row)
    columns = ['test_cases', 'expected_output'] + list(params)
    return pd.DataFrame(rows, columns=columns)


def _generate_suite(source_path: str, function_name: str, param_types: Dict[str, str],
        num_cases: int, model: str) -> Tuple[TestCaseSuite, List[str]]:
    """ Calls Claude to generate a TestCaseSuite for the target function.

    Shared by `generate_test_cases()` and `generate_injectable_test_cases()`
    -- they differ only in which shape they render the result into.
    :rtype: Tuple[TestCaseSuite, List[str]]
    """
    path = Path(source_path)
    function_source, params = get_function_source_and_params(path, function_name)

    missing = [p for p in params if p not in param_types]
    if missing:
        raise ValueError(
            f"Missing type for parameter(s): {', '.join(missing)}. "
            f"Supported types: {sorted(SUPPORTED_CAST_TYPES)}."
        )

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY (see .env)
    prompt = build_prompt(function_source, function_name, params, num_cases)

    response = client.messages.parse(
        model=model,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
        output_format=TestCaseSuite,
    )
    return response.parsed_output, params


def generate_injectable_test_cases(source_path: str, function_name: str, param_types: Dict[str, str],
        num_cases: int = 10, model: str = DEFAULT_MODEL) -> pd.DataFrame:
    """ Generates an AI-authored test suite ready for
    `AbinModel.inject_tests()` -- same parameters as `generate_test_cases`,
    but returns the parsed (bare-column, typed-value) shape instead of
    the CSV-file shape.
    :rtype: pd.DataFrame
    """
    suite, params = _generate_suite(source_path, function_name, param_types, num_cases, model)
    return build_injectable_dataframe(suite, params, param_types)


def generate_test_cases(source_path: str, function_name: str, param_types: Dict[str, str],
        num_cases: int = 10, model: str = DEFAULT_MODEL) -> pd.DataFrame:
    """ Generates an AI-authored test suite for a target function.

    :param source_path: Path to the .py file containing the function.
    :type  source_path: str
    :param function_name: The target function's name.
    :type  function_name: str
    :param param_types: Maps each parameter name to a CSV cast type
        (one of SUPPORTED_CAST_TYPES).
    :type  param_types: Dict[str, str]
    :param num_cases: Roughly how many test cases to request.
    :type  num_cases: int
    :param model: The Claude model to use.
    :type  model: str
    :rtype: pd.DataFrame
    """
    suite, params = _generate_suite(source_path, function_name, param_types, num_cases, model)
    return build_dataframe(suite, params, param_types)


def write_csv(df: pd.DataFrame, output_path: str) -> None:
    """ Writes a generated test suite DataFrame to a CSV file.
    :rtype: None
    """
    df.to_csv(output_path, index=False)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate an AI-authored CSV test suite for a Python function."
    )
    parser.add_argument("source", help="Path to the .py file containing the target function")
    parser.add_argument("function", help="Name of the target function")
    parser.add_argument("types", help="Comma-separated name:type pairs, e.g. 'x:int,y:int,z:int'")
    parser.add_argument("-n", "--num-cases", type=int, default=10)
    parser.add_argument("-o", "--output", default=None, help="Output CSV path (default: <function>.csv)")
    parser.add_argument("-m", "--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    param_types = dict(pair.split(":") for pair in args.types.split(","))
    df = generate_test_cases(args.source, args.function, param_types, args.num_cases, args.model)
    output_path = args.output or f"{args.function}.csv"
    write_csv(df, output_path)
    print(f"Wrote {len(df)} test cases to {output_path}")


if __name__ == "__main__":
    main()
