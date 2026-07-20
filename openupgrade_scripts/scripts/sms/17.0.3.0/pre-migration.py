# Copyright 2026 NuoBiT Solutions - Eric Antones <eantones@nuobit.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from openupgradelib import openupgrade


@openupgrade.migrate()
def migrate(env, version):
    """Pre-create sms_sms.uuid filled with one value per row.

    The uuid field (new in 17.0) is declared with a callable default and
    a unique constraint. Without this script the ORM creates the column
    during the upgrade and evaluates the default only once, so every
    pre-existing row receives the same value and the uuid_unique
    constraint fails to install.
    """
    if not openupgrade.column_exists(env.cr, "sms_sms", "uuid"):
        openupgrade.logged_query(env.cr, "ALTER TABLE sms_sms ADD COLUMN uuid varchar")
    # Fill missing values and break any duplicate group left by a
    # previous upgrade run without this script (deterministic per id,
    # same 32-hex shape as uuid4().hex, idempotent).
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE sms_sms
        SET uuid = md5('sms_sms-uuid-' || id::text)
        WHERE uuid IS NULL
            OR uuid IN (
                SELECT uuid FROM sms_sms GROUP BY uuid HAVING count(*) > 1
            )
        """,
    )
