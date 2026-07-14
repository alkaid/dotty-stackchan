# Claude Code Session Prompt

This prompt delegates deployment to the repository's canonical runbook instead
of duplicating commands that can drift.

```text
Read AGENTS.md, CLAUDE.md, and docs/deployment.md before making changes.

Deploy the complete Dotty StackChan stack on one Linux Docker host. Use only
the tracked root compose.yml. Build application source, providers, extensions,
personas, and built-in assets into images through the repository Dockerfiles.
Do not add source bind mounts, docker cp, docker exec, per-service Compose
files, or post-start source patching.

Use Compose service DNS for all container-to-container calls. Configure public
client origins separately for StackChan hardware and browsers; they may point
to LAN addresses or public gateways and are rendered into the OTA configuration.

Create .env from .env.example, fill the required public origins, ports, admin
token, and model routing values, then run make setup. Preserve .env, data/, models/, tmp/,
and the external state directories on updates. Finish by running make doctor,
docker compose ps, and the health checks documented in docs/deployment.md.

If deployment behavior, Dockerfiles, Compose services, environment variables,
mounts, model routing, or service call paths change, update
docs/deployment.md in the same change.
```
