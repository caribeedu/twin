# Native host evals

Proves one host-native adapter (Claude Code hooks) shares the Twin cognitive
core with MCP — `HostSessionBinding`, proactive Context Pack, observations,
and display-only interventions — without a parallel memory store.

The binding closes on **SessionEnd** (not on provider per-turn `turn_completed`);
reusing the external session id afterwards opens a fresh occurrence.

Also runs a **fake host** adapter (`fake_host.py`) that never imports
`claude_code`, proving the universal event contract across four dimensions:

- `fake_host_contract` — lifecycle: `turn_completed` keeps the binding open,
  `session_end` closes it once, reuse opens a new occurrence, and the core
  modules never import a provider adapter.
- `fake_host_security` — unclassified sessions leak no domain memories; a
  dialogue-driven domain upgrade never widens persona/purpose/audience/vault.
- `fake_host_caps` — a host without `user_message` in
  `context_injection_events` still upgrades the domain but holds the pack.
- `fake_host_budget` — a blown pack deadline drops the pack yet persists the
  binding + domain (`pack_skipped_budget`).

```bash
PYTHONPATH=tests python -m evals.native.run
```
