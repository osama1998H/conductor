# M2 — Scheduled Job Type certification matrix

**Window:** 2026-04-30 20:00 UTC+3 to now (~4 days, natural cron + initial force-trigger pass).
**Site:** frappe.localhost (frappe + erpnext + hrms + datavalue_theme_15 + conductor)
**Mechanism:** Path B — `conductor.frappe_scheduled_loop` reads `tabScheduled Job Type` and dispatches due rows through `conductor.dispatcher.enqueue`. Frappe's own scheduler is paused via `pause_scheduler: 1`.

## Summary

- Active rows in `tabScheduled Job Type`: **105**
- Rows with ≥1 dispatch in window: **105** (100%)
- Rows with 0 dispatches (frequency too long for 4d window): **0**
- Rows where dispatches == succeeded (clean pass): **105**
- Rows with partial pass: **0**

## By frequency

| Frequency | Active rows | Total dispatches | Succeeded | Pass rate |
|---|---|---|---|---|
| All | 5 | 2650 | 2650 | 100.0% |
| Cron | 11 | 3122 | 3122 | 100.0% |
| Daily | 9 | 36 | 36 | 100.0% |
| Daily Long | 3 | 12 | 12 | 100.0% |
| Daily Maintenance | 41 | 182 | 182 | 100.0% |
| Hourly | 3 | 264 | 264 | 100.0% |
| Hourly Long | 3 | 264 | 264 | 100.0% |
| Hourly Maintenance | 15 | 1322 | 1322 | 100.0% |
| Monthly | 3 | 3 | 3 | 100.0% |
| Monthly Long | 3 | 5 | 5 | 100.0% |
| Weekly | 2 | 3 | 3 | 100.0% |
| Weekly Long | 7 | 7 | 7 | 100.0% |

## Findings

### Finding 1: Stuck-QUEUED bug — queue mismatch (FIXED 2026-05-04)

The campaign discovered that 248 jobs (all on the `long` queue) were stranded in `QUEUED` status. Root cause: the takeover loop's queue-map sends `Daily*`/`Weekly*`/`Monthly*` rows to the `long` queue, but the bench Procfile only ran a worker on `--queue default`. Dispatches succeeded (XADD landed in the `long` stream) but no consumer existed.

**Fix:** Procfile updated to `--queue default --queue long`. After restart, all 248 stranded jobs flushed to SUCCEEDED in seconds.

**Operator footgun:** the doctor health-gate (M8) should warn when the takeover loop is enabled but the bench worker(s) collectively don't cover every queue the queue-map produces.


## Per-row matrix

| # | SJT id | Method | Frequency | Dispatches | Succeeded | First run | Last run |
|---|---|---|---|---|---|---|---|
| 1 | `deferred_revenue.process_deferred_accounting` | `erpnext.accounts.deferred_revenue.process_deferred_accounting` | Monthly Long | 2 | 2 | 2026-04-30 20:02 | 2026-05-01 00:04 |
| 2 | `fiscal_year.auto_create_fiscal_year` | `erpnext.accounts.doctype.fiscal_year.fiscal_year.auto_create_fiscal_year` | Daily Maintenance | 5 | 5 | 2026-04-30 20:03 | 2026-05-04 00:09 |
| 3 | `gl_entry.rename_gle_sle_docs` | `erpnext.accounts.doctype.gl_entry.gl_entry.rename_gle_sle_docs` | Cron | 89 | 89 | 2026-04-30 20:04 | 2026-05-04 11:30 |
| 4 | `process_statement_of_accounts.send_auto_email` | `erpnext.accounts.doctype.process_statement_of_accounts.process_statement_of_accounts.send_auto_email` | Daily Maintenance | 5 | 5 | 2026-04-30 20:05 | 2026-05-04 00:09 |
| 5 | `process_subscription.create_subscription_process` | `erpnext.accounts.doctype.process_subscription.process_subscription.create_subscription_process` | Daily Maintenance | 5 | 5 | 2026-04-30 20:06 | 2026-05-04 00:09 |
| 6 | `utils.auto_create_exchange_rate_revaluation_daily` | `erpnext.accounts.utils.auto_create_exchange_rate_revaluation_daily` | Daily Maintenance | 5 | 5 | 2026-04-30 20:07 | 2026-05-04 00:09 |
| 7 | `utils.auto_create_exchange_rate_revaluation_monthly` | `erpnext.accounts.utils.auto_create_exchange_rate_revaluation_monthly` | Monthly Long | 2 | 2 | 2026-04-30 20:08 | 2026-05-01 00:04 |
| 8 | `utils.auto_create_exchange_rate_revaluation_weekly` | `erpnext.accounts.utils.auto_create_exchange_rate_revaluation_weekly` | Weekly | 2 | 2 | 2026-04-30 20:09 | 2026-05-03 00:10 |
| 9 | `utils.run_ledger_health_checks` | `erpnext.accounts.utils.run_ledger_health_checks` | Daily Maintenance | 5 | 5 | 2026-04-30 20:10 | 2026-05-04 00:09 |
| 10 | `asset_maintenance_log.update_asset_maintenance_log_status` | `erpnext.assets.doctype.asset_maintenance_log.asset_maintenance_log.update_asset_maintenance_log_status` | Daily Maintenance | 5 | 5 | 2026-04-30 20:11 | 2026-05-04 00:09 |
| 11 | `asset.make_post_gl_entry` | `erpnext.assets.doctype.asset.asset.make_post_gl_entry` | Daily Maintenance | 5 | 5 | 2026-04-30 20:12 | 2026-05-04 00:09 |
| 12 | `asset.update_maintenance_status` | `erpnext.assets.doctype.asset.asset.update_maintenance_status` | Daily Maintenance | 5 | 5 | 2026-04-30 20:13 | 2026-05-04 00:09 |
| 13 | `depreciation.post_depreciation_entries` | `erpnext.assets.doctype.asset.depreciation.post_depreciation_entries` | Daily Maintenance | 5 | 5 | 2026-04-30 20:14 | 2026-05-04 00:09 |
| 14 | `supplier_quotation.set_expired_status` | `erpnext.buying.doctype.supplier_quotation.supplier_quotation.set_expired_status` | Daily Maintenance | 5 | 5 | 2026-04-30 20:15 | 2026-05-04 00:09 |
| 15 | `supplier_scorecard.refresh_scorecards` | `erpnext.buying.doctype.supplier_scorecard.supplier_scorecard.refresh_scorecards` | Daily Maintenance | 5 | 5 | 2026-04-30 20:18 | 2026-05-04 00:09 |
| 16 | `accounts_controller.update_invoice_status` | `erpnext.controllers.accounts_controller.update_invoice_status` | Daily Maintenance | 5 | 5 | 2026-04-30 20:34 | 2026-05-04 00:09 |
| 17 | `contract.update_status_for_contracts` | `erpnext.crm.doctype.contract.contract.update_status_for_contracts` | Daily Maintenance | 5 | 5 | 2026-04-30 20:39 | 2026-05-04 00:09 |
| 18 | `email_campaign.send_email_to_leads_or_contacts` | `erpnext.crm.doctype.email_campaign.email_campaign.send_email_to_leads_or_contacts` | Daily Maintenance | 5 | 5 | 2026-04-30 20:55 | 2026-05-04 00:09 |
| 19 | `email_campaign.set_email_campaign_status` | `erpnext.crm.doctype.email_campaign.email_campaign.set_email_campaign_status` | Daily Maintenance | 5 | 5 | 2026-04-30 21:11 | 2026-05-04 00:09 |
| 20 | `opportunity.auto_close_opportunity` | `erpnext.crm.doctype.opportunity.opportunity.auto_close_opportunity` | Daily Maintenance | 5 | 5 | 2026-04-30 21:12 | 2026-05-04 00:09 |
| 21 | `utils.open_leads_opportunities_based_on_todays_event` | `erpnext.crm.utils.open_leads_opportunities_based_on_todays_event` | Daily Maintenance | 5 | 5 | 2026-04-30 21:13 | 2026-05-04 00:09 |
| 22 | `plaid_settings.automatic_synchronization` | `erpnext.erpnext_integrations.doctype.plaid_settings.plaid_settings.automatic_synchronization` | Hourly Maintenance | 89 | 89 | 2026-04-30 20:00 | 2026-05-04 11:00 |
| 23 | `bom_update_log.resume_bom_cost_update_jobs` | `erpnext.manufacturing.doctype.bom_update_log.bom_update_log.resume_bom_cost_update_jobs` | Cron | 332 | 332 | 2026-04-30 20:00 | 2026-05-04 11:30 |
| 24 | `bom_update_tool.auto_update_latest_price_in_all_boms` | `erpnext.manufacturing.doctype.bom_update_tool.bom_update_tool.auto_update_latest_price_in_all_boms` | Daily Maintenance | 5 | 5 | 2026-04-30 22:00 | 2026-05-04 00:09 |
| 25 | `project.collect_project_status` | `erpnext.projects.doctype.project.project.collect_project_status` | Hourly Maintenance | 89 | 89 | 2026-04-30 20:00 | 2026-05-04 11:00 |
| 26 | `project.hourly_reminder` | `erpnext.projects.doctype.project.project.hourly_reminder` | Hourly | 88 | 88 | 2026-04-30 20:00 | 2026-05-04 11:00 |
| 27 | `project.project_status_update_reminder` | `erpnext.projects.doctype.project.project.project_status_update_reminder` | Hourly Maintenance | 88 | 88 | 2026-04-30 20:00 | 2026-05-04 11:00 |
| 28 | `project.send_project_status_email_to_users` | `erpnext.projects.doctype.project.project.send_project_status_email_to_users` | Daily Maintenance | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 29 | `project.update_project_sales_billing` | `erpnext.projects.doctype.project.project.update_project_sales_billing` | Daily Maintenance | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 30 | `task.set_tasks_as_overdue` | `erpnext.projects.doctype.task.task.set_tasks_as_overdue` | Daily Maintenance | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 31 | `quality_review.review` | `erpnext.quality_management.doctype.quality_review.quality_review.review` | Daily Maintenance | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 32 | `quotation.set_expired_status` | `erpnext.selling.doctype.quotation.quotation.set_expired_status` | Daily Maintenance | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 33 | `company.cache_companies_monthly_sales_history` | `erpnext.setup.doctype.company.company.cache_companies_monthly_sales_history` | Daily Maintenance | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 34 | `email_digest.send` | `erpnext.setup.doctype.email_digest.email_digest.send` | Daily Maintenance | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 35 | `repost_item_valuation.repost_entries` | `erpnext.stock.doctype.repost_item_valuation.repost_item_valuation.repost_entries` | Hourly Maintenance | 88 | 88 | 2026-04-30 20:00 | 2026-05-04 11:00 |
| 36 | `serial_no.update_maintenance_status` | `erpnext.stock.doctype.serial_no.serial_no.update_maintenance_status` | Daily Maintenance | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 37 | `reorder_item.reorder_item` | `erpnext.stock.reorder_item.reorder_item` | Daily Maintenance | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 38 | `issue.auto_close_tickets` | `erpnext.support.doctype.issue.issue.auto_close_tickets` | Daily Maintenance | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 39 | `service_level_agreement.check_agreement_status` | `erpnext.support.doctype.service_level_agreement.service_level_agreement.check_agreement_status` | Daily Maintenance | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 40 | `bulk_transaction.retry` | `erpnext.utilities.bulk_transaction.retry` | Hourly Maintenance | 88 | 88 | 2026-04-30 20:00 | 2026-05-04 11:00 |
| 41 | `video.update_youtube_data` | `erpnext.utilities.doctype.video.video.update_youtube_data` | Hourly Maintenance | 88 | 88 | 2026-04-30 20:00 | 2026-05-04 11:00 |
| 42 | `auto_repeat.make_auto_repeat_entry` | `frappe.automation.doctype.auto_repeat.auto_repeat.make_auto_repeat_entry` | Daily Maintenance | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 43 | `reminder.send_reminders` | `frappe.automation.doctype.reminder.reminder.send_reminders` | Cron | 332 | 332 | 2026-04-30 20:00 | 2026-05-04 11:30 |
| 44 | `log_settings.run_log_clean_up` | `frappe.core.doctype.log_settings.log_settings.run_log_clean_up` | Daily Maintenance | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 45 | `prepared_report.expire_stalled_report` | `frappe.core.doctype.prepared_report.prepared_report.expire_stalled_report` | Hourly Maintenance | 88 | 88 | 2026-04-30 20:00 | 2026-05-04 11:00 |
| 46 | `security_settings_alert.check_security_txt_expiry` | `frappe.core.doctype.security_settings.security_settings_alert.check_security_txt_expiry` | Cron | 4 | 4 | 2026-05-01 06:02 | 2026-05-04 06:05 |
| 47 | `user_invitation.mark_expired_invitations` | `frappe.core.doctype.user_invitation.user_invitation.mark_expired_invitations` | Daily Maintenance | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 48 | `deferred_insert.save_to_db` | `frappe.deferred_insert.save_to_db` | Cron | 332 | 332 | 2026-04-30 20:00 | 2026-05-04 11:30 |
| 49 | `changelog_feed.fetch_changelog_feed` | `frappe.desk.doctype.changelog_feed.changelog_feed.fetch_changelog_feed` | Weekly Long | 1 | 1 | 2026-05-03 00:10 | 2026-05-03 00:10 |
| 50 | `event.send_event_digest` | `frappe.desk.doctype.event.event.send_event_digest` | Daily | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 51 | `document_follow.send_daily_updates` | `frappe.desk.form.document_follow.send_daily_updates` | Daily | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 52 | `document_follow.send_hourly_updates` | `frappe.desk.form.document_follow.send_hourly_updates` | Hourly Maintenance | 88 | 88 | 2026-04-30 20:00 | 2026-05-04 11:00 |
| 53 | `document_follow.send_weekly_updates` | `frappe.desk.form.document_follow.send_weekly_updates` | Weekly Long | 1 | 1 | 2026-05-03 00:10 | 2026-05-03 00:10 |
| 54 | `notifications.clear_notifications` | `frappe.desk.notifications.clear_notifications` | Daily Maintenance | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 55 | `backups.delete_downloadable_backups` | `frappe.desk.page.backups.backups.delete_downloadable_backups` | Hourly Maintenance | 88 | 88 | 2026-04-30 20:00 | 2026-05-04 11:00 |
| 56 | `utils.delete_old_exported_report_files` | `frappe.desk.utils.delete_old_exported_report_files` | Hourly Maintenance | 88 | 88 | 2026-04-30 20:00 | 2026-05-04 11:00 |
| 57 | `auto_email_report.send_daily` | `frappe.email.doctype.auto_email_report.auto_email_report.send_daily` | Daily Maintenance | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 58 | `auto_email_report.send_monthly` | `frappe.email.doctype.auto_email_report.auto_email_report.send_monthly` | Monthly | 1 | 1 | 2026-05-01 00:04 | 2026-05-01 00:04 |
| 59 | `email_account.notify_unreplied` | `frappe.email.doctype.email_account.email_account.notify_unreplied` | Cron | 332 | 332 | 2026-04-30 20:00 | 2026-05-04 11:30 |
| 60 | `email_account.pull` | `frappe.email.doctype.email_account.email_account.pull` | Cron | 373 | 373 | 2026-04-30 20:00 | 2026-05-04 11:30 |
| 61 | `newsletter.send_scheduled_email` | `frappe.email.doctype.newsletter.newsletter.send_scheduled_email` | Hourly | 88 | 88 | 2026-04-30 20:00 | 2026-05-04 11:00 |
| 62 | `notification.trigger_daily_alerts` | `frappe.email.doctype.notification.notification.trigger_daily_alerts` | Daily | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 63 | `queue.flush` | `frappe.email.queue.flush` | All | 530 | 530 | 2026-04-30 20:00 | 2026-05-04 11:36 |
| 64 | `queue.retry_sending_emails` | `frappe.email.queue.retry_sending_emails` | All | 530 | 530 | 2026-04-30 20:00 | 2026-05-04 11:36 |
| 65 | `dropbox_settings.take_backups_daily` | `frappe.integrations.doctype.dropbox_settings.dropbox_settings.take_backups_daily` | Daily Maintenance | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 66 | `dropbox_settings.take_backups_weekly` | `frappe.integrations.doctype.dropbox_settings.dropbox_settings.take_backups_weekly` | Weekly Long | 1 | 1 | 2026-05-03 00:10 | 2026-05-03 00:10 |
| 67 | `google_calendar.sync` | `frappe.integrations.doctype.google_calendar.google_calendar.sync` | All | 530 | 530 | 2026-04-30 20:00 | 2026-05-04 11:36 |
| 68 | `google_contacts.sync` | `frappe.integrations.doctype.google_contacts.google_contacts.sync` | Daily Maintenance | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 69 | `google_drive.daily_backup` | `frappe.integrations.doctype.google_drive.google_drive.daily_backup` | Daily Maintenance | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 70 | `google_drive.weekly_backup` | `frappe.integrations.doctype.google_drive.google_drive.weekly_backup` | Weekly Long | 1 | 1 | 2026-05-03 00:10 | 2026-05-03 00:10 |
| 71 | `s3_backup_settings.take_backups_daily` | `frappe.integrations.doctype.s3_backup_settings.s3_backup_settings.take_backups_daily` | Daily Maintenance | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 72 | `s3_backup_settings.take_backups_monthly` | `frappe.integrations.doctype.s3_backup_settings.s3_backup_settings.take_backups_monthly` | Monthly Long | 1 | 1 | 2026-05-01 00:04 | 2026-05-01 00:04 |
| 73 | `s3_backup_settings.take_backups_weekly` | `frappe.integrations.doctype.s3_backup_settings.s3_backup_settings.take_backups_weekly` | Weekly Long | 1 | 1 | 2026-05-03 00:10 | 2026-05-03 00:10 |
| 74 | `link_count.update_link_count` | `frappe.model.utils.link_count.update_link_count` | Cron | 332 | 332 | 2026-04-30 20:00 | 2026-05-04 11:30 |
| 75 | `user_settings.sync_user_settings` | `frappe.model.utils.user_settings.sync_user_settings` | Hourly Maintenance | 88 | 88 | 2026-04-30 20:00 | 2026-05-04 11:00 |
| 76 | `monitor.flush` | `frappe.monitor.flush` | All | 530 | 530 | 2026-04-30 20:00 | 2026-05-04 11:36 |
| 77 | `oauth.delete_oauth2_data` | `frappe.oauth.delete_oauth2_data` | Hourly Maintenance | 88 | 88 | 2026-04-30 20:00 | 2026-05-04 11:00 |
| 78 | `sqlite_search.build_index_if_not_exists` | `frappe.search.sqlite_search.build_index_if_not_exists` | Cron | 332 | 332 | 2026-04-30 20:00 | 2026-05-04 11:30 |
| 79 | `sessions.clear_expired_sessions` | `frappe.sessions.clear_expired_sessions` | Daily Maintenance | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 80 | `energy_point_log.send_monthly_summary` | `frappe.social.doctype.energy_point_log.energy_point_log.send_monthly_summary` | Monthly | 1 | 1 | 2026-05-01 00:04 | 2026-05-01 00:04 |
| 81 | `energy_point_log.send_weekly_summary` | `frappe.social.doctype.energy_point_log.energy_point_log.send_weekly_summary` | Weekly Long | 1 | 1 | 2026-05-03 00:10 | 2026-05-03 00:10 |
| 82 | `energy_point_settings.allocate_review_points` | `frappe.social.doctype.energy_point_settings.energy_point_settings.allocate_review_points` | Daily Maintenance | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 83 | `twofactor.delete_all_barcodes_for_users` | `frappe.twofactor.delete_all_barcodes_for_users` | Hourly Maintenance | 88 | 88 | 2026-04-30 20:00 | 2026-05-04 11:00 |
| 84 | `change_log.check_for_update` | `frappe.utils.change_log.check_for_update` | Weekly Long | 1 | 1 | 2026-05-03 00:10 | 2026-05-03 00:10 |
| 85 | `global_search.sync_global_search` | `frappe.utils.global_search.sync_global_search` | Cron | 332 | 332 | 2026-04-30 20:00 | 2026-05-04 11:30 |
| 86 | `client.send_queued_events` | `frappe.utils.telemetry.pulse.client.send_queued_events` | Cron | 332 | 332 | 2026-04-30 20:00 | 2026-05-04 11:30 |
| 87 | `personal_data_deletion_request.process_data_deletion_request` | `frappe.website.doctype.personal_data_deletion_request.personal_data_deletion_request.process_data_deletion_request` | Hourly Maintenance | 88 | 88 | 2026-04-30 20:00 | 2026-05-04 11:00 |
| 88 | `personal_data_deletion_request.remove_unverified_record` | `frappe.website.doctype.personal_data_deletion_request.personal_data_deletion_request.remove_unverified_record` | Daily Maintenance | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 89 | `web_page.check_publish_status` | `frappe.website.doctype.web_page.web_page.check_publish_status` | Hourly Maintenance | 88 | 88 | 2026-04-30 20:00 | 2026-05-04 11:00 |
| 90 | `employee_reminders.send_birthday_reminders` | `hrms.controllers.employee_reminders.send_birthday_reminders` | Daily | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 91 | `employee_reminders.send_reminders_in_advance_monthly` | `hrms.controllers.employee_reminders.send_reminders_in_advance_monthly` | Monthly | 1 | 1 | 2026-05-01 00:04 | 2026-05-01 00:04 |
| 92 | `employee_reminders.send_reminders_in_advance_weekly` | `hrms.controllers.employee_reminders.send_reminders_in_advance_weekly` | Weekly | 1 | 1 | 2026-05-03 00:10 | 2026-05-03 00:10 |
| 93 | `employee_reminders.send_work_anniversary_reminders` | `hrms.controllers.employee_reminders.send_work_anniversary_reminders` | Daily | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 94 | `daily_work_summary_group.send_summary` | `hrms.hr.doctype.daily_work_summary_group.daily_work_summary_group.send_summary` | Daily | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 95 | `daily_work_summary_group.trigger_emails` | `hrms.hr.doctype.daily_work_summary_group.daily_work_summary_group.trigger_emails` | Hourly | 88 | 88 | 2026-04-30 20:00 | 2026-05-04 11:00 |
| 96 | `interview.send_daily_feedback_reminder` | `hrms.hr.doctype.interview.interview.send_daily_feedback_reminder` | Daily | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 97 | `interview.send_interview_reminder` | `hrms.hr.doctype.interview.interview.send_interview_reminder` | All | 530 | 530 | 2026-04-30 20:00 | 2026-05-04 11:36 |
| 98 | `job_opening.close_expired_job_openings` | `hrms.hr.doctype.job_opening.job_opening.close_expired_job_openings` | Daily | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 99 | `leave_ledger_entry.process_expired_allocation` | `hrms.hr.doctype.leave_ledger_entry.leave_ledger_entry.process_expired_allocation` | Daily Long | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 100 | `shift_assignment.mark_expired_shift_assignments_as_inactive` | `hrms.hr.doctype.shift_assignment.shift_assignment.mark_expired_shift_assignments_as_inactive` | Daily | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 101 | `shift_schedule_assignment.process_auto_shift_creation` | `hrms.hr.doctype.shift_schedule_assignment.shift_schedule_assignment.process_auto_shift_creation` | Hourly Long | 88 | 88 | 2026-04-30 20:00 | 2026-05-04 11:00 |
| 102 | `shift_type.process_auto_attendance_for_all_shifts` | `hrms.hr.doctype.shift_type.shift_type.process_auto_attendance_for_all_shifts` | Hourly Long | 88 | 88 | 2026-04-30 20:00 | 2026-05-04 11:00 |
| 103 | `shift_type.update_last_sync_of_checkin` | `hrms.hr.doctype.shift_type.shift_type.update_last_sync_of_checkin` | Hourly Long | 88 | 88 | 2026-04-30 20:00 | 2026-05-04 11:00 |
| 104 | `utils.allocate_earned_leaves` | `hrms.hr.utils.allocate_earned_leaves` | Daily Long | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
| 105 | `utils.generate_leave_encashment` | `hrms.hr.utils.generate_leave_encashment` | Daily Long | 4 | 4 | 2026-05-01 00:04 | 2026-05-04 00:09 |
