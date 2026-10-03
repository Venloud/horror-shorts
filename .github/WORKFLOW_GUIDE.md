# Workflow & AI Implementation Guide

## What this file is
This file documents GitHub automation and AI-assisted implementation work in plain English. It is documentation only and does not change how the project runs.

## What to document
For each workflow, record:
- **Name**
- **Trigger** — push, pull request, schedule, manual, or another event
- **Purpose** — what it actually does
- **External services** — APIs or platforms it touches
- **Secrets required** — names only; never secret values
- **Manual steps** — anything the owner still needs to do

## AI implementation notes
When an AI-assisted change is made, explain what changed, why it changed, which files/workflows are affected, and any manual step that remains. The goal is that you can open the repository and immediately understand what was implemented in the background without reconstructing the work from chat history.

## Key distinction
**CI/build workflows** validate or build the project. **Connection/check workflows** authenticate or verify external platforms. **Production/posting workflows** perform the actual content operation. Do not treat these as the same thing.

## Security
Never put API keys, refresh tokens, passwords, cookies, or other secret values in this file.
