"""Generate synthetic CSVs in downloads/dashboard so the pipeline (archive, load, dbt)
and the dashboard can be tried without access to the real dashboard.

    python scripts/make_demo_data.py --days 84 --agents 45

Everything is random: agents, e-mails, tickets and numbers. Only the column
layout matches the real exports. The data follows the patterns a support
operation shows, so the reports built on it behave like real ones:

- ticket volume follows the weekday and has promotion spikes and a slow trend;
- the roster is staffed for a normal day; a spike builds a backlog that is
  cleared over the following days;
- newer agents are slower, Tier 2 agents handle harder tickets;
- when there is less work than capacity, CPH and occupancy fall;
- resolution time, FCR and CSAT get worse when the backlog is high;
- the forecast is close on normal days and misses promotion days.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import re
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HEADERS = {
  "cph_details": [
    "部门名称 Department_Name",
    "Tier",
    "Tenure",
    "Agent Email",
    "业务日期｜Business Date",
    "CS/SPS/SPG Efficiency Official",
    "Segment",
    "主技能组名称｜agent_primary_skill_group_name",
    "CPH-Every 1 Production Hour",
    "#close",
    "ConPD (New)",
    "# Contact (new)",
    "Paid Hours",
    "Productivity Rate Official",
    "Occupancy_Rate ",
    "Utilization_rate",
    "Failed CPD",
    "online_work_proportion | 在线对客占比",
    "busy_work_proportion | 忙碌对客占比",
    "Productivity_numerator (hrs)",
    "Online (hrs)",
    "Busy (hrs)",
    "Idle (hrs)",
    "Abnormal (hrs)",
    "Break (hrs)",
    "Training (hrs)",
    "Meeting (hrs)",
    "Other (hrs)",
    "Concurrency｜平均v数",
    "im_ticket_contact_with_call",
    "no_im_ticket_contact_with_call",
    "xfn_finished_cnt",
    "pick_up_session_cnt_without_l3"
  ],
  "ticket_details": [
    "Create_Date",
    "Close_Date",
    "Overall Submit Date",
    "ticket_id ｜ 工单id",
    "ticket_skill_group_name ｜ 工单坐席技能组",
    "final_dealer_email",
    "user_type_name_en ｜ 用户类型",
    "ticket_type_new_name_en ｜ 工单类型",
    "shop_name",
    "level3_label_name",
    "Country｜国家",
    "ticket_channel_name_en ｜渠道",
    "cb_last_mile_provider",
    "scene_instance_id",
    "channel_instance_id ｜ IM会话id",
    "sub_status_name_en ｜ 工单子状态",
    "final_dealer_time｜最后处理时间",
    "im_skill_group_name ｜ IM会话坐席技能组",
    "Ticket Link (BPO)",
    "create_im_ticket_type_name｜im建单方式名称",
    "Official is_CSAT_survey_invited｜是否下发综合服务满意度问卷",
    "lsp_ticket_result｜lsp工单处理状态",
    "first_sub_ticket_create_time",
    "Create",
    "overall_survey_score",
    "total_first_response_time (hrs)",
    "First_contact_resolution",
    "Resolution Hours",
    "Contact Cnt",
    "First_response_ticket_volume_in24hrs//24h首响工单量",
    "official ticket_24H_resolution_rate ｜ 工单24H解决率"
  ],
  "csat_details": [
    "Official CSAT_survey_submit_date｜综合服务满意度问卷提交日期",
    "UserType",
    "ticket_id ｜ 工单id",
    "level3_label",
    "ticket_skill_group_name ｜ 工单坐席技能组",
    "Country｜国家",
    "final_dealer_email",
    "Official CSAT_survey_score｜综合服务满意度问卷评分",
    "ticket_channel_name_en ｜渠道",
    "im_skill_group_name ｜ IM会话坐席技能组",
    "seller_id ｜ 商家id",
    "手写原因"
  ],
  "ontime_attendance": [
    "schedule_date_local_timezone",
    "Department (Latest)",
    "Agent Tag Name",
    "agent_email",
    "Late Count",
    "Attendance Count",
    "On-Time Attendance"
  ],
  "backlog_details": [
    "date",
    "user_type_name_en",
    "access_party_name",
    "Backlog Rate",
    "unassigned_cnt",
    "unprocessed_cnt",
    "pending_cnt",
    "onhold_cnt",
    "unassigned_duration_over_24h_ticket_cnt",
    "unprocessed_duration_over_24h_ticket_cnt",
    "processing_duration_over_24h_ticket_cnt",
    "pending_duration_over_72h_ticket_cnt",
    "onhold_duration_over_72h_ticket_cnt",
    "close_cnt"
  ],
  "fc_actual_details": [
    "Business Date",
    "skill_group_name",
    "Forecast Traffic",
    "Actual Traffic",
    "Traffic Variance",
    "Forecast FTE",
    "Production Schedule FTE"
  ]
}


def norm(header: str) -> str:
    """Same normalisation the database loader applies to column names."""
    text = re.sub(r"[^a-z0-9]+", "_", str(header).strip().lower())
    return re.sub(r"_+", "_", text).strip("_")


INDEX = {key: {norm(h): i for i, h in enumerate(cols)} for key, cols in HEADERS.items()}

SKILL_GROUPS = {
    "VN-SS-L2L-Inquiry-TK-VB-L1": {"agents": 0.45, "demand": 0.45, "im": "VN-SS-L2L-Inquiry-IM-VB-L1"},
    "VN-CR-L2L-Inquiry-TK-VB-L1": {"agents": 0.25, "demand": 0.22, "im": "VN-CR-L2L-Inquiry-IM-VB-L1"},
    "VN-KAS-L2L-Inquiry-TK-VB-L1": {"agents": 0.30, "demand": 0.33, "im": "VN-KAS-L2L-Inquiry-IM-VB-L1"},
}
USER_MIX = {"Seller": 0.58, "Creator": 0.24, "Buyer": 0.18}
TEAMS = ["TeamA", "TeamB", "TeamC"]
TENURES = ["<90", "91-180", "180-270", "271-360", ">361"]
TENURE_SPEED = [0.80, 0.92, 0.99, 1.04, 1.09]
TENURE_WEIGHTS = [0.16, 0.22, 0.20, 0.18, 0.24]
LABELS = [
    "Account issue", "Payment and settlement", "Affiliate and commission",
    "Order and logistics", "Shop violation appeal", "Product listing",
]

# weekday: Monday = 0
DEMAND_BY_WEEKDAY = [1.10, 1.04, 1.00, 0.99, 1.00, 0.74, 0.66]
WORK_PROB_BY_WEEKDAY = [0.93, 0.94, 0.94, 0.93, 0.93, 0.62, 0.50]
# promotion days: demand multiplier
EVENTS = {
    date(2026, 9, 9): 1.30, date(2026, 9, 10): 1.15,
    date(2026, 10, 10): 1.42, date(2026, 10, 11): 1.22, date(2026, 10, 12): 1.08,
    date(2026, 10, 25): 1.12, date(2026, 11, 1): 1.28,
}

BASE_CPH = {"IM": 14.5, "Ticket": 19.0}
RHO = 0.86  # normal-day demand as a share of normal-day capacity


def clamp(value, low, high):
    return max(low, min(high, value))


class Writer:
    def __init__(self, stamp: str):
        self.stamp = stamp
        self.out_dir = ROOT / "downloads" / "dashboard"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def write(self, name: str, rows: list[list]) -> None:
        path = self.out_dir / f"{name}-{self.stamp}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(HEADERS[name])
            writer.writerows(rows)
        print(f"{path.name}: {len(rows)} rows")


FAMILY = ["nguyen", "tran", "le", "pham", "hoang", "vu", "dang", "bui", "do", "ngo", "duong", "ly"]
GIVEN = ["anh", "linh", "huy", "trang", "minh", "thao", "hung", "ngoc", "quan", "lan", "phuc", "mai",
         "khoa", "hoa", "tuan", "yen", "nam", "chi", "duc", "vy"]


def fake_email(rnd: random.Random, n: int) -> str:
    """Vietnamese-style work address on a reserved domain; the number keeps it unique."""
    return f"{rnd.choice(GIVEN)}.{rnd.choice(FAMILY)}{n:02d}@example.com"


def make_agents(rnd: random.Random, count: int) -> list[dict]:
    names = list(SKILL_GROUPS)
    weights = [SKILL_GROUPS[n]["agents"] for n in names]
    agents = []
    for n in range(count):
        tier = "Tier 2 Agent" if rnd.random() < 0.28 else "Tier 1 Agent"
        tenure_i = rnd.choices(range(len(TENURES)), TENURE_WEIGHTS)[0]
        agents.append({
            "email": fake_email(rnd, n),
            "team": TEAMS[n % len(TEAMS)],
            "tier": tier,
            "tenure": TENURES[tenure_i],
            "speed": TENURE_SPEED[tenure_i] * (0.86 if tier == "Tier 2 Agent" else 1.0) * rnd.gauss(1.0, 0.045),
            "skill": rnd.choices(names, weights)[0],
            "part_time": rnd.random() < 0.12,
            "dual": rnd.random() < 0.55,
            "primary": rnd.choice(["IM", "Ticket"]),
        })
    return agents


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--days", type=int, default=21)
    parser.add_argument("--agents", type=int, default=40)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--end", type=date.fromisoformat, default=date.today() - timedelta(days=1),
                        help="last day of data (default: yesterday)")
    args = parser.parse_args()

    rnd = random.Random(args.seed)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    days = [args.end - timedelta(days=n) for n in range(args.days - 1, -1, -1)]
    last_day = days[-1]
    agents = make_agents(rnd, args.agents)
    group_agents = {g: [a for a in agents if a["skill"] == g] for g in SKILL_GROUPS}

    cph_ix, tkt_ix, csat_ix = INDEX["cph_details"], INDEX["ticket_details"], INDEX["csat_details"]
    cph_rows, ticket_rows, csat_rows = [], [], []
    attendance_rows, backlog_rows, forecast_rows = [], [], []
    backlog_prev = {g: 0.0 for g in SKILL_GROUPS}
    ticket_serial = 0

    for day_number, day in enumerate(days):
        weekday = day.weekday()
        event = EVENTS.get(day, 1.0)
        trend = 1.0 + 0.0007 * day_number
        work_prob = min(0.98, WORK_PROB_BY_WEEKDAY[weekday] + (0.04 if event > 1.15 else 0))

        # ---- who works, and how much capacity that gives each skill group
        shifts = []  # (agent, segment, hours dict)
        late_by_agent = {}
        for agent in agents:
            if rnd.random() > work_prob:
                continue
            paid = (4.0 if agent["part_time"] else 7.5) + rnd.uniform(-0.25, 0.25) + (0.5 if event > 1.15 else 0)
            brk = (0.4 if agent["part_time"] else rnd.uniform(0.6, 0.9))
            training = rnd.uniform(0.5, 1.5) if rnd.random() < 0.12 else 0.0
            meeting = rnd.uniform(0.1, 0.4) if rnd.random() < 0.6 else 0.0
            abnormal = rnd.uniform(0, 0.08)
            online = max(paid - brk - training - meeting - abnormal, 0.5)
            segments = ["IM", "Ticket"] if agent["dual"] else [agent["primary"]]
            shares = [0.7, 0.3] if agent["dual"] else [1.0]
            if agent["dual"] and agent["primary"] == "Ticket":
                segments = ["Ticket", "IM"]
            late_by_agent[agent["email"]] = rnd.random() < (0.07 if weekday == 0 else 0.05)
            for segment, share in zip(segments, shares):
                prod = online * share * 0.97
                capacity = prod * BASE_CPH[segment] * agent["speed"] * rnd.gauss(1.0, 0.04)
                shifts.append({
                    "agent": agent, "segment": segment, "share": share, "paid": paid * share,
                    "online": online * share, "brk": brk * share, "training": training * share,
                    "meeting": meeting * share, "abnormal": abnormal * share, "prod": prod,
                    "capacity": capacity,
                })

        capacity_by_group = {g: sum(s["capacity"] for s in shifts if s["agent"]["skill"] == g) for g in SKILL_GROUPS}
        normal_capacity = {
            g: len(group_agents[g]) * 0.93 * 5.7 * 16.0 for g in SKILL_GROUPS
        }

        # ---- demand, closing and backlog per skill group
        demand, closed, backlog, pressure, fill = {}, {}, {}, {}, {}
        for g, meta in SKILL_GROUPS.items():
            base = normal_capacity[g] * RHO * DEMAND_BY_WEEKDAY[weekday] * event * trend
            demand[g] = max(int(round(base * rnd.gauss(1.0, 0.04))), 0)
            cap = capacity_by_group[g]
            closed[g] = min(cap, demand[g] + backlog_prev[g])
            backlog[g] = demand[g] + backlog_prev[g] - closed[g]
            pressure[g] = clamp(backlog_prev[g] / max(normal_capacity[g], 1), 0.0, 1.5)
            fill[g] = closed[g] / cap if cap else 0.0

        # ---- productivity rows
        for s in shifts:
            g = s["agent"]["skill"]
            f = fill[g]
            noise = rnd.gauss(1.0, 0.06)
            closed_i = max(int(round(s["capacity"] * f * noise)), 0)
            # s["online"] is the time spent in the three working statuses; the report adds
            # abnormal time on top of it to get the hours the agent was available.
            busy = s["online"] * clamp(0.28 + 0.48 * f + rnd.gauss(0, 0.025), 0.25, 0.9)
            idle = min(max(s["online"] - busy, 0.0), s["online"] * rnd.uniform(0.05, 0.12))
            waiting = max(s["online"] - busy - idle, 0.0)
            available = s["online"] + s["abnormal"]
            # hours counted as productive follow the workload: quiet days leave more idle time
            prod_i = s["prod"] * clamp(0.66 + 0.22 * f + rnd.gauss(0, 0.012), 0.7, 0.99)
            concurrency = rnd.uniform(1.5, 2.1) if s["segment"] == "IM" else 1.0
            row = [""] * len(HEADERS["cph_details"])
            row[cph_ix["department_name"]] = s["agent"]["team"]
            row[cph_ix["tier"]] = s["agent"]["tier"]
            row[cph_ix["tenure"]] = s["agent"]["tenure"]
            row[cph_ix["agent_email"]] = s["agent"]["email"]
            row[cph_ix["business_date"]] = day.isoformat()
            row[cph_ix["cs_sps_spg_efficiency_official"]] = "SPG" if s["agent"]["tier"] == "Tier 2 Agent" else "SPS"
            row[cph_ix["segment"]] = s["segment"]
            row[cph_ix["agent_primary_skill_group_name"]] = g
            row[cph_ix["cph_every_1_production_hour"]] = round(closed_i / prod_i, 4) if prod_i else ""
            row[cph_ix["close"]] = closed_i
            row[cph_ix["contact_new"]] = int(closed_i * rnd.uniform(1.0, 1.25))
            row[cph_ix["paid_hours"]] = round(s["paid"], 4)
            row[cph_ix["productivity_rate_official"]] = round(prod_i / s["paid"], 4)
            row[cph_ix["occupancy_rate"]] = round(prod_i / available, 4) if available else ""
            row[cph_ix["utilization_rate"]] = round(available / s["paid"], 4)
            row[cph_ix["failed_cpd"]] = 1 if rnd.random() < 0.04 else 0
            row[cph_ix["online_work_proportion"]] = round(waiting / s["paid"], 4)
            row[cph_ix["busy_work_proportion"]] = round(busy / s["paid"], 4)
            row[cph_ix["productivity_numerator_hrs"]] = round(prod_i, 4)
            row[cph_ix["online_hrs"]] = round(waiting, 4)
            row[cph_ix["busy_hrs"]] = round(busy, 4)
            row[cph_ix["idle_hrs"]] = round(idle, 4)
            row[cph_ix["abnormal_hrs"]] = round(s["abnormal"], 4)
            row[cph_ix["break_hrs"]] = round(s["brk"], 4)
            row[cph_ix["training_hrs"]] = round(s["training"], 4)
            row[cph_ix["meeting_hrs"]] = round(s["meeting"], 4)
            row[cph_ix["other_hrs"]] = 0
            row[cph_ix["concurrency_v"]] = round(concurrency, 3)
            cph_rows.append(row)

        # ---- attendance
        working = [a for a in agents if a["email"] in late_by_agent]
        for agent in working:
            late = 1 if late_by_agent[agent["email"]] else 0
            attendance_rows.append([day.isoformat(), agent["team"], "Agent", agent["email"], late, 1, 1 - late])
        total_late = sum(late_by_agent.values())
        attendance_rows.append([day.isoformat(), "Sum", "", "", total_late, len(working),
                                round(1 - total_late / max(len(working), 1), 4)])

        # ---- tickets and CSAT
        for g, meta in SKILL_GROUPS.items():
            workers = [s["agent"] for s in shifts if s["agent"]["skill"] == g] or group_agents[g]
            res_scale = 1.0 + 0.9 * pressure[g]
            for _ in range(demand[g]):
                ticket_serial += 1
                channel = "IM" if rnd.random() < 0.58 else "Webform"
                user_type = rnd.choices(list(USER_MIX), list(USER_MIX.values()))[0]
                agent = rnd.choice(workers)
                created = datetime(day.year, day.month, day.day, rnd.randint(7, 22), rnd.randint(0, 59))
                resolution = rnd.lognormvariate(math.log(3.2), 1.2) * res_scale * (0.45 if channel == "IM" else 1.0)
                first_response = rnd.lognormvariate(math.log(0.02 if channel == "IM" else 0.7), 0.8)
                fcr = rnd.random() < clamp(0.80 - 0.18 * pressure[g] - (0.07 if channel == "Webform" else 0.0), 0.3, 0.9)
                closed_at = created + timedelta(hours=resolution)
                is_closed = closed_at.date() <= last_day
                ticket_id = f"T{day:%y%m%d}{ticket_serial:07d}"

                row = [""] * len(HEADERS["ticket_details"])
                row[tkt_ix["create_date"]] = day.isoformat()
                row[tkt_ix["close_date"]] = closed_at.date().isoformat() if is_closed else ""
                row[tkt_ix["overall_submit_date"]] = "1970-01-01"
                row[tkt_ix["ticket_id_id"]] = ticket_id
                row[tkt_ix["ticket_skill_group_name"]] = g
                row[tkt_ix["final_dealer_email"]] = agent["email"] if is_closed else ""
                row[tkt_ix["user_type_name_en"]] = user_type
                row[tkt_ix["ticket_type_new_name_en"]] = "Question"
                row[tkt_ix["country"]] = "VN"
                row[tkt_ix["ticket_channel_name_en"]] = channel
                row[tkt_ix["sub_status_name_en"]] = "Closed" if is_closed else "Processing"
                row[tkt_ix["im_skill_group_name_im"]] = meta["im"] if channel == "IM" else "NULL"
                row[tkt_ix["create"]] = 1
                row[tkt_ix["overall_survey_score"]] = 0
                row[tkt_ix["total_first_response_time_hrs"]] = round(first_response, 6)
                row[tkt_ix["first_contact_resolution"]] = int(fcr) if is_closed else ""
                row[tkt_ix["resolution_hours"]] = round(resolution, 4) if is_closed else ""
                row[tkt_ix["first_response_ticket_volume_in24hrs_24h"]] = 1 if first_response <= 24 else 0
                row[tkt_ix["official_ticket_24h_resolution_rate_24h"]] = (1 if resolution <= 24 else 0) if is_closed else ""
                ticket_rows.append(row)

                if is_closed and rnd.random() < (0.35 if channel == "IM" else 0.20):
                    p_sat = clamp(0.91 - (0.09 if not fcr else 0) - (0.13 if resolution > 24 else 0)
                                  - 0.06 * pressure[g] + (agent["speed"] - 1) * 0.1, 0.35, 0.97)
                    if rnd.random() < p_sat:
                        score = 5 if rnd.random() < 0.62 else 4
                    else:
                        score = rnd.choices([1, 2, 3], [0.35, 0.25, 0.40])[0]
                    survey = [""] * len(HEADERS["csat_details"])
                    survey[csat_ix["official_csat_survey_submit_date"]] = closed_at.date().isoformat()
                    survey[csat_ix["usertype"]] = user_type
                    survey[csat_ix["ticket_id_id"]] = ticket_id
                    survey[csat_ix["level3_label"]] = rnd.choice(LABELS)
                    survey[csat_ix["ticket_skill_group_name"]] = g
                    survey[csat_ix["country"]] = "VN"
                    survey[csat_ix["final_dealer_email"]] = agent["email"]
                    survey[csat_ix["official_csat_survey_score"]] = score
                    survey[csat_ix["ticket_channel_name_en"]] = channel
                    survey[csat_ix["im_skill_group_name_im"]] = meta["im"] if channel == "IM" else "NULL"
                    csat_rows.append(survey)

        # ---- backlog by user type
        total_open = sum(backlog.values())
        total_created = max(sum(demand.values()), 1)
        total_closed = sum(closed.values())
        aged = clamp(0.08 + 0.55 * total_open / total_created, 0.05, 0.7)
        for user_type, share in USER_MIX.items():
            open_n = total_open * share
            parts = [open_n * p for p in (0.34, 0.14, 0.27, 0.25)]  # unassigned, unprocessed, pending, onhold
            row = [""] * len(HEADERS["backlog_details"])
            row[0] = day.isoformat()
            row[1] = user_type
            row[2] = "ALL"
            row[3] = round(open_n / max(total_created * share, 1), 4)
            counts = [
                *parts,
                parts[0] * aged, parts[1] * aged * 0.6, (open_n * 0.05) * aged,
                parts[2] * aged * 0.5, parts[3] * aged * 0.5,
            ]
            for offset, value in enumerate(counts):
                row[4 + offset] = int(round(value))
            row[13] = int(round(total_closed * share))
            backlog_rows.append(row)

        # ---- forecast vs actual per skill group
        for g in SKILL_GROUPS:
            miss = -0.14 if event > 1.15 else rnd.gauss(0.01, 0.04)
            forecast_traffic = demand[g] / (1 + miss) if event > 1.15 else demand[g] * (1 + rnd.gauss(0.01, 0.045))
            scheduled = sum(0.5 if s["agent"]["part_time"] else 1.0 for s in shifts
                            if s["agent"]["skill"] == g and s["segment"] == s["agent"]["primary"])
            # tickets one agent-day can handle, with a 12% planning buffer for shrinkage
            fte_needed = forecast_traffic / (96.0 * 0.88)
            forecast_rows.append([
                day.isoformat(), g, int(round(forecast_traffic)), demand[g],
                round((demand[g] - forecast_traffic) / max(forecast_traffic, 1), 4),
                round(fte_needed, 2), round(scheduled, 2),
            ])

        backlog_prev = backlog

    writer = Writer(stamp)
    writer.write("cph_details", cph_rows)
    writer.write("ticket_details", ticket_rows)
    writer.write("csat_details", csat_rows)
    writer.write("ontime_attendance", attendance_rows)
    writer.write("backlog_details", backlog_rows)
    writer.write("fc_actual_details", forecast_rows)


if __name__ == "__main__":
    main()
