# Changelog

A log of notable fixes and architectural changes, with the reasoning
behind each one. Newest first.

## 2026-08-23 &mdash; Filter incompatible hypothesis candidates via lightweight symbol table

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

## 2026-08-21 &mdash; Fix RCE via unsafe eval() of AST pattern metadata

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

## 2026-08-21 &mdash; Fix tight coupling of search traversal and runtime evaluation

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

## 2026-08-21 &mdash; Fix state mutation via disk scraping & dynamic import contamination

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

## 2025-07-20 &mdash; ABD-14: Replace MongoDB daemon dependency with embedded SQLite

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

## 2025-07-20 &mdash; ABD-12: Headless CLI Orchestrator (decouple GUI)

**Module:** `AbinDriver.py` & Engine Orchestrator

**Description:** The engine was tightly coupled to desktop GUI components
(`pyqtSignalQueue`, `AbinView`).

**Impact:** A true CI/CD-ready or plugin-driven platform can't depend on a
graphical event loop.

**Fix:** Extracted the core repair loop out of the PyQt driver and into a
standalone CLI orchestrator (`cli.py`, using `argparse`). The PyQt interface
is relegated to a completely optional client that merely invokes the CLI.
