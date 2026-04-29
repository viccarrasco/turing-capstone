"""Seed a synthetic demo company for live presentations.

Inserts ~60 fake alarms under company_id=99001 covering scenarios the agent's
example prompts hit: SLA / dispatch latency, peak hours, alarm-type breakdown,
faulty-equipment trends, false alarms, responder efficiency.

Run:
    docker compose exec api python -m app.cli.demo_seed seed
    docker compose exec api python -m app.cli.demo_seed clean   # remove all demo rows
"""

from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.db import SessionLocal
from app.models import Conversation, HistoricAlarm, Message

DEMO_COMPANY_ID = 99001
DEMO_BATCH_ID = "demo-seed-2026"

ALARM_TYPES = [
    (1, "Intrusion", "intrusion"),
    (2, "Fire", "fire"),
    (3, "Panic", "panic"),
    (4, "Equipment failure", "equipment_failure"),
    (5, "Test", "test"),
]

AREAS = [
    (101, "Front entrance"),
    (102, "Back entrance"),
    (103, "Garage"),
    (104, "Perimeter zone A"),
    (105, "Perimeter zone B"),
    (106, "Storage room"),
]

RESPONDERS = [
    (1001, "Demo Responder Alpha"),
    (1002, "Demo Responder Bravo"),
    (1003, "Demo Responder Charlie"),
    (1004, "Demo Responder Delta"),
    (1005, "Demo Responder Echo"),
]

# Per-responder dispatch profile: (mean_seconds, stddev_seconds).
# Charlie is intentionally slow (SLA breach scenario).
# Echo is intentionally fast (positive outlier scenario).
RESPONDER_PROFILE = {
    1001: (180, 40),
    1002: (220, 50),
    1003: (480, 90),  # slow — SLA breach material
    1004: (210, 60),
    1005: (90, 25),   # fast
}

CLIENTS = [(5001, "Demo Client A"), (5002, "Demo Client B"), (5003, "Demo Client C")]


def _seeded_alarm(rng: random.Random, idx: int, base_ts: datetime) -> HistoricAlarm:
    alarm_type = rng.choices(
        ALARM_TYPES,
        weights=[40, 5, 10, 25, 20],  # equipment failures over-represented for demo
        k=1,
    )[0]
    area = rng.choice(AREAS)
    responder = rng.choice(RESPONDERS)
    client = rng.choice(CLIENTS)

    # Bias creation hour toward 18:00-23:00 to give a clear "peak hour" pattern.
    hour_pool = [8, 9, 10, 14, 18, 19, 20, 20, 21, 21, 22, 22, 23]
    hour = rng.choice(hour_pool)
    minute = rng.randint(0, 59)
    second = rng.randint(0, 59)
    creation_at = base_ts.replace(hour=hour, minute=minute, second=second)

    mean, stddev = RESPONDER_PROFILE[responder[0]]
    dispatch_secs = max(20, int(rng.gauss(mean, stddev)))
    conclusion_at = creation_at + timedelta(seconds=dispatch_secs)

    # 8% false alarms: cancelled by demo user.
    canceled_user = "demo_user_ops" if rng.random() < 0.08 else None

    return HistoricAlarm(
        id=900_000_000 + idx,
        company_id=DEMO_COMPANY_ID,
        alarm_id=900_000 + idx,
        alarm_type_id=alarm_type[0],
        area_id=area[0],
        agent_id=2001 + (idx % 3),
        client_id=client[0],
        billing_account_id=client[0],
        responder_id=responder[0],
        triggered_zones_count=rng.randint(1, 4),
        alarm_allocation="demo_dispatch",
        alarm_category="home_alarm",
        alarm_signal=alarm_type[2],
        alarm_type_description=alarm_type[1],
        alarm_confirmed_saved_user=None,
        alarm_canceled_user=canceled_user,
        area_description=area[1],
        agent_name=f"Demo Agent {1 + (idx % 3)}",
        client_description=client[1],
        transmitter=f"DEMO-TX-{1 + (idx % 4)}",
        responder_name=responder[1],
        sqs_message_id=f"demo-sqs-{idx}",
        alarm_conclusion_at=conclusion_at,
        alarm_delegated_at=creation_at + timedelta(seconds=5),
        alarm_reopened_at=None,
        alarm_delegated=True,
        data={},
        sqs_message_attributes={},
        created_at=creation_at,
        updated_at=conclusion_at,
        mongodb_id=f"demo-mongo-{idx:08d}",
        video_url=None,
        zones_description=f"Zone {1 + (idx % 4)}",
        alarm_creation_at=creation_at,
        imported_at=datetime.utcnow(),
        import_batch_id=DEMO_BATCH_ID,
        legacy_data={},
    )


def seed(count: int = 60, seed_value: int = 42) -> int:
    rng = random.Random(seed_value)
    today = datetime.now(timezone.utc).replace(microsecond=0)

    with SessionLocal() as session:
        existing = session.query(HistoricAlarm).filter_by(company_id=DEMO_COMPANY_ID).count()
        if existing:
            print(f"company_id={DEMO_COMPANY_ID} already has {existing} rows; skipping.")
            print("Run with `clean` first if you want to reseed.")
            return 0

        rows = []
        for idx in range(count):
            days_back = rng.randint(0, 29)
            base_ts = (today - timedelta(days=days_back)).replace(microsecond=0)
            rows.append(_seeded_alarm(rng, idx, base_ts))

        session.add_all(rows)
        session.commit()

        # Seed one example conversation so the Conversations view is non-empty.
        conv = Conversation(
            company_id=DEMO_COMPANY_ID,
            title="Demo: peak hours and SLA",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(conv)
        session.flush()
        session.add_all([
            Message(
                conversation_id=conv.id,
                role="user",
                content="What are our peak alarm hours?",
                sql_query=None,
                query_results=None,
                usage_meta=None,
            ),
            Message(
                conversation_id=conv.id,
                role="assistant",
                content="(demo placeholder — re-run live to populate)",
                sql_query=None,
                query_results=None,
                usage_meta=None,
            ),
        ])
        session.commit()

        print(f"Seeded {len(rows)} demo alarms under company_id={DEMO_COMPANY_ID}.")
        print(f"Use X-Company-Id: {DEMO_COMPANY_ID} for the live demo.")
        return len(rows)


def clean() -> int:
    with SessionLocal() as session:
        result = session.execute(
            delete(HistoricAlarm).where(HistoricAlarm.company_id == DEMO_COMPANY_ID)
        )
        conv_ids = [
            row[0]
            for row in session.query(Conversation.id)
            .filter_by(company_id=DEMO_COMPANY_ID)
            .all()
        ]
        if conv_ids:
            session.execute(delete(Message).where(Message.conversation_id.in_(conv_ids)))
            session.execute(delete(Conversation).where(Conversation.id.in_(conv_ids)))
        session.commit()
        deleted = result.rowcount or 0
        print(f"Removed {deleted} demo alarms and {len(conv_ids)} demo conversations.")
        return deleted


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed/clean synthetic demo data.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    seed_p = sub.add_parser("seed", help="Insert demo rows.")
    seed_p.add_argument("--count", type=int, default=60)
    seed_p.add_argument("--seed", type=int, default=42)
    sub.add_parser("clean", help="Remove all demo rows.")
    args = parser.parse_args()

    if args.cmd == "seed":
        seed(count=args.count, seed_value=args.seed)
    elif args.cmd == "clean":
        clean()


if __name__ == "__main__":
    main()
