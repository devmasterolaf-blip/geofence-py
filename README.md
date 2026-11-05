# geofence-py

Computational geometry and geofencing for latitude/longitude data in pure
Python (standard library only at runtime), with a small `geofence` command
line tool.

Work in progress: the modules are being added one at a time. A full README
follows once the public API has settled.

## Development

```
python3 -m venv .venv
.venv/bin/pip install -e ".[test]"
.venv/bin/python -m pytest
```

## License

MIT, see [LICENSE](LICENSE).
