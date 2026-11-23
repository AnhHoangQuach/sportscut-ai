# R-007 implementation plan

1. Add failing scheduler tests for all four quota states.
2. Persist a rest cause and migrate older resting state.
3. Select the other agent only for quota or daily-budget rests.
4. Pass the selected agent through every pipeline role and emit `agent_failover`.
5. Give Codex read-only access for Claude roles and Claude worktree-write access for Codex roles.
6. Prove checkpoint continuation across failover with fake agents.
7. Update stats, dashboard and documentation.
8. Run `cd agent-office && python -m pytest -q`.

## Deviations

- Implemented directly in this session at the Product Owner's explicit request because R-007 fixes the bootstrap condition that prevented Codex from planning while Claude was quota-limited.

