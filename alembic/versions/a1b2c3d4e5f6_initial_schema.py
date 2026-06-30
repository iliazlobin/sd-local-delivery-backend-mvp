"""initial_schema

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-06-30 01:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all MVP tables: dcs, products, inventory, orders, order_line_items."""
    op.create_table(
        "dcs",
        sa.Column("dc_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("center_lat", sa.Double(), nullable=False),
        sa.Column("center_lon", sa.Double(), nullable=False),
        sa.Column("delivery_radius_mi", sa.Double(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("dc_id"),
    )
    op.create_table(
        "products",
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("dc_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("brand", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("unit_price_cents", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["dc_id"], ["dcs.dc_id"]),
        sa.PrimaryKeyConstraint("product_id"),
        sa.UniqueConstraint("dc_id", "name"),
    )
    op.create_index("ix_products_dc_category", "products", ["dc_id", "category"])
    op.create_index("ix_products_dc_name", "products", ["dc_id", "name"])
    op.create_table(
        "inventory",
        sa.Column("inventory_id", sa.Uuid(), nullable=False),
        sa.Column("dc_id", sa.Text(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("stock_on_hand", sa.Integer(), nullable=False),
        sa.Column("reserved_qty", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["dc_id"], ["dcs.dc_id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.product_id"]),
        sa.PrimaryKeyConstraint("inventory_id"),
        sa.UniqueConstraint("dc_id", "product_id"),
    )
    op.create_table(
        "orders",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("dc_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("total_amount_cents", sa.Integer(), nullable=False),
        sa.Column("delivery_address", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["dc_id"], ["dcs.dc_id"]),
        sa.PrimaryKeyConstraint("order_id"),
    )
    op.create_index("ix_orders_status_created", "orders", ["status", "created_at"])
    op.create_table(
        "order_line_items",
        sa.Column("line_item_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_cents", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.order_id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.product_id"]),
        sa.PrimaryKeyConstraint("line_item_id"),
    )


def downgrade() -> None:
    """Drop all MVP tables."""
    op.drop_table("order_line_items")
    op.drop_index("ix_orders_status_created", table_name="orders")
    op.drop_table("orders")
    op.drop_table("inventory")
    op.drop_index("ix_products_dc_name", table_name="products")
    op.drop_index("ix_products_dc_category", table_name="products")
    op.drop_table("products")
    op.drop_table("dcs")
