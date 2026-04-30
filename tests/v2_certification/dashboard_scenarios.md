# v2-cert M4 — Dashboard scenario catalog

Each scenario is a single `expect` MCP run. Use the Playwright tool to execute the
steps; capture a screenshot at the end of each scenario; record pass/fail in
`dashboard.md` (Task 15).

Open URL for every scenario: `http://localhost:8000/conductor-dashboard`
Login as Administrator before the first scenario; subsequent scenarios reuse the session.

For every scenario, run it twice — once in light mode, once in dark mode — using the ModeToggle in the header.

## Overview page

1. **Loads with stats.** Open `/conductor-dashboard`. Expect 4 NumberCards (queue depth, workers, DLQ pending, schedules) + 2 QueueChart cards visible. Screenshot.
2. **NumberCard click navigates.** Click "Workers" card. Expect navigation to `/workers`. Screenshot.
3. **Live queue depths refresh.** Trigger `bench conductor doctor --demo` from terminal; watch QueueChart update within 5s. Screenshot before + after.

## Live Feed page

4. **Stream renders rows.** Navigate to `/feed`. Trigger `bench conductor doctor --demo`. Expect new event Cards to appear in the ScrollArea. Screenshot.
5. **Pause toggle freezes feed.** Click the Pause Switch. Trigger another demo job. Expect no new rows. Click Resume — backlog flushes. Screenshot.

## Jobs page

6. **DataTable renders + sorts.** Navigate to `/jobs`. Click "Created" header. Expect rows reorder. Screenshot.
7. **Faceted status filter.** Click status filter, select "Succeeded". Expect only succeeded rows visible. Screenshot.
8. **Pagination.** Click next-page. Expect rows change. Click prev-page. Screenshot both.
9. **Detail tabs render.** Click any row. Expect Sheet/Card detail with tabs (Overview / Runs / Args). Click each tab. Screenshot.
10. **Retry button works.** Pick a Failed row. Click Retry. Confirm in dialog. Expect new attempt row in Runs tab. Screenshot.
11. **Cancel button works.** Pick a Queued/Running row. Click Cancel. Confirm. Expect status flip. Screenshot.

## DLQ page

12. **DataTable renders.** Navigate to `/dlq`. Screenshot.
13. **Bulk-select + bulk-retry.** Check 3 rows. Click "Retry selected" in sticky action bar. Confirm. Expect rows leave DLQ. Screenshot.
14. **Edit-and-retry dialog.** Click Edit on a row. Modify args JSON. Click Retry. Expect new Conductor Job. Screenshot.
15. **Discard works.** Check 1 row. Click Discard. Confirm. Expect row removed. Screenshot.

## Schedules page

16. **Table renders + Switch toggles.** Navigate to `/schedules`. Click Switch on any enabled row → disabled. Toggle back. Screenshot.
17. **Run Now dispatches.** Click Run Now. Expect new Conductor Job in /jobs. Screenshot before + after.
18. **Detail Sheet opens.** Click row. Expect right-side Sheet with last dispatch + next 10 fires + calendar. Screenshot.

## Workers page

19. **Table renders with heartbeat sort.** Navigate to `/workers`. Expect rows sorted by last heartbeat. Screenshot.
20. **Tooltip shows exact ISO time.** Hover any heartbeat cell. Expect Tooltip with ISO timestamp. Screenshot.

## Workflows page

21. **Definitions card grid renders.** Navigate to `/workflows`. Screenshot.
22. **Recent runs table renders.** Same page. Screenshot.
23. **Click row → run detail.** Click any run. Expect navigation to detail page with Mermaid DAG + step Table. Screenshot.

## Workflow run detail

24. **Mermaid renders.** On a workflow detail page. Expect SVG DAG visible. Screenshot.
25. **Step table renders + JsonViewer expands.** Click any step. Expect args/output JsonViewer. Screenshot.

## Theme + responsiveness

26. **Light/dark toggle persists.** Set dark mode. Reload. Expect dark restored. Switch to light. Reload. Expect light restored.
27. **Sidebar collapse.** Resize viewport to ~700px. Expect sidebar collapses to icon-only. Screenshot.
