# Native host evals

Proves one host-native adapter (Claude Code hooks) shares the Twin cognitive
core with MCP — `HostSessionBinding`, proactive Context Pack, observations,
and display-only interventions — without a parallel memory store.

The binding closes on **SessionEnd** (not on Claude's per-turn Stop); reusing
the external session id afterwards opens a fresh occurrence.

```bash
PYTHONPATH=tests python -m evals.native.run
```
