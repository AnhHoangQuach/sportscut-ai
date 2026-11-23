# Separate agent roles plan

1. Failing tests `tests/test_roles.py`: config/roles defaults + legacy `[parallel]`, state migration,
   steps/logs/messages by role, Tester → Developer loop, tests changed by dev, rest/probe/failures/
   budget per CLI, `office wake <role|cli>`, failover by role pairs, stats per role + CLI, prompt
   markers recognised (no role prompt mistaken for another).
2. `models` (ROLES, providers, FAILOVER, STEP_ROLE, Task.tester_files/dev_changed_tests,
   Agent.provider), `config` ([roles], per-role [parallel]), `store` (migration, roles_of, provider_of).
3. `scheduler` (role steps, one wake per CLI, failover pairs), `pipeline` (_call/_rest/_wake per
   CLI, role messages, independent Tester flow), `worktree.changed_files`, `stats`, `cli wake`.
4. Prompts (test.md independent Tester; dev.md keeps Tester tests), sim agent, dashboard/3D.
5. Update existing tests to role names; docs, AGENTS.md/CLAUDE.md, INDEX, DECISIONS.

Verify: `cd agent-office && python -m pytest -q` and `office demo` screenshots (four desks).
