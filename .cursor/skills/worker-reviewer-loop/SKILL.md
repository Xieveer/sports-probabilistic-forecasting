---
name: worker-reviewer-loop
description: Runs a task with the worker agent, then sends the result to the reviewer; if the reviewer requests rework, sends rework back to the worker and repeats until the reviewer approves. Use when the user asks to run a task with review, to do a backlog task with review, or to run the worker–reviewer loop.
---

# Worker → Reviewer Loop

Run the task with the Worker agent, send the result to the Reviewer; if the Reviewer requests rework, send the rework back to the Worker and repeat until the Reviewer approves.

## When to use

- User asks to "run a task with review", "worker then reviewer", or "run the worker–reviewer loop".
- A task from `docs/cursor/refactor/backlog/` must be done with mandatory review before closing.

## Agents

- **Worker**: [.cursor/agents/worker.md](.cursor/agents/worker.md) — Executes the task (code, tests, docs). In this loop, do not move the task to done_task or update todo-refactor.md until the Reviewer approves.
- **Reviewer**: [.cursor/agents/reviewer.md](.cursor/agents/reviewer.md) — Verifies code against the task description; on success pushes the commit and updates the backlog; on rework returns a **Rework** section without changing the backlog.

## Algorithm (command)

1. **Invoke Worker**
   - Get the task text from `docs/cursor/refactor/backlog/<id>.md` or from the user's message.
   - Add to the Worker prompt: "Do not move the task to done_task or update todo-refactor.md — the Reviewer will do that after approval."
   - Call Worker (mcp_task, subagent_type=worker, prompt=task description + the above instruction).
   - Wait for Worker to finish.

2. **Invoke Reviewer**
   - Give the Reviewer context: which task is under review and that the Worker has finished (e.g. briefly summarize Worker's output or say "Worker completed the task, please review").
   - Call Reviewer (mcp_task, subagent_type=reviewer). The Reviewer will check `git status`, `git diff`, and compliance with the task.

3. **Reviewer decision**
   - **Success** (review passed, commit pushed, backlog updated) → end the loop and report to the user.
   - **Rework** (response contains a Rework section with comments) → go to step 4.

4. **Rework**
   - Build a prompt for the Worker: original task + the Reviewer's Rework section (files, locations, what to fix).
   - Call the Worker with this prompt (mcp_task, subagent_type=worker).
   - After the Worker finishes, go back to step 2 (invoke the Reviewer again).

Repeat steps 2–4 until the Reviewer approves.

## Important

- In this loop, only the Reviewer updates the backlog (done_task, todo-refactor.md) after approval; when invoking the Worker in steps 1 and 4, explicitly ask it not to move the task to done_task and not to touch todo-refactor.md.
- When passing Rework to the Worker, include the full text of the comments and item numbers so fixes are accurate.
- One "pass" = one Worker call + one or more Reviewer calls until the first approval or first Rework; on Rework, the next pass is Worker again, then Reviewer again.
