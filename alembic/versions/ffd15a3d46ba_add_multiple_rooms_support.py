"""add_multiple_rooms_support

Revision ID: ffd15a3d46ba
Revises: a41df36fca7a
Create Date: 2025-11-18 03:58:54.303062

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ffd15a3d46ba'
down_revision: Union[str, None] = 'a41df36fca7a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add room_slots field to schedule_items (number of rooms needed)
    op.add_column('schedule_items', sa.Column('room_slots', sa.Integer(), nullable=False, server_default='1'))

    # Add room_slots field to day_schedule_entries
    op.add_column('day_schedule_entries', sa.Column('room_slots', sa.Integer(), nullable=False, server_default='1'))


def downgrade() -> None:
    op.drop_column('day_schedule_entries', 'room_slots')
    op.drop_column('schedule_items', 'room_slots')
