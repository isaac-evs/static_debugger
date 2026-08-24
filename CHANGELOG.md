# Changelog

A log of notable fixes and architectural changes, with the reasoning
behind each one. Newest first.

## Fix short-circuited predicate that silently dropped bound methods

**Module:** `model/core/AbinDebugger.py` (`get_all_func_names`)

**Description:** `getmembers(module, isfunction or ismethod)` &mdash; since
`isfunction` is itself a truthy function object, `isfunction or ismethod`
evaluates to `isfunction` alone at the `or` expression, before `getmembers`
is even called; `ismethod` is never consulted.

**Impact:** Any module-level bound method reference would be silently
excluded from the function names used to filter suspicious-ranking
events, since it's neither caught by `isfunction` nor ever checked
against `ismethod`.

**Fix:** Replaced the bare `isfunction or ismethod` with an actual
predicate function, `lambda obj: isfunction(obj) or ismethod(obj)`.

**Verified:** A module-level plain function and a module-level bound
method reference are both now found by `get_all_func_names` (only the
plain function was found before the fix). Full `Middle.py` benchmark
unaffected.

---

## Stop stripping string literals out of reconstructed logical lines

**Module:** `model/abstractor/PythonLLOC.py` (`logical_LOC`)

**Description:** When reconstructing a logical line of code from tokenize
output, every `STRING` token was unconditionally skipped, regardless of
whether it was a standalone docstring or part of a larger statement.

**Impact:** Any string literal embedded in a real statement (e.g.
`elif c == "x" or c == "y":`) got stripped out along with genuine
docstrings, producing broken text like `elif c == or c == :`. Verified
directly with that exact input.

**Fix:** Track the tokens on each logical line separately from the
reconstructed text. A line is only treated as a skippable
docstring/bare-string statement when its *entire* content is a single
`STRING` token (nothing else) &mdash; any string that's part of a larger
statement is now preserved.

**Verified:** The exact reproduction (`elif c == "x" or c == "y":`) now
reconstructs correctly; a true docstring-only line still correctly
returns `None`; plain code with no strings and code with embedded string
comparisons/assignments are all unaffected. Full `Middle.py`/
`HappyNumber.py`/`PasswordStrength.py` benchmarks unaffected.

---

## Remove unused clean_temporal_files (crashes if called, has no callers)

**Module:** `model/FaultLocalizator.py`

**Description:** `clean_temporal_files` used `with curr_dir.joinpath('temp') as temp_dir:`
&mdash; `pathlib.Path` doesn't implement the context manager protocol, so
calling this method would immediately crash with
`AttributeError: 'PosixPath' object has no attribute '__enter__'`.

**Finding:** Not reachable in practice: it has no callers anywhere in the
codebase. It existed to clean up the `temp/` directory from the old
disk-based candidate-writing workflow, which was already removed
(`model/HypothesisGenerator.py` no longer writes candidates to disk).

**Fix:** Deleted the method instead of fixing a bug in dead code, along
with the `pathlib`/`shutil` imports that existed only to support it.

---

## Compare typed test results instead of their string representations

**Module:** `AbinModel.py` (`parse_csv_data`), `model/core/ModelTester.py` (`model_testing`)

**Description:** Test assertions compared `str(test_result) == str(expected_output)`.
`expected_output` has no `:type` annotation in the CSV (unlike input-arg
columns, which already use `json.loads` for `list`/`tuple`/`dict`), so it
was always left as a raw string.

**Impact:** `str()`-comparison is both incorrect and formatting-fragile:
`str(1.0) != str(1)` and `str(True) != str(1)` despite being equal values,
and a sequence written as `"[1,2,3]"` in the CSV would never match a
function returning `[1, 2, 3]` (Python's own `str()` adds a space after
each comma) even though the values are identical.

**Fix:** Added `coerce_expected_output()`, applied to the whole
`expected_output` column in `parse_csv_data`: tries `ast.literal_eval` to
recover the real typed value (int/float/bool/None/list/tuple/dict/...),
falling back to the raw string when the cell isn't a valid literal (e.g.
unquoted text like a password-strength label). `model_testing` now
compares `test_result == expected_output` directly (wrapped in a
try/except, so an exotic `__eq__` can't crash the test loop) instead of
stringifying both sides.

**Verified:** All three failure modes above now pass correctly
(`[1,2,3]`-vs-`[1, 2, 3]`, `True`-vs-`"1"`, `1.0`-vs-`"1"`). Full
`Middle.py`/`HappyNumber.py`/`BitonicSort.py` benchmarks unaffected.

---

## Fix constant abstraction corrupted by deprecated ast.Num/ast.Str shims

**Module:** `model/abstractor/NodeMapper.py`, `NodeAbstractor.py`, `HypothesisAbductor.py`

**Description:** The identifier-attribute list used for abstraction was
hardcoded as `['id', 'n', 's', 'name', 'asname', 'module', 'attr', 'arg']`.
`ast.Num`/`ast.Str` (`.n`/`.s`) were deprecated in favor of `ast.Constant`
(`.value`) back in Python 3.8, but kept as compatibility shims that proxy
straight to `.value` &mdash; on Python 3.12 those shims make `hasattr(node, 'n')`
*and* `hasattr(node, 's')` both `True` for every `Constant` node.

**Impact:** Worse than "ignored": every numeric/string/bool/None constant
got abstracted *twice*. The first pass correctly mapped it to a label; the
second pass read that label back through the *other* shim (since both
proxy to the same `.value`), treated it as a brand new token, and
overwrote it with a second, wrong label &mdash; corrupting the identifier
mapping and the resulting pattern hexdigest for every constant. Verified
directly: abstracting the literal `42` produced `map_ids={'42':
'Constant0', 'Constant0': 'Constant1'}` and left `node.value` as the
string `'Constant1'` instead of a usable label for `42`.

**Fix:** Replaced `'n'`/`'s'` with `'value'` in all four occurrences of the
identifier list, guarded by a new `has_identifier_attr()` helper that only
treats `'value'` as an identifier on `ast.Constant` nodes specifically
(`.value` is also a plain child-node field on `Attribute`, `Subscript`,
`Return`, `Assign`, etc., which must never be abstracted the same way).
Also fixed the companion type-coercion logic in
`HypothesisAbductor.abduct_node`, which used to special-case node types
named `'Num'`/`'Bytes'` to restore a substituted string back to a real
int/float/complex/bytes &mdash; those never fire for a unified `Constant`
label, so also added explicit `None`/`bool` handling.

**Verified:** Abstracting `42`/`3.14`/`'hello'`/`True`/`None` each now
produces exactly one clean label with no corruption. A full abduction
round-trip (`return 1` &rarr; `return 99`-style fix pattern, offering
candidate tokens `1`/`42`/`100`) produces real integer literals
(`return 42`) rather than quoted strings (`return '42'`). Confirmed the
pre-fix code reproduces the exact corruption described above. Full
`Middle.py`/`HappyNumber.py` benchmarks unaffected (neither exercises
constant abstraction).

---

## Remove unused inspect.getsource()-based code

**Module:** `model/core/AbinDebugger.py`, `model/debugger/StatisticalDebugger.py`

**Description:** `AbinDebugger.get_model_ast` and `SpectrumDebugger.code()`
(plus its `_repr_html_`/`__str__`/`__repr__` wrappers) had no callers
anywhere in the codebase &mdash; `get_model_ast` is simply never invoked, and
`SpectrumDebugger`'s `__str__`/`__repr__` are fully shadowed in
`AbinDebugger`'s MRO by `RankingDebugger`'s (confirmed via `__mro__`
inspection), so `code()` could never actually run.

**Fix:** Deleted both, rather than keep unused surface area around. Also
removes the module's last usage of `cgitb` (deprecated since 3.11, removed
entirely in 3.13) and `inspect`, since nothing else in the file needed them.

---

## Pin candidate comparisons to a stable baseline instead of a drifting one

**Module:** `AbinModel.py` (`_search`)

**Description:** Candidate hypotheses are evaluated by comparing their test
observations against a baseline (`prev_observation`). Inside the sibling
hypothesis loop, that same variable was also being reassigned to whatever a
nested recursive dive (triggered by an earlier sibling's `Improvement`)
happened to return.

**Impact:** A sibling hypothesis tried *after* another one triggered a
recursive dive was compared against that unrelated deeper candidate's
leftover observation instead of the actual baseline, instead of the
original unpatched program's behavior &mdash; corrupting `Behavior`
classification (Improvement/Same/Worsened) for every subsequent sibling at
that search depth and making sequential runs non-deterministic.

**Fix:** Introduced `baseline_observation`, captured once per
localizator/model and left untouched by recursive calls; every hypothesis
evaluated against the *same* set of siblings now uses it. `prev_observation`
still tracks the current best result for return-value/refinement bookkeeping,
but is no longer conflated with the comparison baseline. The baseline is
only refreshed when a genuinely new starting point is drawn (a refinement
retry re-runs `model_testing()` on a different improvement candidate).

**Verified:** A targeted reproduction (two sibling hypotheses where the
first triggers a recursive dive returning a different observation shape)
confirmed the second sibling was compared against the dive's leftover
result pre-fix, and against the correct original baseline post-fix. Full
`Middle.py` benchmark (all three schemas) unaffected.

---

## Fix dangling SIGALRM leaking across sequential test runs

**Module:** `model/core/ModelTester.py` (`model_testing`), `model/core/AbinDebugger.py` (`__exit__`)

**Description:** The test-timeout timer (`signal.setitimer(ITIMER_REAL, TEST_TIMEOUT)`)
was armed inside `with debugger:` and disarmed (`setitimer(..., 0)`) on the
line right after the block, with no `try`/`finally` between them.

**Impact:** When a candidate patch caused a runtime exception, some
exception paths make `AbinDebugger.__exit__` return `False` (re-raising
instead of swallowing) &mdash; that skips the disarm line entirely, leaving the
OS alarm clock armed in the background. It then fires `SIGALRM`
asynchronously mid-way through a later, unrelated test, crashing it with a
spurious `TimeoutError`.

**Fix:** Wrapped the per-test-case execution in `try`/`finally`, so
`signal.setitimer(ITIMER_REAL, 0)` always runs regardless of which path
`__exit__` takes.

**Verified:** Reproduced the exact re-raise path (a `ModelTester` whose
target function doesn't exist, so no `call` event is ever captured) and
confirmed that before the fix the timer was left armed with ~5 seconds
still pending after the exception propagated; after the fix it's reliably
`(0.0, 0.0)` in every case. Full `Middle.py` benchmark unaffected.

---

## Upgrade SBL tracing to sys.monitoring (PEP 669) and fix function-wrapper cache

**Module:** `model/debugger/Tracer.py`, `model/debugger/StackInspector.py`, `model/debugger/Collector.py`, `model/debugger/AbinCollector.py`
**Requires:** Python 3.12+ (bumped from 3.9; see `.python-version`/`requirements.txt`)

**Description:** SBL instrumentation relied on legacy `sys.settrace` hooks, and
inside the tracing hooks `StackInspector.create_function` was caching by
`(function_name, lineno)` &mdash; a key that changes on almost every traced
line, so it failed to deduplicate and effectively created a new `FunctionType`
wrapper per line anyway.

**Impact:** `sys.settrace` hands a full frame to Python on every single event,
introducing a heavy execution penalty on iterative/recursive code. On top of
that, the ineffective cache meant thousands of redundant `FunctionType`
allocations per test run (measured: a `fib(20)` trace alone would have
produced 87,566 `FunctionType` objects for 2 actual functions), adding GC
pressure on longer benchmark runs.

**Fix:** Replaced `sys.settrace` with `sys.monitoring` (PEP 669) &mdash; the
project now requires Python 3.12+ for this. `sys.settrace` is kept only as a
defensive fallback if a monitoring tool slot can't be claimed. Fixed
`create_function`'s cache to key on the code object itself (unique per
compiled function, constant across every line of one execution, and safe
against cross-run collisions between independently-compiled candidate
models). Added `resolve_function()`, a cached combination of
`search_func`/`create_function`, and switched `CoverageCollector`/
`AbinCollector` to use it instead of duplicating that lookup on every event.
Caches are per-instance (not class-level), so they don't accumulate stale
entries across the lifetime of a long repair session.

Verified: `sys.monitoring` correctly active end-to-end (confirmed via tool-id
introspection), the SIGALRM test-timeout mechanism still interrupts correctly
under the new tracer, the cache fix reduces a `fib(20)` trace from 87,566
`FunctionType` allocations down to 2, and the full `Middle.py`/`HappyNumber.py`
benchmarks are unaffected.

---

## Extend fault localization to boolean sub-expressions

**Module:** `model/HypothesisGenerator.py`, `model/abstractor/SubExpressionVisitor.py`

**Description:** Spectrum-based localization (Ochiai) ranks suspiciousness
strictly at the Line-of-Code level, but AST pattern synthesis operates at
the AST node/sub-expression level.

**Impact:** If a faulty line contains a compound expression (e.g.
`if check(u) and authorize(p):`), Ochiai flags the entire line, but the
abduction engine had no way to target the specific sub-node that actually
holds the defect &mdash; a fix pattern only matched if it happened to cover
the *entire* line's structure.

**Fix:** Added `get_boolop_operands()`, which decomposes an `if`/`while`
test's boolean chain into its individual operands. `HypothesisGenerator`
now tries the whole-statement candidate first (unchanged default behavior)
and, only if that finds no matching patterns, falls back to matching each
operand individually, splicing the abducted fix back into a standalone
header line. Verified end-to-end with a pattern that only matches a single
operand of a two-operand `and` expression: the fallback correctly finds and
applies it while leaving the sibling operand untouched.

---

## Filter incompatible hypothesis candidates via lightweight symbol table

**Commit:** `704231f`
**Module:** `model/abstractor/HypothesisAbductor.py`, `model/HypothesisGenerator.py`

**Description:** Candidate identifiers were substituted into hypotheses via a
brute-force Cartesian product over every name of the right AST-node category,
with no regard for how the name is actually used (e.g. plugging an int
variable into a `Call.func` slot).

**Impact:** Every nonsensical combination still cost a full test-suite run
before failing with a `NameError`/`TypeError`, wasting significant execution
time on candidates that could never work.

**Fix:** Added `SymbolTable`, which walks the bugged program once and records
best-effort usage evidence per name (ever called, ever subscripted/iterated).
`HypothesisAbductor.infer_template_roles()` determines each abstract label's
structural role from the fix pattern's own AST shape, and `get_possible_ids()`
filters each candidate slot by role before the Cartesian product/test
evaluation stage.

---

## Fix RCE via unsafe eval() of AST pattern metadata

**Commit:** `c7fd06e`
**Module:** `model/abstractor/HypothesisAbductor.py`, `model/abstractor/Bugfix.py`

**Description:** AST nodes were reconstructed from stored pattern metadata
with `eval(dump_src, vars(ast), {})`.

**Impact:** Since `vars(ast)` has no `__builtins__` key, Python silently
injects the real `__builtins__` into it for `eval()`, so a crafted
`abstract_node` string (e.g. from a pattern mined off an untrusted public
repo via `--mine`) could call `__import__`/`open`/etc. and execute arbitrary
code &mdash; a critical Remote Code Execution vulnerability.

**Fix:** Added `SafeASTLiteral.safe_ast_literal_eval()`, which parses the
dump text with `ast.parse()` (pure syntax, nothing executes) and walks the
tree, reconstructing only `ast.AST` subclass calls and literals/lists/tuples.
Anything else raises `ValueError` instead of running.

---

## Fix tight coupling of search traversal and runtime evaluation

**Commit:** `55cfd4f`
**Module:** `AbinModel.py` (`start_auto_debugging`)

**Description:** DFS/BFS/A* search traversal, DB-backed hypothesis
generation, and test-suite evaluation were mixed into one monolithic
recursive method that mutated `self.bugfixing_hyphotesis`/`self.candidate`
on every stack frame.

**Impact:** On DFS backtracking, a parent frame's own (unrelated) hypothesis
could silently overwrite a child frame's actual winning fix before it
propagated back up.

**Fix:** Added `SearchSchema` (stateless DFS/BFS/A* traversal strategies) and
`EvaluationEngine` (pure candidate evaluation, no shared state). Split
`start_auto_debugging` into a thin public entry point and a private
`_search` that returns a pure `SearchResult` &mdash; including the actual
winning hypothesis/candidate/depth &mdash; instead of relying on instance
attributes mutated across recursive frames.

---

## Fix state mutation via disk scraping & dynamic import contamination

**Commit:** `4669e3c`
**Module:** `model/HypothesisGenerator.py`, `model/core/ModelTester.py`, `model/HyphotesisTester.py`

**Description:** To test candidate repair hypotheses, the engine wrote
physical temporary files to disk (`temp/model{N}.py`), guessed line
indentation with a regex (`re.split('\w', ...)`), and dynamically
re-imported the file via `importlib` spec loaders.

**Impact:** Running concurrent test suites or parallel debugging sessions on
the same machine caused race conditions where workers overwrote each other's
temporary disk files. Physical disk I/O per candidate also added latency,
and imported modules risked stale bytecode lingering in `sys.modules`.

**Fix:** Replaced the `SourceLoader`/`spec_from_loader`/`module_from_spec`
machinery in `ModelTester` with `compile()` + `exec()` into an isolated
`ModuleType` namespace (no disk I/O, nothing added to `sys.modules`). Replaced
the regex indentation guess in `ModelConstructor.build_hypothesis_model` with
an `ast.NodeTransformer` that splices the hypothesis into the parsed tree.
Removed the dead disk-writing methods in `HypothesisGenerator` that were
unreachable in the live pipeline.

---

## Replace MongoDB daemon dependency with embedded SQLite

**Module:** System-wide architecture (`AbinModel`, `AbinDriver`, `cli.py`)

**Description:** The repair pipeline relied on an external document database
daemon (`mongod` on port 27017) to store and query AST bug patterns.

**Impact:** Requiring developers or CI/CD pipelines to install, configure,
authenticate, and run a separate background database service just to debug
or repair a local Python script introduced excessive usability friction.
Inter-process communication over TCP loopback sockets was also far slower
than in-memory/local-file lookups.

**Fix:** Replaced MongoDB with embedded SQLite (`patterns.db`), using modern
SQLite's native JSON support (`json_extract`, `json_tree`) to index and query
pattern data from a portable, self-contained local file &mdash; no daemon
required.

---

## Headless CLI Orchestrator (decouple GUI)

**Module:** `AbinDriver.py` & Engine Orchestrator

**Description:** The engine was tightly coupled to desktop GUI components
(`pyqtSignalQueue`, `AbinView`).

**Impact:** A true CI/CD-ready or plugin-driven platform can't depend on a
graphical event loop.

**Fix:** Extracted the core repair loop out of the PyQt driver and into a
standalone CLI orchestrator (`cli.py`, using `argparse`). The PyQt interface
is relegated to a completely optional client that merely invokes the CLI.
