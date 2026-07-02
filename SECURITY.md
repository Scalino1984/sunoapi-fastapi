# Security Policy

## Supported Versions

This repository currently tracks the active `main` branch. Security fixes are expected to land there first.

## Reporting a Vulnerability

Please do not publish suspected security issues as public GitHub issues.

Report vulnerabilities privately through GitHub Security Advisories for this repository, or contact the maintainer through the profile linked on GitHub.

Include:

- affected version or commit
- clear reproduction steps
- expected and actual impact
- whether any provider keys, local files or user data could be exposed

## Secrets and Provider Keys

Never commit real `.env` files, API keys, OAuth tokens, SSH keys, databases or generated media storage.

Use `.env.example` for documented placeholder values only. Real credentials belong in a local `.env` or deployment secret manager.

## External Provider Costs

This app can call paid services such as SunoAPI.org, OpenAI, Groq, Replicate and other configured providers. Security reports and tests should avoid real provider calls unless explicitly agreed.
