env = locals().get("env")
# return a picking so that we have something to migrate
picking = env.ref("stock.outgoing_shipment_main_warehouse1")
return_wizard = (
    env["stock.return.picking"]
    .with_context(
        active_id=picking.id,
        active_ids=picking.ids,
        active_model=picking._name,
    )
    .create({})
)
return_wizard._onchange_picking_id()
return_wizard._create_returns()

# Open deliveries of products with stock, one case each, found by their origin in
# test_stock_migration.py; the delivery type reserves on confirmation
stock = env.ref("stock.stock_location_stock")
customers = env.ref("stock.stock_location_customers")
delivery_type = env.ref("stock.picking_type_out")


def _product(code, quantity=100, **values):
    product = env["product.product"].create(
        {"name": code, "default_code": code, "type": "product", **values}
    )
    if quantity:
        env["stock.quant"]._update_available_quantity(product, stock, quantity)
    return product


def _delivery(origin, products, demand, uom=None, confirm=True, **move_values):
    delivery = env["stock.picking"].create(
        {
            "origin": origin,
            "picking_type_id": delivery_type.id,
            "location_id": stock.id,
            "location_dest_id": customers.id,
            "move_ids": [
                (
                    0,
                    0,
                    {
                        "name": product.name,
                        "product_id": product.id,
                        "product_uom_qty": demand,
                        "product_uom": (uom or product.uom_id).id,
                        "location_id": stock.id,
                        "location_dest_id": customers.id,
                        **move_values,
                    },
                )
                for product in products
            ],
        }
    )
    if confirm:
        delivery.action_confirm()
    return delivery


def _add_done_line(picking, product, quantity, move=None, **values):
    # without a move, v16 makes one for the line, with no demand
    return env["stock.move.line"].create(
        {
            "move_id": move and move.id,
            "picking_id": picking.id,
            "product_id": product.id,
            "product_uom_id": product.uom_id.id,
            "location_id": picking.location_id.id,
            "location_dest_id": picking.location_dest_id.id,
            "qty_done": quantity,
            **values,
        }
    )


# reserved, with nothing done
_delivery("ou17-reserved", _product("OU17-RESERVED"), 3).action_assign()
# reserved and done in equal quantities
delivery = _delivery("ou17-done-equal", _product("OU17-DONE-EQUAL"), 4)
delivery.action_assign()
delivery.move_line_ids.qty_done = 4
# done more than reserved
delivery = _delivery("ou17-done-more", _product("OU17-DONE-MORE"), 5)
delivery.action_assign()
delivery.move_line_ids.qty_done = 8
# done less than reserved
delivery = _delivery("ou17-done-less", _product("OU17-DONE-LESS"), 10)
delivery.action_assign()
delivery.move_line_ids.qty_done = 6
# done with nothing reserved, on a line added by hand to the move
delivery = _delivery("ou17-done-unreserved", _product("OU17-DONE-UNRESERVED"), 2)
delivery.do_unreserve()
_add_done_line(delivery, delivery.move_ids.product_id, 2, delivery.move_ids)
# reserved in a unit other than the product's, the product's figure rounded to 0
delivery = _delivery(
    "ou17-other-unit",
    _product("OU17-OTHER-UNIT"),
    1,
    uom=env.ref("uom.product_uom_dozen"),
)
delivery.action_assign()
env.cr.execute(
    "UPDATE stock_move_line SET reserved_qty = 0 WHERE id IN %s",
    (tuple(delivery.move_line_ids.ids),),
)
# more demand than stock, so reserved in part, with nothing done
_delivery("ou17-partially-available", _product("OU17-PARTIALLY-AVAILABLE"), 150)
# a reserved line beside a line added by hand to its move with a quantity done
delivery = _delivery("ou17-several-lines", _product("OU17-SEVERAL-LINES"), 3)
_add_done_line(delivery, delivery.move_ids.product_id, 1, delivery.move_ids)
# an empty line added by hand to a move with nothing reserved
delivery = _delivery("ou17-empty-line", _product("OU17-EMPTY-LINE"), 1)
delivery.do_unreserve()
_add_done_line(delivery, delivery.move_ids.product_id, 0, delivery.move_ids)
# a move cancelled after a quantity was done on its line, beside a reserved one
delivery = _delivery(
    "ou17-cancelled-done",
    _product("OU17-CANCELLED-DONE") | _product("OU17-BESIDE-CANCELLED-DONE"),
    1,
)
delivery.action_assign()
cancelled = delivery.move_ids.filtered(
    lambda move: move.product_id.default_code == "OU17-CANCELLED-DONE"
)
cancelled.move_line_ids.qty_done = 1
cancelled._action_cancel()
# a move cancelled with nothing done, so without lines, beside a reserved one
delivery = _delivery(
    "ou17-cancelled-lineless",
    _product("OU17-CANCELLED-LINELESS") | _product("OU17-BESIDE-CANCELLED-LINELESS"),
    1,
)
delivery.action_assign()
delivery.move_ids.filtered(
    lambda move: move.product_id.default_code == "OU17-CANCELLED-LINELESS"
)._action_cancel()
# an inventory applied with no difference, whose move is done with a line of nothing
# done, and a done move without lines, which no v16 flow makes but a database may hold
quant = env["stock.quant"].search(
    [
        ("product_id", "=", _product("OU17-INVENTORY-EQUAL").id),
        ("location_id", "=", stock.id),
    ]
)
quant.inventory_quantity = quant.quantity
quant._apply_inventory()
delivery = _delivery("ou17-done-lineless", _product("OU17-DONE-LINELESS"), 1)
delivery.move_line_ids.qty_done = 1
delivery.button_validate()
env.flush_all()
env.cr.execute("DELETE FROM stock_move_line WHERE picking_id = %s", (delivery.id,))

view = env.ref("stock.warehouse0").view_location_id


def _to_view(lines):
    # v16 allowed it on a line not done, where it wasn't a reservation
    env.cr.execute(
        "UPDATE stock_move_line SET location_id = %s WHERE id IN %s",
        (view.id, tuple(lines.ids)),
    )
    lines.invalidate_recordset(["location_id"])


# a quantity done on an open line taken from a view, beside an empty line there and
# one whose quantity done is NULL, as a line written by SQL may be
delivery = _delivery("ou17-view", _product("OU17-VIEW"), 1)
delivery.do_unreserve()
for quantity in (1, 0, 0):
    line = _add_done_line(
        delivery, delivery.move_ids.product_id, quantity, delivery.move_ids
    )
    _to_view(line)
env.cr.execute("UPDATE stock_move_line SET qty_done = NULL WHERE id = %s", (line.id,))
# the same on a draft picking, beside a line done from stock
delivery = _delivery("ou17-view-draft", _product("OU17-VIEW-DRAFT"), 2, confirm=False)
_add_done_line(delivery, delivery.move_ids.product_id, 1, delivery.move_ids)
_to_view(_add_done_line(delivery, delivery.move_ids.product_id, 1, delivery.move_ids))
# the same on a move reserved in part from stock
delivery = _delivery("ou17-view-partially", _product("OU17-VIEW-PARTIALLY"), 150)
_to_view(_add_done_line(delivery, delivery.move_ids.product_id, 1, delivery.move_ids))
# a line added by hand to an open picking, so on a move v16 makes for it with no
# demand, taken from a view
delivery = _delivery("ou17-view-added", _product("OU17-VIEW-ADDED-BESIDE"), 1)
delivery.action_assign()
_to_view(_add_done_line(delivery, _product("OU17-VIEW-ADDED"), 1))
# a line of a lot, a package and an owner taken from a view, where the quants of the
# product differ from it in one of the three each
product = _product("OU17-VIEW-LOT", quantity=0, tracking="lot")
lots = env["stock.lot"].create(
    [
        {"name": name, "product_id": product.id, "company_id": view.company_id.id}
        for name in ("OU17-LOT-1", "OU17-LOT-2")
    ]
)
packages = env["stock.quant.package"].create(
    [{"name": name} for name in ("OU17-PACKAGE-1", "OU17-PACKAGE-2")]
)
owners = env["res.partner"].create(
    [{"name": name} for name in ("OU17 Owner 1", "OU17 Owner 2")]
)
delivery = _delivery("ou17-view-lot", product, 1)
_to_view(
    _add_done_line(
        delivery,
        product,
        1,
        delivery.move_ids,
        lot_id=lots[0].id,
        package_id=packages[0].id,
        owner_id=owners[0].id,
    )
)
for lot, package, owner in (
    (lots[1], packages[0], owners[0]),
    (lots[0], packages[1], owners[0]),
    (lots[0], packages[0], owners[1]),
):
    env.cr.execute(
        """
        INSERT INTO stock_quant (
            product_id, location_id, lot_id, package_id, owner_id, company_id,
            quantity, reserved_quantity, in_date, create_uid, create_date, write_uid,
            write_date
        )
        VALUES (%s, %s, %s, %s, %s, %s, 0, 0, now(), 1, now(), 1, now())
        """,
        (product.id, view.id, lot.id, package.id, owner.id, view.company_id.id),
    )
# a consumable's line taken from a view, which reserves nothing on a quant
consumable = env["product.product"].create(
    {
        "name": "OU17-VIEW-CONSUMABLE",
        "default_code": "OU17-VIEW-CONSUMABLE",
        "type": "consu",
    }
)
delivery = _delivery("ou17-view-consumable", consumable, 1)
delivery.do_unreserve()
_to_view(_add_done_line(delivery, consumable, 1, delivery.move_ids))
# a product counted in whole units, whose quantities may still hold a fraction, as
# Odoo rounds them only where it computes them: a demand typed with one, above what
# its line on a view had done by less than the unit's rounding
whole_units = env["uom.uom"].create(
    {
        "name": "OU17 whole units",
        "category_id": env["uom.category"].create({"name": "OU17 whole units"}).id,
        "uom_type": "reference",
        "rounding": 1.0,
    }
)
product = _product("OU17-WHOLE-DEMAND", uom_id=whole_units.id, uom_po_id=whole_units.id)
delivery = _delivery("ou17-view-whole-demand", product, 2.3)
delivery.do_unreserve()
_to_view(_add_done_line(delivery, product, 2, delivery.move_ids))
# an open receipt from the vendors, reserved where reservation is bypassed, so with no
# quant at its source, of a product counted in kilograms, beside a line added by hand
# to it, taken from a view
suppliers = env.ref("stock.stock_location_suppliers")
kilogram = env.ref("uom.product_uom_kgm")
counted = _product("OU17-KILOGRAMS", uom_id=kilogram.id, uom_po_id=kilogram.id)
receipt = env["stock.picking"].create(
    {
        "origin": "ou17-receipt",
        "picking_type_id": env.ref("stock.picking_type_in").id,
        "location_id": suppliers.id,
        "location_dest_id": stock.id,
        "move_ids": [
            (
                0,
                0,
                {
                    "name": counted.name,
                    "product_id": counted.id,
                    "product_uom_qty": 5,
                    "product_uom": kilogram.id,
                    "location_id": suppliers.id,
                    "location_dest_id": stock.id,
                },
            )
        ],
    }
)
receipt.action_confirm()
receipt_move = receipt.move_ids
_to_view(_add_done_line(receipt, _product("OU17-RECEIPT-VIEW-ADDED", quantity=0), 1))
# a delivery in tonnes of that product, waiting for the receipt, with a line of 1 kg
# done beside a line done on a view
tonne = env.ref("uom.product_uom_ton")
delivery = _delivery(
    "ou17-small-waiting",
    counted,
    1,
    uom=tonne,
    move_orig_ids=[(4, receipt_move.id)],
)
_add_done_line(delivery, counted, 1, delivery.move_ids)
_to_view(_add_done_line(delivery, counted, 1, delivery.move_ids))

env.cr.commit()
