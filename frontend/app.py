"""
Minimal Flask frontend for AbinDebugger.

Mirrors cli.py's flags (--model, --tests, --func, --complexity, --schema,
--generate-ai-tests, --ai-model) as an HTML form -- model/tests files and
target functions are auto-detected instead of typed in, and the run
streams live progress into an in-page terminal panel instead of a
separate results page.

Can be started from anywhere -- it chdirs to the project root itself,
so form paths and config.py's relative paths (e.g. SQLITE_DB_PATH)
resolve consistently either way:

    python3 frontend/app.py
    # or
    cd frontend && python3 app.py

Caveat: the repair run executes in a background thread so it can stream
live while the request/response cycle stays free for the browser's SSE
connection. AbinModel's per-test timeout is signal-based
(signal.setitimer), which in CPython only interrupts the *main* thread
-- armed from a background thread it still fires, but on the main
thread, not the one actually running the (possibly hung) candidate. A
genuinely infinite-looping candidate can therefore hang a run
indefinitely in this UI. cli.py runs on the main thread and does not
have this limitation.
"""
import ast
import json
import logging
import os
import queue
import sys
import threading
import uuid
from pathlib import Path
from textwrap import dedent

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)  # config.py's relative paths (e.g. SQLITE_DB_PATH)
                         # and cli.py's convention both assume cwd == project
                         # root; enforce that regardless of where this was
                         # launched from. (Requires use_reloader=False below --
                         # Werkzeug's reloader re-execs using a relative script
                         # path that breaks once cwd has moved.)

import pandas as pd
from flask import Flask, Response, jsonify, render_template, request

import cli  # noqa: F401 -- import runs cli.load_settings(), wiring DebugController.APP_SETTINGS
import logger as AbinLogging
from AbinModel import AbinModel, parse_csv_data
from model.HypothesisRefinement import AbductionSchema
from model.misc.generate_test_cases import DEFAULT_MODEL, generate_injectable_test_cases

app = Flask(__name__)

SCHEMA_MAP = {
    "DFS": AbductionSchema.DFS,
    "BFS": AbductionSchema.BFS,
    "A_STAR": AbductionSchema.A_star,
}

BENCHMARKS_DIR = PROJECT_ROOT / "benchmarks"

RUNS = {}  # run_id -> queue.Queue, populated by _execute_run, drained by /stream
_DONE = object()  # sentinel marking end-of-stream on a run's queue


def resolve_path(raw: str) -> str:
    """ Resolves a form path against the project root, not the process's
    cwd -- so "benchmarks/Middle.py" works the same whether the server
    was started from the project root or from inside frontend/.
    :rtype: str
    """
    path = Path(raw)
    return str(path if path.is_absolute() else PROJECT_ROOT / path)


def list_benchmark_files():
    """ Auto-detects available model (.py) and test-suite (.csv) files
    under benchmarks/, as project-root-relative paths.
    :rtype: Tuple[List[str], List[str]]
    """
    if not BENCHMARKS_DIR.is_dir():
        return [], []
    models = sorted(f"benchmarks/{p.name}" for p in BENCHMARKS_DIR.glob("*.py"))
    tests = sorted(f"benchmarks/{p.name}" for p in BENCHMARKS_DIR.glob("*.csv"))
    return models, tests


def list_functions(model_path: str) -> list:
    """ Auto-detects top-level function names defined in a .py file.
    :rtype: List[str]
    """
    tree = ast.parse(Path(model_path).read_text())
    return [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


class _QueueLogHandler(logging.Handler):
    """ Forwards a single run's debugging_logger records into its SSE
    queue, filtered to the run's own worker thread so concurrent runs
    (e.g. two browser tabs) never cross-talk. """

    def __init__(self, q: queue.Queue, thread_id: int):
        super().__init__()
        self.q = q
        self.thread_id = thread_id

    def emit(self, record: logging.LogRecord) -> None:
        if record.thread != self.thread_id:
            return
        message = dedent(str(record.getMessage())).strip()
        if message:
            self.q.put(message)


def _execute_run(run_id: str, q: queue.Queue, form: dict) -> None:
    """ Runs one debugging session (mirrors cli.py's main()), pushing
    each progress line into `q` as it happens instead of printing.
    Runs on a background thread -- see the module docstring's caveat
    about signal-based per-test timeouts. """
    handler = _QueueLogHandler(q, threading.get_ident())
    logger_obj = AbinLogging.debugging_logger
    prev_level = logger_obj.level
    logger_obj.addHandler(handler)
    logger_obj.setLevel(logging.INFO)  # force visibility for the live terminal, regardless of .env LOG_LEVEL
    try:
        model_path = resolve_path(form.get("model", ""))
        tests_path = resolve_path(form.get("tests", ""))
        func_name = form.get("func", "")
        complexity = int(form.get("complexity") or 3)
        schema = form.get("schema", "DFS")
        num_ai_tests = int(form.get("generate_ai_tests") or 0)
        ai_model = form.get("ai_model") or DEFAULT_MODEL
        api_key = form.get("api_key") or None  # never logged, never persisted -- used for this run only

        q.put(f"Loading test suite from {tests_path}...")
        try:
            df = pd.read_csv(tests_path, keep_default_na=False)
        except Exception as e:
            q.put(f"[error] Failed to load test suite: {e}")
            return
        test_cases, parsed_types = parse_csv_data(df)

        q.put(f"Initializing repair for '{func_name}' in '{model_path}'...")
        q.put(f"Complexity: {complexity} | Schema: {schema}")
        try:
            abin = AbinModel(
                function_name=func_name,
                bugged_file_path=model_path,
                test_suite=test_cases,
                max_complexity=complexity,
                abduction_schema=SCHEMA_MAP[schema],
            )
        except Exception as e:
            q.put(f"[error] Failed to initialize AbinModel: {e}")
            return

        if num_ai_tests > 0:
            param_types = dict(zip(parsed_types["input_args"], parsed_types["type"]))
            q.put(f"Generating {num_ai_tests} AI-authored test case(s) via {ai_model}...")
            try:
                ai_tests = generate_injectable_test_cases(
                    source_path=model_path,
                    function_name=func_name,
                    param_types=param_types,
                    num_cases=num_ai_tests,
                    model=ai_model,
                    api_key=api_key,
                )
            except Exception as e:
                q.put(f"[error] AI test generation failed: {e}. Continuing without AI-generated tests.")
            else:
                abin.inject_tests(ai_tests)
                q.put(f"Injected {len(ai_tests)} AI-generated test case(s). Test suite size: {len(abin.test_suite)}")

        try:
            repaired_code, behavior, prev_observation, new_observation = abin.start_auto_debugging()
        except Exception as e:
            q.put(f"[error] Debugging run failed: {e}")
            return

        if repaired_code:
            result = {"status": "success", "message": "SUCCESSFUL REPAIR! Found candidate fix:",
                      "code": "\n".join(repaired_code)}
        elif behavior.name == "Valid":
            result = {"status": "valid", "message": "NO DEFECT FOUND. All tests passed on the original model.",
                      "code": None}
        else:
            result = {"status": "failed",
                      "message": "UNABLE TO REPAIR. No candidate hypotheses passed the test suite.", "code": None}
        q.put("RESULT::" + json.dumps(result))
    finally:
        logger_obj.removeHandler(handler)
        logger_obj.setLevel(prev_level)
        q.put(_DONE)


@app.route("/", methods=["GET"])
def index():
    models, tests = list_benchmark_files()
    return render_template("index.html", ai_model_default=DEFAULT_MODEL, models=models, tests=tests)


@app.route("/functions", methods=["GET"])
def functions():
    model = request.args.get("model", "")
    if not model:
        return jsonify({"functions": []})
    try:
        return jsonify({"functions": list_functions(resolve_path(model))})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/run", methods=["POST"])
def run():
    run_id = uuid.uuid4().hex
    q = queue.Queue()
    RUNS[run_id] = q
    threading.Thread(target=_execute_run, args=(run_id, q, request.form.to_dict()), daemon=True).start()
    return jsonify({"run_id": run_id})


@app.route("/stream/<run_id>", methods=["GET"])
def stream(run_id):
    q = RUNS.get(run_id)
    if q is None:
        return jsonify({"error": "unknown run_id"}), 404

    def generate():
        while True:
            item = q.get()
            if item is _DONE:
                yield "event: done\ndata: {}\n\n"
                break
            for line in str(item).splitlines() or [""]:
                yield f"data: {line}\n\n"
        RUNS.pop(run_id, None)

    return Response(generate(), mimetype="text/event-stream")


if __name__ == "__main__":
    app.run(debug=True, port=5000, use_reloader=False, threaded=True)
