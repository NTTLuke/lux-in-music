# Security policy

## Supported use

Use the latest release on your own computer. Lux In Music listens on
`127.0.0.1` by default. The studio and its inference runtime have no user login,
access control or HTTPS. Do not expose either service to the internet or to
untrusted people on a network. Public source code does not make a running studio
safe to host publicly.

Anyone who can reach the studio can read song metadata (including lyrics and
styles), download audio, submit jobs, delete songs and request model downloads.
Local binding alone is not a complete browser security boundary: the API does
not currently validate Host or Origin. Authentication, request validation and
resource limits are needed before using it as a shared service.

Models, songs, settings and runtime logs stay in ignored local directories.
Do not upload them in an issue, pull request or debugging attachment. Never
post private lyrics, style prompts, credentials or personal paths. Use synthetic
examples and redact diagnostics before sharing them. The model and component
licenses are separate from the source code license.

## Reporting a vulnerability

Use **Security → Report a vulnerability** on GitHub when private vulnerability
reporting is enabled. If that option is unavailable, ask the maintainer for a
private reporting channel without posting the vulnerability or confidential
content. Do not open a public issue containing exploit details or private songs.

Include the app version, operating system, affected component, impact and a
minimal reproduction using synthetic data. Reports are reviewed on a best-effort
basis; there is no promised response time. Fixes target the latest release.

## Maintainer checks before public publication

- Review all branches, tags, releases, issue/PR edit history, attachments and
  Actions logs/artifacts for confidential data. A secret scanner will not identify
  a private song. Deleting a branch does not remove every retained GitHub object.
- Remove exposed credentials and rotate them. For retained sensitive GitHub
  objects, follow [GitHub's removal procedure](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)
  and confirm cleanup before changing visibility. A clean clone alone is not
  proof that old commit URLs and edit history are gone.
- Enable private vulnerability reporting, secret scanning/push protection,
  Dependabot alerts and appropriate code scanning where available. Review
  collaborator access and require two-factor authentication for maintainers.
- Protect main and release tags; review changes to Actions, setup and release
  scripts. Keep PR checks read-only and require approval for fork workflows.
  The manual release script currently pushes a version commit directly to main:
  any protection must explicitly accommodate that identity or publication will
  fail. Prefer a release-PR process if direct pushes must be prohibited.
- Audit built archives and release notes. Distribute source/packages and the
  approved public demo only, without local songs, model weights or credentials.

GitHub guidance: [secure Actions use](https://docs.github.com/en/actions/reference/security/secure-use).
