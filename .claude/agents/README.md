# claude-agent-pack (v4)

Six generalist Claude Code subagents — a software team in a box. Works locally and in Claude Code on the web (cloud sessions pick up `.claude/agents/` from the repo automatically).

| Agent | Role | Key behavior |
|---|---|---|
| principal-pm | Scoping & planning | Defines "done" + out-of-scope; tags every task Proven/Improve/New |
| senior-dev | Implementation + debugging | Solution ladder; pushes back on overbuilt asks once; owns git hygiene; verifies own work |
| qa-code-reviewer | Testing + review | Read-only by design; SHIP / SHIP WITH FIXES / DO NOT SHIP verdicts |
| ux-ui-designer | Anything user-facing | States intended "feel" up front; anti-generic design rules |
| devops-engineer | Infra/ops on any platform | Establishes host vs target OS first; evidence-first diagnosis; config backups; reboot-proof fixes |
| tech-writer | PRDs, CLAUDE.md, docs | Verifies claims against code; numbered requirements for traceability |


## New in v4 — platform neutrality

The pack no longer assumes any OS or environment. Core principle now baked into every relevant agent: **the machine Claude Code runs on is NOT the platform the project targets.** Concretely:

- devops-selfhost → **devops-engineer**: platform-agnostic (Linux/macOS/Windows/cloud/home-lab), establishes host AND target platform before acting, reports what couldn't be tested on the current host
- **senior-dev**: platform discipline (portable path APIs, line endings, case-sensitivity, no OS-specific shell-outs when portable APIs exist) + dependency vetting rules for the ladder's PROVEN rung
- **qa-code-reviewer**: platform sweep — hunts hardcoded separators and dev-machine-only assumptions; untested target platforms are a disclosed limitation, never a silent pass
- **ux-ui-designer**: designs for the real screen set (mobile/desktop/both) and respects platform conventions
- **tech-writer**: per-OS command variants in docs for multi-platform projects
- **principal-pm**: target platform(s) pinned down as part of scoping every plan
- **templates**: PROJECT-CLAUDE.md gained a Targets section; USER-CLAUDE.md stripped of project/target assumptions — it now describes only the host machine and universal working rules

Every agent has an **orientation step** (reads CLAUDE.md + project files at start, since subagents wake with zero context) and a **report contract** (fixed final-summary format — the parent session only sees that summary, and the formats interlock across agents).

## The intended workflow

principal-pm (scope) → tech-writer (numbered PRD) → senior-dev (build) → qa-code-reviewer (verdict) → ux-ui-designer (polish). Skip stages freely — it's a menu, not a mandate. Naming the agent explicitly ("use the principal-pm agent to scope this") routes more reliably than auto-delegation.
