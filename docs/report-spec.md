# Report specification

What the existing Daily (Power BI) and Hourly (Excel) reports contain and how every figure is defined. It was written from the Power BI model (DAX measures, calculated columns, Power Query sources, report pages) and the hourly Excel template (sheets, conditional formatting, macro), so the pipeline and the dashboard can reproduce the same numbers. No names or e-mails from those files are kept here.

## 1. The two reports

| | Daily report | Hourly report |
|---|---|---|
| Tool | Power BI, exported to PDF | Excel template; a macro copies ranges as PNG images |
| Pages / sheets | SPS (printed as **Non-KA**), SPG (printed as **KA**), JP Support, Addition, Tenure Dashboard, a BSC page | Backlog matrix, Backlog Actionable, Team performance, agent boards for SPS, SPG and JP Support |
| Window | Last 7 days, weeks W-3 to current week, month to date | Today, by hour |
| Unit of view | Channel (EC, IM) x task group x user type | Function (KA / Non-KA) x user type x ticket type x ageing x status; agent level |

The hourly macro only exports the ranges `Backlog`, `BacklogActionable`, `Team` and the SPS / SPG / JP Support boards as images to a local folder. Everything before that (pasting the hourly extracts, refreshing the pivots) is manual.

## 2. Reference tables

- **Skill group map** (`Dim SkillGroup`, `Dim_SkillGroup`): every skill group maps to Function (KA or Non-KA), user type (Seller, Creator), task group (Question SS, Question CR, Appeal, IM SS, IM CR, IM SS AI, SWAT SS/CR, Support JP SS/CR), channel (EC or IM), LOB (SPS or SPG) and a target handle-per-hour.
- **Task group to channel and ticket type** (`Dim_TaskGroup`): Question SS and CR are EC / Question, Appeal is EC / Appeal, IM SS and IM CR are IM / Question, Support JP is EC / Support.
- **Targets** (`Target_record`): one row per metric, LOB, user type, channel and ticket type, with `EffectiveTime` and `DeActiveTime`. The target used on a date is the row whose period contains it. Metrics: 24HFRR, 24HRR, 60S, Backlog ratio, CONPD, CPD, CPH, CSAT, FE RATE, HPH, OR, QA Score, TQM AAA, UR.
- **Glide path** (`Dim_GlidePath`, and a table in the Excel): handle-per-hour target by tenure week W1 to W12 and task group, so newcomers are held to a ramp.
- **Tenure**: from the roster's production date. 0 days or less: none; up to 7 days: W1; up to 14: W2; and so on to W6 (42 days); then Oldbie. Newbie means within 6 weeks.
- **Weeks**: Sunday to Saturday, `WEEKNUM`. Current week = week of the latest date; previous week = week of the latest date minus 7. Windows used: 7 days, 14 days, last 4 weeks, last 8 weeks, month to date.

## 3. Metric definitions

| Metric | Definition |
|---|---|
| ConPD | sum(contacts) / sum(paid hours) x 8 |
| CPD | sum(closed) / sum(paid hours) x 8 |
| CPH | sum(closed) / sum(production hours) |
| Handle/Hour | (sum(today handled) - sum(ticket transfer times)) / (sum(online hours) x 24) |
| Occupancy rate (OR) | sum(productivity numerator hours) / (online + busy + idle + abnormal hours) |
| Utilization rate (UR) | (online + busy + idle + abnormal hours) / paid hours |
| CSAT | survey responses with score 4 or 5 / all responses |
| 24H RR | Question tickets resolved within 24h / Question tickets |
| 24H FRR | Webform tickets with a first response within 24h / Webform tickets |
| 60S FRT | IM sessions with a response within 60s / IM sessions |
| Chat concurrency | sum(chat duration) / sum(engaged duration); chat duration is capped at 2 hours; engaged duration merges overlapping chats of the same agent and day |
| IM transfer rate | IM tickets of type Transfer / IM tickets |
| Backlog ratio | (unassigned, unprocessed, processing over 24h + pending, on-hold over 72h) / closed. WFM part = the first three, OPs part = the last two |
| Backlog (daily) | for each date, the snapshot of the **latest import hour** of that date |
| Backlog trend | slope of a straight line through the daily backlog in view. Up when slope > 1% of the average per step, down when < -1%. Speed: slow < 0.5%, moderate < 2%, fast otherwise |
| Shrinkage | sum(shrinkage points) / roster rows whose shift code is not H, OFF, ML, R or blank |
| On-time attendance | 1 - late count / attendance count |
| TQM AAA | tickets passing the attribute check / distinct tickets scored |
| Week over week | current week value - previous week value (and as a % of the previous week) |

## 4. Targets and status colours

- Higher is better (most metrics): **green** at or above target, **amber** from 80% of target up to target, **red** below 80% of target. The Excel boards use the same 80% rule for Handle/Hrs against the agent's target.
- Lower is better: backlog ratio is green at or below target; IM transfer rate is green at or below target and red above it.
- TQM AAA is two-state (green or red).
- Balanced scorecard (BSC) metrics: CSAT, 60S, CPD, backlog, FTE fulfilment, L2 accuracy, on-time attendance, each shown as achievement = actual / target.
- Some targets are written into the formulas instead of the target table: ConPD for EC and IM combined is 72; CPH by task group (Appeal 11, Question SS 4.5, Question CR 10); CPD for Question SS is 40.

## 5. Hourly report content

1. **Backlog matrix**: count of tickets by function, user type, ticket type (Appeal, Question) and ageing (<24h, 24-48h, 48-72h, 72-96h, >96h) against status (Assigned, On-hold, Open, Pending, Unassigned) with totals.
2. **Backlog actionable**: backlog, actionable and % actionable by function, ticket type and status. The source rows are one per skill group and hour: today handled, online hours, agents, un-actionable, actionable, hour, volume.
3. **Agent boards** (SPS, SPG, JP Support): per agent and task group, open / assigned / pending / on-hold, total solved, online hours, solved per hour, CPD, today handled, handle per hour against the target (coloured), grouped by task group with a total line.
4. **Team performance**: per team, the same measures plus `TeamTargetCap` and % achievement.

## 6. Findings in the existing files

These are worth fixing in whichever tool stays the source of truth:

- **Glide paths disagree** between the Excel and the Power BI model. Examples: Appeal week 4 is 14.7 in the Excel and 12 in Power BI; Question SS week 4 is 8 vs 7; Question CR week 3 is 8 vs 6.
- **Colour rules with a bug**: the OR and UR formats turn red only when the value is negative (never), so values below 80% of target get no colour; the backlog ratio rule has an amber branch that can never be reached; the BSC L2 accuracy format reads the 60S value.
- **Targets hard-coded** in measures (see section 4) instead of the target table, so they have no effective dates.
- **Manual hourly step**: data is pasted into Excel and the images are written to a local drive path.
- **Hourly snapshots exist already**: the backlog table carries the import hour, so intraday history can be kept instead of only the latest snapshot.

## 7. Where each part comes from in this pipeline

| Report part | Source in the pipeline |
|---|---|
| ConPD, CPD, CPH, OR, UR, handle per hour | `cph_details` |
| CSAT | `csat_details` |
| 24H RR, 24H FRR, volume | `ticket_details` |
| 60S FRT, concurrency, transfer rate | `im_details` |
| TQM AAA | `tqm_details` |
| On-time attendance | `ontime_attendance` |
| Shrinkage, tenure, line manager | roster (Lark Base) |
| Backlog ratio | `backlog_details` |
| Backlog matrix, actionable, hourly agent boards | `backlog_actionable_capacity`, `productivity_data_report` (Lark sheets) |
| Forecast and FTE | `fc_actual_details` |
