# Copyright 2024-2025 Tecnativa - Víctor Martínez
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from openupgradelib import openupgrade

_deleted_xml_records = ["maintenance.mail_alias_equipment"]


@openupgrade.migrate()
def migrate(env, version):
    openupgrade.load_data(env, "maintenance", "17.0.1.0/noupdate_changes.xml")
    openupgrade.delete_records_safely_by_xml_id(
        env,
        _deleted_xml_records,
    )
