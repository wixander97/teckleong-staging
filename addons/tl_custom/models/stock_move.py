# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.


from collections import defaultdict
from datetime import timedelta
from itertools import groupby
from odoo.tools import groupby as groupbyelem
from operator import itemgetter

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.osv import expression
from odoo.tools.float_utils import float_compare, float_is_zero, float_round
from odoo.tools.misc import clean_context, OrderedSet

PROCUREMENT_PRIORITIES = [('0', 'Normal'), ('1', 'Urgent')]


class StockMove(models.Model):
    _inherit = "stock.move"

    electrode_number = fields.Char('Electrode Number')
    notes = fields.Char('Notes')
    is_more_than_demand = fields.Boolean(string='Is More Than Demand', compute='_compute_is_more_than_demand')
    balance_qty = fields.Float('Balance Qty', compute='_compute_balance_qty')
    balance_qty_stored = fields.Float('Balance Qty Stored')
    exchange_item_id = fields.Many2one('stock.move', string='Exchange Item')
    sale_return_moves_ids = fields.Many2many('stock.move', string="Sale Return Moves", compute='_compute_sale_return_moves_ids')

    def name_get(self):
        stock_list = []

        for record in self:
            name = ''

            if record.picking_id:
                name += record.picking_id.name + " - "

            if record.product_id:
                if record.product_id.default_code:
                    name += '[' + record.product_id.default_code + ']'

                name += record.product_id.name

            stock_list.append((record.id, name))

        return stock_list

    @api.model
    def _name_search(self, name, args=None, operator='ilike', limit=100, name_get_uid=None):
        args = args or []
        domain = []
        if name:
            domain = ['|', ('picking_id.name', operator, name), ('product_id.name', operator, name)]
        return self._search(expression.AND([domain, args]), limit=limit, access_rights_uid=name_get_uid)

    def _compute_balance_qty(self):
        for move in self:
            # product = self.env['product.product'].sudo().browse(move.product_id.id)
            # move.balance_qty = product.with_context(warehouse=move.picking_id.picking_type_id.warehouse_id.id).qty_available
            balance_qty = 0

            if move.product_id and len(move.move_line_ids) > 0:
                quants = self.env['stock.quant'].search([('product_id', '=', move.product_id.id), ('location_id', '=', move.move_line_ids[0].location_id.id)])
                move.balance_qty = sum(quant.quantity for quant in quants)

    def _get_new_picking_values(self):
        res = super(StockMove, self)._get_new_picking_values()

        origins = self.filtered(lambda m: m.origin).mapped('origin')
        origins = list(dict.fromkeys(origins)) # create a list of unique items
        # Will display source document if any, when multiple different origins
        # are found display a maximum of 5
        if len(origins) == 0:
            origin = False
        else:
            origin = ','.join(origins[:5])
            if len(origins) > 5:
                origin += "..."
        
        sale = self.env['sale.order'].search([('name', '=', origins)])

        teckleong_stock_type = 'delivery'
        driver = 'driver_a'

        if sale:
            if sale.self_collection_location:
                teckleong_stock_type = 'self_collection'
                driver = False


        res.update({
            'po_ref': sale.po_ref,
            'customer_ref': sale.client_order_ref,
            'teckleong_stock_type': teckleong_stock_type,
            'note': sale.remarks,
            'driver': driver,
        })
        return res

    @api.depends('move_line_ids')
    def _compute_is_more_than_demand(self):
        for move in self:
            total_done_qty = 0

            for line in move.move_line_ids:
                total_done_qty += line.qty_done

            if total_done_qty > move.product_uom_qty:
                move.is_more_than_demand = True
            else:
                move.is_more_than_demand = False

    def _compute_sale_return_moves_ids(self):
        for move in self:
            sale_return_moves_ids = move.env['stock.move']

            if move.sale_line_id:
                for picking in move.sale_line_id.order_id.picking_ids.filtered(lambda x: x.picking_type_code == 'incoming'):
                    sale_return_moves_ids += picking.move_ids_without_package

            move.sale_return_moves_ids = sale_return_moves_ids

class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    custom_order_line_id = fields.Many2one('sale.order.custom.dimension.line', string='Order Line', related='move_id.purchase_line_id.custom_order_line_id')


class StockRule(models.Model):
    _inherit = 'stock.rule'

    def _get_stock_move_values(self, product_id, product_qty, product_uom, location_id, name, origin, company_id, values):
        res = super(StockRule, self)._get_stock_move_values(product_id, product_qty, product_uom, location_id, name, origin, company_id, values)
        res['electrode_number'] = values.get('electrode_number', False)
        res['notes'] = values.get('notes', False)
        res['description_picking'] = values.get('name', False)

        return res