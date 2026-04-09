# sky-env

> Encrypted environment variable manager for developers who are tired of `.env` files lying around in plaintext.

`sky-env` stores your environment variables in an **AES-256-CBC encrypted SQLite database**, organised by project and environment. The database is portable across machines, safe to back up, and (with the right secret hygiene) safe to commit to a private git repository.

Built with [Sky](https://github.com/anzellai/sky) — a pure functional language that compiles to a single Go binary, no runtime dependencies.

---

## Why sky-env?

The standard developer workflow for environment variables is broken:

- `.env` files sit on disk in **plaintext**, often in the project root
- `.env.example` drifts out of sync with the real `.env`
- Switching between `dev`, `staging`, `prod` means juggling files
- Sharing secrets with teammates means Slack DMs, 1Password lookups, or "ask Bob"
- Backing up secrets means hoping you remembered to copy `.env` before reformatting your laptop
- Multiple projects mean multiple `.env` files to track and rotate

`sky-env` fixes all of these:

| Pain | Fix |
|---|---|
| Plaintext on disk | AES-256-CBC encrypted at rest |
| `.env.example` drift | `sky-env diff` shows missing keys across environments |
| Juggling files | One database, multiple projects, multiple environments |
| Onboarding teammates | Share the encrypted DB + secret separately (Slack the secret, commit the DB) |
| Laptop reformat | `cp ~/.local/sky-env/skyenv.db /backup/` and you're done |
| Multi-project | Auto-detected from `cwd`'s basename |

---

## Install

### macOS / Linux (one-liner)

```bash
curl -fsSL https://github.com/anzellai/sky-env/releases/latest/download/sky-env-$(uname -s | tr A-Z a-z)-$(uname -m | sed 's/x86_64/x64/;s/aarch64/arm64/') -o /usr/local/bin/sky-env
chmod +x /usr/local/bin/sky-env
sky-env init
```

### Manual download

Grab the binary for your platform from [Releases](https://github.com/anzellai/sky-env/releases/latest):

| Platform | Binary |
|---|---|
| macOS arm64 (Apple Silicon) | `sky-env-darwin-arm64` |
| macOS x64 (Intel) | `sky-env-darwin-x64` |
| Linux x64 | `sky-env-linux-x64` |
| Linux arm64 | `sky-env-linux-arm64` |
| Windows x64 | `sky-env-windows-x64.exe` |

`chmod +x` the binary, drop it on your `PATH`, and you're ready.

### Requirements

- **`openssl`** must be on your `PATH` (installed by default on macOS and most Linux distributions)
- That's it — no Node, no Python, no Go, no Sky runtime

### Build from source

```bash
git clone https://github.com/anzellai/sky-env
cd sky-env
sky install
sky build src/Main.sky
./sky-out/sky-env --help
```

---

## Quick start

### 1. Generate your secret (one time, per machine)

```bash
$ sky-env init

Generated sky-env secret (256 bits, hex-encoded):

  2f7eb3c30e4a50f2111e8b402643ca35d0248131ef773550515bd33433326d4d

Add this to your shell config (~/.bashrc or ~/.zshrc):

  export SKY_ENV_SECRET="2f7eb3c30e4a50f2111e8b402643ca35d0248131ef773550515bd33433326d4d"

Then restart your shell or run: source ~/.zshrc

Keep this secret safe — losing it means losing access to
all encrypted environment variables stored under this key.
```

The secret is read from `/dev/urandom` (256 bits of true entropy). It is the only thing you need to keep safe — every encrypted value derives its key from this secret via PBKDF2 (100,000 iterations).

`sky-env init` will refuse to overwrite an existing `SKY_ENV_SECRET` to prevent accidentally destroying access to existing data.

### 2. Import your `.env` file into a named environment

```bash
$ cd ~/code/my-app

$ ls .env*
.env.dev    .env.prod    .env.example

$ sky-env import dev
Imported 12 variables into my-app/dev

$ sky-env import prod
Imported 14 variables into my-app/prod
```

`sky-env import <env>` looks for `.env.<env>` first, then falls back to `.env`, then prompts you with `.env.example` keys interactively. The project name comes from the current directory's basename.

You can now safely delete or git-ignore `.env.dev` and `.env.prod` — they're in the encrypted database.

### 3. Print decrypted variables when you need them

```bash
$ sky-env print dev
API_KEY=abc123
DB_URL=postgres://localhost/myapp_dev
STRIPE_KEY=sk_test_xxx
...

# Pipe straight back into your shell
$ eval "$(sky-env print dev | sed 's/^/export /')"

# Or write back to a temporary file for tools that need .env
$ sky-env print dev > .env
node server.js
rm .env
```

### 4. Set or update individual variables securely

```bash
$ sky-env set dev API_KEY
  Enter value for API_KEY: ********
Set API_KEY in my-app/dev
```

The value is read from stdin so it never appears in your shell history (unlike `export API_KEY=...`).

### 5. Diff environments to find missing keys

```bash
$ sky-env diff
Comparing environments for my-app:

KEY                           dev         staging     prod
------------------------------------------------------------

API_KEY                       OK          OK          OK
DB_URL                        OK          OK          OK
STRIPE_KEY                    OK          MISSING     OK
SENTRY_DSN                    MISSING     OK          OK

Missing keys:
  staging is missing: STRIPE_KEY
  dev is missing: SENTRY_DSN
```

This is the killer feature for keeping environments in sync. No more "it works on staging but breaks on prod because we forgot to add `SENTRY_DSN`."

### 6. List everything

```bash
$ sky-env list
my-app
  - dev
  - staging
  - prod
my-other-app
  - dev
  - prod
internal-tool
  - dev
```

---

## Encryption model

`sky-env` uses **AES-256-CBC** with PBKDF2 key derivation, via the system `openssl` binary. Each encrypted value uses:

- A **fresh random 8-byte salt** (per encryption call)
- **PBKDF2-HMAC-SHA256** with **100,000 iterations** to derive the AES key from your secret
- **AES-256-CBC** symmetric cipher
- Output is base64-encoded with the `Salted__` magic header so it round-trips through SQLite TEXT columns

This is the same encryption you get from `openssl enc -aes-256-cbc -pbkdf2 -salt`. It is **standards-compliant**, **interoperable**, and **decryptable from any tool** that can read the OpenSSL salted format — not a custom Sky-only scheme.

### What this gets you

✓ **At-rest encryption.** Without `SKY_ENV_SECRET`, the SQLite file is opaque ciphertext. No casual or determined reader can recover your values without the secret.

✓ **Per-value salts.** Encrypting the same value twice produces different ciphertexts. An attacker comparing the database across snapshots cannot tell which values changed.

✓ **Slow key derivation.** PBKDF2 with 100k iterations means brute-forcing the secret is computationally expensive — orders of magnitude slower than a naive sha256 hash.

✓ **Standards-based.** If sky-env disappears tomorrow, you can decrypt your database with `openssl enc -aes-256-cbc -pbkdf2 -d -base64 -A -pass env:SKY_ENV_SECRET <<< "<ciphertext>"`.

### What it does NOT protect against

✗ **Losing the secret.** PBKDF2 is one-way. If you lose `SKY_ENV_SECRET`, your data is gone. There is no recovery, no backdoor, no support email. Treat your secret like an SSH private key.

✗ **Active malware on your machine.** If something is running as your user, it can read both the database AND your environment variable. sky-env protects data **at rest**, not against running adversaries.

✗ **Brief temp file exposure.** During encrypt/decrypt, the plaintext is briefly written to a temp file (so `openssl` can read it without the value appearing in process arguments). This file is created in the OS temp directory with default user-only permissions and deleted immediately. Single-user developer machines: fine. Multi-user shared servers: avoid sky-env or use a tmpfs path.

---

## Where is the data stored?

```
~/.local/sky-env/skyenv.db    -- SQLite database
```

The database has two tables:

```sql
CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE env_vars (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    environment TEXT NOT NULL,
    key TEXT NOT NULL,           -- plain text
    value TEXT NOT NULL,         -- AES-256-CBC ciphertext, base64
    UNIQUE(project_id, environment, key)
);
```

Variable **keys** are stored in plain text (so you can grep for `WHERE key = 'API_KEY'`). Variable **values** are encrypted. Project names are also plain text. If you consider key names sensitive (e.g. `STRIPE_LIVE_SECRET_KEY`), keep this in mind.

---

## Portability and backup

The single SQLite file is the entire data store. To move sky-env to a new machine:

```bash
# On the old machine
cp ~/.local/sky-env/skyenv.db /tmp/skyenv.db
# transfer to new machine (scp, syncthing, USB, etc.)

# On the new machine
mkdir -p ~/.local/sky-env
cp /tmp/skyenv.db ~/.local/sky-env/skyenv.db

# AND set the same SKY_ENV_SECRET on the new machine
export SKY_ENV_SECRET="<the same hex string from sky-env init>"
```

The secret never lives in the database, so the database alone is useless without it. The secret never lives on disk (unless you put it in `.bashrc`/`.zshrc`), so it's safe from anyone reading your home directory.

### Can I commit the database to GitHub?

**Private repo:** yes, this is a reasonable backup strategy. Anyone with repo access still cannot read values without the secret. The database is at-rest encrypted with PBKDF2(100k iterations) + AES-256-CBC. Brute-forcing is expensive enough that even a leaked private repo + sufficient compute would not yield secrets quickly. Make sure to:
- Never commit your `SKY_ENV_SECRET` (never put it in repo files, only in your shell config or a secrets manager)
- Rotate the secret periodically and re-import all values

**Public repo:** technically possible but **not recommended**. Even with PBKDF2, a determined attacker with infinite time and compute can attempt offline brute force. If your secret has low entropy (which `sky-env init`'s secrets do not — they're 256 bits from `/dev/urandom`), this becomes feasible. Use private repos or out-of-band backups for sky-env databases.

---

## Sharing secrets with a team

The intended workflow:

1. **One person on the team generates the secret** with `sky-env init` and shares it once via a secure channel (1Password, encrypted Slack DM, signed email, in person on a sticky note).
2. **Each developer sets `SKY_ENV_SECRET`** in their shell config from that shared value.
3. **The encrypted database is committed to your private repo** (or a shared dropbox / NAS / etc.).
4. **`sky-env import dev`** populates the database when someone changes a variable.
5. **Everyone else `git pull`s** to get the updated encrypted database.
6. **Everyone runs `sky-env print dev`** to see the latest values.

When someone leaves the team, rotate the secret:
1. `sky-env print dev > .env.dev.tmp` (and similar for all envs) — using the OLD secret
2. Pick a new secret and update `SKY_ENV_SECRET` everywhere
3. `sky-env import dev` (and similar) — re-encrypts under the new secret
4. Delete the temporary `.env.*.tmp` files
5. Commit the rotated database

---

## Command reference

```
sky-env init               Generate a new 256-bit secret (refuses if SKY_ENV_SECRET already set)
sky-env import <env>       Encrypt and import .env.<env> (or .env, or interactive from .env.example)
sky-env print <env>        Decrypt and print all variables for <env>
sky-env set <env> <key>    Set a single variable (prompts for value via stdin)
sky-env list               List all stored projects and their environments
sky-env diff               Compare environments for the current project, show missing keys
```

The "current project" is always the basename of the working directory. You can manage multiple projects by `cd`-ing between them.

---

## How is sky-env built?

Entirely in [Sky](https://github.com/anzellai/sky), a pure functional language that compiles to a single Go binary. The compiler is written in itself (self-hosted) and ships with:

- **Hindley-Milner type inference** — no type annotations needed, but the compiler still catches every type mismatch
- **Exhaustiveness checking** — all `case` expressions must cover every constructor
- **No runtime panics from FFI** — Go errors flow through `Result String a` at the type level
- **Single 8MB binary output** — no Node, no Python, no Go runtime, no shared libraries

`sky-env` itself is ~600 lines of Sky source split across 11 modules. The encryption logic in `src/Env/Encrypt.sky` is ~70 lines. The whole thing builds in under 2 seconds.

If you're curious about Sky as a language, the [main repo](https://github.com/anzellai/sky) has 17 examples ranging from "hello world" to a full Sky.Live monitoring dashboard.

---

## License

MIT — see [LICENSE](LICENSE).

---

## Contributing

Bug reports and PRs welcome. The code is small and idiomatic Sky, so it's a good entry point if you've never seen a functional language compile to Go before.

If you want to add a feature, please open an issue first to discuss. Things on the roadmap:

- [ ] `sky-env export <env> > file` — explicit export to a file (currently you pipe `print`)
- [ ] `sky-env unset <env> <key>` — remove a single variable
- [ ] `sky-env rename <old> <new>` — rename an environment
- [ ] `sky-env rotate` — re-encrypt all values under a new secret in one command
- [ ] Per-project secrets (different secret per project)
- [ ] Native AES via Sky stdlib (currently shells out to openssl)
