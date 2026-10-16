# SQLite backup and restore drills

The local tool creates verified SQLite snapshots and restores them only into a new directory. It never overwrites a live database, starts a worker or activates a signer. PostgreSQL backup/restore is not implemented or verified by this tool.

## Create and verify

```powershell
node scripts/python.mjs scripts/backup.py
node scripts/python.mjs scripts/backup.py --verify artifacts/backups/YOUR_BUNDLE/manifest.json
```

The default output is a unique directory under ignored `artifacts/backups/`. `--destination` can specify another new local directory. Existing destinations are refused. The paper database must exist. An existing testnet execution database is included; if both execution addresses are configured but that ledger is missing, backup fails rather than silently claiming a complete capture. Check the manifest's roles before relying on it.

Snapshots use SQLite's backup API from a read-only source connection, including committed WAL state. Each snapshot receives an integrity check, SHA-256, file size, schema version and table row counts. The manifest is written only after all requested snapshots finish. A failed run may leave an incomplete directory; absence of a valid manifest means it is not a verified backup.

Paper and testnet snapshots are individually consistent rather than one atomic cross-database snapshot. For a coordinated checkpoint, stop the local service and owner runner after checking exchange positions/protection. Stopping a process does not close an exchange position. Keep an owner-controlled copy off this machine; local ignored artifacts alone are not a disaster recovery strategy. Backups contain account data, public addresses and pitch text, so keep them private. Environment files and private keys are deliberately excluded.

## Isolated recovery drill

```powershell
node scripts/python.mjs scripts/backup.py --restore artifacts/backups/YOUR_BUNDLE/manifest.json
```

By default this creates a new directory under `artifacts/restore-drills/`, with the restored SQLite files and `restore-report.json`. Use `--destination` for a different new directory. The tool verifies all source files before creating the restore directory, checks copied bytes and row counts, and refuses traversal filenames or existing destinations. The report's `exchange_reconciled=false` is intentional.

Do not point a running signer at a restored historical nonce ledger. An older backup may omit already submitted commands or nonces, and an exchange snapshot can change after backup. Keep the signer stopped, preserve the current ledger, investigate unknown commands, compare public exchange orders/fills and obtain a fresh recovery decision before any activation. This drill validates file recovery, not permission to resume financial execution. There is no automatic in-place restore command.

Hashes detect corruption or accidental changes; they are not authentication against someone who can rewrite both the database and manifest. Encryption, off-machine retention, PostgreSQL recovery and production recovery leadership remain operational gates.

The paper snapshot also includes local wallet-authentication tables when present, including public addresses, challenge state and hashed session tokens. Keep this data private. Tokens and pending challenges from a previous API boot are invalid after restart/restore; restoring rows does not restore login authority. No raw wallet signatures, bearer tokens or signing keys are persisted by authentication.

## Verification

Tests include committed WAL content, exact paper state after restore, testnet unknown-command/nonce persistence without entry replay, corruption, traversal, missing sources and overwrite refusal. A real local paper snapshot was also restored into an isolated directory and compared with the stopped source: account, episodes, positions and journal rows matched exactly. No exchange action or live database replacement occurred.

Reference: [Python SQLite backup API](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup).
