# Authorization Invariants

## Path Normalization
- All requests entering the Gateway must undergo `pathlib.Path.resolve()`.
- The resolved path must be checked using `is_relative_to(JULES_ZONE_ROOT)`.
- **Invariant:** String-prefix matching (e.g., `startswith`) is strictly forbidden to prevent prefix-confusion escapes (e.g., `/JulesZone_bypass/`).

## Operation Boundaries
- **Root Enforcement:** Operations cannot target or modify the `JULES_ZONE_ROOT` directory itself, only its contents.
- **Traversal:** `../` and symbolic link resolution across the `JULES_ZONE` boundary must fail closed with a `403 Forbidden`.
- **Recursive Restrictions:** Recursive deletes (`rm -rf`) are bound strictly to the target sub-directory and will halt if any child object fails authorization.

## Authentication Identity
- Valid tokens map strictly to the isolated `JulesWorkspace` profile. They have zero permissions to access `.xpool_recovery` paths.
- **Invariant:** Administrator tokens are distinct from operational Jules tokens.
