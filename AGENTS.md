# AGENTS

## Editing Notes

- Prefer `apply_patch` for manual edits.
- If `apply_patch` fails with a Windows sandbox refresh error such as `windows sandbox: setup refresh failed with status exit code: 1`, do not keep retrying blindly.
- First confirm the target file is writable.
- If the file is writable but `apply_patch` still fails, fall back to a minimal PowerShell edit for that file, keep the change narrowly scoped, and verify the resulting diff.
- This fallback is especially relevant for files under `tests/`, where `apply_patch` has failed intermittently in this workspace.

## Backend and Evaluation Notes

- When adding or updating LangSmith evaluators that use `ChatOpenAI` against OpenAI-compatible gateways, reuse `src/deep_research/structured_output_fallback.py`; do not call `with_structured_output()` directly inside the evaluator.
- For Qwen or similar endpoints that can return `choices=null`, preserve the shared `/no_think` JSON fallback and its payload diagnostics instead of trying a separate LangChain `.invoke()` path first.
- Load environment configuration before importing graph modules; model construction happens at import time. Keep credentials in the local backend `.env`.
- Preserve the evaluator/fetch contract: numerical scores in `score`, explanatory text in `comment`, and structured Scoping details in `value.individual_evaluations`.
- Check failed runs and missing feedback when validating an evaluation; a successful process exit alone does not establish completeness.
- See `docs/maintenance.md` and `docs/architecture-decisions.md` for current behavior. Historical records under `.local/` are archived evidence, not an active implementation plan.
