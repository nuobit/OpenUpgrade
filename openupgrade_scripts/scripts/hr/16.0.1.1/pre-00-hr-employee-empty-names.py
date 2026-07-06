# Copyright 2026 NuoBiT Solutions SL
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0)
from openupgradelib import openupgrade


@openupgrade.migrate()
def migrate(env, version):
    """Name empty-named employees before hr's own migration runs.

    The 16.0 hr post-migration (create_work_contact) creates a res.partner
    per employee taking the partner name from the employee name. Core Odoo
    accepts nameless partners, but with OCA partner_firstname installed its
    _check_name constraint raises EmptyNamesError and the whole -u all dies
    (seen 2026-07-06 on a real 15->16 hop: one active employee with an empty
    name). Give such employees a deterministic non-empty name first —
    work_email when available, a synthetic marker otherwise.

    hr_employee.name is a stored related to resource_resource.name, so fix
    the resource first (source of truth), then the stored column.
    This file sorts before hr's own pre-migration.py by basename, which is
    the guaranteed ordering for same-version scripts.
    """
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE resource_resource r
           SET name = COALESCE(NULLIF(BTRIM(e.work_email), ''),
                               'Employee #' || e.id)
          FROM hr_employee e
         WHERE e.resource_id = r.id
           AND (e.name IS NULL OR BTRIM(e.name) = '')
        """,
    )
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE hr_employee
           SET name = COALESCE(NULLIF(BTRIM(work_email), ''),
                               'Employee #' || id)
         WHERE name IS NULL OR BTRIM(name) = ''
        """,
    )
