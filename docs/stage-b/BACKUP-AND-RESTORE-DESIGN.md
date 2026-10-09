# Backup and Recovery Design

## Core Rule
No destructive operation (overwrite, delete, destructive rename) occurs without a verified, independent backup.

## Backup Identity and Isolation
Backups are placed in an independent, protected target (e.g., a separate rclone remote or a restricted bucket path) not mounted or accessible by the primary `JULES_ZONE` gateway identity. This prevents compromised Jules payloads from intentionally wiping recovery data.

## Workflow Execution
1. Identify destructive mutation.
2. Read target file.
3. Write to `Backup Store` with a timestamped ID and original path metadata.
4. Verify written file hash matches original file hash.
5. If verification succeeds, execute the destructive mutation on the primary store.
6. If verification fails or is interrupted, abort the operation, return a 500 Error, and do not mutate the primary store.

## Restore Authorization
Restores can only be executed by providing an Administrator token, separate from the standard Jules operational token.
