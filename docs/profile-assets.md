# Profile Assets

This repository keeps generated profile assets isolated and workflow-owned.

## Generated files

- `dist/github-contribution-grid-snake.svg`
- `dist/github-contribution-grid-snake-dark.svg`
- `assets/skyline/bujhmml-github-skyline.stl`

The skyline STL appears after the first successful run of `.github/workflows/skyline.yml`.

## Workflows

- `.github/workflows/snake.yml` regenerates only the snake SVG files in `dist/`.
- `.github/workflows/skyline.yml` regenerates only the official `gh skyline` STL in `assets/skyline/`.

## Do not edit by hand

- Do not manually edit files in `dist/`.
- Do not manually edit files in `assets/skyline/`.
- Do not make README changes from asset-refresh workflows.

## Manual skyline regeneration

If you need to regenerate the skyline locally, use the official GitHub CLI extension:

```bash
brew install gh
gh auth login
gh extension install github/gh-skyline
gh skyline --user bujhmml --full --output assets/skyline/bujhmml-github-skyline.stl
```

If you prefer token-based auth, set `GH_TOKEN` or `GITHUB_TOKEN` before running `gh skyline`.
