# 📋 Product Backlog & Roadmap

Living, scrum-style backlog for **Steam Idle Bot**. Tracks shipped work, the prioritized
queue, known defects, and risks. Source of truth for "what's next"; narrative history lives
in [`CHANGELOG.md`](CHANGELOG.md).

---

## Legend

| Field | Values |
|-------|--------|
| **Status** | ✅ Done · 🟡 In progress · ⬜ Todo · 🧊 Icebox |
| **Type** | ✨ Feature · 🐛 Bug · 🧱 Tech-debt · 📚 Docs · 🔐 Security · 🧪 Test |
| **Impact** | 🟥 High · 🟧 Medium · 🟩 Low (user/operational value) |
| **Effort** | `S` ≤½ day · `M` 1–3 days · `L` > 3 days |
| **Priority** | `P0` now · `P1` next · `P2` soon · `P3` later — derived from impact ÷ effort |

**Definition of Done:** code + tests green (`ruff` · `mypy` · `pytest` across 3.12–3.14),
docs/CHANGELOG updated, no committed secrets/artifacts, reviewed & merged to `main`.

**Cadence:** ~1-week sprints. Each closed sprint ships as a PR; backlog re-groomed at close.

---

## ✅ Shipped (sprints 1–5)

> Delivered in PRs [#30](https://github.com/bernardopg/steam-idler-python/pull/30)–[#34](https://github.com/bernardopg/steam-idler-python/pull/34). Test suite grew 204 → 242.

### Sprint 1 — Audit & hardening · PR #30
- [x] 🐛 🟥 Rotate the log file (`RotatingFileHandler`, 10 MB × 3) — fixes unbounded 1 GB log growth
- [x] 🐛 🟥 Live idle/session duration in the panel (was frozen at `0 min`)
- [x] ✨ 🟧 Configurable `--refresh-interval-seconds` / `REFRESH_INTERVAL_SECONDS`
- [x] 🐛 🟧 Tolerate malformed Steam `appdetails` payloads (e.g. app `2321720`)
- [x] 📚 🟥 Correct inverted `eventemitter` dependency note in `CLAUDE.md`

### Sprint 2 — Graceful shutdown · PR #31
- [x] 🐛 🟥 `SIGINT`/`SIGTERM` graceful stop that still emits the session report

### Sprint 3 — Privacy · PR #32
- [x] 🔐 🟧 Consistent account-name redaction across both backends (`utils.redaction`)

### Sprint 4 — Follow-ups · PR #33
- [x] ✨ 🟧 Preflight warnings (Steam not running / no graphical session) for `steam_utility`
- [x] 🐛 🟧 Backfill drained final card counts to `0` in the session report
- [x] ✨ 🟧 steam-utility idle reconciliation (reuse / dedup / report via `/proc`)

### Sprint 5 — Backlog close-out · PR #34
- [x] ✨ 🟧 Checkpoint report mode (`--checkpoint-minutes` → JSON + Markdown) + `--duration-minutes`
- [x] ✨ 🟩 Delayed post-run verification (`--post-run-verify-seconds`)
- [x] ✨ 🟩 `--stop-app-ids` maintenance mode
- [x] 🧪 🟧 run.sh signal-forwarding integration tests
- [x] 📚 🟩 Document expected empty Badge-API card-drop responses

---

## 🎯 Product backlog (prioritized)

### EPIC A — Reliability & resilience
| ID | Type | Item | Impact | Effort | Priority | Status |
|----|------|------|:------:|:------:|:--------:|:------:|
| A1 | 🧪 | Raise coverage on `steam_utility.py` (56%) and `client.py` (79%) | 🟧 | M | P1 | ⬜ |
| A2 | ✨ | Exponential backoff + jitter on reconnect storms | 🟧 | S | P2 | ⬜ |
| A3 | 🧱 | Structured health metrics (uptime, reconnects, drops/hr) exposed to the panel | 🟩 | M | P3 | ⬜ |
| A4 | 🐛 | Detect & recover from a silently-killed steam-utility child mid-session | 🟧 | M | P2 | ⬜ |

### EPIC B — Card-drop accuracy
| ID | Type | Item | Impact | Effort | Priority | Status |
|----|------|------|:------:|:------:|:--------:|:------:|
| B1 | ✨ | Honor Steam's weekly 3-drop / playtime gate in the planner | 🟥 | L | P1 | ⬜ |
| B2 | ✨ | Cross-check badge-API vs scraper counts; warn on divergence | 🟧 | M | P2 | ⬜ |
| B3 | 🧱 | Cache TTL auto-tuning from observed drop cadence | 🟩 | M | P3 | 🧊 |

### EPIC C — Backends & idling
| ID | Type | Item | Impact | Effort | Priority | Status |
|----|------|------|:------:|:------:|:--------:|:------:|
| C1 | ✨ | Multi-account / account-rotation support | 🟥 | L | P2 | 🧊 |
| C2 | ✨ | Windows-native steam-utility process detection (no `/proc`) | 🟧 | M | P2 | ⬜ |
| C3 | 🧱 | Formalize the backend `Protocol` and add a conformance test suite | 🟧 | S | P1 | ⬜ |

### EPIC D — UX (terminal & GUI)
| ID | Type | Item | Impact | Effort | Priority | Status |
|----|------|------|:------:|:------:|:--------:|:------:|
| D1 | 🧪 | GUI test coverage (currently 11%) — extract logic from Tkinter | 🟧 | L | P1 | ⬜ |
| D2 | ✨ | Live-updating terminal panel (in-place refresh, not reprint) | 🟩 | M | P3 | ⬜ |
| D3 | ✨ | GUI: per-game drop progress bars + ETA | 🟩 | M | P3 | 🧊 |

### EPIC E — Observability & reporting
| ID | Type | Item | Impact | Effort | Priority | Status |
|----|------|------|:------:|:------:|:--------:|:------:|
| E1 | ✨ | HTML/Markdown session summary with charts | 🟩 | M | P3 | ⬜ |
| E2 | ✨ | Prometheus/JSON metrics endpoint for long-running hosts | 🟩 | M | P3 | 🧊 |

### EPIC F — Packaging & distribution
| ID | Type | Item | Impact | Effort | Priority | Status |
|----|------|------|:------:|:------:|:--------:|:------:|
| F1 | ✨ | Publish to PyPI (`pipx install steam-idle-bot`) | 🟥 | M | P1 | ⬜ |
| F2 | ✨ | Official Docker image + compose for headless 24/7 idling | 🟧 | M | P2 | ⬜ |
| F3 | 📚 | Release automation (tagged builds, changelog extraction) | 🟧 | S | P2 | ⬜ |

### EPIC G — Quality & testing
| ID | Type | Item | Impact | Effort | Priority | Status |
|----|------|------|:------:|:------:|:--------:|:------:|
| G1 | 🧪 | Enforce a coverage floor in CI (e.g. fail < 80%) | 🟧 | S | P1 | ⬜ |
| G2 | 🧪 | Add `pytest-timeout` to kill hung tests deterministically | 🟧 | S | P1 | ⬜ |
| G3 | 🧱 | Adopt `ruff format --check` as a CI gate | 🟩 | S | P2 | ⬜ |

### EPIC H — Security & privacy
| ID | Type | Item | Impact | Effort | Priority | Status |
|----|------|------|:------:|:------:|:--------:|:------:|
| H1 | 🔐 | Optional OS-keyring credential storage (drop plaintext `.env`) | 🟥 | M | P1 | ⬜ |
| H2 | 🔐 | Redact cookies/tokens in `DetailedLogger` JSON dumps | 🟧 | S | P1 | ⬜ |
| H3 | 🔐 | Document & track the accepted `protobuf<4` advisory exceptions | 🟩 | S | P2 | ✅ |

### EPIC I — Documentation
| ID | Type | Item | Impact | Effort | Priority | Status |
|----|------|------|:------:|:------:|:--------:|:------:|
| I1 | 📚 | Architecture deep-dive page linked from the README diagrams | 🟧 | S | P2 | ⬜ |
| I2 | 📚 | Troubleshooting matrix (auth failures, 429s, no drops) | 🟧 | S | P1 | ⬜ |
| I3 | 📚 | Animated demo (asciinema/GIF) in the README | 🟩 | S | P3 | ⬜ |

---

## 🐛 Known defects / risks

| ID | Severity | Description | Mitigation | Status |
|----|:--------:|-------------|-----------|:------:|
| R1 | 🟧 | steam-utility reconciliation is Linux-only (`/proc`) | No-op elsewhere; tracked as C2 | ⬜ |
| R2 | 🟩 | `protobuf<4` pin blocks GHSA-8qvm-5x2c-j2w7 / GHSA-7gcm-g887-7qv7 | Accepted: only trusted Steam data deserialized | ✅ |
| R3 | 🟧 | Card-drop scraping depends on a short-lived community cookie | Auto browser-cookie recovery; session verify | ✅ |
| R4 | 🟩 | GUI is largely untested (11% coverage) | Tracked as D1 | ⬜ |

---

## 📌 Next sprint candidate (groomed)

Top of queue by impact ÷ effort: **F1** (PyPI), **G1+G2** (coverage floor + test timeout),
**I2** (troubleshooting matrix), **H2** (redact logger dumps), **C3** (backend conformance tests).
