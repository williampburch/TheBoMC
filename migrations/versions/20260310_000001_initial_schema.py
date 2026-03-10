"""initial schema"""

from alembic import op
import sqlalchemy as sa


revision = "20260310_000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "club_member",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "restaurant",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("city", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "buffet_visit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("visit_date", sa.Date(), nullable=False),
        sa.Column("price_per_person", sa.Float(), nullable=False),
        sa.Column("overall_rating", sa.Float(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "weigh_in",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("visit_id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("before_weight", sa.Float(), nullable=False),
        sa.Column("after_weight", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["member_id"], ["club_member.id"]),
        sa.ForeignKeyConstraint(["visit_id"], ["buffet_visit.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("weigh_in")
    op.drop_table("buffet_visit")
    op.drop_table("user")
    op.drop_table("restaurant")
    op.drop_table("club_member")
