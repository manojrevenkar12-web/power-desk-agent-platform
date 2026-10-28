# Held-out set blind-1

38 cases written by a separate writer who read only `heldout/WRITING_CASES.md` (copied into an
empty folder) and never saw the platform's code, prompts, tools or other suites.

- `cases.yaml` sha256 `7c585f2e0a3aabefe5bcc93955f593128d207089a02d736662570209f25c034b`
- `STATUS`: `heldout` until someone studies its failures; then it becomes `regression` and a new
  blind set is written the same way.
- First run: `powerdesk heldout blind-1` writes `reports/heldout/blind-1/first_run.json` once.
  Later runs write `latest.json`; the first run is never rewritten, and a changed `cases.yaml`
  is refused.
