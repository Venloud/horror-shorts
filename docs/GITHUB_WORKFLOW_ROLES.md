# GitHub Actions Workflow Roles

Night Files has several GitHub Actions workflows. They do different jobs and should not be treated as interchangeable.

## Continuous Integration

**File:** `.github/workflows/ci.yml`

This is the project's general **Continuous Integration (CI)** workflow.

GitHub runs it automatically when code is pushed to `main` or when a pull request targets `main`.

CI validates the repository before code is treated as a healthy build:

- checks Python syntax;
- validates JSON configuration;
- validates the Ruflo manifests/contracts when present;
- verifies critical production files exist.

**CI is not a TikTok connection workflow.**

It does not:

- exchange a TikTok OAuth authorization code;
- create or rotate TikTok credentials;
- write GitHub secrets;
- publish a video;
- call TikTok publishing APIs;
- call YouTube publishing APIs.

The CI workflow intentionally has only `contents: read` permission.

## TikTok connection

**File:** `.github/workflows/connect-tiktok.yml`

This is a separate, manually triggered OAuth setup workflow.

It accepts the authorization code or redirect URL after the owner approves the TikTok connection, exchanges that code for a refresh token, and stores the resulting token as the `TIKTOK_REFRESH_TOKEN` repository secret.

Because this workflow handles credentials, it is intentionally separate from CI.

## Production generation

**File:** `.github/workflows/buffer_fill.yml`

This is the production content producer. It generates inventory for the GitHub Release buffer.

It does **not** publish directly to TikTok or YouTube.

## Scheduled publishing

**File:** `.github/workflows/daily.yml`

This is the production distribution workflow.

It checks the buffer first, then publishes the oldest eligible buffered item. Generation occurs only when the buffer is empty.

## YouTube credential check

**File:** `.github/workflows/yt_check.yml`

This checks the YouTube OAuth configuration. It is not general CI and it is not the TikTok connection workflow.

## YouTube backfill

**File:** `.github/workflows/yt_backfill.yml`

This handles the separate historical TikTok-to-YouTube backfill path. It should not be confused with normal buffer publishing.

## Rule

When debugging a GitHub Actions failure, identify the workflow first.

A failure in:

```
ci.yml
```

means repository validation failed.

A failure in:

```
connect-tiktok.yml
```

means the TikTok connection/OAuth setup failed.

A failure in:

```
buffer_fill.yml
```

means content generation/buffering failed.

A failure in:

```
daily.yml
```

means scheduled production distribution failed.

A failure in:

```
yt_check.yml
```

means YouTube credential validation failed.

A failure in:

```
yt_backfill.yml
```

belongs to the separate historical backfill path.

Keeping these boundaries explicit prevents an authentication problem from being mistaken for a CI problem, and prevents a generation failure from being mistaken for a publishing failure.
