#!/usr/bin/env bash
# scripts/preflight.sh
#
# WHY THIS EXISTS
# ----------------
# 0.10.0 took three pushes and left `main` red twice (004a623, c128f7e) before
# going green (d0a80da). Both reds came from the same gap: a version number
# has to agree across SEVEN files --
#
#   packages/research-core/pyproject.toml
#   tools/deep-research/pyproject.toml
#   tools/fact-check/pyproject.toml
#   tools/deep-research/src/deep_research/SMART_TOOL.md
#   tools/fact-check/src/fact_check/SMART_TOOL.md
#   skills/deep-research/SKILL.md          (GENERATED -- never hand-edit)
#   skills/fact-check/SKILL.md             (GENERATED -- never hand-edit)
#
# -- and the ONE thing that actually checks all seven (the external
# conformance kit's `manifest-version-matches-package` rule, run against
# BUILT wheels) is fetched and exercised only by .github/workflows/ci.yml.
# CONTRIBUTING.md documents running it locally too, but that requires a
# SEPARATE clone of microsoft/amplifier-smart-tools and remembering to run it
# against both tool roots with the built (not editable) artifacts -- a step
# with no automation and no reminder, so it is exactly the step that gets
# skipped under deadline pressure. `ruff` + `pytest` were green; CI was not.
#
# This script closes that gap by running everything ci.yml runs, in the same
# order, against the same kind of artifacts (built wheels, not editable
# installs), so "green here" means "green on CI" -- not "green on the two
# jobs a human remembered to run by hand".
#
# THIS BOX ALSO HAS A SECOND GAP CI DOES NOT: real provider credentials,
# resolved through host auth (ANTHROPIC_API_KEY, OPENAI_API_KEY,
# PERPLEXITY_API_KEY, GOOGLE_API_KEY were all found set in this shell while
# writing this script). A GitHub Actions runner starts with none of these;
# this machine does not. A deterministic-path test that quietly starts
# depending on real credentials would pass here and pass on CI (CI has none
# either way) right up until someone runs it on a box like this one and gets
# a different, credential-shaped answer. So this script does not just assert
# credential absence the way CI does (that assertion would be false here,
# always, and a script that fails on a true fact about its own host is
# useless) -- it re-runs the test suite and the deterministic manifest smoke
# INSIDE `env -i`, so the code under test sees the same empty environment CI
# sees, regardless of what is sitting in the calling shell.
#
# WHAT IT MIRRORS (job by job, from .github/workflows/ci.yml)
#   test            ruff check, ruff format --check, pytest -q
#                   (fresh venv, editable install, NO extras -- ci.yml does
#                   not install research-core[agent] either)
#   conformance     credential-visibility report (informational, not fatal --
#                   see note above) -> build both wheels -> install the BUILT
#                   artifacts into a fresh venv -> fetch the conformance kit
#                   fresh -> run it against both tool roots -> deterministic
#                   `manifest` smoke for both tools under `env -i`
#   (scrubbed)      the same pytest suite again, but under `env -i HOME=<a
#                   fresh empty dir> PATH="<venv>/bin:/usr/bin:/bin"` -- not
#                   a ci.yml job, this box's own extra insurance (see above)
#   install-from-git  best-effort only, see USAGE below: this job installs
#                   the tool FROM GIT BY COMMIT SHA, which only means
#                   anything once that commit is reachable on the remote --
#                   it is structurally unprovable for an unpushed commit, and
#                   ci.yml itself only ever runs it after a push to main.
#
# USAGE
#   scripts/preflight.sh                  # test + conformance (default, and
#                                          # the pair that actually broke)
#   scripts/preflight.sh test              # just the `test` job replica
#   scripts/preflight.sh conformance        # just the `conformance` job replica
#   scripts/preflight.sh install-from-git   # best-effort `install-from-git`
#                                            # replica; only meaningful for a
#                                            # commit already on `origin`
#   scripts/preflight.sh all                # everything, including
#                                            # install-from-git
#
# ENV OVERRIDES
#   PREFLIGHT_SPEC_KIT_DIR   Use this existing checkout of
#                            microsoft/amplifier-smart-tools instead of
#                            cloning fresh. Speeds up repeated local runs;
#                            ci.yml always clones fresh, so treat a green
#                            result from a stale override with suspicion --
#                            re-run without it before trusting a "PASS".
#
# COST -- SAY IT PLAINLY
#   `test` alone: ~10-20s once uv's package cache is warm.
#   `conformance` adds: building two wheels (a few seconds), cloning
#   microsoft/amplifier-smart-tools fresh (network, a few seconds to ~1
#   minute depending on connection), and running the kit against both tool
#   roots (a few seconds). Budget **1-2 minutes** for a full default run on a
#   warm cache, longer on the first run of the day or a slow network. This is
#   not a `git commit` hook; it is a pre-push gate. Run it before every push
#   that touches a version, a manifest, or a generated SKILL.md -- not on
#   every save.
#
# WHAT IT CREATES / CLEANS UP
#   Everything lives under one `mktemp -d` per invocation: temp venvs, built
#   wheels, and (unless PREFLIGHT_SPEC_KIT_DIR is set) the fresh conformance
#   kit clone. Removed automatically on exit, success or failure. Your own
#   `.venv` at the repo root is never touched.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

MODE="${1:-default}"

WORK="$(mktemp -d -t research-preflight.XXXXXX)"
cleanup() {
  rm -rf "$WORK"
}
trap cleanup EXIT

overall_status=0
declare -a RESULTS=()

record() {
  # $1: job label, $2: 0 (pass) or nonzero (fail)
  if [ "$2" -eq 0 ]; then
    RESULTS+=("PASS  $1")
  else
    RESULTS+=("FAIL  $1")
    overall_status=1
  fi
}

record_warn() {
  RESULTS+=("WARN  $1")
}

section() {
  echo ""
  echo "############################################################"
  echo "# $1"
  echo "############################################################"
}

# ---------------------------------------------------------------------------
# credential-visibility report (informational -- see header note)
# ---------------------------------------------------------------------------
credential_report() {
  section "credential visibility (informational only -- not a gate)"
  local leaked=""
  for var in PERPLEXITY_API_KEY ANTHROPIC_API_KEY OPENAI_API_KEY \
             GOOGLE_API_KEY GEMINI_API_KEY AZURE_OPENAI_API_KEY; do
    if [ -n "${!var:-}" ]; then leaked="$leaked $var"; fi
  done
  if [ -n "$leaked" ]; then
    echo "this shell resolves real credentials via host auth:$leaked"
    echo "CI never has these. Every deterministic check below is re-run"
    echo "under 'env -i' so it sees what CI sees, not what this shell sees."
  else
    echo "no provider credentials visible in this shell -- same as CI."
  fi
}

# ---------------------------------------------------------------------------
# `test` job replica
# ---------------------------------------------------------------------------
job_test() {
  section "job: test (ruff check, ruff format --check, pytest -q)"
  local venv="$WORK/venv-test"

  echo "--- create environment (fresh venv, NO extras -- matches ci.yml) ---"
  if ! uv venv "$venv" -q; then return 1; fi
  if ! uv pip install --python "$venv/bin/python" -e packages/research-core -q; then return 1; fi
  if ! uv pip install --python "$venv/bin/python" --no-deps \
        -e tools/deep-research -e tools/fact-check -q; then return 1; fi
  if ! uv pip install --python "$venv/bin/python" pytest ruff -q; then return 1; fi

  echo "--- lint and format check ---"
  if ! "$venv/bin/ruff" check .; then return 1; fi
  if ! "$venv/bin/ruff" format --check .; then return 1; fi

  echo "--- pytest -q (normal environment) ---"
  if ! "$venv/bin/python" -m pytest packages/research-core/tests -q; then return 1; fi

  echo "--- pytest -q AGAIN, under env -i (this box's extra insurance) ---"
  local scrubbed_home="$WORK/scrubbed-home"
  mkdir -p "$scrubbed_home"
  if ! env -i HOME="$scrubbed_home" PATH="$venv/bin:/usr/bin:/bin" \
        "$venv/bin/python" -m pytest packages/research-core/tests -q; then
    return 1
  fi

  return 0
}

# ---------------------------------------------------------------------------
# `conformance` job replica
# ---------------------------------------------------------------------------
job_conformance() {
  section "job: conformance (built wheels, fresh conformance kit, both tool roots)"
  local venv="$WORK/venv-conformance"
  local dist="$WORK/dist"

  echo "--- build both distribution roots ---"
  if ! uv build --out-dir "$dist/deep-research" tools/deep-research -q; then return 1; fi
  if ! uv build --out-dir "$dist/fact-check" tools/fact-check -q; then return 1; fi

  echo "--- install the BUILT artifacts (not the source tree) ---"
  if ! uv venv "$venv" -q; then return 1; fi
  if ! uv pip install --python "$venv/bin/python" ./packages/research-core -q; then return 1; fi
  if ! uv pip install --python "$venv/bin/python" --no-deps \
        "$dist"/deep-research/*.whl "$dist"/fact-check/*.whl -q; then return 1; fi

  local spec_dir="${PREFLIGHT_SPEC_KIT_DIR:-}"
  if [ -z "$spec_dir" ]; then
    spec_dir="$WORK/spec"
    echo "--- fetch the conformance kit fresh (matches ci.yml's own reasoning:" \
         "the bar is what the spec says today) ---"
    if ! git clone --depth 1 -q \
          https://github.com/microsoft/amplifier-smart-tools.git "$spec_dir"; then
      return 1
    fi
  else
    echo "--- using PREFLIGHT_SPEC_KIT_DIR=$spec_dir instead of a fresh clone ---"
    echo "    (ci.yml always clones fresh -- treat a PASS here with more"
    echo "    suspicion than one from a fresh clone; re-run without the"
    echo "    override before trusting it)"
  fi

  echo "--- conformance kit against both tool roots ---"
  local status=0
  for root in tools/deep-research tools/fact-check; do
    echo "  -- $root --"
    if ! (cd "$spec_dir" && PATH="$venv/bin:$PATH" uv run conformance/run.py "$REPO_DIR/$root"); then
      echo "  conformance FAILED for $root"
      status=1
    fi
  done

  echo "--- deterministic smoke, environment scrubbed (matches ci.yml exactly) ---"
  if ! env -i PATH="$venv/bin:/usr/bin:/bin" deep-research manifest < /dev/null > /dev/null; then
    echo "  deep-research manifest FAILED under env -i"
    status=1
  fi
  if ! env -i PATH="$venv/bin:/usr/bin:/bin" fact-check manifest < /dev/null > /dev/null; then
    echo "  fact-check manifest FAILED under env -i"
    status=1
  fi

  return $status
}

# ---------------------------------------------------------------------------
# `install-from-git` job replica -- best effort, see header note
# ---------------------------------------------------------------------------
job_install_from_git() {
  section "job: install-from-git (best effort -- see USAGE note)"

  local sha
  sha="$(git rev-parse HEAD)"

  echo "--- $sha (this job only means something once this commit is on origin) ---"
  if ! git ls-remote origin 2>/dev/null | grep -q "$sha"; then
    # A plain ls-remote only lists branch/tag tips, not every ancestor commit,
    # so absence here is common and NOT proof the commit is unreachable.
    # Attempt the real install and let it speak for itself.
    echo "note: $sha is not a branch/tag tip on origin (expected for most"
    echo "commits); attempting the install anyway -- it is the only real test."
  fi

  local venv="$WORK/venv-install-from-git"
  if ! uv venv "$venv" -q; then return 1; fi

  local status=0
  for tool in deep-research fact-check; do
    echo "  -- $tool @ $sha --"
    if ! uv pip install --python "$venv/bin/python" \
          "$tool @ git+$(git remote get-url origin)@${sha}#subdirectory=tools/$tool" -q; then
      echo "  could not install $tool from git @ $sha (commit may not be pushed yet --"
      echo "  this job is structurally unprovable pre-push; see USAGE note)"
      status=1
    else
      if ! "$venv/bin/$tool" manifest < /dev/null > /dev/null; then
        echo "  $tool installed from git but 'manifest' failed"
        status=1
      fi
    fi
  done

  return $status
}

# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------
START_TIME=$(date +%s)

credential_report

case "$MODE" in
  test)
    job_test; record "test" $?
    ;;
  conformance)
    job_conformance; record "conformance" $?
    ;;
  install-from-git)
    job_install_from_git; record "install-from-git" $?
    ;;
  default)
    job_test; record "test" $?
    job_conformance; record "conformance" $?
    ;;
  all)
    job_test; record "test" $?
    job_conformance; record "conformance" $?
    job_install_from_git; record "install-from-git" $?
    ;;
  *)
    echo "usage: $0 [default|test|conformance|install-from-git|all]" >&2
    exit 2
    ;;
esac

END_TIME=$(date +%s)

section "SUMMARY (${MODE}, $((END_TIME - START_TIME))s)"
for line in "${RESULTS[@]}"; do
  echo "  $line"
done

if [ "$overall_status" -eq 0 ]; then
  echo ""
  echo "preflight PASSED -- matches what CI would do with this tree."
else
  echo ""
  echo "preflight FAILED -- CI would fail too. Fix before pushing."
fi

exit "$overall_status"
