# AbinDebugger

AbinDebugger automatically finds and fixes bugs in Python functions.

You give it: a Python file with a broken function, and a set of test cases
(inputs plus the output each one *should* produce). It runs your tests,
figures out which line is most likely to blame, tries a series of small
edits at that line, and re-runs your tests after each one. If an edit
makes every test pass, that's your fix.

No AI is required for the core repair engine to work -- it's driven by a
local database of patterns mined from real bug-fix commits on GitHub. AI
(Claude, ChatGPT, or Gemini) is used only for one optional feature:
generating extra test cases for you.

## Is this for me?

If you've never touched this project before, here's the fastest way to
see what it does, no coding required:

1. Someone hands you a double-click app (`AbinDebugger.app` on macOS,
   `AbinDebugger.exe` on Windows) -- open it. See
   [`frontend/DESKTOP_APP.md`](frontend/DESKTOP_APP.md) if you need to
   build that app yourself.
2. In the window that opens, leave the dropdowns on their defaults
   (they're pre-loaded with a small example) and click **Run debugger**.
3. Watch the live output on the right. Within a few seconds it either
   finds a fix or tells you it couldn't.

That's the whole idea. Everything below is for running it from source
instead of the packaged app.

## What's actually happening (in plain terms)

1. **Run the tests.** Some pass, some fail. That tells the tool the
   function is broken *and* gives it concrete examples of what "fixed"
   looks like.
2. **Guess which line is suspicious.** Lines that only run during
   *failing* tests are more suspicious than lines that run during every
   test. This ranking method is called Ochiai, a standard technique in
   automated debugging research.
3. **Try small edits at that line.** Rather than guessing randomly, it
   looks up how similar-looking buggy lines were actually fixed in real
   GitHub commits (a local database of ~31,000 mined bug-fix patterns),
   and tries edits shaped like those fixes.
4. **Re-run the tests after each edit.** If an edit makes every test
   pass, that edit is the fix. If it makes things worse, it's discarded.
   If it's an improvement but not a full fix, the tool recurses and
   tries further edits on top of it.

All of this happens in memory -- candidate code is compiled and executed
in an isolated namespace, nothing is written to disk during the search.

## Three ways to use it

| Way | Who it's for | Where |
|---|---|---|
| **Desktop app** | Anyone, no setup | Double-click `AbinDebugger.app`/`.exe` -- see [`frontend/DESKTOP_APP.md`](frontend/DESKTOP_APP.md) |
| **Web interface** | Comfortable with a terminal, wants a UI | `python3 frontend/app.py`, then open the URL it prints |
| **Command line** | Scripting, CI, automation | `python3 cli.py --model ... --tests ... --func ...` |

All three run the exact same repair engine underneath -- pick whichever
fits how you like to work.

## Installation (running from source)

Requires Python 3.12+.

```bash
git clone <this repo>
cd static_debugger
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Trying it out

The `benchmarks/` folder has ready-to-use examples: a buggy `.py` file
paired with a `.csv` test suite for each one. `Middle.py` (find the
middle of three numbers) is the simplest one to start with.

**Command line:**

```bash
python3 cli.py --model benchmarks/Middle.py --tests benchmarks/Middle.csv --func middle1
```

**Web interface:**

```bash
python3 frontend/app.py
```

Then open the address it prints (usually `http://127.0.0.1:5000`). The
model/tests dropdowns auto-populate from `benchmarks/`, and the function
dropdown auto-populates from whichever model file you pick.

### Writing your own test suite

A test CSV needs a `test_cases` column, an `expected_output` column, and
one column per function parameter named `paramname: type` (supported
types: `int`, `float`, `str`, `list`, `dict`). See any file in
`benchmarks/*.csv` for the exact shape.

### Command-line flags

```
--model PATH         Path to the .py file with the defective function
--tests PATH          Path to the .csv test suite
--func NAME            Name of the function to debug
--complexity N        Max size of a candidate fix (default: 3)
--schema DFS|BFS|A_STAR  Search strategy (default: DFS)
--mine owner/repo      Mine bug-fix patterns from a GitHub repo into the local database, instead of debugging
```

## AI-assisted test case generation (optional)

If you don't have a test suite yet, both the CLI and web interface can
generate one for you with an LLM (Claude, ChatGPT, or Gemini) -- it reads
the target function's signature and docstring and writes test cases for
what the function is *supposed* to do (not what the current, possibly
buggy code happens to do).

This needs an API key for whichever provider you use. Copy `.env.example`
to `.env` and fill in the key(s) you have:

```bash
cp .env.example .env
# then edit .env and paste in ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY
```

CLI: `--generate-ai-tests N` (how many cases), `--ai-provider`, `--ai-model`.
Web interface: click **Configure…** next to "AI-generated test cases" to
pick a provider, model, and (optionally) paste a key just for that run
instead of using `.env`.

## Project layout

```
cli.py                    Command-line entry point
frontend/app.py           Web interface (Flask)
frontend/desktop.py       Desktop app launcher (wraps the web interface in a native window)
frontend/AbinDebugger.spec  Packaging config for the double-click app (PyInstaller)
AbinModel.py               Orchestrates one debugging run
model/                     The repair engine (fault localization, hypothesis generation/testing, evaluation)
model/misc/generate_test_cases.py  AI test case generation
benchmarks/                Example buggy programs + test suites
patterns.db                 Local database of mined bug-fix patterns the search draws from
```

## License

GNU GPLv3 -- see [`LICENSE.md`](LICENSE.md).

## More detail

`CHANGELOG.md` has a running log of notable changes with the reasoning
behind each one, if you want the history of how this project got here.
