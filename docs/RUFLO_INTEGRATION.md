# Ruflo Integration

## Status

Ruflo is the next external integration for Night Files. The first stage is deliberately lightweight.

The production generator and publisher remain the source of execution truth. Ruflo is not installed or started by the normal GitHub Actions production run.

## Why

Ruflo provides agent orchestration around Claude Code/Codex, including agents, swarms, memory, hooks, and workflows. Night Files can use those ideas to coordinate research, story writing, visual planning, QA, and packaging.

The first Night Files implementation therefore records the orchestration contract without introducing another required runtime.

## Current integration

- `pipeline/ruflo_plan.json` describes the canonical Night Files stages and role ownership.
- `pipeline/ruflo_check.py` validates the plan and prints the delegation graph.
- No existing production Python stage imports Ruflo.
- No new secret is required.
- No Anthropic API key is added to GitHub Actions for Ruflo.
- No Ruflo daemon or swarm is started by production.
- Existing publishing behavior is unchanged.

## Future activation path

1. Use the manifest with Claude Code/Ruflo during non-production development tasks.
2. Add selected agents for research, story review, visual review, or packaging review.
3. Persist only useful patterns/memory that Night Files can safely reuse.
4. Keep production tasks deterministic until Ruflo has been separately validated.
5. Only then consider optional delegation of a specific stage.

## Role contract

### Planner
Maps a task into existing Night Files stages and dependencies. It does not rewrite the production architecture.

### Researcher
Finds source material and verifies claims. For true stories, evidence must remain traceable to the existing research/source system.

### Writer
Produces or revises the story while respecting the existing hook, fact-lock, tone, and duration rules.

### Visual planner
Maps narration to shots, characters, locations, and continuity constraints. It must not weaken the visual QA rules.

### QA reviewer
Reviews the rendered output and diagnostic signals. QA remains report-only in the current production design.

### Packaging reviewer
Reviews captions, titles, hashtags, pinned comments, and platform metadata without changing the actual posting transport.

## Safety boundary

Do not copy Ruflo's full runtime, MCP server, plugin tree, or agent database into Night Files.

Do not make production depend on an external agent swarm.

Do not add Ruflo credentials to the repository.

Do not let an orchestration failure discard a generated video.

## Validation

Run:

```bash
python pipeline/ruflo_check.py
```

Expected:

```
RUFLO CHECK: PASS
```

Official project:
https://github.com/ruvnet/ruflo
