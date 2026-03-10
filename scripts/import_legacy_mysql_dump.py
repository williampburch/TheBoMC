#!/usr/bin/env python3
"""Import the legacy MySQL dump into the current legacy-aligned Flask schema."""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


INSERT_RE = re.compile(r"INSERT INTO `(?P<table>[^`]+)` VALUES (?P<values>.*?);", re.DOTALL)
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass(frozen=True)
class LegacyUser:
    legacy_id: int
    username: str
    password_hash: str
    created_at: datetime | None
    administrator: bool


@dataclass(frozen=True)
class LegacyPerson:
    legacy_id: int
    first_name: str
    last_name: str


@dataclass(frozen=True)
class LegacyVisit:
    legacy_id: int
    year: int
    month: str
    restaurant: str


@dataclass(frozen=True)
class LegacyWeight:
    legacy_id: int
    person_id: int
    visit_id: int
    preweight: float
    postweight: float


@dataclass(frozen=True)
class LegacyComment:
    legacy_id: int
    user_id: int
    comment: str
    created_at: datetime | None


@dataclass(frozen=True)
class ParsedDump:
    users: list[LegacyUser]
    persons: list[LegacyPerson]
    visits: list[LegacyVisit]
    weights: list[LegacyWeight]
    comments: list[LegacyComment]


def split_rows(values_blob: str) -> list[str]:
    rows = []
    depth = 0
    row_start = None
    in_string = False
    escaped = False

    for index, char in enumerate(values_blob):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "'":
                in_string = False
            continue

        if char == "'":
            in_string = True
        elif char == "(":
            if depth == 0:
                row_start = index
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0 and row_start is not None:
                rows.append(values_blob[row_start : index + 1])
                row_start = None

    return rows


def split_fields(row_blob: str) -> list[str]:
    row = row_blob.strip()
    if not row.startswith("(") or not row.endswith(")"):
        raise ValueError(f"Unexpected row format: {row_blob[:80]}")

    fields = []
    current = []
    in_string = False
    escaped = False

    for char in row[1:-1]:
        if in_string:
            current.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "'":
                in_string = False
            continue

        if char == "'":
            in_string = True
            current.append(char)
        elif char == ",":
            fields.append("".join(current).strip())
            current = []
        else:
            current.append(char)

    fields.append("".join(current).strip())
    return fields


def unescape_mysql_string(value: str) -> str:
    if len(value) < 2 or not (value.startswith("'") and value.endswith("'")):
        return value

    inner = value[1:-1]
    output = []
    index = 0
    replacements = {
        "0": "\0",
        "b": "\b",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "Z": "\x1a",
        "\\": "\\",
        "'": "'",
        '"': '"',
    }

    while index < len(inner):
        char = inner[index]
        if char == "\\" and index + 1 < len(inner):
            output.append(replacements.get(inner[index + 1], inner[index + 1]))
            index += 2
            continue
        output.append(char)
        index += 1

    return "".join(output)


def parse_scalar(value: str):
    upper = value.upper()
    if upper == "NULL":
        return None
    if value.startswith("'") and value.endswith("'"):
        return unescape_mysql_string(value)
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return value


def get_insert_rows(sql_text: str, table_name: str) -> list[list[object]]:
    rows = []
    for match in INSERT_RE.finditer(sql_text):
        if match.group("table") != table_name:
            continue
        rows.extend([[parse_scalar(field) for field in split_fields(row)] for row in split_rows(match.group("values"))])
    return rows


def parse_timestamp(value):
    if not value:
        return None
    return datetime.strptime(value, TIMESTAMP_FORMAT)


def parse_dump(dump_path: Path) -> ParsedDump:
    sql_text = dump_path.read_text(encoding="utf-8")

    users = [
        LegacyUser(
            legacy_id=row[0],
            username=row[1],
            password_hash=row[2],
            created_at=parse_timestamp(row[3]),
            administrator=bool(row[4]),
        )
        for row in get_insert_rows(sql_text, "Users")
    ]
    persons = [
        LegacyPerson(legacy_id=row[0], first_name=row[1], last_name=row[2])
        for row in get_insert_rows(sql_text, "Persons")
    ]
    visits = [
        LegacyVisit(legacy_id=row[0], year=row[1], month=row[2], restaurant=row[3].strip())
        for row in get_insert_rows(sql_text, "Visit")
    ]
    weights = [
        LegacyWeight(
            legacy_id=row[0],
            person_id=row[1],
            visit_id=row[2],
            preweight=float(row[3]),
            postweight=float(row[4]),
        )
        for row in get_insert_rows(sql_text, "Weight")
    ]
    comments = [
        LegacyComment(
            legacy_id=row[0],
            user_id=row[1],
            comment=row[2],
            created_at=parse_timestamp(row[3]),
        )
        for row in get_insert_rows(sql_text, "Comments")
    ]

    return ParsedDump(users=users, persons=persons, visits=visits, weights=weights, comments=comments)


def load_app_models():
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    os.environ["SKIP_ADMIN_SEED"] = "1"
    from app import Comment, Person, User, Visit, WeighIn, create_app, db

    return create_app, db, User, Person, Visit, WeighIn, Comment


def select_users(parsed_dump: ParsedDump, include_all_users: bool):
    if include_all_users:
        return parsed_dump.users

    comment_user_ids = {comment.user_id for comment in parsed_dump.comments}
    selected = []
    for user in parsed_dump.users:
        if user.administrator or user.legacy_id in comment_user_ids:
            selected.append(user)
    return selected


def import_dump(parsed_dump: ParsedDump, include_all_users: bool):
    create_app, db, User, Person, Visit, WeighIn, Comment = load_app_models()
    selected_users = select_users(parsed_dump, include_all_users)
    selected_user_ids = {user.legacy_id for user in selected_users}
    stats = Counter()

    app = create_app()
    with app.app_context():
        for user in selected_users:
            record = db.session.get(User, user.legacy_id)
            created = record is None
            if created:
                record = User(id=user.legacy_id, username=user.username, is_admin=user.administrator)
                db.session.add(record)
            record.username = user.username
            record.password_hash = user.password_hash
            record.created_at = user.created_at or datetime.utcnow()
            record.is_admin = user.administrator
            stats["users_created" if created else "users_updated"] += 1

        for person in parsed_dump.persons:
            record = db.session.get(Person, person.legacy_id)
            created = record is None
            if created:
                record = Person(id=person.legacy_id, first_name=person.first_name, last_name=person.last_name)
                db.session.add(record)
            record.first_name = person.first_name
            record.last_name = person.last_name
            stats["members_created" if created else "members_updated"] += 1

        for visit in parsed_dump.visits:
            record = db.session.get(Visit, visit.legacy_id)
            created = record is None
            if created:
                record = Visit(id=visit.legacy_id, year=visit.year, month=visit.month, restaurant=visit.restaurant)
                db.session.add(record)
            record.year = visit.year
            record.month = visit.month
            record.restaurant = visit.restaurant
            stats["visits_created" if created else "visits_updated"] += 1

        db.session.flush()

        for weight in parsed_dump.weights:
            if db.session.get(Person, weight.person_id) is None or db.session.get(Visit, weight.visit_id) is None:
                stats["weights_skipped_missing_reference"] += 1
                continue

            record = db.session.get(WeighIn, weight.legacy_id)
            created = record is None
            if created:
                record = WeighIn(
                    id=weight.legacy_id,
                    person_id=weight.person_id,
                    visit_id=weight.visit_id,
                    before_weight=weight.preweight,
                    after_weight=weight.postweight,
                )
                db.session.add(record)
            record.person_id = weight.person_id
            record.visit_id = weight.visit_id
            record.before_weight = weight.preweight
            record.after_weight = weight.postweight
            stats["weigh_ins_created" if created else "weigh_ins_updated"] += 1

        for comment in parsed_dump.comments:
            if comment.user_id not in selected_user_ids:
                stats["comments_skipped_missing_user"] += 1
                continue

            record = db.session.get(Comment, comment.legacy_id)
            created = record is None
            if created:
                record = Comment(
                    id=comment.legacy_id,
                    user_id=comment.user_id,
                    comment=comment.comment,
                    created_at=comment.created_at or datetime.utcnow(),
                )
                db.session.add(record)
            record.user_id = comment.user_id
            record.comment = comment.comment
            record.created_at = comment.created_at or datetime.utcnow()
            stats["comments_created" if created else "comments_updated"] += 1

        db.session.commit()

    stats["legacy_users_skipped"] = len(parsed_dump.users) - len(selected_users)
    return stats


def print_summary(parsed_dump: ParsedDump, include_all_users: bool):
    selected_users = select_users(parsed_dump, include_all_users)
    print(f"Users in dump: {len(parsed_dump.users)}")
    print(f"Users selected for import: {len(selected_users)}")
    print(f"Members: {len(parsed_dump.persons)}")
    print(f"Visits: {len(parsed_dump.visits)}")
    print(f"Weigh-ins: {len(parsed_dump.weights)}")
    print(f"Comments: {len(parsed_dump.comments)}")
    print(f"Include all users: {'yes' if include_all_users else 'no'}")


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump_path", type=Path, help="Path to the legacy MySQL dump file")
    parser.add_argument("--summary-only", action="store_true", help="Parse the dump without writing to the app database")
    parser.add_argument(
        "--include-all-users",
        action="store_true",
        help="Import every legacy user instead of only admins and comment authors",
    )
    return parser


def main():
    args = build_parser().parse_args()
    parsed_dump = parse_dump(args.dump_path)

    if args.summary_only:
        print_summary(parsed_dump, args.include_all_users)
        return 0

    stats = import_dump(parsed_dump, args.include_all_users)
    for key in sorted(stats):
        print(f"{key}: {stats[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
