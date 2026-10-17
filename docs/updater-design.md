# GreenCraft updater repair

## Contract

Preserve all current content, Iris/Sodium dependency handling, first-install
defaults, user configuration preservation, dedicated-server testing, GPU testing,
monitoring, optional Discord notifications and archived releases.

The repository, not the launcher, resolves updates. Run every six hours and on
manual dispatch. Resolve the current stable Minecraft even when Mojang has not
released a new version. Only when there is no current-version update, investigate
the latest Minecraft. Network or compatibility errors must fail visibly without
publishing a partial candidate or modifying stable.

`greencraft-release.json` is external control-plane metadata. It must never be
listed in the Packwiz index. Its status and timestamps must not change pack
integrity or cause an install. Packwiz still hashes every installed file.

Compare actual installable files plus Minecraft/Fabric versions, excluding release
numbers, timestamps and status. Identical builds are no-ops and preserve an
existing candidate's GPU status and age. A changed build receives the next patch
version above stable and any previous candidate. No component already present
in stable may silently disappear because an optional release is missing.

Validation verifies the complete local hash chain, metadata/index coverage,
release/pack agreement, Modrinth release/MC/loader/dependency compatibility and
download checksums for both client and server content. Dedicated server must
start with the exact pinned Fabric loader. CI evidence is bound to the candidate
payload digest. GPU evidence must refer to that same digest. Promotion requires
both, validates again, archives stable without overwriting an archive, then
copies the candidate and changes only external metadata. A failed push cannot
claim publication. Concurrent remote changes require a new run, never a forced
push or automatic rebase of tested content.

## Publication boundary

Retain the existing local real-GPU validation requirement: GitHub-hosted runners
cannot prove Iris/shader rendering works. Candidate creation and validation are
automatic; stable publication finishes after the local GPU validator passes.
No self-hosted runner, launcher replacement or automatic untested promotion.

## Repair of existing channels

Remove the stale JSON entry and regenerate index/pack hashes for stable and
candidate without changing content pins or settings. Give stable a patch release
for the installation-manifest repair. Legacy candidate evidence is not sufficient
for future promotion; it must pass the new validation pipeline first.

## Implementation and checks

1. Add regression tests for JSON status changes, tampered files, no-op detection,
   patch allocation, missing components, dependency cycles/conflicts and promotion
   evidence. Run before implementation to establish failures.
2. Add shared payload/integrity/version functions; update builder and status tools.
3. Add automatic candidate preparation and online validation with digest evidence.
4. Gate promotion and the GPU validator on exact content; fix workflow execution,
   cleanup, publication and error reporting. Add PR CI without publishing.
5. Repair channel manifests, run unit tests, offline channel checks, online API and
   download checks where available, PowerShell/YAML parsing and workflow lint.
6. Publish a review branch and PR. Main/stable deployment requires review.

## Review focus

Timestamp-only rebuilds; unchanged pending GPU candidates; failed downloads;
status-only attempts to forge promotion; stable changes during a GPU test;
client-only dependencies missed by a server smoke test; Windows CRLF checkout.
