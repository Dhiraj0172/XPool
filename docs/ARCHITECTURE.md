# Architecture Document

## Overview
The XPool-Jules Gateway is designed to provide secure, controlled access for Google Jules to a specific workspace within a larger unified cloud storage pool mounted on Windows. The gateway intercepts all operations, enforcing security policies, authorization, backups, deduplication, and versioning before interfacing with the backend storage.

## Components

### 1. Windows Storage Mount Layer
Provides the foundational filesystem bridge.
- Uses **WinFsp** and **rclone**.
- Mounts early (pre-login availability) while exposing the drive (e.g., `X:`) to the interactive session.
- Explicit path and identity configs are preferred over implicit user defaults.

### 2. Authenticated Jules Gateway
The entry point for Jules interactions.
- Provides authenticated API (e.g., REST API or local socket).
- Parses, normalizes, and verifies incoming requests against paths and capabilities.
- Interfaces via an abstract adapter to the underlying storage.

### 3. Core Subsystems

#### JULES_ZONE Policy Enforcement
- Implements a strict default-deny model outside a dedicated workspace (`JULES_ZONE`).
- Explicit permissions matrix (e.g., read, write, list).

#### Backup & Versioning
- Destructive operations (overwrites, deletes) are intercepted.
- Safely writes a snapshot/backup to an isolated zone.
- Ensures the backup is unmodifiable by standard Jules requests.
- Retains metadata mapping to the version history.

#### Deduplication
- Implements Content-Addressed Storage (CAS).
- Employs hashing to recognize duplicate blobs.
- Reduces duplicate physical writes.

#### Quota & Observability
- Aggregates accurate multi-remote capacity logic safely.
- Exposes structured audit and debug logs.
- Captures system health metrics.

## Logical Flow Diagram
```
[Google Jules Client]
       │
       ▼
[Authenticated API Gateway] ─(Log/Audit)─► (Audit Sink)
       │
       ▼ (Request Validation & Normalization)
       │
       ▼
[Policy Enforcement (JULES_ZONE AuthZ)]
       │
       ▼ (Destructive Mutation?) ──(Yes)──► [Backup/Snapshot Manager]
       │                                            │
       ▼ (No)                                       ▼ (Backup verified)
[Deduplication/CAS Engine] ◄────────────────────────┘
       │
       ▼
[Storage Adapter]
       │
       ▼
[WinFsp / rclone Mount (Windows X:\)]
       │
       ▼
[Cloud Backend]
```
