"""add restaurant atlas"""

from alembic import op
import sqlalchemy as sa


revision = "20260312_120000"
down_revision = "20260311_192131"
branch_labels = None
depends_on = None


restaurant_table = sa.table(
    "restaurant",
    sa.column("id", sa.Integer()),
    sa.column("name", sa.String()),
    sa.column("status", sa.String()),
)

visit_table = sa.table(
    "visit",
    sa.column("visitid", sa.Integer()),
    sa.column("restaurant", sa.String()),
    sa.column("restaurant_id", sa.Integer()),
)


def upgrade():
    op.create_table(
        "restaurant",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("street_address", sa.String(length=255), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("state", sa.String(length=40), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    with op.batch_alter_table("visit", schema=None) as batch_op:
        batch_op.add_column(sa.Column("restaurant_id", sa.Integer(), nullable=True))

    connection = op.get_bind()
    visit_names = [
        row[0]
        for row in connection.execute(
            sa.select(sa.distinct(visit_table.c.restaurant)).where(visit_table.c.restaurant.is_not(None))
        ).fetchall()
    ]

    for name in visit_names:
        connection.execute(restaurant_table.insert().values(name=name, status="visited"))

    restaurant_rows = connection.execute(sa.select(restaurant_table.c.id, restaurant_table.c.name)).fetchall()
    restaurant_ids_by_name = {name: restaurant_id for restaurant_id, name in restaurant_rows}

    for visit_id, restaurant_name in connection.execute(sa.select(visit_table.c.visitid, visit_table.c.restaurant)).fetchall():
        connection.execute(
            visit_table.update()
            .where(visit_table.c.visitid == visit_id)
            .values(restaurant_id=restaurant_ids_by_name[restaurant_name])
        )

    with op.batch_alter_table("visit", schema=None) as batch_op:
        batch_op.alter_column("restaurant_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key("fk_visit_restaurant_id_restaurant", "restaurant", ["restaurant_id"], ["id"])
        batch_op.drop_column("restaurant")


def downgrade():
    with op.batch_alter_table("visit", schema=None) as batch_op:
        batch_op.add_column(sa.Column("restaurant", sa.String(length=255), nullable=True))

    connection = op.get_bind()
    join_stmt = (
        sa.select(visit_table.c.visitid, restaurant_table.c.name)
        .select_from(visit_table.join(restaurant_table, visit_table.c.restaurant_id == restaurant_table.c.id))
    )
    for visit_id, restaurant_name in connection.execute(join_stmt).fetchall():
        connection.execute(
            visit_table.update().where(visit_table.c.visitid == visit_id).values(restaurant=restaurant_name)
        )

    with op.batch_alter_table("visit", schema=None) as batch_op:
        batch_op.alter_column("restaurant", existing_type=sa.String(length=255), nullable=False)
        batch_op.drop_constraint("fk_visit_restaurant_id_restaurant", type_="foreignkey")
        batch_op.drop_column("restaurant_id")

    op.drop_table("restaurant")
