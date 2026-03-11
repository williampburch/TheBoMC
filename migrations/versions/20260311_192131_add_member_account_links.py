"""add member account links"""

from alembic import op
import sqlalchemy as sa


revision = "20260311_192131"
down_revision = "20260310_000001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("person", schema=None) as batch_op:
        batch_op.add_column(sa.Column("account_id", sa.Integer(), nullable=True))
        batch_op.create_unique_constraint("uq_person_account_id", ["account_id"])
        batch_op.create_foreign_key("fk_person_account_id_user", "user", ["account_id"], ["id"])


def downgrade():
    with op.batch_alter_table("person", schema=None) as batch_op:
        batch_op.drop_constraint("fk_person_account_id_user", type_="foreignkey")
        batch_op.drop_constraint("uq_person_account_id", type_="unique")
        batch_op.drop_column("account_id")
