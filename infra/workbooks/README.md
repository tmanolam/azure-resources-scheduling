# Workbooks

Azure Monitor Workbooks for day-2 operation of the Power Scheduler. They are
imported manually (not deployed by Terraform).

| File | Shows |
|---|---|
| `pwrsched-day2-operations.workbook.json` | Start/stop actions and failed/skipped decisions, with a time-range selector (default 24 hours). Times in Bangkok time (UTC+7). |
| `pwrsched-summary.workbook.json` | **For large tenants.** Totals and trends from the one summary record per cycle (`pwrsched.summary`), so it stays fast with thousands of resources: period totals, starts/stops/failures per hour, per-day table, cycle duration (early warning for the scaling backlog), cap events, estimated resource-hours avoided per day (from the v0.7 summary counts), and failed/skipped counts by resource type. Default range 7 days. Dry-run cycles count would-be actions as skipped, so it is most useful once a tenant is live. |

## Import

1. In the Azure portal, open the scheduler's Application Insights resource (`appi-pwrsched-…`).
2. Go to **Workbooks → + New**, then click **Advanced Editor** (`</>`).
3. Choose **Gallery Template**, replace the content with the JSON file, and click **Apply**.
4. **Save** it with a name and resource group (for example, the scheduler's).

Open the workbook from the Application Insights resource so the queries run
against the scheduler's data. Field names follow the telemetry contract in
`src/engine/telemetry.py` (`customDimensions["pwrsched.*"]`).
