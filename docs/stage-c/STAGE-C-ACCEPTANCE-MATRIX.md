# XPool Stage C: Security Acceptance Matrix

| Criterion ID | Required Behavior | Relevant Implementation | Required Evidence | Current Status | Remaining Gap | Dependency/Owner Approval | Objective Pass Condition |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **AC-01** | Public namespace access control | `rclone_adapter.py:_get_remote_path` | Offline Tests | `TESTED_OFFLINE` | Live integration tests | None | Returns 403 on `.xpool_recovery` paths |
| **AC-02** | Backend recovery isolation | N/A | Provider IAM configuration | `BLOCKED` | Separate Rclone credentials | Owner | Gateway token fails to write to `.xpool_recovery` at provider |
| **AC-03** | Backup-before-mutation | `executor.py:execute_write` | Offline Tests | `TESTED_OFFLINE` | Live integration tests | None | Hash verification failure blocks `uploadfile` |
| **AC-04** | Source-change detection | `executor.py:execute_write` | Offline Tests | `TESTED_OFFLINE` | Live integration tests | None | Pre-mutation hash revalidation detects mock mutation |
| **AC-05** | Remote mutation atomicity / TOCTOU | Rclone RC backend | Live API trace | `BLOCKED` | Native `If-Match` support | Owner | Backend natively rejects concurrent external write |
| **AC-06** | SQLite thread safety | `state.py:OperationTracker` | Offline Tests | `TESTED_OFFLINE` | None | None | 10 concurrent threads produce valid DAG states |
| **AC-07** | SQLite multi-process safety | `state.py:OperationTracker` | Offline Tests | `TESTED_OFFLINE` | Live integration load tests | None | 10 concurrent processes produce valid DAG states safely |
| **AC-08** | State transition atomicity | `state.py:update_state` | Offline Tests | `TESTED_OFFLINE` | None | None | Invalid jumps raise `ValueError` |
| **AC-09** | Restart reconciliation | `state.py:reconcile_restarts` | Offline Tests | `TESTED_OFFLINE` | None | None | `MUTATION_EXECUTING` goes to `UNCERTAIN` on boot |
| **AC-10** | Uncertain remote outcomes | `executor.py:execute_write` | Offline Tests | `TESTED_OFFLINE` | None | None | Network timeout triggers `UNCERTAIN` |
| **AC-11** | Recovery retention | GC Script (Missing) | None | `NOT_IMPLEMENTED` | GC Script implementation | Owner | GC logic enforces owner-approved retention duration |
| **AC-12** | GC safety | `state.py:get_active_backup_ids` | Offline Tests | `TESTED_OFFLINE` | GC Script implementation | None | GC script dry-runs skip active operations |
| **AC-13** | Deduplication/CAS correctness | `cas.py` | None | `PLACEHOLDER` | CAS object store implementation | None | Uploading duplicate payloads writes only 1 backend blob |
| **AC-14** | Audit logging secret redaction | `state.py` schema | Offline Tests | `TESTED_OFFLINE` | None | None | `principal_id` stored, `Authorization` token absent |
| **AC-15** | Real-backend integration evidence | N/A | None | `NOT_RUN` | Execution against test backend | Owner | End-to-end tests against real Google Drive pass |
| **AC-16** | Windows host integration auth | N/A | None | `UNAUTHORIZED` | Owner Approval | Owner | Integration authorized |
| **AC-17** | Jules integration auth | N/A | None | `UNAUTHORIZED` | Owner Approval | Owner | Integration authorized |

| **AC-18** | Minimal Gateway API | `main.py:XPoolGatewayHandler` | Offline Tests | `TESTED_OFFLINE` | Live routing tests | None | Denies by default, bounds sizes, traps bad HTTP logic, maps uncertain outcomes safely |
