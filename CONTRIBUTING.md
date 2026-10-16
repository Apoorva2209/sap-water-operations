# Contributing

```bash
pip install -e ".[test]"
python -m pytest -q
```

- Keep the runtime dependency-free (standard library only).
- Any change to safety limits, allocation or verification needs a test.
- Do not claim savings or accuracy that come only from the simulator; label simulated results as simulated.
- Firmware changes must be bench-tested before merging; say how in the pull request.
