# Notification Module

Backend for telling users things happened: in-app notifications (the bell),
email (queued, retried), and push (device registry + dev stub). Lives in
`apps/notifications`. Producers anywhere in the codebase raise events through
**one function** — `apps.notifications.services.notify()` — and never touch
the notification tables directly.

## Concepts

- **Event vs channel.** An *event* is one fact ("you were assigned ticket
  #42"). A *channel* is one road it travels: in-app, email, push. `notify()`
  fans a single event out to every recipient over every channel their
  preferences allow.
- **`Notification`** — one in-app row per recipient (fan-out at write time,
  each row owns its read state). `read_at NULL` = unread. Optional GenericFK
  `target` gives the frontend its deep-link; `title` is denormalized so the
  message stays true even if the target is later renamed/deleted.
- **`NotificationPreference`** — per `(user, category)` switchboard row with
  three booleans (`in_app/email/push_enabled`). Rows are created lazily; a
  missing row means "all on". Categories are a `TextChoices`
  (`ticket | meeting | project | billing | system`) — coarse on purpose,
  users mute areas, not events.
- **`EmailOutbox`** — the email **queue as a DB table** (transactional
  outbox). `notify()` only INSERTs, inside the caller's transaction: rollback
  un-queues the mail; you can never email about something that didn't happen.
- **`PushDevice`** — one registered browser/phone per row; `token` is unique
  and re-registration **re-owns** it (shared machine, new login). Delivery is
  a logging stub in `services._push_to_user()` — the documented seam where
  FCM plugs in.

## Delivery guarantees

- **In-app**: synchronous INSERT, atomic with the business write.
- **Email**: *at-least-once*. The cron worker

  ```
  * * * * *  python manage.py send_queued_emails
  ```

  claims due PENDING rows with `select_for_update(skip_locked=True)` (safe to
  run from several machines), sends, marks SENT only after SMTP accepts.
  Failures retry with exponential backoff (2, 4, 8, 16 min); after
  `MAX_ATTEMPTS=5` the row parks as FAILED with `last_error` for the admin
  (`EmailOutbox` is registered in Django admin as the support view).
- **Push**: dispatched via `transaction.on_commit` — an external call must
  never fire for a transaction that rolls back.

This is the same "DB rows + cron sweep" shape as meeting reminders and ticket
escalation. When volume outgrows a per-minute cron, the upgrade path is
Celery + Redis: `notify()` keeps its signature, the outbox insert becomes
`task.delay()` — no producer changes.

## Endpoints

```
GET    /api/v1/notifications/                    mine, paginated  ?unread= &category=
GET    /api/v1/notifications/unread-count/       {"unread": n} — the badge
POST   /api/v1/notifications/{id}/read/          idempotent
POST   /api/v1/notifications/mark-all-read/      one UPDATE
GET    /api/v1/notification-preferences/         full matrix (rows materialized w/ defaults)
PATCH  /api/v1/notification-preferences/{category}/   flip switches
GET    /api/v1/push-devices/                     my devices
POST   /api/v1/push-devices/                     register (upsert on token: 201 new / 200 refresh)
DELETE /api/v1/push-devices/{id}/                unregister (logout)
```

Notifications are **read-only over the API** (server-generated; no
create/update/delete routes). Everything is scoped to `request.user` in
`get_queryset()` — no role logic at all; even ADMIN can't read another
user's notifications, and foreign ids 404 (§8 layer 2).

## Rules for producers

1. Call `notify(recipients=…, category=…, title=…, body=…, actor=…, target=…)`
   from a **service function**, inside its `transaction.atomic()`.
2. `title` is the rendered sentence — producers own the copy.
3. Actors are never notified about their own actions (handled inside
   `notify()`, don't pre-filter).
4. New module → add one `NotificationCategory` member (code change + nothing
   else; the preference matrix picks it up automatically).

First real producer: `tickets.services.assign_ticket()` notifies the new
assignee.
