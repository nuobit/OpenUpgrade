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


def _product(code):
    product = env["product.product"].create(
        {"name": code, "default_code": code, "type": "product"}
    )
    env["stock.quant"]._update_available_quantity(product, stock, 100)
    return product


def _delivery(origin, products, demand, uom=None):
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
                    },
                )
                for product in products
            ],
        }
    )
    delivery.action_confirm()
    return delivery


def _add_done_line(delivery, product, quantity, move=None):
    # without a move, v16 makes one for the line, with no demand
    return env["stock.move.line"].create(
        {
            "move_id": move and move.id,
            "picking_id": delivery.id,
            "product_id": product.id,
            "product_uom_id": product.uom_id.id,
            "location_id": stock.id,
            "location_dest_id": customers.id,
            "qty_done": quantity,
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
# an inventory applied with no difference, whose move is done with a line of nothing
# done
quant = env["stock.quant"].search(
    [
        ("product_id", "=", _product("OU17-INVENTORY-EQUAL").id),
        ("location_id", "=", stock.id),
    ]
)
quant.inventory_quantity = quant.quantity
quant._apply_inventory()

env.cr.commit()
