# AGENTS

## Editing Notes

- Prefer `apply_patch` for manual edits.
- If `apply_patch` fails with a Windows sandbox refresh error such as `windows sandbox: setup refresh failed with status exit code: 1`, do not keep retrying blindly.
- First confirm the target file is writable.
- If the file is writable but `apply_patch` still fails, fall back to a minimal PowerShell edit for that file, keep the change narrowly scoped, and verify the resulting diff.
- This fallback is especially relevant for files under `tests/`, where `apply_patch` has failed intermittently in this workspace.
