# Changelog

All notable changes to this project are documented here.
This project adheres to [semantic versioning](https://semver.org/).

## 1.0.0

Initial release. Extracted from the Callsy infrastructure repositories, where the construct
had already been running in production.

- `SecureParameter` — one encrypted SecureString parameter, written once with a placeholder
  and never rewritten by a later deploy.
- One IAM role per stack, granted over the whole parameter prefix rather than per parameter.
- `SecureParameter.build_name` — the full name a parameter carries under a prefix.
- `SecureParameter.chain` — serialises a group of parameters so Parameter Store does not throttle.
- `SecureParameter.as_string_parameter` / `as_ecs_secret` — read the deployed value at runtime.
- New over the in-repo version: an explicit `prefix` instead of a repository local config
  object, plus `tags`, `placeholder`, `key_id`, `tier` and `ignore_existing` options.
