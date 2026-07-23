# Twin v1.0 Threat Model

Local-first personal cognitive OS. Assets: memories, judgment, connector secrets, session context, backups.

## Trust boundaries

| Boundary | Trust |
|---|---|
| User / local host | Trusted operator |
| Twin process + `$TWIN_HOME` store | Trusted computing base |
| Cognitive model / LLM | Untrusted for authority — may hallucinate; never auto-confirms Memory/Judgment |
| MCP / HTTP / CLI clients | Authenticated principals with least privilege; default deny |
| External connectors (Slack, GitHub, mail, …) | Untrusted content sources; evidence only |
| Backups / exports | Sensitive at rest; treat as equivalent to the live store |

## Top threats and controls

1. **Prompt injection via ingested content**  
   Content is data, never instruction. Screening (`detect_injection`), quarantine, pack-time exclusion. Connectors quarantine malicious records before percepts.

2. **Cross-domain / persona privilege amplification**  
   Domain firewall + persona scope intersection (never amplifies). Cross-domain recall blocked by default.

3. **Connector credential theft / over-privilege**  
   Secrets in encrypted credential store (`credential_ref` only in DB). Least-privilege health warnings. Revoke is resumable and honest about residual secrets.

4. **Silent corruption of confirmed cognition**  
   Confirm requires evidence + human actor. Consolidation and session closure never confirm Memory/Judgment. Revision collisions go to DLQ, never overwrite.

5. **Runtime poison / stuck workers**  
   CAS claim, leases, DLQ for permanent errors; `model_unavailable` stays retryable (never DLQ). Vault isolation on claim.

6. **Exfiltration via tool output / context packs**  
   Blocked items report counts/reasons, not forbidden content. Injection-screened packs. Capability-gated MCP surfaces.

7. **Incomplete deletion / backup leakage**  
   Tombstones + source deletion events. Backup/export are full-fidelity — operators must protect backup media. Encrypted/incremental backup hardening remains follow-on work.

8. **Malicious or buggy MCP client**  
   Capability checks; preview/confirm fingerprints on agent-facing mutating connector ops; fail closed on missing principal/scope.

## Out of scope for v1.0

- Multi-tenant SaaS isolation
- Formal formal-methods proofs
- Hardware-backed secret enclaves
- Guaranteeing LLM non-hallucination (mitigated by evidence + human confirm)

## Residual risk

Operators still must: protect `$TWIN_HOME` and backup directories, rotate connector tokens, and treat every external document as adversarial input.
