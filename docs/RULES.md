# Adding or fixing a consent-platform rule

1. Save the banner's markup as a fixture in `extension/tests/fixtures/` (strip it to the elements that matter; make each button call `record('reject')`, `record('accept')`, … so the test can see what was clicked).
2. Add or edit the entry in `extension/rules/cmps.json`. Fields (all CSS selectors, comma lists allowed):
   - `detect` — present and visible only while the banner is showing;
   - `container` — the element that disappears when the banner is dismissed;
   - `rejectAll`, `settings`, `panel`, `panelRejectAll`, `toggles`, `save` — optional; when missing, the text classifier is used inside the container or panel;
   - `accept` — never clicked; used to measure how prominent the reject button is;
   - `shadowHost` — for banners rendered inside an open shadow root.
3. Bump `version` in `cmps.json` (date-based), run `python tools/sync_generated.py`, add a test to `extension/tests/test_engine.py`.

Text patterns for the heuristic live in `extension/rules/heuristics.json`; `test_button_classifier` holds the expected classification of common labels in many languages. When adding a language, add both reject and accept phrases, and a case for each to the classifier test.
