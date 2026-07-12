# Copyright Odoo Community Association (OCA)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from openupgradelib import openupgrade

from odoo import api, fields, models

from odoo.addons.base.models.ir_model import (
    IrModel,
    IrModelData,
    IrModelFields,
    IrModelRelation,
    IrModelSelection,
)


def _drop_table(self):
    """Never drop tables"""
    for model in self:
        if self.env.get(model.model) is not None:
            openupgrade.message(
                self.env.cr,
                "Unknown",
                False,
                False,
                "Not dropping the table or view of model %s",
                model.model,
            )


IrModel._drop_table = _drop_table


def _drop_column(self):
    """Never drop columns"""
    for field in self:
        if field.name in models.MAGIC_COLUMNS:
            continue
        openupgrade.message(
            self.env.cr,
            "Unknown",
            False,
            False,
            "Not dropping the column of field %s of model %s",
            field.name,
            field.model,
        )
        continue


IrModelFields._drop_column = _drop_column


@api.model
def _module_data_uninstall(self, modules_to_remove):
    """To pass context, that the patch in __getitem__ of api.Environment uses"""
    patched_self = self.with_context(**{"missing_model": True})
    return IrModelData._module_data_uninstall._original_method(
        patched_self, modules_to_remove
    )


_module_data_uninstall._original_method = IrModelData._module_data_uninstall
IrModelData._module_data_uninstall = _module_data_uninstall


def _module_data_uninstall(self):
    """Don't delete many2many relation tables. Only unlink the
    ir.model.relation record itself.
    """
    self.unlink()


IrModelRelation._module_data_uninstall = _module_data_uninstall


def _process_ondelete(self):
    """Don't break on missing models, missing fields or fields that are no
    longer Selection fields when deleting their selection values"""
    to_process = self.browse([])
    for selection in self:
        try:
            model = self.env[selection.field_id.model]
        except KeyError:
            continue
        field = model._fields.get(selection.field_id.name)
        if field is None or not isinstance(field, fields.Selection):
            # The field vanished or changed type between versions (e.g.
            # selection -> boolean, or reference-field selection rows that
            # became orphans): the ondelete machinery no longer applies,
            # just let the record be unlinked.
            continue
        to_process += selection
    return IrModelSelection._process_ondelete._original_method(to_process)


_process_ondelete._original_method = IrModelSelection._process_ondelete
IrModelSelection._process_ondelete = _process_ondelete
