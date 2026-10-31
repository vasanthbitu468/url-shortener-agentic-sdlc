# ADR-0002: Agents work in a sandbox; the only output is a patch

Status: Accepted

## Context

Agents that write directly to a repository, even on a branch, can damage it, and their changes are harder to roll back step by step.

## Decision

Each run copies the repository into `runs/<id>/baseline` and `runs/<id>/workspace`. Agents edit only the workspace, only within their stage's allowed paths. Checkpoints before every batch make rollback a directory restore. Release produces `changes.patch`, which a human applies and merges through a normal pull request.

## Consequences

- The real repository is never modified by an agent.
- Review happens on an ordinary diff; CI verifies it applies to a clean checkout.
- Applying the patch is one manual step per change, deliberately.
