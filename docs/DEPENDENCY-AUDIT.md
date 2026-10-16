# Locked dependency advisory check

Date: **2026-10-16**, Windows, local development checkout. This is a known-advisory lookup, not an independent security review, source audit, provenance attestation or permission to launch.

## Inputs and results

| Input / tool | Observed result |
| --- | --- |
| `apps/api/requirements.lock`, pip-audit 2.10.1, PyPI advisory service, strict mode | 56 exact package/version pairs audited, zero skipped packages, zero reported vulnerabilities. The audit's complete package/version set matched the lock. |
| Installed application virtual environment | All 56 locked versions matched installed metadata; `pip check` reported no broken requirements. |
| `package-lock.json`, `npm audit --omit=dev --json` | Exit 0, zero reported production vulnerabilities. Development-only dependencies are outside this command's scope. |

Input SHA-256 values:

```text
requirements.lock  6ce0d368f9b7e4892bd73f4df71874ce900a98569f9084a601f2be5214a05996
package-lock.json  e7a01dabcc4fdb65d41bde3a65720adfaad9557af21f107cc75674720cd60762
```

Raw local outputs are ignored artifacts at `artifacts/python-audit-20261016.json` and `artifacts/npm-audit-20261016.json`. The audit tool was installed into a separate ignored environment; application dependencies and lock files were not modified. No automatic dependency fixes were applied.

## Repeat the check

From the repository root, in PowerShell:

```powershell
.venv/Scripts/python.exe -m venv artifacts/tools/security-audit
artifacts/tools/security-audit/Scripts/python.exe -m pip install pip-audit==2.10.1
artifacts/tools/security-audit/Scripts/python.exe -m pip_audit --strict --disable-pip --no-deps -r apps/api/requirements.lock --progress-spinner off --format json --output artifacts/python-audit.json
.venv/Scripts/python.exe -m pip check
npm audit --omit=dev --json
```

On POSIX systems use `bin/python` instead of `Scripts/python.exe`. Advisory lookups use the network; deterministic financial tests remain separate. A failed or partial lookup is not a clean result. Inspect each package for skips and compare the entire reported set with the lock, rather than relying only on a summary count.

The Python command deliberately audits the fully pinned transitive list without resolving or installing it. Python requirements do not yet contain artifact hashes. Known advisories can change after this date, and clean reports do not establish that packages, installation artifacts or the application are safe. Rerun after dependency changes and before a separately reviewed release. Public authentication, external recovery, funded exchange acceptance and independent review remain open.
