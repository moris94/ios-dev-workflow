---
name: factory-status
description: Show the iOS App Factory pipeline status (stages, gate results, locks, stale artifacts, next step) for the current app repository. Use when the user asks where the factory pipeline is, what failed, or what to do next.
allowed-tools: Bash(app-factory status*) Bash(app-factory check*) Bash(app-factory next*)
---

Run `app-factory check` and then `app-factory status`.

For every stage that is `failed` or `stale`, read `factory/gates/<stage>.json` and list
the failing checks (`passed: false`, severity `error`) in one line each.

Finish with the next action:
- an agent stage → "run /ios-app-factory:factory resume"
- a human stop: approvals → run `app-factory approval request <kind>` and tell the human the reply to send in chat;
  credentials → which environment variable to set.
