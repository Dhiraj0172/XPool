# Authorization and Path Security

## Canonical Workspace Identity
The `JULES_ZONE` is defined by an absolute, canonical path (e.g., `X:\JulesWorkspace` or `google_unified:/JulesWorkspace`).

## Path Normalization Rules
1. All incoming paths are treated as relative to the `JULES_ZONE`.
2. Paths are expanded and fully resolved to eliminate `../` sequences.
3. The resulting absolute path is verified to start exactly with the `JULES_ZONE` absolute path.

*Why string-prefix checks fail:* `X:\JulesWorkspace_backup\secret.txt` starts with the prefix `X:\JulesWorkspace`, but it is an illegal escape. Canonical path logic (`pathlib.Path.is_relative_to()`) properly enforces the boundary based on path segments, not bare strings.

## Allowed and Prohibited Operations
- **Allowed:** Read, list, create, append, overwrite, rename (within zone), copy, delete.
- **Prohibited:** Symbolic link creation, junction following, modifying permissions, interacting with `.xpool_recovery`.

## Actual Operation Boundary
Authorization checks happen twice:
1. Upon API request reception (gateway layer).
2. Right before dispatching to the `StorageAdapter` (defense-in-depth).
