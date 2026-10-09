# Test Strategy

## Classification Definitions
1. **OFFLINE_UNIT**: Runs entirely locally with mocks. No network.
2. **ISOLATED_INTEGRATION**: Connects to local file system mock endpoints or local loopback servers.
3. **AUTHORIZED_WINDOWS_INTEGRATION**: Requires explicit execution on the target Windows test machine.
4. **PRODUCTION_ONLY_WITH_EXPLICIT_APPROVAL**: Connects to the real `google_unified:` cloud remote.

## Required Tests

### Authorization & Path Security
- **Test:** Inject `../` sequences, absolute paths outside `JULES_ZONE`, and symlinks.
- **Expected:** Denial before reaching the adapter.
- **Classification:** OFFLINE_UNIT

### Backup Protection
- **Test:** Simulate backup creation failure during an overwrite request.
- **Expected:** The original file is untouched, return 500.
- **Classification:** OFFLINE_UNIT

### Deduplication Safety
- **Test:** Write two identical files. Verify only one CAS blob exists. Delete one file. Verify CAS blob remains.
- **Expected:** GC dry-run confirms reference integrity.
- **Classification:** OFFLINE_UNIT

### End-to-End Jules Connectivity
- **Test:** Mock Jules script executing HTTP REST calls to the gateway, writing and reading data.
- **Expected:** Successful lifecycle in an isolated loopback test.
- **Classification:** ISOLATED_INTEGRATION

### Windows Mount Verification
- **Test:** Reboot test host, verify `X:\` is accessible via WinRM/SSH without an active interactive UI session login, then login and verify Explorer visibility.
- **Expected:** Drive letter available in both contexts.
- **Classification:** AUTHORIZED_WINDOWS_INTEGRATION
