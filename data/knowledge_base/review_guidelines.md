# Team review guidelines

- We use parameterised queries everywhere; any string-built SQL is a blocker.
- Passwords must be hashed with a slow, salted algorithm (bcrypt, scrypt or argon2).
- Secrets come from environment variables or the secret manager, never from code.
- Functions that can fail must not report success after an error.
- Prefer one query with a JOIN or IN (...) over a query per row.
