# Deploy Conductor on Frappe Cloud

This page gets Conductor running on a [Frappe Cloud](https://frappecloud.com) bench. It walks you through choosing the right hosting tier, adding Conductor as a custom app, configuring the site, and starting the worker and scheduler.

You succeed when `bench --site <site> conductor doctor --demo` exits 0 with all nine checks green.

> **Read this first.** Conductor needs two long-running processes per site (`conductor worker`, `conductor scheduler`) registered with the bench's process manager. **Frappe Cloud's shared and private benches do not let you add custom supervisor entries today** — that capability is tracked in [`frappe/press#1903`](https://github.com/frappe/press/issues/1903) and currently lands only on **Dedicated Servers**. The first procedure below is the tier-choice gate; everything after assumes a Private Bench (for the dashboard + dispatch surface) or a Dedicated Server (for full job execution).

---

## Procedure 1 — Pick the right Frappe Cloud tier

Match what you need from Conductor to a Frappe Cloud tier before you start.

| Tier | Custom apps | SSH | Custom workers / scheduler | Conductor outcome |
|---|---|---|---|---|
| **Shared / Public Bench** | ❌ | ❌ | ❌ | Not supported. Choose a Private Bench or Dedicated Server. |
| **Private Bench** | ✅ | ✅ (debug only) | ❌ ([press#1903](https://github.com/frappe/press/issues/1903)) | Dispatch and dashboard work. Job execution does not — no worker can run. |
| **Dedicated Server** | ✅ | ✅ (full) | ✅ | Full Conductor install. The rest of this guide applies. |

Use this table to decide:

- **You only need the dashboard, audit trail, and HTTP `/api/method/frappe.enqueue` shim** — a Private Bench is enough. Stop after Procedure 3.
- **You need jobs to actually execute** — you need a Dedicated Server. Run every procedure on this page.
- **You're on a Shared Bench** — you cannot install Conductor. Move the site to a Private Bench or Dedicated Server first.

---

## Procedure 2 — Add Conductor to the bench

Frappe Cloud installs apps in two stages: first onto the **bench**, then onto the **site**. This procedure does the first stage.

1. Open your bench in the Frappe Cloud dashboard. From your bench group, click **Apps**.
2. Click **Add App**, then choose the custom-app option.
3. Paste the Conductor repository URL:

    ```
    https://github.com/osama1998H/conductor
    ```

    For a private fork, use the personal-access-token form: `https://<username>:<PAT>@github.com/<org>/<repo>.git`.

4. Pick the branch you want pinned. Use `main` for the latest release; pin a tag (e.g. `v2.0.0`) for production.
5. Click **Update Available** in the bench group. Frappe Cloud queues a build.
6. Wait for the build to turn green. The build runs `pip install` against `pyproject.toml`, which pulls in `redis`, `msgpack`, `structlog`, and `croniter`.

Reference: [Frappe Cloud — How to install a custom app](https://docs.frappe.io/cloud/benches/custom-app).

---

## Procedure 3 — Install Conductor on the site

Once the bench build succeeds, attach Conductor to the site.

1. Open the **site** dashboard (not the bench).
2. Click the **Apps** tab.
3. Click **Install App** and pick `conductor` from the list of bench-installed apps.

Frappe Cloud runs the app's `after_install` hook on the site, which seeds the five default queues (`critical`, `default`, `long`, `short`, `workflow`) and the `Conductor Operator` role. You can verify the queues by visiting `<site>/app/conductor-queue`.

Reference: [Frappe Cloud — Installing an app](https://docs.frappe.io/cloud/installing-an-app).

---

## Procedure 4 — Configure the site's Redis URL

Conductor reads its configuration from a nested `conductor` object in `site_config.json`. The loader requires this nesting; flat keys are not supported (see `conductor/config/__init__.py`).

1. From the site dashboard, click **Site Config**.
2. Add a key named `conductor` whose value is a JSON object:

    ```json
    {
      "redis_url": "redis://<frappe-cloud-redis-host>:<port>/2",
      "default_queue": "default",
      "stream_max_len": 10000
    }
    ```

    Use the bench's `redis_queue` URL with the database forced to `2`. You can read the URL from `common_site_config.json` via SSH (`bench --site <site> show-config`) or by asking Frappe Cloud support.

3. Click **Update Configuration**.

If your tier's **Site Config** UI rejects nested JSON values, fall back to writing the key over SSH:

```bash
bench --site <site> set-config -p conductor '{"redis_url":"redis://...:2","default_queue":"default","stream_max_len":10000}'
```

The `-p` flag tells `set-config` to parse the value as JSON. The full key reference lives at [`reference-configuration.md`](reference-configuration.md).

If you stop here on a **Private Bench**, the dashboard, dispatch APIs, and HTTP `frappe.enqueue` shim all work — but every dispatched job stays in `QUEUED` because no worker is running.

---

## Procedure 5 — Run the worker and scheduler (Dedicated Server only)

This procedure registers Conductor's two long-running processes with the server's supervisor. It only works on the **Dedicated Server** tier, which gives you root SSH and the right to edit `/etc/supervisor/conf.d/`.

1. SSH into the server as the bench user. Frappe Cloud's [SSH Access](https://docs.frappe.io/cloud/benches/ssh) doc covers key setup.

2. Create a supervisor config for the worker and scheduler. Replace `<bench-name>` with your bench's directory name and `<site>` with your site:

    ```ini
    ; /etc/supervisor/conf.d/<bench-name>-conductor.conf

    [program:<bench-name>-conductor-worker]
    command=/home/frappe/<bench-name>/env/bin/bench --site <site> conductor worker --queue default --concurrency 4
    directory=/home/frappe/<bench-name>
    user=frappe
    autostart=true
    autorestart=true
    stopwaitsecs=120
    stdout_logfile=/home/frappe/<bench-name>/logs/conductor-worker.log
    stderr_logfile=/home/frappe/<bench-name>/logs/conductor-worker.err.log

    [program:<bench-name>-conductor-scheduler]
    command=/home/frappe/<bench-name>/env/bin/bench --site <site> conductor scheduler
    directory=/home/frappe/<bench-name>
    user=frappe
    autostart=true
    autorestart=true
    stopwaitsecs=30
    stdout_logfile=/home/frappe/<bench-name>/logs/conductor-scheduler.log
    stderr_logfile=/home/frappe/<bench-name>/logs/conductor-scheduler.err.log

    [group:<bench-name>-conductor]
    programs=<bench-name>-conductor-worker,<bench-name>-conductor-scheduler
    ```

    Use `stopwaitsecs=120` on the worker so supervisor lets a long job finish on graceful shutdown rather than killing it.

3. Reload supervisor:

    ```bash
    sudo supervisorctl reread
    sudo supervisorctl update
    sudo supervisorctl status <bench-name>-conductor:*
    ```

    Expected — both processes report `RUNNING` with a recent `started` timestamp.

4. Persist the config across bench updates. Frappe Cloud regenerates supervisor config on every deploy, so add the same stanzas to a Frappe Cloud **support ticket** asking the team to merge them into the bench's managed supervisor template. Until that lands, re-add the file after each deploy.

---

## Procedure 6 — Verify end-to-end

Run the doctor over SSH:

```bash
bench --site <site> conductor doctor --demo
```

Expected — all nine checks pass and exit code 0:

```
[1/9] Redis connectivity..................................... OK
[2/9] Default queues seeded.................................. OK
[3/9] Consumer groups exist.................................. OK
[4/9] XADD/XREADGROUP/XACK round-trip........................ OK
[5/9] Takeover queue coverage................................ OK
[6/9] Pause scheduler when takeover active................... OK
[7/9] frappe.enqueue shim active............................. OK
[8/9] End-to-end demo dispatch (conductor.demo.echo)......... OK
[9/9] Result round-trip...................................... OK
```

If `[8/9]` or `[9/9]` fails, the worker is not consuming the `default` queue — recheck `supervisorctl status` from Procedure 5.

Open `https://<site>/conductor-dashboard` to confirm the SPA loads and the **Workers** tab shows your worker as `ALIVE`.

---

## What to do on a Private Bench (no worker)

If you stopped after Procedure 4 because you are on a Private Bench, here is what works and what does not.

**Works:**

- The dashboard at `/conductor-dashboard` (read-only views of jobs, schedules, DLQ, workflows).
- `conductor.enqueue(...)` from app code — the dispatch row, idempotency lock, and Redis stream entry are all written.
- The HTTP `frappe.enqueue` override (`override_whitelisted_methods` in `hooks.py`) — incoming `/api/method/frappe.enqueue` calls land in Conductor's stream.

**Does not work:**

- Job execution. Every dispatched job stays in `QUEUED`.
- Schedules. Cron rows never fire.
- Retries, the DLQ sweeper, the reaper. Nothing is running them.

This makes a Private Bench useful for **staging the migration** — your code can call `conductor.enqueue` everywhere, and you can audit the dispatch path — but production execution requires the Dedicated Server tier or another platform with supervisor access.

---

## If something went wrong

- **Build fails on the bench with a `pip install` error** — Conductor needs Python 3.10+. Frappe Cloud benches on Frappe 14 ship 3.10; on Frappe 15 they ship 3.11. Confirm your bench is on Frappe 14.x or 15.x. Older benches will fail.
- **`Add App` rejects the GitHub URL** — for private repos, the URL must include a personal access token: `https://<user>:<PAT>@github.com/...`. The plain HTTPS URL only works for public repos.
- **Site Config UI rejects `conductor` as a JSON value** — your tier's UI is flat-key only. Use the SSH fallback in Procedure 4 (`bench set-config -p conductor '{...}'`).
- **`doctor` step 1 (Redis connectivity) fails** — `conductor.redis_url` is wrong. Read the bench's actual Redis URL from `common_site_config.json` (`bench --site <site> show-config | grep redis_queue`).
- **`doctor` step `[8/9]` fails with "demo job did not terminate within 10s"** — the worker is not running or not consuming `default`. Run `sudo supervisorctl status <bench>-conductor:*` and `tail -f logs/conductor-worker.log`.
- **Workers vanish after a Frappe Cloud deploy** — Frappe Cloud regenerates supervisor config on every deploy and overwrites your custom stanza. File a Frappe Cloud support ticket asking them to merge the Conductor entries into the bench's managed supervisor template.
- **Dashboard 404** — Conductor is installed but the static assets did not build. Force a rebuild: `bench build --app conductor` over SSH, then `bench --site <site> clear-cache`. On a Private Bench without SSH, redeploy the bench from the dashboard.

---

## See also

- [`tutorial-getting-started.md`](tutorial-getting-started.md) — the same flow on a self-hosted bench.
- [`reference-configuration.md`](reference-configuration.md) — every `site_config` and `common_site_config` key Conductor reads.
- [`reference-cli.md`](reference-cli.md) — every `bench conductor *` subcommand the supervisor stanzas call.
- [`how-to-run-multi-tenant.md`](how-to-run-multi-tenant.md) — pool-mode worker for multiple sites on one process, useful on a Dedicated Server with many tenants.
- [`explanation-architecture.md`](explanation-architecture.md) — what the worker and scheduler actually do, and why they need to be long-lived.
- [Frappe Cloud — Private Benches](https://docs.frappe.io/cloud/benches) — the source of truth for what each tier exposes.
