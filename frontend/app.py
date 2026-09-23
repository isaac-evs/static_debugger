"""
Minimal Flask frontend for AbinDebugger.

Mirrors cli.py's flags (--model, --tests, --func, --complexity, --schema,
--generate-ai-tests, --ai-model) as an HTML form -- model/tests files and
target functions are auto-detected instead of typed in, and the run
streams live progress into an in-page terminal panel instead of a
separate results page.

Can be started from anywhere -- it chdirs to a fixed directory itself,
so form paths and config.py's relative paths (e.g. SQLITE_DB_PATH)
resolve consistently either way:

    python3 frontend/app.py
    # or
    cd frontend && python3 app.py

When frozen into a desktop app with PyInstaller (see desktop.py), bundled
resources (templates/, benchmarks/) are read from the extracted bundle
(sys._MEIPASS), which is often read-only and wiped between launches, so
writable state (patterns.db) instead lives under ~/.abindebugger. Running
from source, both are just the project root, unchanged from before.

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
import csv
import io
import json
import logging
import os
import queue
import sys
import threading
import time
import uuid
from pathlib import Path
from textwrap import dedent

if getattr(sys, "frozen", False):
    # Inside a PyInstaller bundle: bundled data files (templates/,
    # benchmarks/) live under the extraction root, not next to this file.
    RESOURCE_ROOT = Path(sys._MEIPASS)
    DATA_DIR = Path.home() / ".abindebugger"  # writable, persists across launches
else:
    RESOURCE_ROOT = Path(__file__).resolve().parent.parent
    DATA_DIR = RESOURCE_ROOT

sys.path.insert(0, str(RESOURCE_ROOT))
DATA_DIR.mkdir(parents=True, exist_ok=True)
os.chdir(DATA_DIR)  # config.py's relative paths (e.g. SQLITE_DB_PATH) and
                     # cli.py's convention both assume cwd == a fixed,
                     # writable directory; enforce that regardless of where
                     # this was launched from. (Requires use_reloader=False
                     # below -- Werkzeug's reloader re-execs using a relative
                     # script path that breaks once cwd has moved.)

import pandas as pd
from flask import Flask, Response, jsonify, render_template, request

import cli  # runs cli.load_settings(), wiring DebugController.APP_SETTINGS
import config as DebugController
import logger as AbinLogging
from AbinModel import AbinModel, parse_csv_data
from model.core.ModelTester import PassedTest
from model.HypothesisRefinement import AbductionSchema
from model.misc.generate_test_cases import DEFAULT_MODELS, PROVIDERS, generate_injectable_test_cases

# patterns.db (the mined bug-fix pattern database HypothesisGenerator reads
# from -- read-only outside of cli.py --mine) ships as a bundled resource,
# not writable state, so it must resolve against RESOURCE_ROOT regardless of
# cwd/DATA_DIR. cli.load_settings()'s fallback leaves this as a bare
# relative "patterns.db", which would otherwise silently resolve to an
# empty DB under DATA_DIR and starve the search of every learned pattern.
DebugController.APP_SETTINGS["SQLITE_DB_PATH"] = str(RESOURCE_ROOT / "patterns.db")

app = Flask(__name__, template_folder=str(RESOURCE_ROOT / "frontend" / "templates"))

SCHEMA_MAP = {
    "DFS": AbductionSchema.DFS,
    "BFS": AbductionSchema.BFS,
    "A_STAR": AbductionSchema.A_star,
}

BENCHMARKS_DIR = RESOURCE_ROOT / "benchmarks"

RUNS = {}  # run_id -> queue.Queue, populated by _execute_run, drained by /stream
_DONE = object()  # sentinel marking end-of-stream on a run's queue

RUN_RESULTS = {}  # run_id -> CSV text for /download, populated once a run finishes
_MAX_STORED_RESULTS = 30  # bounds memory for a long-lived local session


def _outcome_label(observation, index: int) -> str:
    """ 'PASSED'/'FAILED' for observation[index], or '' if that index
    doesn't exist (the run never got that far -- e.g. AI test generation
    or AbinModel setup failed before any test executed).

    Observations are positional (same order/length as the test suite
    DataFrame), not name-keyed: a test that never got to execute is
    recorded with the generic name 'UndefinedTest', so correlating by
    name would collide multiple real tests into one row. Index is the
    only reliable join key.
    :rtype: str
    """
    if not observation or index >= len(observation):
        return ""
    return "PASSED" if observation[index][1] is PassedTest else "FAILED"


def _build_results_csv(test_ids, prev_observation, new_observation) -> str:
    """ Renders a before/after pass-fail table as CSV text, joining
    purely by position (see _outcome_label).
    :rtype: str
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["test_case", "before", "after"])
    for i, test_id in enumerate(test_ids):
        writer.writerow([test_id, _outcome_label(prev_observation, i), _outcome_label(new_observation, i)])
    return buf.getvalue()


def resolve_path(raw: str) -> str:
    """ Resolves a form path against the bundled resource root, not the
    process's cwd -- so "benchmarks/Middle.py" works the same whether
    running from source (any launch directory) or from a frozen build.
    :rtype: str
    """
    path = Path(raw)
    return str(path if path.is_absolute() else RESOURCE_ROOT / path)


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
    start_time = time.time()
    try:
        model_path = resolve_path(form.get("model", ""))
        tests_path = resolve_path(form.get("tests", ""))
        func_name = form.get("func", "")
        complexity = int(form.get("complexity") or 3)
        schema = form.get("schema", "DFS")
        num_ai_tests = int(form.get("generate_ai_tests") or 0)
        ai_provider = form.get("ai_provider") or "anthropic"
        ai_model = form.get("ai_model") or DEFAULT_MODELS.get(ai_provider)
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
            q.put(f"Generating {num_ai_tests} AI-authored test case(s) via {ai_provider}/{ai_model}...")
            try:
                ai_tests = generate_injectable_test_cases(
                    source_path=model_path,
                    function_name=func_name,
                    param_types=param_types,
                    num_cases=num_ai_tests,
                    provider=ai_provider,
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

        test_ids = test_cases["test_cases"].tolist()
        before_passed = sum(1 for i in range(len(test_ids)) if _outcome_label(prev_observation, i) == "PASSED")
        after_passed = sum(1 for i in range(len(test_ids)) if _outcome_label(new_observation, i) == "PASSED")
        result["stats"] = {
            "function": func_name,
            "complexity": complexity,
            "schema": schema,
            "hypotheses_tried": abin.abduction_breadth,
            "duration_seconds": round(time.time() - start_time, 2),
            "before_passed": before_passed,
            "after_passed": after_passed,
            "total_tests": len(test_ids),
            "download_url": f"/download/{run_id}.csv",
        }
        if len(RUN_RESULTS) >= _MAX_STORED_RESULTS:
            RUN_RESULTS.pop(next(iter(RUN_RESULTS)))
        RUN_RESULTS[run_id] = _build_results_csv(test_ids, prev_observation, new_observation)

        q.put("RESULT::" + json.dumps(result))
    finally:
        logger_obj.removeHandler(handler)
        logger_obj.setLevel(prev_level)
        q.put(_DONE)


@app.route("/", methods=["GET"])
def index():
    models, tests = list_benchmark_files()
    return render_template(
        "index.html",
        models=models,
        tests=tests,
        providers=PROVIDERS,
        default_models=DEFAULT_MODELS,
    )


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


@app.route("/download/<run_id>.csv", methods=["GET"])
def download(run_id):
    csv_text = RUN_RESULTS.get(run_id)
    if csv_text is None:
        return jsonify({"error": "unknown or expired run_id"}), 404
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="abindebugger_{run_id[:8]}.csv"'},
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000, use_reloader=False, threaded=True)
