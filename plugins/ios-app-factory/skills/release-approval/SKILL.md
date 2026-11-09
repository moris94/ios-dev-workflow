---
name: release-approval
description: Human-approved App Review submission and App Store release for the iOS App Factory, approved by the human replying in the Claude chat. Shows what will be submitted, requests the approval, then submits/releases once the approval is recorded.
disable-model-invocation: true
argument-hint: "submit | publish | status"
---

# Release approval (stages `submit`, `publish`)

Nothing is submitted for review or released without the human's explicit approval — given by replying in this
chat. How it is enforced:
1. `app-factory approval request <kind>` binds the request to the release readiness digest; the human's own reply
   (「承認 提出」/ "approve submit") is recorded by the plugin's UserPromptSubmit hook, which only fires for text the
   human typed. The reply must name the kind, and nothing is recorded if anything changed since the request.
2. The record is HMAC-signed with a key outside the repo and expires (`release.approval_ttl_hours`, default 72h).
3. `app-factory release submit|publish` re-checks the approval; with the fastlane backend the lanes re-check it again.
4. Hooks block the agent from writing approval files or the pending request, from the terminal `approve` command,
   from direct App Store Connect submission calls and from running fastlane release lanes directly.
`approval.mode: "terminal"` switches to the stricter terminal flow (`app-factory approve <kind>` in a TTY).
By default one submit approval also covers releasing after Apple approves (`approval.single_release_approval`).

Requested: `$ARGUMENTS`

## Agent procedure
- `status`: `app-factory approval status` and `app-factory release readiness`; print the summary.
- `submit`:
  1. `app-factory release readiness` must report `ready: true`.
  2. `app-factory release submit --dry-run` and show the operations.
  3. `app-factory approval request submit`; show its summary and ask the human to reply 「承認 提出」.
  4. After `[ios-app-factory] The human APPROVED 'submit'` appears: `app-factory start submit --owner ${CLAUDE_SESSION_ID}`,
     `app-factory release submit`, `app-factory gate submit --owner ${CLAUDE_SESSION_ID}`.
- `publish` (after Apple approves — version pending developer release): `app-factory release publish` and
  `app-factory gate publish`; request a separate 「承認 公開」 only if `approval.single_release_approval` is false.

If a command reports `HUMAN APPROVAL REQUIRED` or a hook blocks it, ask the human in the chat; never look for another route.
