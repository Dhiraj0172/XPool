# Jules Session Task Template

**To: Google Jules Autonomous Session**
**Subject: Independent Task Execution for XPool Gateway Integration**

## 1. Assignment
You have been assigned task **{{TASK_ID}}**: **{{TASK_TITLE}}**.
Review `docs/stage-c/PARALLEL-TASK-MANIFEST.json` for your specific `objective` and `expected_outputs`.

## 2. Boundaries and Ownership
- You **OWN** the following paths: `{{OWNED_PATHS}}`.
- You are **FORBIDDEN** from modifying: `{{FORBIDDEN_PATHS}}`.
- If you require a change to a forbidden path (e.g., modifying an input contract), you must STOP, mark the task as `BLOCKED`, and report the required change to the Integration Owner.

## 3. Strict Rules of Engagement
- **Do not invent APIs:** Adhere strictly to the signatures defined in `docs/stage-c/IMPLEMENTATION-SPECIFICATION.md` and `docs/stage-c/API-AND-DATA-CONTRACTS.md`.
- **Do not touch production:** You must run tests exclusively in the `{{TEST_ENVIRONMENT}}` environment. Do not attempt to access the real `X:\` drive or live cloud remotes unless explicitly authorized.
- **Do not deploy:** Do not commit, push, or merge your branch without approval.

## 4. Required Output
At the conclusion of your session, you must return a structured completion report containing:
1.  **Task Status**: `PASS`, `FAIL`, or `BLOCKED`.
2.  **Changed Files**: Exact paths of files created or modified.
3.  **Test Evidence**: Exact terminal commands run (e.g., `pytest src/gateway/test_main.py`) and their raw output. Do not claim tests passed without showing the output.
4.  **Blockers/Assumptions**: Any deviation from the specification due to environmental limitations.
