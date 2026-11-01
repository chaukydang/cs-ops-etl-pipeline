"""Generate synthetic CSVs in downloads/dashboard so the archive and database
stages (and dbt) can be tried without access to the real dashboard.

    python scripts/make_demo_data.py --days 21 --agents 40

Names, e-mails and numbers are random; only the column layout matches the
real exports.
"""

from __future__ import annotations

import argparse
import csv
import random
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

SKILL_GROUPS = [
    "VN-SS-L2L-Inquiry-TK-VB-L1",
    "VN-CR-L2L-Inquiry-TK-VB-L1",
    "VN-KAS-L2L-Inquiry-TK-VB-L1",
]
USER_TYPES = ["Seller", "Creator", "Buyer"]
TENURES = ["<90", "91-180", "180-270", "271-360", ">361"]


def write(name: str, key: str, rows: list[list], stamp: str) -> None:
    out_dir = ROOT / "downloads" / "dashboard"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}-{stamp}.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADERS[key])
        writer.writerows(rows)
    print(f"{path.name}: {len(rows)} rows")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=21)
    parser.add_argument("--agents", type=int, default=40)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    rnd = random.Random(args.seed)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    days = [date.today() - timedelta(days=n) for n in range(args.days, 0, -1)]
    agents = [
        {
            "email": f"agent{n:03d}@example.com",
            "tier": rnd.choice(["Tier 1 Agent", "Tier 2 Agent"]),
            "tenure": rnd.choice(TENURES),
            "skill": rnd.choice(SKILL_GROUPS),
            "dept": rnd.choice(["TeamA", "TeamB", "TeamC"]),
        }
        for n in range(args.agents)
    ]

    # productivity per agent / day / segment
    cph = []
    for day in days:
        for agent in agents:
            if rnd.random() < 0.15:  # day off
                continue
            for segment in ("IM", "Ticket"):
                paid = round(rnd.uniform(3.0, 4.2), 3)
                online = round(paid * rnd.uniform(0.7, 0.9), 3)
                busy = round(online * rnd.uniform(0.3, 0.5), 3)
                closed = rnd.randint(0, 40)
                row = [""] * len(HEADERS["cph_details"])
                row[0] = agent["dept"]
                row[1] = agent["tier"]
                row[2] = agent["tenure"]
                row[3] = agent["email"]
                row[4] = day.isoformat()
                row[5] = rnd.choice(["SPS", "SPG"])
                row[6] = segment
                row[7] = agent["skill"]
                row[8] = round(closed / paid, 4) if paid else ""
                row[9] = closed
                row[11] = rnd.randint(closed, closed + 15)
                row[12] = paid
                row[13] = round(busy / paid, 4)
                row[14] = round(online / paid, 4)
                row[15] = round(rnd.uniform(0.7, 0.95), 4)
                row[16] = rnd.randint(0, 2)
                row[19] = round(busy, 3)
                row[20] = online
                row[21] = busy
                row[22] = round(online - busy, 3)
                row[23] = 0
                row[24] = round(rnd.uniform(0, 0.3), 3)
                cph.append(row)
    write("cph_details", "cph_details", cph, stamp)

    # tickets
    tickets = []
    for day in days:
        for n in range(rnd.randint(150, 260)):
            agent = rnd.choice(agents)
            row = [""] * len(HEADERS["ticket_details"])
            closed_day = day + timedelta(days=rnd.choice([0, 0, 0, 1]))
            row[0] = day.isoformat()
            row[1] = closed_day.isoformat()
            row[2] = "1970-01-01"
            row[3] = f"T{day:%y%m%d}{n:05d}"
            row[4] = agent["skill"]
            row[5] = agent["email"]
            row[6] = rnd.choice(USER_TYPES)
            row[7] = "Question"
            row[11] = "VN"
            row[12] = rnd.choice(["IM", "Webform"])
            row[17] = "NULL"
            row[24] = 1
            row[25] = rnd.choice(["0", "1", "2", "3", "4", "5"])
            row[26] = round(rnd.uniform(0.0005, 0.05), 6)
            row[27] = rnd.choice(["0", "1"])
            row[28] = round(rnd.uniform(0.02, 30), 4)
            tickets.append(row)
    write("ticket_details", "ticket_details", tickets, stamp)

    # csat
    csat = []
    for day in days:
        for n in range(rnd.randint(40, 90)):
            agent = rnd.choice(agents)
            row = [""] * len(HEADERS["csat_details"])
            row[0] = day.isoformat()
            row[1] = rnd.choice(USER_TYPES)
            row[2] = f"T{day:%y%m%d}{n:05d}"
            row[3] = "Account issue"
            row[4] = agent["skill"]
            row[5] = "VN"
            row[6] = agent["email"]
            row[7] = rnd.choice(["1", "2", "3", "4", "5", "5", "5", "4"])
            row[8] = rnd.choice(["IM", "Webform"])
            row[9] = "NULL"
            csat.append(row)
    write("csat_details", "csat_details", csat, stamp)

    # attendance (includes the "Sum" roll-up rows the real export has)
    attendance = []
    for day in days:
        for agent in agents:
            if rnd.random() < 0.15:
                continue
            late = rnd.choice([0, 0, 0, 1])
            attendance.append([day.isoformat(), agent["dept"], "Agent", agent["email"], late, 1, 1 - late])
        attendance.append([day.isoformat(), "Sum", "", "", "", len(agents), 0.95])
    write("ontime_attendance", "ontime_attendance", attendance, stamp)

    # backlog
    backlog = []
    for day in days:
        for user_type in USER_TYPES:
            row = [""] * len(HEADERS["backlog_details"])
            row[0] = day.isoformat()
            row[1] = user_type
            row[2] = "ALL"
            row[3] = round(rnd.uniform(0.02, 0.3), 4)
            row[4:13] = [rnd.randint(0, 500) for _ in range(9)]
            row[13] = rnd.randint(100, 1500)
            backlog.append(row)
    write("backlog_details", "backlog_details", backlog, stamp)

    # forecast vs actual
    forecast = []
    for day in days:
        for skill in SKILL_GROUPS:
            fc = rnd.randint(300, 900)
            actual = int(fc * rnd.uniform(0.85, 1.15))
            fte = round(rnd.uniform(8, 25), 2)
            forecast.append(
                [day.isoformat(), skill, fc, actual, round((actual - fc) / fc, 4), fte,
                 round(fte * rnd.uniform(0.85, 1.1), 2)]
            )
    write("fc_actual_details", "fc_actual_details", forecast, stamp)


if __name__ == "__main__":
    main()
