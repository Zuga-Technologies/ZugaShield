# Justin's TODO — ZugaShield

Cybersecurity lane. Primary repo. First-drop calibration batch.

## Active

- [ ] **#1 — Add OWASP LLM Top 10 mapping to documentation** ([Justin] Add OWASP LLM Top 10 mapping to documentation)
  - Output: `docs/owasp-llm-mapping.md`
  - Read Mike's `Mikes-Edits` TODO.md notes on LLM03/09/10 first; incorporate, don't re-derive.
- [ ] **#4 — Community signature: ChatML format injection** ([Justin] Community signature: ChatML format injection)
  - Output: signature + ≥10-variant attack corpus + tests
  - Gates wider Shield autonomy.
- [ ] **#10 — First manual signature cycle (role-defining)** ([Justin] First manual signature cycle + own human-review seat for autonomous authoring)
  - Output: 3–5 new signatures across `zugashield/signatures/*.json`, all 3 deterministic checks pass, real citations.
  - Long-term role: human-review seat for Zugabot's autonomous authoring loop.
  - Run this AFTER #1 and #4 land — it depends on the OWASP map and signature mechanics.

## Workflow

- Branch off this branch (`Justins-Edits`) for each PR.
- PR target = default branch (`master`).
- Buga reviews each PR.

## References

- Spec: `docs/superpowers/specs/2026-05-06-justin-cybersecurity-deliverables-design.md` (parent monorepo)
- Lane file: `memory/projects/active/project_justin_cybersecurity_lane.md` (parent monorepo)
- Mike's parallel work: `git show origin/Mikes-Edits:TODO.md`
