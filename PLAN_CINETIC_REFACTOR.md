# PLAN — Rebrand & Refactor CRAB → **CINETIC**

> Goal: transform this codebase into a new application, **CINETIC**, that does
> everything CRAB does (plus everything we have added: per-node tournament
> dump, the result analyzer, topology-aware node selection, the TUI node-list /
> topology-map sources, sbatch error surfacing, scrollbars) — but presents as a
> genuinely new project. That means (a) a complete rebrand, top to bottom, and
> (b) a real reshaping of the core architecture so it reads as a fresh codebase,
> not a find-and-replaced clone. Where we touch the core we should also *improve*
> it, not just rename it.

This is the user's own project (remotes: `cpt-harlock/CRAB`, `lor3ny/CRAB`), and
a sibling repo `cpt-harlock/cinetic` already exists (the topology parser is kept
grammar-compatible with it). So this is a legitimate rebrand/restructure of
owned code, not a clone of a third party.

---

## 0. Decisions — CONFIRMED ✅

All three recommended defaults accepted by the user (2026-06-25): D1 in-place
`cinetic` branch, D2 clean break + legacy compat shim, D3 keep JSON config keys.

| # | Decision | Confirmed choice | Why |
|---|----------|---------------------|-----|
| D1 | **Where it lands** | New branch `cinetic` in *this* repo; do the in-place transform there. Decide later whether to push to a fresh `cinetic` repo or overwrite `cpt-harlock/cinetic`. | Keeps history + lets us diff/validate against working CRAB. Avoids committing half-renamed states to `master`/`forked`. |
| D2 | **Backward compatibility** | **Clean break** on naming (`CINETIC_*`, new script names) **with a thin one-release compat shim**: a loader that still *reads* legacy `CRAB_*` env vars and old `config.json`/`environment.json` so existing `data/` runs and example configs keep working. | "Appears new" wants a clean break; the shim costs ~1 small module and saves breaking the 11 example configs + historical runs. |
| D3 | **Config JSON key names** | **Keep the JSON config schema keys identical** (`global_options`, `experiments`, `apps`, …); add a `schema_version` field. | The config format is a user-facing contract with many example files; renaming keys is high-churn, low-benefit, and would break `examples/`. Rebrand the *code*, not the data contract. |

Also pick a TUI identity (see §5): default proposal is an **electric-cyan/violet
"kinetic" theme on near-black**, replacing the current Sapienza gold/red.

---

## 1. Guiding principles

1. **Behavior-preserving.** Every phase ends with the same runnable behavior:
   `tui`, CLI orchestrate→worker→CSV, analyzer, topology parser all still work.
2. **Reshape, don't just rename.** The deepest fingerprint is the
   `os.environ["CRAB_*"]` config bus threaded through 71 wrappers + engine. We
   replace it with a typed runtime context (§4.A1). That single change both
   modernizes the core and erases the most recognizable pattern.
3. **One commit theme per phase**, so the rebrand is reviewable and bisectable.
   Commit/push to `forked` **only when explicitly asked** (existing workflow).
4. **Translate Italian comments/identifiers to English** as we touch files —
   improves maintainability and further differentiates the source.
5. **Keep the topology parser grammar** (compatible with `cinetic` reference) —
   that compatibility is a feature, not a fingerprint.

---

## 2. Rebrand inventory (mechanical layer)

### 2.1 Python package
- `src/crab/` → `src/cinetic/` (git mv the whole tree).
- All imports `from crab.…` / `import crab` / `crab.` → `cinetic.…`
  - Sites confirmed: `cli.py`, `tui.py`, `tournament_analyzer.py`,
    `topology_parser.py`, all `tests/*.py`, and internal modules
    (`topology/__init__.py`, `topology/parser.py`, `cli/orchestrator.py`,
    `analysis/topo.py`, `tui/widgets/topology_map.py`,
    `tui/widgets/benchmark_options.py`, package docstrings).
- `sys.path.insert(0, …/src)` shims in the entry scripts keep working unchanged.

### 2.2 Environment variables (`CRAB_*` → `CINETIC_*`)
Counts from the tree (rename all, provide compat fallback per D2):

| Old | New | Refs |
|-----|-----|------|
| `CRAB_ROOT` | `CINETIC_ROOT` | 93 (mostly `wrappers/*.get_binary_path`) |
| `CRAB_SYSTEM` | `CINETIC_SYSTEM` | 8 (engine output path, controller) |
| `CRAB_WRAPPERS_PATH` | `CINETIC_WRAPPERS_PATH` | 5 |
| `CRAB_NODE_RESULTS_DIR` | `CINETIC_NODE_RESULTS_DIR` | 3 (+ `tournament_nb.c`) |
| `CRAB_PINNING_FLAGS` | `CINETIC_PINNING_FLAGS` | 2 |
| `CRAB_WL_MANAGER`, `CRAB_PRESET`, `CRAB_MPIRUN`, `CRAB_MPIRUN_ADDITIONAL_FLAGS`, `CRAB_MPIRUN_MAP_BY_NODE_FLAG`, `CRAB_MPIRUN_HOSTNAMES_FLAG`, `CRAB_MINIFE_PATH`, `CRAB_IB_DEVICES`, `CRAB_AMG_PATH`, `CRAB_G*`, `CRAB_GPU_BENCH`, `CRAB_XCCL_BENCH` | `CINETIC_*` | 1 each |

> Implementation note: rather than 93 scattered `os.environ["CINETIC_ROOT"]`
> calls, route reads through the new runtime accessor (§4.A1). The compat shim
> (D2) lives in exactly one place: it seeds `CINETIC_*` from any legacy `CRAB_*`
> at startup and warns once.

### 2.3 Generated artifacts & paths
- `crab_job.sh` → `cinetic_job.sh` (`engine.py:766`).
- Output root `data/<CRAB_SYSTEM>/…` → `data/<CINETIC_SYSTEM>/…` (`engine.py:749`).
- The run-index CSV line (`engine.py:756`) and the reproducibility snapshot
  (`config.json`, `environment.json`) — keep filenames per D3, but the *content*
  uses new env keys. (Optional: rename to `run.json` / `runtime.json` if we want
  the snapshot to read fresh too — low risk, decide in §4.A4.)
- `.env` single-line preset + `CRAB_PRESET` → `CINETIC_PRESET`.

### 2.4 Presets & data contract
- `presets.json`: env dicts currently emit `CRAB_*` keys → rewrite to `CINETIC_*`
  (`_common` + 8 active + `example_preset`). `__CWD__` substitution unchanged.
- `examples/**` and historical `data/**`: leave on disk; the compat shim (D2)
  reads them. Do **not** rewrite historical run outputs.

### 2.5 Docs & identity
- `README.md`: retitle (drop 🦀 / "Co-Running Applications Benchmarking"); new
  name expansion for CINETIC, new tagline, badges, asciicast placeholder.
- `CLAUDE.md`: rewrite project header, paths (`src/cinetic/`), env-var table,
  commands. (This file is our own context doc — update fully.)
- `PLAN.md`, `PLAN_RESULT_ANALYZER.md`: update references; keep design content.
- LICENSE/authorship unchanged.

> **Name expansion** — propose **CINETIC = "Co-running INterference & nEtwork
> Topology Investigation for Clusters"** (or simpler: *Cluster Interference &
> NEtwork Topology Inspection of Co-running apps*). Confirm preferred expansion.

---

## 3. What stays the same

- The JSON **config schema** (keys, semantics of `start`/`end`/`partition`,
  allocation modes) — per D3.
- The **topology neutral-format** JSON and parser grammar.
- The **wrapper contract** (`metadata`, `get_binary_path`, `read_data`, `conv`)
  — only the env accessor inside changes.
- The MPI/C benchmark sources' *measurement logic* (only the `CRAB_*` env name in
  `tournament_nb.c`'s results-dir lookup changes).
- CSV output columns and the `=`-fenced per-round node dumps.

---

## 4. Core architecture changes (the "genuinely different + better" layer)

Ordered by impact. A1–A4 are the recommended core; A5–A6 optional.

### A1 — Replace the `os.environ` config bus with a typed runtime context **(highest impact)**
**Problem today:** configuration is a global string bus — `os.environ["CRAB_ROOT"]`
read in 93 places, env (de)serialized to `environment.json`, re-read by the
worker. It's implicit, untyped, and the single most recognizable CRAB pattern.

**Change:**
- New `cinetic/runtime.py` (or `cinetic/config/context.py`): a frozen
  `RuntimeContext` dataclass — `root`, `wrappers_path`, `system`, `wl_manager`,
  `mpirun`, `pinning_flags`, `node_results_dir`, feature flags, extra mpirun
  flags, plus a `raw: dict[str,str]` escape hatch for benchmark-specific keys
  (`CINETIC_MINIFE_PATH`, etc.).
- `RuntimeContext.from_env()` builds it once (applying the D2 legacy shim);
  `.to_env()` serializes for the worker; `.snapshot()` writes the JSON.
- Wrappers switch `os.environ["CRAB_ROOT"]` → `ctx.root` via a tiny module-level
  accessor `from cinetic.runtime import ctx` (lazy singleton). Mechanical but it
  reshapes every wrapper's `get_binary_path` and removes the env-string idiom.
- Engine & wl_manager take `ctx` as a constructor arg instead of reading globals.

**Payoff:** typed, testable, explicit; and the diff touches every core file in a
way that makes the lineage structurally different.

**Scope decision taken during P3 (refinement of the above):** the wrappers are
`exec`-loaded *in-process* and read `os.environ["CINETIC_ROOT"]` at import time,
and the spawned MPI/Slurm subprocesses inherit `os.environ`. There, the
environment is a *legitimate transport*, not sloppy globals. So `RuntimeContext`
was made the typed front door for the **framework core** (engine + `wl_manager`
backends), which is the recognizable part and the part worth unit-testing;
`os.environ` is retained — and now documented — purely as the live transport
across those two boundaries and for dynamic per-experiment values (the
node-results dir). Rewriting all 71 `exec`-loaded wrappers to take a context
object was judged high-churn / high-fragility / low-value and intentionally
**not** done. Net effect: the core no longer reads scattered `CINETIC_*` from
`os.environ` (only two intentional transport touch-points remain), and the
backends are now constructible and testable with an injected context.

### A2 — Unify the five top-level scripts into one `cinetic` CLI
**Today:** `cli.py`, `tui.py`, `tournament_analyzer.py`, `topology_parser.py`,
`blink_plotter.py` are independent scripts each doing their own `sys.path` hack.

**Change:** a single dispatch (argparse sub-parsers) exposed as a console script:
```
cinetic run     -p <preset> -c <config.json>     # was cli.py
cinetic tui                                       # was tui.py
cinetic analyze <run|exp> --topology …            # was tournament_analyzer.py
cinetic topo    <ibnetdiscover> -o topo.json      # was topology_parser.py
cinetic plot                                      # was blink_plotter.py
```
- Implement in `cinetic/__main__.py` + `cinetic/cli/app.py`; each subcommand is a
  thin call into existing module entrypoints (`run_from_cli`, analyzer `main`,
  parser `main`).
- Keep the old top-level `*.py` as 3-line deprecation shims (or delete under a
  clean break — decide with D2). The internal orchestrator `--worker` path moves
  to a hidden `cinetic _worker` subcommand (§A4).

### A3 — Add real packaging (`pyproject.toml`, PEP 621)
- `src/` layout already matches a packaged project. Add `pyproject.toml`:
  - `project.name = "cinetic"`, scripts → `cinetic = "cinetic.__main__:main"`.
  - Dependencies = current `requirements.txt`; extras `[tui]` (textual,
    textual-fspicker), `[analysis]` (matplotlib), `[dev]`.
  - `pip install -e .` then `cinetic …` works without `sys.path` hacks.
- Keep `requirements*.txt` as generated pins or point README at extras.

### A4 — Clean up the orchestrator/worker split
**Today:** worker mode is selected by sniffing `--worker` in `sys.argv` inside
`run_from_cli`; worker reads `config.json` + `environment.json` from the run dir.

**Change:**
- Make the worker an explicit (hidden) subcommand `cinetic _worker <dir>` invoked
  by the generated `cinetic_job.sh` — no argv sniffing.
- Rename the job script `cinetic_job.sh`; optionally rename the snapshot pair to
  `run.json` (config) + `runtime.json` (resolved context) so generated artifacts
  read fresh. Compat shim still reads the old names (D2).
- Engine emits the `#SBATCH` header (incl. our framework-managed `--nodelist`
  logic) unchanged in behavior.

### A5 — (Optional) Re-shape the package tree
Rename for a fresh mental model, only if we want deeper differentiation:
- `core/wl_manager/` → `cinetic/executors/` (`slurm.py`, `mpi.py`, `template.py`).
- `core/models.py` → `cinetic/schema.py` (the `AppConfig`/`BenchmarkState`
  dataclasses).
- `core/engine.py` → split the 800-line module into `engine/allocator.py`
  (NodeAllocator), `engine/runner.py` (ExperimentRunner), `engine/engine.py`.
  This also tames a known large file.

### A6 — (Optional) Config schema versioning + validation
- Add `"schema_version": 1` to written configs; a `cinetic/schema.py` loader that
  accepts version-less (legacy CRAB) configs and normalizes them. Light dataclass
  validation with clear error messages (replaces silent `.get()` chains).

---

## 5. TUI redesign (`src/cinetic/tui/`)

The TUI is the most visible surface — it must look like a different product.

1. **Identity / theme.** Replace the Sapienza gold/red dark palette in
   `assets/tui.tcss` (renamed `cinetic.tcss`) with a distinct **"kinetic"**
   identity. Proposed palette (confirm or pick alternate):
   - background `#0d1117`, surface `#161b22`, primary `#22d3ee` (electric cyan),
     secondary `#a78bfa` (violet), accent `#0ea5e9`, success `#34d399`,
     text `#e6edf3`.
   - Alternatives to offer: (b) "amber terminal" mono, (c) "magma" orange/red on
     charcoal. One question to the user with previews when we start.
2. **Header/footer & wordmark.** Set `App.TITLE = "CINETIC"`,
   `App.SUB_TITLE = "<expansion>"`; add a small ASCII wordmark on first paint /
   an About binding. Distinct footer bindings styling.
3. **Fix & translate.** Fix the `SECTIONS` typo `"Enviroment Settings"` →
   `"Environment Settings"`; translate Italian comments/labels in
   `app.py`, `benchmark_options.py`, `environment_settings.py`,
   `variable_row.py`, `controller.py`, and the `.tcss` comments to English.
4. **Class renames (optional but cheap):** `BenchmarkApp` → `CineticApp`;
   `entrypoint set in pyproject` → `cinetic.tui.app:CineticApp`. Update the 2
   TUI tests that import these.
5. **Preserve all features** added recently: topology-map modal, node-list
   source, vertical+horizontal scrollbars, runner-log sbatch error surfacing.
6. Re-validate headlessly with `App.run_test()` after the rename (the existing
   pattern used for `tests/test_topology_map_screen.py`).

---

## 6. Phased execution (each phase independently runnable)

| Phase | Scope | Validation gate |
|-------|-------|-----------------|
| **P0** ✅ | Branch `cinetic`; add `pyproject.toml` (A3) alongside existing scripts; confirm `pip install -e .` imports `crab` still. | DONE — branch created, pyproject validated, package discoverable, imports OK. |
| **P1** ✅ | Package rename `src/crab`→`src/cinetic` + all imports + the 3 tests. Top-level scripts updated. | DONE — `git mv` (history kept), 15 py files rewritten, 3 standalone tests pass, analyzer + CLI run. |
| **P2** ✅ | Env-var rename `CRAB_*`→`CINETIC_*` everywhere + compat shim (D2) + `presets.json` rewrite + `cinetic_job.sh`/output path. | DONE — 119 files swept, `compat.py` shim wired into orchestrator + worker, `tournament_nb.c` legacy fallback, presets clean, analyzer end-to-end OK. |
| **P3** ✅ | A1 runtime context: introduce `RuntimeContext`, migrate engine + wl_manager off `os.environ`. | DONE — `runtime.py` added; engine + slurm/mpi/template backends read typed ctx; `os.environ` kept only as the documented subprocess/dynamic transport; new `tests/test_runtime_context.py` (7) + existing tests pass; analyzer unaffected. **Scope note below.** |
| **P4** ✅ | A2 unified `cinetic` CLI + A4 worker subcommand. | DONE — `cinetic.__main__` dispatch (run/tui/analyze/topo/plot + hidden `_worker`); analyzer moved to `cinetic.analysis.cli`; engine launches worker via `__main__.py _worker` (file-mode, no PYTHONPATH needed); pyproject `[project.scripts]`; `cli.py`/`tournament_analyzer.py` kept as back-compat shims; all subcommands + tests verified. |
| **P5** ✅ | TUI redesign (§5): theme, wordmark, typo, English, optional class rename. | DONE — kinetic cyan/violet palette (`tui.tcss`→`cinetic.tcss`); `BenchmarkApp`→`CineticApp` with TITLE/SUB_TITLE + About binding; `Enviroment`→`Environment` typo fixed; CRAB branding strings + app.py Italian comments translated; headless `run_test()` smoke + all 4 standalone suites pass. (Deeper Italian comments in some widgets remain as optional cosmetic cleanup.) |
| **P6** | Docs: README, CLAUDE.md, PLAN files, analyzer `tournament_nb.c` env name. | Docs reference only CINETIC; `make` in `benchmarks/blink` still builds. |
| **P7** *(opt)* | A5 tree reshape + A6 schema versioning. | Tests + full loop. |

Commit per phase; **push to `forked` only on explicit "go"/"commit and push".**

---

## 7. Risks & mitigations

- **71 wrappers** are the bulk of env refs → mechanical `git grep`-driven rename;
  P3 routes them through one accessor so a mistake is caught in one place. Add a
  smoke check that every wrapper module imports and `get_binary_path()` returns a
  path under `CINETIC_ROOT`.
- **Historical `data/` runs & `examples/`** reference `CRAB_*` / `crab_job.sh` →
  covered by D2 compat shim; never rewrite historical outputs.
- **C benchmark** `tournament_nb.c` reads `CRAB_NODE_RESULTS_DIR` → rename in C +
  keep a getenv fallback to the old name; recompile in P6.
- **Partial-rename commits** breaking `master` → all work on the `cinetic` branch.
- **Textual theme regressions** → headless `run_test()` gate in P5 (the
  `$text-muted`/`$warning` runtime vars must resolve under the new palette).

---

## 8. Out of scope (unless requested)

- Changing benchmark measurement semantics or CSV/topology data formats.
- Creating/pushing to a new remote repo (depends on D1).
- Reworking the analyzer's statistics (recently completed and validated).
- Renaming JSON config keys (D3).

---

## 9. First concrete step

On approval: create branch `cinetic`, add `pyproject.toml` (P0), and produce the
exhaustive `git grep` rename map for review before any bulk `git mv` — so the
mechanical layer (P1/P2) is auditable before it lands.
