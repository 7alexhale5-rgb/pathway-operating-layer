# System-Design Proof Gates — concrete acceptance criteria per pathway

Source: senior-level system-design engineering standards (Hayk Simonyan, *System Design
Explained*, 2026). Purpose: give each core pathway a **falsifiable engineering gate** so
"proven" is checkable by a critic, not asserted. These are the *content* of a pathway's proof;
the proof registry (`world-class-data-boundary.md`) remains the *boundary*. Covers the 11 core
pathways plus the `field` extension.

**Applicability:** many gates below assume a web/API/infra surface (DB SPOF, CORS/CSRF/XSS,
self-healing nodes, HTTP status/idempotency). Apply each **only where that surface exists**; on
a non-web outcome (a data-only, docs, or agent task) mark the gate N/A with a structured reason
or substitute the equivalent surface contract — never silently drop it.

The course, watched end-to-end, is one `production-secure` itinerary told in order:
single-server → tier split → DB choice → horizontal scale → load-balance → kill SPOF → API
contract → protocol → auth → authz → close the 7 security holes. Map it onto the pathways:

| Pathway | Concrete proof gate (fail the pathway if absent) |
|---|---|
| **research** | Each core tech choice (SQL vs NoSQL vs graph vs KV; REST vs GraphQL vs gRPC; TCP vs UDP; sync vs queue) carries a one-line written rationale tied to the workload — consistency need, read/write shape, latency, client compatibility. No un-argued defaults. |
| **govern** | One named metric the work moves + one explicit out-of-scope boundary, fixed before implementation (the API "requirements + scope + performance requirements" step). |
| **data** | Entity model + lineage documented; tenant/data boundary explicit (who reads which rows); the shared DB is **not** an un-mitigated single point of failure (redundancy/retries/health checks). |
| **security** | The 7-point checklist IS the acceptance criteria: (1) rate-limit per-user + global, (2) CORS locked to known origins, (3) parameterized queries only (no string-built SQL/NoSQL), (4) internal endpoints network-gated, (5) CSRF tokens with session cookies, (6) XSS sanitation on stored-then-rendered content, (7) authz enforced per-action after authn — RBAC/ABAC/ACL, never "logged-in = allowed". |
| **release** | A rollback path exists (versioned API `/v1→/v2` without breaking clients, feature flag, or reversible migration); health checks gate traffic; self-healing replaces failed nodes; no deploy births a new SPOF. |
| **implementation** | First slice runs end-to-end on a real artifact before any scaling/abstraction ("every complex system starts single-server"). Throwaway-v1-first = the Karpathy ladder. |
| **quality** | Contract-level checks as a regression set: correct status codes (200/201/204/400/401/404/500), idempotency (GET/PUT idempotent, POST not), bounded responses (pagination/filtering/sorting), consistent naming. Not "it ran once." |
| **field** | A real operator exercised the real surface and something changed ("the best API is usable without reading the docs" — usability judged by the user, not the builder). |
| **observability** | Every automated stage emits a signal on success/failure; a failure is attributable to a specific stage (health checks on servers *and* balancers; 4xx=client / 5xx=server as the first diagnostic split). |
| **techdebt** | On the touched/high-risk paths: no new duplicated data path; each new/changed/high-risk dependency justified; provisional choices carry a named deprecation plan (deprecation is part of the API lifecycle). "Don't pump the system with everything — be selective." |
| **design** | Interface serves a **named** workflow (not the implementation's convenience); consistent naming/casing/patterns; for UI, rendered proof of the key states + a token/a11y check; for an API, a stable client-specified response shape. |
| **docs** | The next operator can run/extend from a named artifact — exact runbook/command or ADR path exists and is current; provisional decisions dated (versioning + "usable without docs" as the contract; maintenance is an explicit lifecycle phase). |

## Risk overlays get teeth

| Overlay | Defining principle |
|---|---|
| **tenant-authz** | Authz is per-action per-tenant, checked after authn, never inferred from session. |
| **production-mutation** | Idempotency + POST-is-not-idempotent + parameterized queries — every state change is deliberate, bounded, injection-safe. |
| **rollback** | API versioning + self-healing + redundancy — every change has an undo; no change creates a SPOF. |
| **incident-response** | Health checks on servers + balancers + 4xx/5xx taxonomy — locate the failing component fast. |
| **supply-chain** | Prefer proven managed components (Nginx/Redis/managed LB) over self-built; provenance of every dependency. |
| **human-gate** | High-stakes changes need human sign-off; the operator owns the judgment call. |
| **llm-agent-eval** | **Gap — not covered.** The source is silent on agent-output quality — nothing on evaluating an LLM agent's outputs (hallucination, grounding, drift). This overlay's proof must come from the self-improving-loop framework + a regression/eval golden set, NOT from system-design theory. |

## The limit
World-class on databases, scaling, APIs, auth, security (the plumbing); **silent on
agent-output quality**. Use it to make the infrastructure pathways (data, security, release,
observability) concrete; source `llm-agent-eval` proof elsewhere.

Operator-facing companion (with worked Ko example + plain-English framing):
`~/Projects/memory-vault/operator-artifacts/systems-engineering-x-11-pathways-2026-07-06.md`.
