# Security

- The dashboard PIN defaults to `1234` for demos. **Set `SAP_PIN`** before running on any network, and only set `SAP_HOST=0.0.0.0` on a trusted farm network. There is no TLS or per-user accounts yet.
- Safety-critical stops (e-stop, dry-run, overcurrent, heartbeat loss) must also exist in hardware; never rely on this software alone for personal or equipment safety.
- Report vulnerabilities privately via GitHub's "Report a vulnerability" (Security tab) rather than a public issue.
