"""initial schema"""

from alembic import op
import sqlalchemy as sa


revision = "20260310_000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "person",
        sa.Column("personid", sa.Integer(), nullable=False),
        sa.Column("first_name", sa.String(length=255), nullable=False),
        sa.Column("last_name", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("personid"),
        sa.UniqueConstraint("first_name", "last_name", name="uq_person_name"),
    )
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("password", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("administrator", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_table(
        "visit",
        sa.Column("visitid", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.String(length=20), nullable=False),
        sa.Column("restaurant", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("visitid"),
    )
    op.create_table(
        "comment",
        sa.Column("commentid", sa.Integer(), nullable=False),
        sa.Column("userid", sa.Integer(), nullable=False),
        sa.Column("comment", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["userid"], ["user.id"]),
        sa.PrimaryKeyConstraint("commentid"),
    )
    op.create_table(
        "weight",
        sa.Column("weightid", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("visit_id", sa.Integer(), nullable=False),
        sa.Column("preweight", sa.Float(), nullable=False),
        sa.Column("postweight", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["person.personid"]),
        sa.ForeignKeyConstraint(["visit_id"], ["visit.visitid"]),
        sa.PrimaryKeyConstraint("weightid"),
    )


def downgrade():
    op.drop_table("weight")
    op.drop_table("comment")
    op.drop_table("visit")
    op.drop_table("user")
    op.drop_table("person")
