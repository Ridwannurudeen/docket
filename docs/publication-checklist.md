# Repository publication checklist

Repository publication is an owner-only action. No repository visibility change was
performed while preparing this checklist. Complete the steps in order; stop if a gate does
not match its stated result.

The history review is intentionally **accept-and-harden**, not a rewrite. Rewriting would
invalidate commit-pinned evidence in `docs/operational-evidence.md`,
`docs/source-deploy-manifest.md`, and `docs/deliberation/AUDIT-BACKLOG.md`. Historical
findings remain historical; the publication gate is a clean tip, an explicit disclosure,
and no live credential in any reachable object.

1. [ ] Review the uncommitted W13 report's exact release, clean-clone, and full-history
   sweep results; approve accept-and-harden only if it lists paths and finding kinds without
   values: `Get-Content -Raw .\BUILD-REPORT.md`
2. [ ] Confirm the local release branch is `main` and that the only permitted untracked
   handoff is `BUILD-REPORT.md`: `git branch --show-current; git status --short`
3. [ ] Confirm the default-branch tip contains the public landing files, CI, and this
   checklist: `git ls-tree -r --name-only HEAD -- README.md LICENSE AI_USAGE.md .github/workflows/ci.yml docs/publication-checklist.md`
4. [ ] Review every retained Actions log because GitHub makes Actions history and logs
   public with the repository: GitHub > **Actions** > **ci** > each retained run > inspect
   its jobs and logs; stop and rotate before publication if a credential appears.
5. [ ] Record the exact tip that will become public: `git rev-parse HEAD`
6. [ ] Push that exact `main` tip to GitHub: `git push origin main`
7. [ ] Require both jobs on that pushed tip to pass: GitHub > **Actions** > **ci** > the
   run for the recorded commit > confirm **test** and **package** are green.
8. [ ] Confirm the repository still names `main` as its default branch: GitHub >
   **Settings** > **General** > **Default branch** > `main`.
9. [ ] Set the repository's public landing metadata: repository page > **About** gear >
   add `https://docket.gudman.xyz/` as the website and save.
10. [ ] Change visibility only after steps 1-9 pass: GitHub > **Settings** > **General** >
    **Danger Zone** > **Change repository visibility** > **Public** > confirm the
    repository, click **I have read and understand these effects**, then click
    **Make this repository public**.
11. [ ] Protect the now-public default branch: GitHub > **Settings** > **Rules** >
    **Rulesets** > **New branch ruleset** > target `main`, require **test** and **package**,
    then activate the ruleset.
12. [ ] Verify visibility and the default branch from GitHub's API:
    `gh repo view Ridwannurudeen/docket --json visibility,defaultBranchRef,url`
13. [ ] Verify an anonymous Git client can read the published `main` tip:
    `$env:GIT_TERMINAL_PROMPT='0'; git -c credential.helper= ls-remote https://github.com/Ridwannurudeen/docket.git refs/heads/main`
14. [ ] Verify the public README and live judge route both answer:
    `@('https://raw.githubusercontent.com/Ridwannurudeen/docket/main/README.md','https://docket.gudman.xyz/') | ForEach-Object { (Invoke-WebRequest -UseBasicParsing -Uri $_ -Headers @{Accept='text/html'}).StatusCode }`
15. [ ] Keep the repository public and the live site reachable through 2026-09-23; check
    daily: `@('https://github.com/Ridwannurudeen/docket','https://docket.gudman.xyz/') | ForEach-Object { (Invoke-WebRequest -UseBasicParsing -Uri $_ -Headers @{Accept='text/html'}).StatusCode }`

Publication is not hackathon submission approval. Do not submit, publish a release, or
broadcast a registration or payment transaction without the owner's separate explicit
approval for that action.
