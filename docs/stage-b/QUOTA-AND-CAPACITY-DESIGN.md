# Quota and Capacity Design

## Quota Reporting
- **Provider-reported quota**: Retrieved via `rclone rc core/stats` or `operations/about` for individual underlying remotes.
- **Union-reported capacity**: Ignored or heavily caveated, as union remotes often incorrectly sum overlapping quotas.
- **Logical Usage**: Calculated from the reference database (the sum of all file sizes presented to Jules).
- **Physical Usage**: The actual size of the deduplicated CAS store.

## Shared Quotas & Uncertainty
If remotes share a backend quota (e.g., multiple accounts on the same Google Workspace), adding them together produces a false "independent capacity."
- The gateway will treat the largest individual remote free space as the maximum safe file upload size, rather than the sum of all free space.
- The `QUOTA_INDEPENDENCE_STATUS` will remain `BLOCKED` until explicit evidence proves the backend accounts have fully independent, non-overlapping storage allocations.

## Quota Exhaustion
When a remote returns a 403 Quota Exceeded error, the `StorageAdapter` translates this accurately to the Gateway. The Gateway will not mask this failure or pretend the write succeeded.
