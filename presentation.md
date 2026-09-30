---
title: AbinDebugger — Architecture & How AI Was Integrated
---

# Slide 1 — What AbinDebugger is (30 seconds)

- Automatically finds and fixes bugs in Python functions.
- Deterministic core engine: fault localization + a local database of
  mined bug-fix patterns + in-memory candidate testing. **No AI required
  for this to work at all.**
- AI is one optional module bolted onto the side, not a rewrite of the
  core. That separation is the whole story of this deck.
- Say: *"Everything from here on is about where AI sits in the system
  and why I drew the boundary where I did — not about prompt
  engineering."*

---

# Slide 2 — Motor principal: el flujo de AbinDebugger (sin IA)

**PASO 01 — Localización del Fallo**
Rastreo directo en ejecución para aislar la línea defectuosa.

→

**PASO 02 — Generación de Patrones**
Mutación de código basada en ~31k correcciones conocidas.

→

**PASO 03 — Validación en Memoria**
Ejecución inmediata de pruebas sin interactuar con modelos externos.

- This is the whole engine before any AI is involved — three steps,
  looped until a candidate passes every test.
- "Sin interactuar con modelos externos" is the point to land: nothing
  here calls an LLM. This loop worked exactly like this before I ever
  touched the AI feature, and it's what AI plugs into later, not what
  it replaces.

### Antes vs. ahora: cómo se valida un candidato

| | Antes (archivo temporal) | Ahora (validación en memoria) |
|---|---|---|
| Dónde corre | Se escribía el candidato a un archivo `.py` en disco (`config.py` aún tiene un `WORKING_DIR` de esa época, ya sin uso) | `compile()` + `exec()` directo en un namespace aislado, nunca toca disco |
| Riesgo de condición de carrera | Sí — candidatos concurrentes podían pisarse el mismo archivo | Ninguno — cada candidato vive solo en memoria del proceso |
| Contaminación de `sys.modules` | Posible, si el archivo se importaba como módulo | Imposible — se ejecuta en un `ModuleType` desechable, nunca registrado |
| Velocidad | Un I/O de disco por candidato probado | Cientos de candidatos por segundo |

- Say: *"This wasn't an AI change — it's a foundational engineering
  decision this project already made before I started, and it's the
  reason the search can try hundreds of hypotheses per second instead
  of being bottlenecked on disk I/O."*
- Evidence this really happened: `config.py` still carries a dead
  `WORKING_DIR = MAIN_DIR.joinpath('temp')` that nothing in the current
  codebase references anymore — a fossil of the old file-based flow.

---

# Slide 3 — Optimización: caché del rastreador de fallos

**El problema**
El rastreador (quien observa cada línea ejecutada para encontrar el
fallo) creaba un objeto nuevo en memoria por cada línea observada, en
lugar de reutilizar uno solo por función.

**La prueba**
| | Objetos creados |
|---|---|
| Antes | 87,566 |
| Después | 2 |

**+40,000x menos uso de memoria** — y menos trabajo para el recolector
de basura de Python en cada corrida.

- Say: *"Esto es un eje distinto a la mejora de velocidad del
  rastreador (50–100x, de settrace a sys.monitoring) — aquí hablamos
  de memoria, no de velocidad."*

---

# Slide 4 — System architecture (show `architecture.mermaid`)

- Three entry points, one shared core: `cli.py`, the Flask web UI
  (`frontend/app.py`), and a desktop app (`frontend/desktop.py`) that's
  just the Flask app wrapped in a native window via pywebview.
- All three construct the same `AbinModel` object and call the same
  methods — no duplicated repair logic anywhere.
- The repair engine (fault localization → hypothesis generation →
  in-memory testing) is a closed loop that never talks to an LLM.
- AI test generation sits **beside** that loop, not inside it — it only
  ever produces one artifact (a test suite) and hands it off through a
  single method call.
- Say: *"Three doors, one house. Pick whichever entry point fits how
  someone wants to work — the engine underneath doesn't change."*

---

# Slide 5 — Design principle: keep AI at the edge, not the core

- Everything that decides *whether a patch is correct* stays
  deterministic: re-run the tests, compare pass/fail. No LLM judgment
  calls in that path.
- AI's only job: help produce a better/larger **test suite** before the
  search starts. It never touches fault localization, patch generation,
  or which candidate wins.
- Why this boundary, architecturally:
  - Keeps the core engine's behavior explainable and reproducible —
    same tests in, same search, every time.
  - AI failures (bad key, rate limit, malformed response) degrade
    gracefully to "you just don't get extra tests" instead of corrupting
    the repair itself.
  - Testable in isolation: the AI module has its own inputs/outputs
    (`TestCaseSuite`) independent of the search engine's internals.

---

# Slide 6 — The integration seam: one method, not a framework

- Original scope on the table: a full "Plugin Hub" — subprocess
  isolation, a stdin/stdout JSON protocol, language-agnostic third-party
  plugins.
- I stopped and asked: who actually writes a plugin for this today?
  Nobody. Adding process lifecycle management and a versioned wire
  protocol for zero current consumers is complexity with no payoff.
- What shipped instead: **`AbinModel.inject_tests(df)`** — one method.
  Validates the incoming DataFrame's shape, appends it to the live test
  suite, and keeps the search engine's own internal copy
  (`evaluation_engine.test_suite`) in sync.
- This is the architectural takeaway to lead with: *start at the
  smallest interface that solves the real problem; only generalize into
  a framework once there's a second real consumer asking for it.*

---

# Slide 7 — Provider abstraction: one interface, three backends

- Claude, ChatGPT, and Gemini all have different SDKs and different
  method names — that's an implementation detail, not something the
  rest of the system should know about.
- Pattern used: a single dispatch table (`provider name -> call
  function`), each backend function normalized to return the exact same
  shape (`TestCaseSuite`, one schema, shared by all three).
- Everything downstream (CSV building, `inject_tests()`, the CLI flag,
  the web UI) only ever sees that one shape — it has no idea which
  provider actually produced it.
- Consequence: adding a fourth provider later is a one-function change
  in one file. Nothing else in the system moves.

---

# Slide 8 — Concurrency & security design

- The web/desktop UI needs to stream live progress while a run is in
  flight — a plain request/response can't do that, so the actual repair
  runs on a background thread while the HTTP request stays free to
  stream Server-Sent Events back to the browser.
- I initially assumed running the search on a background thread broke
  the engine's per-test timeout (signal handlers only reliably fire on
  the main thread in CPython) — documented it as a known gap, then
  actually traced the mechanism instead of trusting that assumption:
  the timeout doesn't rely on a signal interrupting the thread
  directly. It flips a shared flag that the execution tracer polls
  *on whichever thread is running the candidate*, so ordinary hung code
  is still caught correctly here. Corrected the docs once I found that.
  Later that same mechanism turned out to be the reason the Windows
  build crashed on launch (`SIGALRM` doesn't exist there) — and because
  the signal only ever set a flag, swapping it for a `threading.Timer`
  fixed Windows without touching the interruption logic. The one real gap — a C-level block with no Python trace
  events — is what the new Abort button covers.
- API keys: entered per-request in the UI, used to construct that one
  API call, then discarded — never written to disk, never logged, never
  stored server-side. Verified by blanking the `.env` key and confirming
  generation still worked from the in-page field alone.

---

# Slide 9 — Packaging: reusing the same architecture, not rebuilding it

- Considered a Rust rewrite and an async (FastAPI) rewrite for the
  desktop-distribution problem. Rejected both — neither one touches the
  actual bottleneck, which was *distribution friction*, not runtime
  performance.
- Desktop app = the same Flask app, unmodified, running in a
  `pywebview` native window, packaged with PyInstaller. Zero duplicated
  logic between "web mode" and "desktop mode."
- One real bug this surfaced: a frozen bundle can be read-only and gets
  re-extracted per launch, so the app had to explicitly separate
  *read-only bundled resources* (code, `patterns.db`) from *writable
  per-user state* — a distinction the source-mode app never had to make
  before packaging forced it to be explicit.

---

# Slide 10 — Wrap-up: the architecture decisions that mattered

1. AI lives at the edge of the system (test generation only), never in
   the decision loop that judges correctness.
2. One method (`inject_tests`) instead of a plugin framework — sized to
   the actual, current problem.
3. One provider interface, three interchangeable backends behind it.
4. Concurrency tradeoffs stated explicitly, not buried.
5. Packaging reused the existing architecture instead of forking it for
   a different runtime.
- Say: *"None of this was AI writing code unsupervised — every one of
  these was a scoping decision I made and then verified against the
  running system."*
