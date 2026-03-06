# Release Guide

This repository now supports both Python package releases and npm launcher releases.

## Before releasing

- Run `python -m unittest discover -s tests -q`
- Run `python -m pytest -q`
- Run `npm pack --dry-run`

## Python package release

Build artifacts:

```bash
python -m pip install --upgrade build twine
python -m build
python -m twine check dist/*
```

Upload to PyPI:

```bash
python -m twine upload dist/*
```

## npm launcher release

The npm package is only a launcher. It still bootstraps the Python `neudev` package underneath.

Preview the package:

```bash
npm pack --dry-run
```

Publish to npm:

```bash
npm publish --access public
```

## Versioning

- Python package version comes from `neudev/__init__.py`
- npm package version is stored in `package.json`

Update both before release.
