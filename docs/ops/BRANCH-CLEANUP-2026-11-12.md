# Remote branch cleanup report - 2026-11-11

Repository: khs0927/Ontology-platform. Audit performed from a throwaway clone, working only on remote refs; no repository files were edited and no commits were pushed.

## Summary

| Item | Count |
| --- | --- |
| Remote heads at audit start (first observation) | 92 |
| Remote heads at deletion step | 91 |
| Branches deleted (fully merged, no open/draft PR, older than 3 days) | 32 |
| Deleted refs verifiable as ancestors of origin/main at deletion time | 32 |
| Deletions rejected or skipped | 0 |
| Remote heads after cleanup (at report time) | 60 |
| Kept: main | 1 |
| Kept: open/draft PR heads | 8 |
| Kept: recently updated heads (< 3 days, no open PR) | 11 |
| Kept: branches with commits not contained in main | 39 |
| Kept: release/* | 1 |

Main tip at audit start: `94222fc8b8b9ea2b4445e1cb617698273a2353ff`. Main tip after cleanup: `2d69e2edb8aed74acf1a3209ae411289236eb356`. Main advanced during the audit because other maintainers merged work concurrently; the ancestor check was always run against the then-current `origin/main`.

Safety rules applied before every deletion: branch is not `main`, not `gh-pages`, not `release/*`, not the head of any open or draft PR, not updated in the last 3 days, and its fetched tip is already contained in `origin/main` (`git merge-base --is-ancestor`).

## Deleted branches (32)

All of these tips were already contained in `origin/main`, so no commit became unreachable: everything is recoverable from main history (and GitHub PR "Restore branch" where a merged PR exists).

| Branch | Old tip |
| --- | --- |
| `claude/happy-brahmagupta-rqzg2t` | `cfc55b88bf7300005e58cb128c41ec90acfbe444` |
| `claude/kind-mayer-5osi75` | `71257e70114e89b9d8c4c5b7fc3033eee032e926` |
| `data/sketchup-asset-sha` | `2e95bc916461cd5f506207935ab7df0b0b3af9cb` |
| `docs/aec-pipeline-handoff-20261023` | `4b868bcdf438442423a625d43e8530651ae89ae0` |
| `docs/drawing-analysis-guide` | `0398563538048bc2dbe1d6775e4c0311872f9ce7` |
| `docs/main-pc-todo-20261009` | `c842aecfcd2a11489d90528c1b5e87e09bd2094d` |
| `docs/regulation-framework-plan` | `a7351151918982c481a6e4408a90a08799841892` |
| `docs/sketchup-0914-regroup-plan` | `6229438e35acbc0add729760cd5a265250450691` |
| `docs/status-refresh-20261008` | `fb255c3d4ac657c225917404d0122fd7020bf3f4` |
| `feat/80-batch-per-item-results` | `adaab316a1b5f268a4d3b4b542fad71cea4fe948` |
| `feat/80-review-rejected-state` | `9fafbac146331a5a446330780aa8fde1e8dfda34` |
| `feat/80-weight-cap` | `be0bd52f40dbb04293d56a0a2b135943208dfe13` |
| `feat/chat-memory-graph-index-20261015` | `d3e5c3746c5614a37878d2b0a4f2ecd32bcc40cf` |
| `feat/drawing-number-extraction` | `88ef0c8aa42424a9cfb3962abc18287005941bcc` |
| `feat/readonly-ontology-runtime-audit-20261105` | `65a2035809e6aef116ab2e92f9ad38034eb8eed6` |
| `feat/regulation-gateway-bridge` | `46228e8e87e46b5fa2a70cac0c5d7a6d001e5fae` |
| `feat/sketchup-asset-index` | `39044883943b56a4d1f0bc26f6413c3958f74fe1` |
| `feat/sketchup-asset-sha-levels` | `29da03ceed1c5a7c2f264cbc0da4764ea8846b67` |
| `feat/sketchup-bim-asset-cards` | `0d2e6f350fbe5f1eee331c35bcc85dfc6b93948e` |
| `feat/sketchup-bim-asset-playbook` | `1211d0530cc955f84d12d846b21a8743eff69fbc` |
| `feat/sketchup-cards-hierarchy-input` | `d982d56c50cc3d87a6079d266762d81efdc4ac85` |
| `feat/sketchup-class-supplement` | `49e350ecca44184319111c4996e9c466c12fe44a` |
| `feat/sketchup-object-ontology` | `2a03f5f902f84f6f3af6c0200f7322919d326e97` |
| `feat/sketchup-openings` | `3e40ffa73977f6c8e5178996a2bef12192560471` |
| `feat/sketchup-review-candidates` | `f5222e00e2ade6c92088973e7928ccfc667120cc` |
| `feat/zium-template-remaining` | `895c97d52490463031c12dd364d75d92a1c96589` |
| `fix/sketchup-collection-rollback` | `4e5eb397a7be19ede9c70c2947cb83d7bbac2429` |
| `fix/sketchup-import-evidence-idempotent` | `bdef47d0f1cc15abbbea6e12cb36768a51328c9b` |
| `fix/sketchup-review-import-regroup` | `540a0e07ce4afa2fc4b846fdb514e886f69247dd` |
| `fix/switch-venv-quoting` | `61ad0eb7c107d8ec8ec3a32640ebb0667ab74c48` |
| `integration/pr100-retired-hscad-20261105` | `1a8b6c1f449b89eeda305239dc9140f68c42e300` |
| `review/sion-map-relation-decisions` | `30bfe35e83ed6febb1700bbbcd42e9f513acc823` |

## Kept - open/draft PR heads (8)

| Branch | PR | Tip |
| --- | --- | --- |
| `feat/nvidia-auto-ontology-federation-20261107` | draft #109 | `fd217d6832` |
| `cursor/graphrag-audit-preview-notice-50a9` | #120 | `6ff0f757d1` |
| `cursor/status-ps51-switch-32e8` | #121 | `8ac8df2f26` |
| `cursor/drawing-retrieval-benchmark-55f9` | #122 | `e0fd32667b` |
| `cursor/pc-independent-readonly-api-a9bd` | #123 | `29dd13b623` |
| `cursor/sketchup-model-ingest-32e5` | #124 | `52a43348c9` |
| `cursor/fast-review-sitting-205d` | #125 | `71c663f5a9` |
| `cursor/review-extraction-weights-7277` | #126 | `5f990dae5a` |

## Kept - branches with commits not in origin/main (39)

These tips are not ancestors of `origin/main`, so they were never eligible for deletion. PR state is shown so the owner can decide per branch.

| Branch | Ahead | Behind | Tip date | PR state | Tip |
| --- | --- | --- | --- | --- | --- |
| `feat/gap-fill-upgrades` | 11 | 513 | 2026-10-07 16:18:43 +00:00 | closed unmerged PR #20 | `4c528bbe2a` |
| `feat/temporal-relations-20261001` | 11 | 529 | 2026-10-01 10:41:12 +00:00 | merged PR #14 (squash/rebase; tip not an ancestor of main) | `05af854d00` |
| `feat/zium-standards-manifest` | 9 | 165 | 2026-10-24 14:00:25 +00:00 | merged PR #86 (squash/rebase; tip not an ancestor of main) | `f352baa35b` |
| `feat/hindsight-advisory-memory-20261001` | 9 | 528 | 2026-10-01 13:45:30 +00:00 | no PR found | `336338c5c7` |
| `grokbot/hueflow-mcp2-coexistence-20261027` | 8 | 147 | 2026-10-28 13:13:47 +00:00 | merged PR #89 (squash/rebase; tip not an ancestor of main) | `ed8fc877ba` |
| `feat/aec-cair-federation-20261001` | 8 | 531 | 2026-09-30 16:18:35 +00:00 | merged PR #11 (squash/rebase; tip not an ancestor of main) | `57f83a25c9` |
| `docs/sketchup-agent-playbook` | 8 | 150 | 2026-10-27 18:00:34 +00:00 | merged PR #82 (squash/rebase; tip not an ancestor of main) | `5c07cbb258` |
| `docs/chatgpt-audit-20261002-1105-e92060` | 7 | 527 | 2026-10-02 17:59:33 +00:00 | closed unmerged PR #17 | `962367aa37` |
| `codex/restore-github-actions-ci-20260924` | 6 | 531 | 2026-09-23 19:08:01 +00:00 | merged PR #9 (squash/rebase; tip not an ancestor of main) | `606ff229f9` |
| `feat/scoped-api-security-20261001` | 5 | 530 | 2026-10-01 10:26:09 +00:00 | merged PR #12 (squash/rebase; tip not an ancestor of main) | `7ba19c2241` |
| `feat/hindsight-advisory-memory-20261002` | 5 | 527 | 2026-10-02 11:06:47 +00:00 | merged PR #16 (squash/rebase; tip not an ancestor of main) | `b38244355e` |
| `test/sketchup-asset-schema` | 5 | 150 | 2026-10-27 17:59:58 +00:00 | merged PR #78 (squash/rebase; tip not an ancestor of main) | `6d0d981678` |
| `codex/circleci-restore-cutover-20260924` | 5 | 535 | 2026-09-23 17:38:48 +00:00 | merged PR #7 (squash/rebase; tip not an ancestor of main) | `cd68c2291d` |
| `feat/zium-nanumsquare` | 4 | 163 | 2026-10-24 14:07:24 +00:00 | merged PR #88 (squash/rebase; tip not an ancestor of main) | `ab5f134899` |
| `dependabot/uv/pypdf-6.21.2` | 4 | 156 | 2026-10-27 16:28:04 +00:00 | closed unmerged PR #85 | `98dfe95d97` |
| `grokbot/packages-tests` | 4 | 168 | 2026-10-16 19:56:55 +00:00 | merged PR #74 (squash/rebase; tip not an ancestor of main) | `56ae0fc0c2` |
| `feat/sion-auth-firewall-20261001` | 4 | 530 | 2026-10-01 10:34:51 +00:00 | closed unmerged PR #13 | `22a0daf09a` |
| `codex/pg-verification-integrity-20260923` | 4 | 538 | 2026-09-23 13:26:58 +00:00 | merged PR #4 (squash/rebase; tip not an ancestor of main) | `56c3518760` |
| `feat/local-gap-fill-and-upgrades` | 4 | 513 | 2026-10-07 15:25:31 +00:00 | closed unmerged PR #21 | `279b59554e` |
| `claude/project-thread-au08rs` | 4 | 528 | 2026-10-02 00:58:24 +00:00 | merged PR #15 (squash/rebase; tip not an ancestor of main) | `f0ff22a292` |
| `docs/ci-os-matrix` | 3 | 296 | 2026-10-08 04:17:34 +00:00 | closed unmerged PR #34 | `19bfcdeb53` |
| `codex/p0-remediation-20260924` | 3 | 531 | 2026-09-29 18:39:33 +00:00 | closed unmerged PR #10 | `dda76950f9` |
| `grokbot/law-knowledge` | 2 | 168 | 2026-10-16 19:56:57 +00:00 | merged PR #75 (squash/rebase; tip not an ancestor of main) | `f5aa23c0f5` |
| `docs/status-20261009-pr51-eval` | 2 | 168 | 2026-10-17 05:57:15 +00:00 | merged PR #77 (squash/rebase; tip not an ancestor of main) | `523d3125f8` |
| `feat/zium-guidelines-ontology` | 2 | 164 | 2026-10-24 13:04:11 +00:00 | merged PR #87 (squash/rebase; tip not an ancestor of main) | `4b0dec91de` |
| `codex/cair-error-boundary-20261003` | 2 | 525 | 2026-10-03 11:05:52 +00:00 | merged PR #18 (squash/rebase; tip not an ancestor of main) | `45f2ded9ef` |
| `fix/aec-backup-docker-cp-mirror` | 2 | 168 | 2026-10-17 05:59:41 +00:00 | merged PR #76 (squash/rebase; tip not an ancestor of main) | `c59c2f45f7` |
| `grokbot/fix-known-relation-types-20261028` | 1 | 138 | 2026-10-28 14:52:23 +00:00 | no PR found | `8bb78e5b61` |
| `grokbot/ontology-refresh-20261028` | 1 | 145 | 2026-10-28 13:22:38 +00:00 | merged PR #92 (squash/rebase; tip not an ancestor of main) | `53f1c43d81` |
| `issue-81/graphrag-eval-fixture` | 1 | 146 | 2026-10-27 18:45:10 +00:00 | merged PR #91 (squash/rebase; tip not an ancestor of main) | `cb6bef6c22` |
| `docs/mcp-status-20261024` | 1 | 166 | 2026-10-24 06:25:30 +00:00 | merged PR #84 (squash/rebase; tip not an ancestor of main) | `fdd83ffa40` |
| `codex/fix-private-auth-openapi-20260924` | 1 | 537 | 2026-09-23 16:43:22 +00:00 | merged PR #6 (squash/rebase; tip not an ancestor of main) | `251065fad1` |
| `codex/fix-windows-file-uri-test-20260924` | 1 | 537 | 2026-09-23 15:45:10 +00:00 | merged PR #5 (squash/rebase; tip not an ancestor of main) | `451fa9fec2` |
| `test/ci-os-coverage` | 1 | 296 | 2026-10-08 04:10:53 +00:00 | closed unmerged PR #35 | `f3e62dfed3` |
| `feat/aec-assets-mcp` | 1 | 166 | 2026-10-24 05:43:22 +00:00 | no PR found | `89e63318ff` |
| `docs/zium-lineweight-label-probe` | 1 | 138 | 2026-10-28 15:01:42 +00:00 | merged PR #95 (squash/rebase; tip not an ancestor of main) | `fd25e91596` |
| `docs/mobile-readonly-snapshot-mcp` | 1 | 170 | 2026-10-13 16:44:53 +00:00 | merged PR #72 (squash/rebase; tip not an ancestor of main) | `c154b293aa` |
| `fix/aec-task-registration-midnight` | 1 | 85 | 2026-11-07 15:52:28 +00:00 | merged PR #111 (squash/rebase; tip not an ancestor of main) | `9574721327` |
| `bench/sion-nvidia-actual-ci-20261107` | 1 | 85 | 2026-11-07 12:07:03 +00:00 | no PR found | `214d4704b9` |

### Left for the owner to decide (12)

Branches whose only PR was closed without merging, or that have no PR, but which still carry unique commits. These are the ones worth a human look before anything is deleted:

- `feat/gap-fill-upgrades` - ahead 11, closed unmerged PR #20
- `feat/hindsight-advisory-memory-20261001` - ahead 9, no PR found
- `docs/chatgpt-audit-20261002-1105-e92060` - ahead 7, closed unmerged PR #17
- `dependabot/uv/pypdf-6.21.2` - ahead 4, closed unmerged PR #85
- `feat/sion-auth-firewall-20261001` - ahead 4, closed unmerged PR #13
- `feat/local-gap-fill-and-upgrades` - ahead 4, closed unmerged PR #21
- `docs/ci-os-matrix` - ahead 3, closed unmerged PR #34
- `codex/p0-remediation-20260924` - ahead 3, closed unmerged PR #10
- `grokbot/fix-known-relation-types-20261028` - ahead 1, no PR found
- `test/ci-os-coverage` - ahead 1, closed unmerged PR #35
- `feat/aec-assets-mcp` - ahead 1, no PR found
- `bench/sion-nvidia-actual-ci-20261107` - ahead 1, no PR found

The other 27 unique-commit branches have a **merged** PR but their commit tip is not a direct ancestor of main (squash/rebase merges). The content is most likely in main already; they were still kept, because the safe rule is strict ancestry and only the owner should confirm squash-merged branches.

## Kept - recently updated heads (< 3 days, no open PR) (11)

Never eligible for deletion regardless of ancestry, to avoid racing active work:

- `ci/aec-drift-inventory-20261109` - tip 2026-11-08 17:14:52 +00:00, ahead 0, behind 78, merged PR #112 (squash/rebase; tip not an ancestor of main)
- `claude/aec-port-ontology-105-106` - tip 2026-11-09 04:58:04 +00:00, ahead 4, behind 67, merged PR #117 (squash/rebase; tip not an ancestor of main)
- `claude/cloud-work-completion-upgrade-beuecn` - tip 2026-11-09 04:11:18 +00:00, ahead 0, behind 65, merged PR #116 (squash/rebase; tip not an ancestor of main)
- `claude/gallant-goodall-u0z28w` - tip 2026-11-11 13:58:20 +00:00, ahead 0, behind 73, merged PR #115 (squash/rebase; tip not an ancestor of main)
- `claude/youthful-johnson-tygvk1` - tip 2026-11-11 14:31:57 +00:00, ahead 0, behind 37, merged PR #101 (squash/rebase; tip not an ancestor of main)
- `feat/aec-catchup-108-109-20261111` - tip 2026-11-11 14:44:40 +00:00, ahead 4, behind 43, no PR found
- `feat/aec-gdrive-cad-pack-20261109` - tip 2026-11-11 14:08:55 +00:00, ahead 0, behind 27, merged PR #113 (squash/rebase; tip not an ancestor of main)
- `feat/embedhub-nvidia` - tip 2026-11-09 17:07:55 +00:00, ahead 0, behind 55, merged PR #106 (squash/rebase; tip not an ancestor of main)
- `fix/graphrag-audit-isolation` - tip 2026-11-11 13:57:44 +00:00, ahead 1, behind 84, merged PR #107 (squash/rebase; tip not an ancestor of main)
- `fix/land-layer-fail-closed` - tip 2026-11-10 10:36:10 +00:00, ahead 3, behind 59, merged PR #118 (squash/rebase; tip not an ancestor of main)
- `refactor/archontos-as-dependency` - tip 2026-11-09 16:59:25 +00:00, ahead 0, behind 60, merged PR #119 (squash/rebase; tip not an ancestor of main)

## Kept - protected defaults

- `main` - tip `2d69e2edb8aed74acf1a3209ae411289236eb356` (default branch, ahead 0 by definition)
- `release/v0.3.0-prep` - release branch, kept (ahead 1)

## Concurrent activity observed (not caused by this cleanup)

The remote was live while this audit ran, so head counts drifted. First enumeration: 92 heads. Classification (before any cleanup write): 91 heads. Immediately after the 32 deletions: 59 heads. At report time: 60 heads. The differences are explained by other maintainers'/agents' work:

- `fix/ci-verify-postgres-client` (head of PR #127) was present in the initial open-PR list but already gone from remote heads by the classification step; PR #127 is closed without merge and its branch was removed by another actor. It was not deleted by this cleanup.
- `ci/postgres-service-container` (head of PR #128) was present and protected during classification; PR #128 was merged at 14:54:51Z and the head branch was auto-deleted afterwards. It was not in the deletion list and was not touched by this cleanup.
- `origin/main` advanced from `94222fc8` to `2d69e2ed` during the audit (concurrent merges, including PR #128). The ancestry check was re-run against the then-current `origin/main` immediately before each deletion.
- `release/v0.3.0-prep` appeared after the cleanup while a concurrent release task prepared v0.3.0; it is protected by the `release/*` rule. Other branches were also created or updated by concurrent tasks during the audit (for example `feat/aec-catchup-108-109-20261111` and `fix/graphrag-audit-isolation`); none were touched by this cleanup because none were eligible under the safety rules.

## Remote default branch / origin/HEAD check

The remote default branch is healthy: `git ls-remote --symref origin HEAD` reports `ref: refs/heads/main HEAD` and the GitHub API default branch is `main`. The oddity is local-only: throwaway clones made from the lead's clone inherited a stale `refs/remotes/origin/HEAD` symbolic ref pointing at a feature branch (`ci/postgres-service-container` in this clone, `docs-refresh` in the lead's clone), even though those clones were on `main` physically. This is a local clone artifact, not a remote misconfiguration; a fresh `git remote set-head origin -a` fixes each clone. No remote ref named `gh-pages` or `release/*` existed at audit start.

## Recovery

Every deleted tip was contained in `origin/main` at deletion time, so the commits remain reachable and no history was lost. To restore one of these refs, recreate the branch at the recorded old tip, e.g. `git push origin <old-tip>:refs/heads/<branch>`, or use the merged PR's "Restore branch" button on GitHub.

## Verification

- Head counts observed with `git ls-remote --heads origin`: 92 (first enumeration), 91 (classification, before cleanup writes), 59 (immediately after deleting 32), 60 (report time). The gap between head-count math and the deletion count is fully explained by the concurrent activity listed above.
- Post-cleanup re-audit found 0 remaining deletion candidates: every remaining head is main, an open/draft PR, a release branch, updated within 3 days, or has commits not in main.
- All 8 open/draft PR heads present at report time still exist on the remote.
- No deletion was rejected by the remote; 0 skipped/failed items.
- Every deleted tip was re-verified as an ancestor of the then-current `origin/main` immediately before its deletion, and every deletion was confirmed by re-listing remote heads (0 of 32 still present).

## Second pass - 2026-11-12 04:05-04:15 KST

Run from the lead clone after the cutover, against the remote refs only. No repository file was edited for the cleanup itself and no commit was pushed by it.

**Backup first.** A bundle of every ref was created before any deletion and verified:

```
%USERPROFILE%\sion-bundles\ontology-platform-all-refs-20261112-040515.bundle   (8,534,428 bytes)
$ git bundle verify ... -> "The bundle records a complete history."
```

The same file was copied to the Drive backup lake (`G:\내 드라이브\AEC-INTELLIGENCE\backups\`), so the state before the deletion is recoverable off the machine as well.

**Selection rule.** A remote head was deleted only when all of the following held:

- it is not `main`, not `gh-pages`, not `release/*`;
- it is not the head of an open or draft PR (no PR was open on the repository at that moment);
- its tip is either an ancestor of the then-current `origin/main` (`git merge-base --is-ancestor`) **or** it carries no patch-unique commit (`git cherry origin/main <branch>` reports only `-`, i.e. every commit is already reachable in `main` by patch id).

| Group | Count |
| --- | --- |
| Remote heads at the start of the second pass | 54 |
| Deleted: tip is an ancestor of `origin/main` | 8 |
| Deleted: no patch-unique commit left | 11 |
| Deleted: total | 19 |
| Skipped or rejected | 0 |
| Remote heads after the second pass | 35 |
| Kept: `main` | 1 |
| Kept: heads with patch-unique commits (real pending work) | 34 |

**Deleted branches (19)**

```
ci/aec-drift-inventory-20261109      claude/cloud-work-completion-upgrade-beuecn
claude/gallant-goodall-u0z28w        claude/youthful-johnson-tygvk1
docs/main-pc-cutover-20261112        feat/aec-gdrive-cad-pack-20261109
feat/embedhub-nvidia                 fix/switch-legacy-prefix
codex/fix-private-auth-openapi-20260924   codex/fix-windows-file-uri-test-20260924
docs/mcp-status-20261024              docs/mobile-readonly-snapshot-mcp
docs/zium-lineweight-label-probe      fix/aec-task-registration-midnight
fix/graphrag-audit-isolation          grokbot/fix-known-relation-types-20261028
grokbot/ontology-refresh-20261028     issue-81/graphrag-eval-fixture
test/sketchup-asset-schema
```

The eleven "no patch-unique commit" branches are branches whose work was merged by a squash or by a later rebase, so their tips are not ancestors of `main` while their content is already in `main` (`git cherry` reports `-` for every commit). They were therefore kept by the naive ancestor rule and deleted only after the patch-id check.

**Kept on purpose (34 heads with patch-unique commits)**

`bench/sion-nvidia-actual-ci-20261107`, `claude/aec-port-ontology-105-106`, `claude/project-thread-au08rs`, `codex/cair-error-boundary-20261003`, `codex/circleci-restore-cutover-20260924`, `codex/p0-remediation-20260924`, `codex/pg-verification-integrity-20260923`, `codex/restore-github-actions-ci-20260924`, `dependabot/uv/pypdf-6.21.2`, `docs/chatgpt-audit-20261002-1105-e92060`, `docs/ci-os-matrix`, `docs/sketchup-agent-playbook`, `docs/status-20261009-pr51-eval`, `feat/zium-guidelines-ontology`, `feat/aec-assets-mcp`, `feat/aec-cair-federation-20261001`, `feat/aec-catchup-108-109-20261111`, `feat/gap-fill-upgrades`, `feat/hindsight-advisory-memory-20261001`, `feat/hindsight-advisory-memory-20261002`, `feat/local-gap-fill-and-upgrades`, `feat/scoped-api-security-20261001`, `feat/sion-auth-firewall-20261001`, `feat/temporal-relations-20261001`, `feat/zium-nanumsquare`, `feat/zium-standards-manifest`, `fix/aec-backup-docker-cp-mirror`, `fix/land-layer-fail-closed`, `fix/review-document-candidates`, `grokbot/hueflow-mcp2-coexistence-20261027`, `grokbot/law-knowledge`, `grokbot/packages-tests`, `test/ci-os-coverage`.

These carry work that is not in `main` yet, so they are left for their owners to finish, merge or drop. `fix/review-document-candidates` is the branch of PR #137, merged at the time of this pass.

**Verification.** Every deletion was confirmed by re-listing the remote heads (`git ls-remote --heads origin`): 54 before, 35 after, and none of the 19 names is present any more. `origin/HEAD` still points at `main`.


