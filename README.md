# clip-engine

Turns long gaming VODs into vertical short clips on GitHub Actions runners (CPU only).
Code only: no clips, tokens or notes live here. Nothing is ever posted from this repo.

- `feasibility.yml`: step 0 test (download one VOD, time whisper.cpp on CPU, find moments, render a few clips).
  Output is a one-day workflow artifact.

The clip engine is [iyansr/gaming-clip](https://github.com/iyansr/gaming-clip) (AGPL-3.0), cloned at a pinned
commit when a job runs; it is not copied into this repo.
