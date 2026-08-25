"""
Minimal Flask frontend for AbinDebugger.

Mirrors cli.py's flags (--model, --tests, --func, --complexity, --schema,
--generate-ai-tests, --ai-model) as a single HTML form, driving the same
AbinModel / generate_injectable_test_cases calls the CLI uses. Blocking
request/response -- no streaming, no background jobs -- since the repair
loop is CPU-bound and this is a single-user local tool.

Run from the project root (paths in the form are resolved relative to
the process's working directory, same as cli.py):

    python3 frontend/app.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from flask import Flask, render_template, request

import cli  # noqa: F401 -- import runs cli.load_settings(), wiring DebugController.APP_SETTINGS
from AbinModel import AbinModel, parse_csv_data
from model.HypothesisRefinement import AbductionSchema
from model.misc.generate_test_cases import DEFAULT_MODEL, generate_injectable_test_cases

app = Flask(__name__)

SCHEMA_MAP = {
    "DFS": AbductionSchema.DFS,
    "BFS": AbductionSchema.BFS,
    "A_STAR": AbductionSchema.A_star,
}


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", ai_model_default=DEFAULT_MODEL)


@app.route("/run", methods=["POST"])
def run():
    model_path = request.form["model"]
    tests_path = request.form["tests"]
    func_name = request.form["func"]
    complexity = int(request.form.get("complexity") or 3)
    schema = request.form.get("schema", "DFS")
    num_ai_tests = int(request.form.get("generate_ai_tests") or 0)
    ai_model = request.form.get("ai_model") or DEFAULT_MODEL

    try:
        df = pd.read_csv(tests_path, keep_default_na=False)
    except Exception as e:
        return render_template("result.html", error=f"Failed to load test suite '{tests_path}': {e}")

    test_cases, parsed_types = parse_csv_data(df)

    try:
        abin = AbinModel(
            function_name=func_name,
            bugged_file_path=model_path,
            test_suite=test_cases,
            max_complexity=complexity,
            abduction_schema=SCHEMA_MAP[schema],
        )
    except Exception as e:
        return render_template("result.html", error=f"Failed to initialize AbinModel: {e}")

    ai_log = None
    ai_error = None
    if num_ai_tests > 0:
        param_types = dict(zip(parsed_types["input_args"], parsed_types["type"]))
        try:
            ai_tests = generate_injectable_test_cases(
                source_path=model_path,
                function_name=func_name,
                param_types=param_types,
                num_cases=num_ai_tests,
                model=ai_model,
            )
        except Exception as e:
            ai_error = str(e)
        else:
            abin.inject_tests(ai_tests)
            ai_log = f"Injected {len(ai_tests)} AI-generated test case(s). Test suite size: {len(abin.test_suite)}"

    try:
        repaired_code, behavior, prev_observation, new_observation = abin.start_auto_debugging()
    except Exception as e:
        return render_template("result.html", error=f"Debugging run failed: {e}")

    if repaired_code:
        status, message, code = "success", "SUCCESSFUL REPAIR! Found candidate fix:", "\n".join(repaired_code)
    elif behavior.name == "Valid":
        status, message, code = "valid", "NO DEFECT FOUND. All tests passed on the original model.", None
    else:
        status, message, code = "failed", "UNABLE TO REPAIR. No candidate hypotheses passed the test suite.", None

    return render_template(
        "result.html",
        status=status,
        message=message,
        code=code,
        ai_log=ai_log,
        ai_error=ai_error,
        func_name=func_name,
        model_path=model_path,
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
