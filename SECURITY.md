# Security Policy

## Supported versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

Older or unreleased versions are not supported with security fixes.

## Reporting a vulnerability

Please report security vulnerabilities **privately**. Do not open a public
issue or pull request for a suspected vulnerability.

Use GitHub's private vulnerability reporting:

1. Go to the **Security** tab of this repository.
2. Open **Report a vulnerability** to file a private GitHub Security Advisory.

We aim to acknowledge new reports within **5 business days** and will keep you
updated as we investigate and prepare a fix. Once a fix is available we will
coordinate a disclosure timeline with the reporter.

## Security-relevant characteristics

Logica Mind stores and recalls user memory, which may include personal data
(PII). When evaluating or deploying it, keep the following in mind:

- **User memory / PII** — the library persists durable memories and an evolving
  user model. Treat the underlying store as containing personal data.
- **Bundle export is HMAC-signed** — exported memory bundles are signed with an
  HMAC so their integrity can be verified on import. Protect the signing key.
- **PII redaction** — `redact_pii()` is available to scrub common personal data
  patterns from text before it is stored or exported.
- **GDPR-style erasure** — the library supports erasing a subject's data
  (`forget_about()` / `purge()`) to satisfy right-to-erasure requests.
- **API keys from the environment** — embedding and LLM providers read their
  credentials (for example Voyage or OpenAI keys) from environment variables.
  Keys are never hard-coded or committed; manage them with your own secret
  store and never log them.

If you discover a way these protections can be bypassed, please report it
privately as described above.
