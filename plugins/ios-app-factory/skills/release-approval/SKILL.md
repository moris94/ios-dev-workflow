---
name: release-approval
description: Human-approved App Review submission and App Store release for the iOS App Factory. Explains the approval commands the human runs in their own terminal and runs submit/publish only after a valid approval exists.
disable-model-invocation: true
argument-hint: "submit | publish | status"
---

# Release approval (stages `submit`, `publish`)

Nothing is submitted for review or released without an explicit human approval. This is enforced by:
1. `app-factory approve` refuses to run without an interactive terminal or from inside Claude Code,
   and requires typing `SUBMIT <App> <version> (<build>)` exactly;
2. the approval is HMAC-signed with a key outside the repo, bound to the readiness digest, and expires
   (`release.approval_ttl_hours`, default 72h) — any change after approval invalidates it;
3. PreToolUse hooks block the agent from running `approve`, from `release submit|publish` without a valid
   approval, from direct App Store Connect submission calls, from fastlane deliver/submit, and from editing
   approval/ledger/state files.

Requested: `$ARGUMENTS`

## Agent procedure
- `status`: `app-factory status` and `app-factory release readiness`; print the summary.
- `submit`:
  1. `app-factory release readiness` must report `ready: true`.
  2. `app-factory release submit --dry-run` and show the operations.
  3. Ask the human to run, in their own terminal (not through Claude):
     `app-factory approve submit`
  4. When they confirm, `app-factory start submit --owner ${CLAUDE_SESSION_ID}`, `app-factory release submit`,
     `app-factory gate submit --owner ${CLAUDE_SESSION_ID}`.
- `publish` (only after Apple approves — version state `PENDING_DEVELOPER_RELEASE`):
  ask the human to run `app-factory approve publish`, then `app-factory release publish` and `app-factory gate publish`.

If any command reports `HUMAN APPROVAL REQUIRED` or a hook blocks it, stop and tell the human; never look for another route.
