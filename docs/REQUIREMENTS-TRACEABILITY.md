# Requirements Traceability Matrix

| Req ID | Description | Current State | Status | Required Implementation | Files & Modules | Dependencies | Test Strategy | Acceptance Criteria | Safety Prerequisites | Evidence Needed |
|---|---|---|---|---|---|---|---|---|---|---|
| REQ-01 | Baseline & Gap Analysis (Phase 1) | Empty repo | IN_PROGRESS | `docs/` artifacts | `docs/*` | None | Review | Discovery completed | None | Artifacts exist |
| REQ-02 | Storage Backend & Win Mount (Phase 2) | Missing | NOT_STARTED | WinFsp + rclone wrapper | `src/storage/`, `windows/` | WinFsp, rclone | Env test | Real backend integration tested isolatedly | Explicit auth | Test logs |
| REQ-03 | Auth Jules Gateway (Phase 3) | Missing | NOT_STARTED | API endpoint | `src/gateway/`, `src/auth/` | Web framework | End-to-end API test | Only authorized callers accepted | None | E2E mock logs |
| REQ-04 | JULES_ZONE Policy (Phase 4) | Missing | NOT_STARTED | Path/Op policy | `src/policy/` | None | Adversarial path test | Unauthorized ops denied | None | Policy test results|
| REQ-05 | Backup before Destructive Mut. (Phase 5) | Missing | NOT_STARTED | Backup interceptor | `src/backup/` | Storage adapter | Fault injection test | Failed backup blocks mutation | None | Trace logs |
| REQ-06 | Independent Backup Protection (Phase 6) | Missing | NOT_STARTED | Access boundary | `src/auth/`, `src/backup/` | Auth integration | Security test | Jules cannot touch backup | None | Security logs |
| REQ-07 | Real Deduplication (Phase 7) | Missing | NOT_STARTED | Content-addressed store | `src/dedup/` | Hash lib | Data-integrity test | File hashes match original | None | Verification output |
| REQ-08 | Versioning and Restore (Phase 8) | Missing | NOT_STARTED | Version manager | `src/versions/` | Dedup module | Restore test | Restored hash equals original | None | Restore test logs |
| REQ-09 | Multi-Remote Quota (Phase 9) | Missing | NOT_STARTED | Quota query system | `src/storage/` | rclone stats | Edge case tests | Accurate non-overlapping capacity reported | None | Quota logs |
| REQ-10 | Audit & Observability (Phase 10) | Missing | NOT_STARTED | Structured logging | `src/audit/`, `src/health/`| Logging lib | Failure tests | All decisions logged securely | None | Log output |
| REQ-11 | Automated Test Suite (Phase 11) | Missing | NOT_STARTED | Unit/Int test suites | `tests/` | pytest (e.g.) | Execution | Reproducible test outputs | None | Test coverage |
