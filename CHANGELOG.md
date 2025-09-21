# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project adheres to Semantic Versioning.

## [Unreleased]

### Added

- CLI: Support `--config PATH` to load a custom configuration file (matches documentation).
- README: Language toggle badges (English / Português-BR) at the top.

### Changed

- Docs (EN/PT-BR):
  - Removed outdated reference to gevent; clarified we use resilient HTTP sessions with retries/backoff.
  - Clarified environment variable precedence and `.env` behavior when running via UV.
  - Fixed Security links in localized READMEs to point to local `SECURITY.md`.
  - Minor wording tweaks and reminders not to commit `config.py`.

### Fixed

- Ensured USAGE and README CLI flags and behavior align with code (e.g., `--config`, caching, and filtering flags).

### Internal

- No behavior changes to idling logic; documentation and CLI parity improvements only.
