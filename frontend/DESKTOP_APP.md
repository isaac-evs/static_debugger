# AbinDebugger desktop app

A packaged version of the frontend for someone who shouldn't have to touch a
terminal: one double-click app, no Python install, no `pip`, no browser
address bar. Same Flask app underneath, running in a native window via
[pywebview](https://pywebview.flowrl.com/).

## For you: building and sending it

**Easiest: GitHub Actions.** In this repo on GitHub, go to Actions ->
"Build desktop app" -> Run workflow. It builds both macOS and Windows
versions (they can't be cross-compiled -- each runs on that OS) and attaches
them as downloadable artifacts on the run's page. Download the one you need,
zip it if it isn't already, and send it over (email, Drive, whatever).

**Building locally instead** (only works for your own OS):

```bash
pip install -r requirements.txt -r requirements-desktop.txt
pyinstaller frontend/AbinDebugger.spec --noconfirm
```

Output: `dist/AbinDebugger.app` (macOS) or `dist/AbinDebugger/` (Windows,
a folder -- zip the whole folder before sending).

## For the PI: running it

**macOS:** unzip if needed, then double-click `AbinDebugger.app`. The first
time, macOS will refuse with "cannot be opened because the developer cannot
be verified" (the app isn't code-signed by an Apple developer account) --
right-click the app instead and choose **Open**, then click **Open** again
in the dialog. Only needed once.

**Windows:** unzip, open the `AbinDebugger` folder, double-click
`AbinDebugger.exe`. Windows SmartScreen will likely show "Windows protected
your PC" for the same reason (unsigned) -- click **More info**, then
**Run anyway**. Only needed once.

After that, a window opens with the same form/live-terminal UI as the
browser version. No install step, nothing else to configure. Clicking
"Configure…" next to AI-generated test cases opens a small dialog to pick
a provider (Claude, ChatGPT, or Gemini) and paste an API key for that run --
otherwise they can leave it at 0 and use the debugger with the built-in
example benchmarks as-is.

## Known limitations

- **Runs the actual repair on a background thread** (needed so the app
  window stays responsive while streaming live progress). AbinModel's
  per-test timeout is signal-based and only reliably interrupts the main
  thread, so a genuinely infinite-looping candidate could hang a run with
  no recovery but closing and reopening the app. Not a concern for the
  bundled example benchmarks; worth knowing if you point it at other code.
- **~200MB app size**, mostly the bundled `patterns.db` (31k+ mined
  bug-fix patterns the search draws from) plus pandas/matplotlib/anthropic.
  Nothing to trim without losing real functionality.
- **Unsigned** (no Apple Developer / Windows code-signing certificate), so
  both OSes show a one-time "unknown developer" warning -- see above.
