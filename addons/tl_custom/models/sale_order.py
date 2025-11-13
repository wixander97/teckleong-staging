# -*- coding: utf-8 -*-
#################################################################################
# Author      : Webkul Software Pvt. Ltd. (<https://webkul.com/>)
# Copyright(c): 2015-Present Webkul Software Pvt. Ltd.
# License URL : https://store.webkul.com/license.html/
# All Rights Reserved.
#
#
#
# This program is copyright property of the author mentioned above.
# You can`t redistribute it and/or modify it.
#
#
# You should have received a copy of the License along with this program.
# If not, see <https://store.webkul.com/license.html/>
#################################################################################

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError, AccessError
from odoo import SUPERUSER_ID
import re
import time
import json
from datetime import datetime, timedelta, date
from dateutil.parser import parse
import string

import logging
_logger = logging.getLogger(__name__)

class SaleOrder(models.Model):
    _inherit = "sale.order"

    @api.model
    def fields_get(self, fields=None):
        fields_to_hide = ['amount_total']
        res = super(SaleOrder, self).fields_get(fields)

        for field in fields_to_hide:
            if field in res:
                res[field]['searchable'] = False

        return res

    def action_add_csol(self):
        self.custom_dimension_line_ids.create({
            'partner_id': self.partner_id.id,
            'order_ids': self.id,
            'quantity': 1,
            'parent_product_id': 28012,
            'unit_price': 10,
            'is_woocommerce': True
        })

    def action_manual_send_email_quotation_expiry(self):
        self.action_sent_expiry_notification(self)

    def find_expired_quotation(self):
        expiry_date = date.today() + timedelta(days=1)

        sale_obj = self.env['sale.order'];
        sales = sale_obj.search([
            ('validity_date', '=', expiry_date),
            ('state', 'in', ['draft', 'sent']),
        ])

        for data in sales:
            data.action_sent_expiry_notification(data)
            data.state = 'sent'

    def action_sent_expiry_notification(self, data):
        self.ensure_one()
        
        # determine subject and body in the portal user's language
        template = self.env.ref('tl_custom.mail_template_data_tl_quotation_expiration')
        if not template:
            raise UserError(_('The template email not found'))

        lang = self.user_id.sudo().lang
        template.with_context(dbname=self._cr.dbname,lang=lang).send_mail(data.id, force_send=True)

        return True

    @api.model
    def create(self, vals):
        if vals.get('remarks'):
            vals['remarks'] = vals['remarks'].replace("<p>", "<br>")
            vals['remarks'] = vals['remarks'].replace("</p>", "")

            if vals['remarks'][:4] == "<br>":
                vals['remarks'] = vals['remarks'][4:]

        res = super(SaleOrder, self).create(vals)

        return res

    def write(self, vals):
        if vals.get('remarks'):
            vals['remarks'] = vals['remarks'].replace("<p>", "<br>")
            vals['remarks'] = vals['remarks'].replace("</p>", "")

            if vals['remarks'][:4] == "<br>":
                vals['remarks'] = vals['remarks'][4:]

        res = super(SaleOrder, self).write(vals)

        for order in self:
            state = vals['state'] if vals.get('state') else False
            is_woocommerce = vals['is_woocommerce'] if vals.get('is_woocommerce') else order.is_woocommerce

            if is_woocommerce:
                if state == 'sale':

                    if not self.is_confirming:
                        self.is_confirming = True
                        order.action_confirm()
                        self.is_confirming = False

                        invoice = self._create_invoices()
                        invoice.action_post()

                        payment_vals = {
                            'date': date.today(),
                            'payment_type': 'inbound',
                            'partner_type': 'customer',
                            'partner_id': invoice.partner_id.id,
                            'amount': invoice.amount_total,
                            'journal_id': invoice.company_id.woocommerce_journal_id.id,
                            'company_id': invoice.company_id.id,
                            'currency_id': invoice.currency_id.id,
                            'ref': invoice.name,
                        }

                        payment = self.env['account.payment'].with_context(default_invoice_ids=[(4, invoice.id, False)]).create(payment_vals)
                        payment.action_post()
                        receivable_line = payment.line_ids.filtered('credit')
                        invoice.js_assign_outstanding_line(receivable_line.id)

                    if any(expense_policy not in [False, 'no'] for expense_policy in order.order_line.mapped('product_id.expense_policy')):
                        if not order.analytic_account_id:
                            order._create_analytic_account()

                    order.order_line._action_launch_stock_rule()
                    order.order_line.sudo()._purchase_service_generation()

                elif state == 'cancel':
                    inv = order.invoice_ids.filtered(lambda inv: inv.state == 'draft')
                    inv.button_cancel()

                    do = order.picking_ids.filtered(lambda do: do.state in ['draft', 'waiting', 'confirmed', 'ready'])
                    do.action_cancel()

        return res

    @api.returns('self', lambda value: value.id)
    def copy(self, default=None):
        default = dict(default or {})

        default['order_line'] = False
        default['client_order_ref'] = self.client_order_ref
        default['validity_date'] = (datetime.now() + timedelta(days=5))

        return super(SaleOrder, self).copy(default)

    @api.onchange('partner_id')
    def onchange_partner_id(self):

        property_account_position_id = self.partner_id.property_account_position_id if self.partner_id.property_account_position_id else self.partner_id.parent_id.property_account_position_id

        if property_account_position_id:
            for custom_line in self.custom_dimension_line_ids:
                for tax in custom_line.tax_ids:
                    for rec in property_account_position_id.tax_ids:
                        if tax._origin.id == rec.tax_src_id.id:
                            custom_line.tax_ids = [(3, tax.id)]
                            custom_line.tax_ids += rec.tax_dest_id
        else:
            for custom_line in self.custom_dimension_line_ids:
                custom_line.tax_ids = custom_line.parent_product_id.product_tmpl_id.taxes_id

        return super(SaleOrder, self).onchange_partner_id() 

    @api.onchange('validity_date')
    def _validity_date(self):
        for line in self:
            if line.validity_date == False:
               line.validity_date = (datetime.now()+timedelta(days=5))

    @api.model_create_multi
    def create(self,vals):
        for values in vals:
            date = values.get('commitment_date')
            if date == False:
                values['commitment_date'] = (datetime.now()+timedelta(days=5))
        return super(SaleOrder, self).create(vals) 

    @api.onchange('discount_overall')
    def _discount_overall(self):
        if self.order_line:
            for order_lines in self.order_line:
                order_lines.update({
                    'discount_overall':self.discount_overall,
                    })
            for order_lines in self.custom_dimension_line_ids:
                order_lines.update({
                    'discount_overall':self.discount_overall,
                    })

    def action_confirm(self):
        _logger.info("=" * 100)
        _logger.info(f"ACTION CONFIRM STARTED FOR SALE ORDER: {self.name}")
        _logger.info(f"Order Date: {self.date_order}")
        _logger.info(f"Warehouse: {self.warehouse_id.name}")
        _logger.info(f"Custom Dimension Lines: {len(self.custom_dimension_line_ids)}")
        _logger.info("=" * 100)
        
        self.is_confirming = True

        special_chars = string.punctuation
        job_order_line_ids = []
        parent_product_ids = []

        for custom_line in self.custom_dimension_line_ids:
            _logger.info(f"\n>>> Processing Custom Line: {custom_line.description}")
            _logger.info(f"    Parent Product: {custom_line.parent_product_id.name}")
            _logger.info(f"    Quantity: {custom_line.quantity}")
            _logger.info(f"    Width: {custom_line.width}, Length: {custom_line.length}, KG: {custom_line.kg}")
            product_name = custom_line.parent_product_id.name
            product_sku = ''
            
            # Product SKU calculation to find existing products or Create product with that name
            if custom_line.parent_product_id.default_code:
                product_sku = custom_line.parent_product_id.default_code + '-'

            if custom_line.parent_product_id.product_tmpl_id.width != custom_line.width:
                # Product SKU code based on width
                width_code = str(int(round(custom_line.width)))

                if not len(width_code) >= 4:
                    while len(width_code) != 4:
                        width_code = '0' + width_code

                product_name += " x " + str(custom_line.width) + "mm"

                product_sku += width_code     

            if custom_line.parent_product_id.product_tmpl_id.length != custom_line.length:
                # Product SKU code based on length
                length_code = str(int(round(custom_line.length)))

                if not len(length_code) >= 4:
                    while len(length_code) != 4:
                        length_code = '0' + length_code

                product_name += " x " + str(custom_line.length) + "mm"

                product_sku += length_code

            if custom_line.parent_product_id.product_tmpl_id.kg != custom_line.kg:
                # Product SKU code based on weight(KG)
                kg_code = str(int(custom_line.kg * 1000))
                max_len = 4

                if len(str(int(custom_line.kg))) == 2:
                    max_len = 5

                if not len(kg_code) >= max_len:
                    while len(kg_code) != max_len:
                        kg_code = '0' + kg_code

                product_name += " x " + str(custom_line.kg) + "kg"

                product_sku += kg_code 

            product_id = custom_line.parent_product_id.id
            child_roduct = False

            """ Find If product match with required width, length, kg """
            if custom_line.parent_product_id.is_parent_product:
                parent_product_ids.append(custom_line.parent_product_id.id)
                child_roduct = self.env['product.product'].search([
                    ('default_code', '=', product_sku),
                    ('parent_product_id', '=', custom_line.parent_product_id.id),
                    ('width', '=', custom_line.width),
                    ('length', '=', custom_line.length),
                    ('kg', '=', custom_line.kg),
                ], limit=1)
            else:
                parent_product_ids.append(custom_line.parent_product_id.parent_product_id.id)
                child_roduct = custom_line.parent_product_id         
                
            """ if product not found then it will create new product with that width, length and kg """
            if child_roduct:
                product = child_roduct
            else : 
                product = self.env['product.product'].create({
                    'name': product_name,
                    'default_code': product_sku,
                    
                    'diameter': custom_line.diameter,
                    'width': custom_line.width,
                    'thickness': custom_line.thickness,
                    'length': custom_line.length,
                    'kg': custom_line.kg,
                    'across_flat': custom_line.across_flat,
                    'mesh_number': custom_line.mesh_number,
                    'mesh_size': custom_line.mesh_size,
                    'hole_diameter': custom_line.hole_diameter,
                    'width_2': custom_line.width_2,
                    'pitch': custom_line.pitch,
                    'inner_diameter': custom_line.inner_diameter,

                    'dimension_uom_id': custom_line.dimension_uom_id.id,
                    'parent_product_id': custom_line.parent_product_id.id,
                    'uom_id': custom_line.product_uom_id.id,
                    'uom_po_id': custom_line.product_uom_id.id,
                    'detailed_type': 'product',
                    'tracking': 'lot',
                    'categ_id': custom_line.parent_product_id.categ_id.id,
                })
                
            """ prepare job order line for job order of required SO with above created or selected product """
            if custom_line.quantity > 0 and custom_line.parent_product_id.type == 'product':
                job_order_line_ids.append((0, 0, {
                    'requested_width': custom_line.width,
                    'requested_length': custom_line.length,
                    'requested_thickness': custom_line.thickness,
                    'requested_diameter': custom_line.diameter,
                    'requested_kg': custom_line.kg,
                    'requested_across_flat': custom_line.across_flat ,
                    'requested_mesh_number': custom_line.mesh_number ,
                    'requested_mesh_size': custom_line.mesh_size ,
                    'requested_hole_diameter': custom_line.hole_diameter ,
                    'requested_width_2': custom_line.width_2 ,
                    'requested_pitch': custom_line.pitch ,
                    'requested_inner_diameter': custom_line.inner_diameter,
                    'product_uom_id': custom_line.product_uom_id.id,
                    'quantity': custom_line.quantity,
                    'product_id': product.id,
                    'receipt_location_id': self.warehouse_id.lot_stock_id.id,
                    'electrode_number': custom_line.electrode_number,
                    'custom_order_line_id': custom_line.id,
                }))

            record_exist = False
            note_exist = False

            ''' prepare sale.order.line if found order line then reflect quantity, unit price, electrode number
            in that order line and if note exists in dimention line then it will add in sale order line '''
            for sale_order_line in self.order_line:
                if sale_order_line.custom_order_line_id == custom_line:
                    if sale_order_line.display_type == '' or not sale_order_line.display_type:
                        record_exist = True
                        sale_order_line.product_uom_qty = custom_line.quantity
                        sale_order_line.price_unit = custom_line.unit_price
                        sale_order_line.electrode_number = custom_line.electrode_number

                        sale_order_line.write({
                            'product_id': product.id,
                            'name': custom_line.description,
                            'product_uom_qty': custom_line.quantity,
                            'price_unit': custom_line.unit_price,
                            'tax_id': custom_line.tax_ids._ids,
                            'discount': custom_line.discount,
                            'discount_overall': self.discount_overall,
                            'product_uom': custom_line.product_uom_id.id,
                            'electrode_number': custom_line.electrode_number,
                        })

                    elif sale_order_line.display_type == 'line_note':
                        note_exist = True
                        sale_order_line.name = custom_line.notes

            ''' if order line doesn't exist then it will create new order line with notes also 
            most of time it will not exist in SO due to cutting flow '''
            if not record_exist:
                self.order_line.create({
                    'product_id': product.id,
                    'name': custom_line.description,
                    'product_uom_qty': custom_line.quantity,
                    'price_unit': custom_line.unit_price,
                    'tax_id': custom_line.tax_ids._ids,
                    'discount': custom_line.discount,
                    'discount_overall': self.discount_overall,
                    'order_id': self.id,
                    'product_uom': custom_line.product_uom_id.id,
                    'electrode_number': custom_line.electrode_number,
                    'custom_order_line_id': custom_line.id,
                    'notes': custom_line.notes,
                }) 

            if not note_exist and custom_line.notes:
                self.order_line.create({
                    'display_type': 'line_note',
                    'order_id': self.id,
                    'name': custom_line.notes,
                    'custom_order_line_id': custom_line.id,
                })   
                        
        job_order = False

        ''' if found dimention line then create job order with that lines '''
        _logger.info(f"\n{'='*80}")
        _logger.info(f"JOB ORDER LINE IDS TO CREATE: {len(job_order_line_ids)}")
        _logger.info(f"PARENT PRODUCT IDS: {parent_product_ids}")
        
        if len(job_order_line_ids) > 0 : 
            job_order = self.env['job.order'].create({
                'sale_order_id': self.id,
                'job_order_line_ids': job_order_line_ids,
                'location_id': self.warehouse_id.id,
                'datetime': self.date_order,
            })
            _logger.info(f"✓ Job Order Created: {job_order.name}")

        if job_order:
            _logger.info(f"\n{'='*80}")
            _logger.info(f"STARTING STOCK ALLOCATION PROCESS")
            _logger.info(f"Job Order: {job_order.name}")
            _logger.info(f"Job Order Lines: {len(job_order.job_order_line_ids)}")
            
            job_order_cutting_ids = []
            stocks = []

            ''' Get all child products of selected product with available quantities '''
            product_arr = self.env['product.product'].search([
                ('parent_product_id', 'in', parent_product_ids),
                ('qty_available', '>', 0)
            ])
            _logger.info(f"Found {len(product_arr)} child products with available quantities")

            if product_arr:
                ''' Get all on hand(available) stock quants of above child products and append to stocks[] list '''
                stock_quant = self.env['stock.quant'].search([
                    ('product_id', 'in', product_arr._ids),
                    ('quantity', '>', 0),
                    ('on_hand', '=', True),
                ])
                _logger.info(f"Found {len(stock_quant)} stock quants with on-hand quantity")

                ''' Add all on hand stock quantity to "stocks" list '''
                for stock in stock_quant:
                    stocks.append({
                        'id': stock.id,
                        'quantity': stock.quantity,
                        'warehouse_id': stock.location_id.warehouse_id.id,
                        'product': stock.product_id.id,
                        'parent_product': stock.product_id.parent_product_id.id,
                        'lot_name': stock.lot_id.name,
                        'product_length': round(stock.product_id.product_tmpl_id.length, 2),
                        'product_width': round(stock.product_id.product_tmpl_id.width, 2),
                        'product_kg': round(stock.product_id.product_tmpl_id.kg, 2),

                        'lot_name_check': ''.join(e for e in stock.lot_id.name if e.isalnum()),
                    })
                    _logger.info(f"  Stock: {stock.product_id.name} | Qty: {stock.quantity} | "
                               f"Length: {round(stock.product_id.product_tmpl_id.length, 2)}mm | "
                               f"Width: {round(stock.product_id.product_tmpl_id.width, 2)}mm | "
                               f"Lot: {stock.lot_id.name}")
                
                _logger.info(f"\n{'='*80}")
                _logger.info(f"TOTAL STOCKS LOADED: {len(stocks)}")
                _logger.info(f"{'='*80}\n")

                for idx, line in enumerate(job_order.job_order_line_ids):
                    _logger.info(f"\n{'#'*80}")
                    _logger.info(f"PROCESSING JOB ORDER LINE {idx + 1}/{len(job_order.job_order_line_ids)}")
                    _logger.info(f"Product: {line.product_id.name}")
                    _logger.info(f"Parent Product: {line.product_id.parent_product_id.name}")
                    _logger.info(f"Requested: Width={line.requested_width}, Length={line.requested_length}, Qty={line.quantity}")
                    _logger.info(f"is_have_width: {line.is_have_width}, is_have_length: {line.is_have_length}")
                    _logger.info(f"Parent Width: {line.parent_product_id.product_tmpl_id.width}, Parent Length: {line.parent_product_id.product_tmpl_id.length}")
                    _logger.info(f"{'#'*80}")
                    
                    lot = []

                    ''' if any purchase move line of SO then it will add lot name to lot[] list
                    most of time it will not exist in SO due to cutting flow '''
                    for pml in self.purchase_move_line_ids:
                        if pml.custom_order_line_id == line.custom_order_line_id:
                            lot.append(pml.lot_name)

                    if not line.product_id.is_parent_product and line.product_id.parent_product_id == line.product_id:
                        """
                            If selected width/length product is not parent product
                            and selected width/length product and its parent product is same
                            - line.product_id : Newly cutted product or exsting cutted product
                        """
                        '''  '''
                        done_quantity = 0

                        fil_stocks = list(filter(lambda x: x['parent_product'] == line.product_id.parent_product_id.id , stocks))

                        while done_quantity != line.quantity and len(fil_stocks) > 0:
                            fil_stocks = list(filter(lambda x: x['parent_product'] == line.product_id.parent_product_id.id and x['lot_name'] in lot and x['quantity'] > 0 , stocks))


                            if len(fil_stocks) == 0:
                                fil_stocks = list(filter(lambda x: x['parent_product'] == line.product_id.parent_product_id.id and x['quantity'] > 0 , stocks))

                                stock_alpha = sorted([x for x in fil_stocks if x['lot_name_check'].isalpha()], key=lambda x: (x['lot_name_check'], x['quantity']))
                                stock_alnum = sorted([x for x in fil_stocks if x['lot_name_check'].isalnum() and not x['lot_name_check'].isalpha() and not x['lot_name_check'].isnumeric()], key=lambda x: (x['lot_name_check'], x['quantity']))

                                stock_alnum_start = sorted([x for x in stock_alnum if x['lot_name_check'][0].isalpha() and not x['lot_name_check'][-1].isalpha()], key=lambda x: (x['lot_name_check'], x['quantity']))
                                stock_alnum_end = sorted([x for x in stock_alnum if not x['lot_name_check'][0].isalpha() and x['lot_name_check'][-1].isalpha()], key=lambda x: (x['lot_name_check'], x['quantity']))
                                
                                stock_num = sorted([x for x in fil_stocks if x['lot_name_check'].isnumeric()], key=lambda x: (x['lot_name_check'], x['quantity'])) 

                                for x in stock_num:
                                    x['lot_name_check'] = int(x['lot_name_check'])

                                stock_num = sorted(stock_num, key=lambda x: x['lot_name_check'])

                                for x in stock_num:
                                    x['lot_name_check'] = str(x['lot_name_check'])

                                fil_stocks = stock_alpha + stock_alnum_start + stock_num + stock_alnum_end

                            if not fil_stocks:
                                continue

                            # for x in fil_stocks:
                            #     x['lot_name'] = str(x['lot_name'])

                            selected_stock = fil_stocks[0]
                            quantity = 0

                            if selected_stock['quantity'] >= line.quantity - done_quantity:
                                quantity = line.quantity - done_quantity
                                done_quantity = line.quantity
                                list(filter(lambda x: x['id'] == selected_stock['id'], stocks))[0]['quantity'] -= quantity
                            else:
                                quantity = selected_stock['quantity']
                                done_quantity += selected_stock['quantity']
                                list(filter(lambda x: x['id'] == selected_stock['id'], stocks))[0]['quantity'] = 0

                            product = self.env['product.product'].browse(selected_stock['product'])

                            job_order_cutting_ids.append({
                                'job_order_id_char': int(job_order.id),
                                'job_order_line_id': line.id,
                                'stock_quantity_id': selected_stock['id'],
                                'done_quantity': quantity,
                                'warehouse_id': selected_stock['warehouse_id'],

                                'length_balance': 0,
                                'width_balance': 0,
                                'diameter_balance': 0,
                                'thickness_balance': 0,
                                'kg_balance': 0,
                                'across_flat_balance': 0,
                                'mesh_number_balance': 0,
                                'mesh_size_balance': 0,
                                'hole_diameter_balance': 0,
                                'width_2_balance': 0,
                                'pitch_balance': 0,
                                'inner_diameter_balance': 0,
                            })

                            if selected_stock['lot_name'] and quantity > 0:
                                if not line.custom_order_line_id.batch_number:
                                    line.custom_order_line_id.batch_number = selected_stock['lot_name'] + ';'
                                else:
                                    if not line.custom_order_line_id.batch_number.find(selected_stock['lot_name']) != -1:
                                        line.custom_order_line_id.batch_number += selected_stock['lot_name'] + ';'


                    ''' 2D when requested product have both length and width '''
                    # IMPORTANT: Only process in Case 2D if BOTH parent width AND parent length are 0
                    # If parent has width but no length (or vice versa), it should go to Case Length/Width instead
                    if line.is_have_width and line.is_have_length and not line.product_id.is_parent_product and line.product_id.parent_product_id != line.product_id and line.parent_product_id.product_tmpl_id.width == 0 and line.parent_product_id.product_tmpl_id.length == 0:
                        ''' if selected width/length product have width and length and width/length of its parent product is 0 '''
                        _logger.info("=" * 80)
                        _logger.info(f"ENTERING CASE 2D (WIDTH + LENGTH)")
                        _logger.info(f"Product: {line.product_id.name}")
                        _logger.info(f"Parent Product: {line.parent_product_id.name}")
                        _logger.info(f"Requested Width: {line.requested_width}mm, Length: {line.requested_length}mm")
                        _logger.info(f"Quantity Needed: {line.quantity} pieces")
                        
                        fil_stocks = list(filter(lambda x: x['parent_product'] == line.product_id.parent_product_id.id , stocks))
                        _logger.info(f"Filtered Stocks (same parent): {len(fil_stocks)} stocks available")
                        
                        lowest = round(line.requested_width, 2)
                        highest = round(line.requested_length, 2)

                        if line.requested_length < line.requested_width:
                            lowest = round(line.requested_length, 2)
                            highest = round(line.requested_width, 2)

                        _logger.info(f"Lowest dimension: {lowest}mm, Highest dimension: {highest}mm")
                        
                        lowest_sum = lowest * line.quantity
                        _logger.info(f"Total Lowest Sum: {lowest_sum}mm")

                        quantity_done = 0

                        while quantity_done < line.quantity and len(fil_stocks) > 0:
                            _logger.info(f"\n--- 2D ITERATION START (Qty Done: {quantity_done}/{line.quantity}) ---")
                            fil_stocks = list(filter(lambda x: x['parent_product'] == line.product_id.parent_product_id.id and x['quantity'] > 0 , stocks))
                            
                            if len(list(filter(lambda x: x['parent_product'] == line.product_id.parent_product_id.id and x['quantity'] > 0 and x['lot_name'] in lot , stocks))) > 0:
                                fil_stocks = list(filter(lambda x: x['parent_product'] == line.product_id.parent_product_id.id and x['quantity'] > 0 and x['lot_name'] in lot , stocks))
                                
                                # FIX: Apply exact match check to lot-filtered stocks too!
                                fit_stocks = sorted(list(filter(lambda x:(round(x['product_length'], 2) == round(line.requested_length, 2) and round(x['product_width'], 2) == round(line.requested_width, 2)), fil_stocks)), key=lambda x:x['id']) + sorted(list(filter(lambda x:(round(x['product_length'], 2) == round(line.requested_width, 2) and round(x['product_width'], 2) == round(line.requested_length, 2)), fil_stocks)), key=lambda x:x['id'])
                                
                                if len(fit_stocks) > 0:
                                    # Use exact match stocks
                                    fil_stocks = fit_stocks
                            
                            # PRIORITY 1: EXACT MATCH - Width and Length match exactly
                            # FIX: Use rounding to avoid floating point comparison issues
                            fit_stocks = sorted(list(filter(lambda x:(round(x['product_length'], 2) == round(line.requested_length, 2) and round(x['product_width'], 2) == round(line.requested_width, 2)), fil_stocks)), key=lambda x:x['id']) + sorted(list(filter(lambda x:(round(x['product_length'], 2) == round(line.requested_width, 2) and round(x['product_width'], 2) == round(line.requested_length, 2)), fil_stocks)), key=lambda x:x['id'])
                            
                            if len(fit_stocks) > 0:
                                fit_stock_alpha = sorted([x for x in fit_stocks if x['lot_name_check'].isalpha()], key=lambda x: (x['lot_name_check'], x['quantity'])) 
                                fit_stock_alnum = sorted([x for x in fit_stocks if x['lot_name_check'].isalnum() and not x['lot_name_check'].isalpha() and not x['lot_name_check'].isnumeric()], key=lambda x: (x['lot_name_check'], x['quantity'])) 
                                
                                fit_stock_alnum_start = sorted([x for x in fit_stock_alnum if x['lot_name_check'][0].isalpha() and not x['lot_name_check'][-1].isalpha()], key=lambda x: x['lot_name_check'])
                                fit_stock_alnum_end = sorted([x for x in fit_stock_alnum if not x['lot_name_check'][0].isalpha() and x['lot_name_check'][-1].isalpha()], key=lambda x: x['lot_name_check'])

                                fit_stock_num = sorted([x for x in fit_stocks if x['lot_name_check'].isnumeric()], key=lambda x: (x['lot_name_check'], x['quantity'])) 

                                for x in fit_stock_num:
                                    x['lot_name_check'] = int(x['lot_name_check'])

                                fit_stock_num = sorted(fit_stock_num, key=lambda x: x['lot_name_check'])

                                for x in fit_stock_num:
                                    x['lot_name_check'] = str(x['lot_name_check'])

                                fit_stocks = fit_stock_alpha + fit_stock_alnum_start + fit_stock_num + fit_stock_alnum_end

                            # PRIORITY 2: LARGER DIMENSIONS - but only reasonable sizes
                            # Strategy: Prefer stocks with minimal waste, prioritize one dimension matching
                            
                            reasonable_stocks = []
                            rejected_stocks = []  # Track rejected stocks for debugging
                            for stock in fil_stocks:
                                stock_w = round(stock['product_width'], 2)
                                stock_l = round(stock['product_length'], 2)
                                req_w = round(line.requested_width, 2)
                                req_l = round(line.requested_length, 2)
                                
                                rejection_reason = None  # Track why this stock was rejected
                                
                                # Check if stock can cut the requested dimension
                                # Case 1: stock_w >= req_w AND stock_l >= req_l
                                if stock_w >= req_w and stock_l >= req_l:
                                    width_waste = round(stock_w - req_w, 2)
                                    length_waste = round(stock_l - req_l, 2)
                                    total_waste = round(width_waste + length_waste, 2)
                                    
                                    # 4-Level Priority System (Gradual Relaxation):
                                    # Priority 1: Exact match - one dimension has almost no waste (<0.01mm)
                                    # Priority 2: Optimal - both dimensions within 50% waste
                                    # Priority 3: Acceptable - at least one dimension within 50% waste
                                    # Priority 4: Fallback - any stock that can fit (no waste limit)
                                    priority = 0
                                    if width_waste < 0.01 or length_waste < 0.01:
                                        priority = 1  # Exact match
                                    elif width_waste <= req_w * 0.5 and length_waste <= req_l * 0.5:
                                        priority = 2  # Both within 50%
                                    elif width_waste <= req_w * 0.5 or length_waste <= req_l * 0.5:
                                        priority = 3  # At least one within 50% (changed from 30% to 50%)
                                    else:
                                        priority = 4  # Fallback - stock can fit but high waste
                                    
                                    reasonable_stocks.append({
                                        **stock,
                                        'priority': priority,
                                        'total_waste': total_waste,
                                        'width_waste': width_waste,
                                        'length_waste': length_waste
                                    })
                                
                                # Case 2: stock_w >= req_l AND stock_l >= req_w (rotated)
                                elif stock_w >= req_l and stock_l >= req_w:
                                    width_waste = round(stock_w - req_l, 2)
                                    length_waste = round(stock_l - req_w, 2)
                                    total_waste = round(width_waste + length_waste, 2)
                                    
                                    # Same 4-level priority for rotated orientation
                                    priority = 0
                                    if width_waste < 0.01 or length_waste < 0.01:
                                        priority = 1  # Exact match
                                    elif width_waste <= req_l * 0.5 and length_waste <= req_w * 0.5:
                                        priority = 2  # Both within 50%
                                    elif width_waste <= req_l * 0.5 or length_waste <= req_w * 0.5:
                                        priority = 3  # At least one within 50%
                                    else:
                                        priority = 4  # Fallback
                                    
                                    reasonable_stocks.append({
                                        **stock,
                                        'priority': priority,
                                        'total_waste': total_waste,
                                        'width_waste': width_waste,
                                        'length_waste': length_waste
                                    })
                                else:
                                    # Stock too small for both orientations
                                    rejection_reason = f"TOO SMALL: {stock_w:.1f}x{stock_l:.1f} cannot fit {req_w:.1f}x{req_l:.1f} in any orientation"
                                
                                # Track rejected stocks
                                if rejection_reason:
                                    rejected_stocks.append({
                                        'product': stock['product'],
                                        'width': stock_w,
                                        'length': stock_l,
                                        'qty': stock['quantity'],
                                        'reason': rejection_reason
                                    })
                            
                            # Sort by: priority first (lower=better), then total waste (smaller=better)
                            each_stock = sorted(reasonable_stocks, key=lambda x: (x['priority'], x['total_waste'], x['product_length'] * x['product_width'], x['id']))
                            
                            # Summary by priority level
                            priority_summary = {}
                            for stock in each_stock:
                                p = stock.get('priority', 0)
                                priority_summary[p] = priority_summary.get(p, 0) + 1
                            
                            # Combine: EXACT MATCH first, then reasonable larger stocks
                            fil_stocks = fit_stocks + each_stock
                            fil_stocks_filter = []

                            if not fil_stocks:
                                continue

                            for fil_stock in fil_stocks:
                                if fil_stock not in fil_stocks_filter:
                                    fil_stocks_filter.append(fil_stock)

                            fil_stocks = fil_stocks_filter
                            
                            selected_stock = fil_stocks[0]
                            done_quantity = 0

                            length_1_balance = 0
                            width_1_balance = 0
                            length_2_balance = 0
                            width_2_balance = 0

                            if line.requested_length == selected_stock['product_length'] and line.requested_width == selected_stock['product_width']:
                                if selected_stock['quantity'] >= line.quantity:
                                    done_quantity += line.quantity - quantity_done
                                    list(filter(lambda x: x['id'] == selected_stock['id'], stocks))[0]['quantity'] -= line.quantity
                                    lowest_sum = 0
                                    quantity_done = line.quantity

                                else:
                                    done_quantity += selected_stock['quantity']
                                    list(filter(lambda x: x['id'] == selected_stock['id'], stocks))[0]['quantity'] -= line.quantity
                                    lowest_sum -= (done_quantity * lowest)
                                    quantity_done += done_quantity

                            else:
                                list(filter(lambda x: x['id'] == selected_stock['id'], stocks))[0]['quantity'] -= 1
                                stock_lowest = selected_stock['product_length']
                                stock_highest = selected_stock['product_width']

                                if selected_stock['product_length'] > selected_stock['product_width']:
                                    stock_lowest = selected_stock['product_width']
                                    stock_highest = selected_stock['product_length']

                                if (selected_stock['product_width'] >= line.requested_width * (line.quantity - quantity_done) and selected_stock['product_length'] > line.requested_length) or (selected_stock['product_length'] >= line.requested_width * (line.quantity - quantity_done) and selected_stock['product_width'] > line.requested_length):
                                    lowest_sum = line.requested_width * (line.quantity - quantity_done)
                                    lowest = line.requested_width
                                    highest = line.requested_length

                                elif (selected_stock['product_length'] >= line.requested_length * (line.quantity - quantity_done) and selected_stock['product_width'] > line.requested_width) or (selected_stock['product_width'] >= line.requested_length * (line.quantity - quantity_done) and selected_stock['product_length'] > line.requested_width):
                                    lowest_sum = line.requested_length * (line.quantity - quantity_done)
                                    lowest = line.requested_length
                                    highest = line.requested_width

                                lowest_done = 0

                                if stock_highest >= lowest and stock_lowest >= highest:
                                    while(stock_highest >= lowest and stock_lowest >= highest and quantity_done < line.quantity):
                                        stock_highest -= round(lowest, 2)
                                        stock_highest = round(stock_highest, 2)
                                        done_quantity += 1
                                        lowest_sum -= lowest
                                        quantity_done += 1

                                    lowest_done = lowest * done_quantity

                                elif stock_highest >= highest and stock_lowest >= lowest:
                                    while(stock_highest >= highest and stock_lowest >= lowest and quantity_done < line.quantity):
                                        stock_lowest -= round(lowest, 2)
                                        stock_lowest = round(stock_lowest, 2)
                                        done_quantity += 1
                                        lowest_sum -= lowest
                                        quantity_done += 1

                                    lowest_done = lowest * done_quantity

                                if selected_stock['product_width'] == lowest_done and selected_stock['product_length'] >= highest:
                                    length_1_balance = selected_stock['product_length'] - highest
                                    width_1_balance = selected_stock['product_width']

                                    length_2_balance =  selected_stock['product_length']
                                    width_2_balance = 0

                                elif selected_stock['product_length'] == lowest_done and selected_stock['product_width'] >= highest:
                                    length_1_balance = selected_stock['product_length'] 
                                    width_1_balance = selected_stock['product_width'] - highest

                                    length_2_balance =  0
                                    width_2_balance = selected_stock['product_width']

                                elif selected_stock['product_width'] == highest and selected_stock['product_length'] >= lowest_done:
                                    length_1_balance = selected_stock['product_length'] - lowest_done
                                    width_1_balance = selected_stock['product_width']

                                    length_2_balance =  selected_stock['product_length']
                                    width_2_balance = 0

                                elif selected_stock['product_length'] == highest and selected_stock['product_width'] >= lowest_done:
                                    length_1_balance = selected_stock['product_length'] 
                                    width_1_balance = selected_stock['product_width'] - lowest_done

                                    length_2_balance =  0
                                    width_2_balance = selected_stock['product_width']

                                elif (selected_stock['product_width'] >= lowest_done and selected_stock['product_length'] >= highest):
                                    length_1_balance = selected_stock['product_length'] - highest
                                    width_1_balance = selected_stock['product_width']

                                    length_2_balance =  selected_stock['product_length'] - (selected_stock['product_length'] - highest)
                                    width_2_balance = selected_stock['product_width'] - lowest_done

                                elif (selected_stock['product_length'] >= lowest_done and selected_stock['product_width'] >= highest):
                                    length_1_balance = selected_stock['product_length']
                                    width_1_balance = selected_stock['product_width'] - highest

                                    length_2_balance =  selected_stock['product_length'] - lowest_done
                                    width_2_balance = selected_stock['product_width'] - (selected_stock['product_width'] - highest)

                            if done_quantity > 0:
                                product = self.env['product.product'].browse(selected_stock['product'])

                                job_order_cutting_ids.append({
                                    'job_order_id_char': int(job_order.id),
                                    'job_order_line_id': line.id,
                                    'stock_quantity_id': selected_stock['id'],
                                    'done_quantity': done_quantity,
                                    'warehouse_id': selected_stock['warehouse_id'],

                                    'length_balance': length_1_balance if length_1_balance > width_1_balance else width_1_balance,
                                    'width_balance': width_1_balance if width_1_balance < length_1_balance else length_1_balance,
                                    'diameter_balance': product.diameter,
                                    'thickness_balance': product.thickness,
                                    'kg_balance': product.kg,
                                    'across_flat_balance': product.across_flat ,
                                    'mesh_number_balance': product.mesh_number ,
                                    'mesh_size_balance': product.mesh_size ,
                                    'hole_diameter_balance': product.hole_diameter ,
                                    'width_2_balance': product.width_2 ,
                                    'pitch_balance': product.pitch ,
                                    'inner_diameter_balance': product.inner_diameter,
                                    'length_balance_2': length_2_balance if length_2_balance > width_2_balance else width_2_balance,
                                    'width_balance_2': width_2_balance if width_2_balance < length_2_balance else length_2_balance,
                                })

                                if selected_stock['lot_name'] and done_quantity > 0:
                                    if not line.custom_order_line_id.batch_number:
                                        line.custom_order_line_id.batch_number = selected_stock['lot_name'] + ';'
                                    else:
                                        if not line.custom_order_line_id.batch_number.find(selected_stock['lot_name']) != -1:
                                            line.custom_order_line_id.batch_number += selected_stock['lot_name'] + ';'


                    else:
                        if line.is_have_length and line.parent_product_id.product_tmpl_id.length == 0:
                            ''' if selected product have only length and length of its parent product is 0 i.e Iron Rod '''
                            _logger.info("=" * 80)
                            _logger.info(f"ENTERING CASE LENGTH")
                            _logger.info(f"Product: {line.product_id.name}")
                            _logger.info(f"Parent Product: {line.parent_product_id.name}")
                            _logger.info(f"Requested Length: {line.requested_length}mm")
                            _logger.info(f"Quantity Needed: {line.quantity} pieces")
                            
                            length_sum = line.requested_length * line.quantity
                            _logger.info(f"Total Length Sum: {length_sum}mm")

                            ''' filter out stocks with product where parent product of selected
                            product is same as parent product of stock product '''
                            fil_stocks = list(filter(lambda x: x['parent_product'] == line.product_id.parent_product_id.id , stocks))
                            _logger.info(f"Filtered Stocks (same parent): {len(fil_stocks)} stocks available")

                            quantity_done = 0

                            while length_sum > 0 and len(fil_stocks) > 0:
                                _logger.info(f"\n--- ITERATION START (Qty Done: {quantity_done}, Length Sum: {length_sum}mm) ---")
                                fil_stocks = list(filter(lambda x: x['parent_product'] == line.product_id.parent_product_id.id and x['quantity'] > 0, stocks))
                                _logger.info(f"Available stocks with quantity > 0: {len(fil_stocks)}")

                                if len(list(filter(lambda x: x['parent_product'] == line.product_id.parent_product_id.id and x['quantity'] > 0 and x['lot_name'] in lot, stocks))) > 0:
                                    fil_stocks = list(filter(lambda x: x['parent_product'] == line.product_id.parent_product_id.id and x['quantity'] > 0 and x['lot_name'] in lot, stocks))
                                    _logger.info(f"Using LOT-FILTERED stocks: {len(fil_stocks)} stocks with lot in {lot}")
                                else:
                                    _logger.info(f"No lot filter applied, checking for exact match...")
                                    fit_stocks = sorted(list(filter(lambda x: x['product_length'] == line.requested_length, fil_stocks)), key=lambda x: x['id'])
                                    _logger.info(f"Exact match stocks (length={line.requested_length}mm): {len(fit_stocks)} found")

                                    if fit_stocks:
                                        ''' if requested length found in stock '''
                                        fit_stock_alpha = sorted([x for x in fit_stocks if x['lot_name_check'].isalpha()], key=lambda x: (x['lot_name_check'], x['quantity'])) 
                                        fit_stock_alnum = sorted([x for x in fit_stocks if x['lot_name_check'].isalnum() and not x['lot_name_check'].isalpha() and not x['lot_name_check'].isnumeric()], key=lambda x: (x['lot_name_check'], x['quantity'])) 

                                        fit_stock_alnum_start = sorted([x for x in fit_stock_alnum if x['lot_name_check'][0].isalpha() and not x['lot_name_check'][-1].isalpha()], key=lambda x: x['lot_name_check'])
                                        fit_stock_alnum_end = sorted([x for x in fit_stock_alnum if not x['lot_name_check'][0].isalpha() and x['lot_name_check'][-1].isalpha()], key=lambda x: x['lot_name_check'])

                                        fit_stock_num = sorted([x for x in fit_stocks if x['lot_name_check'].isnumeric()], key=lambda x: (x['lot_name_check'], x['quantity'])) 

                                        for x in fit_stock_num:
                                            x['lot_name_check'] = int(x['lot_name_check'])

                                        fit_stock_num = sorted(fit_stock_num, key=lambda x: x['lot_name_check'])

                                        for x in fit_stock_num:
                                            x['lot_name_check'] = str(x['lot_name_check'])

                                        fit_stocks = fit_stock_alpha + fit_stock_alnum_start + fit_stock_num + fit_stock_alnum_end 

                                    ''' stock with product whose length is more than request length; sorted with product length
                                    due to unavailability of proper request length product in stock '''
                                    larger_stocks_raw = list(filter(lambda x: (x['product_length'] > line.requested_length), fil_stocks))
                                    
                                    # Sort by: pieces per stock (DESC), then length (ASC), then id
                                    # Priority: stock that yields MORE pieces should be used first
                                    larger_stocks = sorted(larger_stocks_raw, key=lambda x: (-int(x['product_length'] / line.requested_length), x['product_length'], x['id']))
                                    
                                    _logger.info(f"Larger stocks (length > {line.requested_length}mm): {len(larger_stocks)} found")
                                    if larger_stocks:
                                        for ls in larger_stocks:
                                            pieces_yield = int(ls['product_length'] / line.requested_length)
                                            _logger.info(f"  - {ls['product_length']}mm (qty: {ls['quantity']}) → yields {pieces_yield} pieces/stock")
                                    
                                    fil_stocks = fit_stocks + larger_stocks
                                    
                                if not fil_stocks:
                                    _logger.warning("No suitable stocks found! Breaking loop.")
                                    continue

                                # select first sorted length product
                                selected_stock = fil_stocks[0]
                                # select length of first sorted length product
                                selected_stock_length = fil_stocks[0]['product_length']
                                # FIX: must be here before ANY use of pieces_per_stock
                                product = self.env['product.product'].browse(selected_stock['product'])
                                pieces_per_stock = product.pieces_per_stock or 0

                                _logger.info(f"SELECTED STOCK:")
                                _logger.info(f"  Stock ID: {selected_stock['id']}")
                                _logger.info(f"  Stock Length: {selected_stock_length}mm")
                                _logger.info(f"  Available Quantity: {selected_stock['quantity']} stocks")
                                _logger.info(f"  Lot Name: {selected_stock.get('lot_name', 'N/A')}")
                                
                                # Track how many stocks we need to consume for this cutting operation
                                stocks_to_consume = 0
                                # Track total pieces cut from all stocks
                                total_pieces_cut = 0

                                if selected_stock_length == line.requested_length:
                                    _logger.info(f"→ EXACT MATCH: Stock length equals requested length")
                                    ''' stock quantity match with selected quantity '''
                                    if selected_stock['quantity'] >= line.quantity:
                                        stocks_to_consume = line.quantity - quantity_done
                                        _logger.info(f"  Sufficient stock: consuming {stocks_to_consume} stocks")
                                        list(filter(lambda x: x['id'] == selected_stock['id'], stocks))[0]['quantity'] -= stocks_to_consume
                                        length_sum = 0
                                        quantity_done = line.quantity
                                        total_pieces_cut = stocks_to_consume

                                    else:
                                        stocks_to_consume = selected_stock['quantity']
                                        _logger.info(f"  Insufficient stock: consuming all {stocks_to_consume} stocks")
                                        list(filter(lambda x: x['id'] == selected_stock['id'], stocks))[0]['quantity'] = 0
                                        length_sum -= (stocks_to_consume * line.requested_length)
                                        quantity_done += stocks_to_consume
                                        total_pieces_cut = stocks_to_consume

                                    selected_stock_length = 0
                                    _logger.info(f"  Total pieces cut: {total_pieces_cut}, Quantity done: {quantity_done}")

                                else:
                                    _logger.info(f"→ NEED TO CUT: Stock length > requested length")
                                    ''' stock quantity doesn't match with selected quantity - need to cut multiple pieces from stock '''
                                    # Calculate how many pieces can be cut from ONE stock
                                    pieces_per_stock = int(selected_stock_length / line.requested_length)
                                    
                                    # Calculate how many pieces we still need
                                    pieces_needed = int(length_sum / line.requested_length)
                                    if length_sum % line.requested_length > 0:
                                        pieces_needed += 1
                                    
                                    _logger.info("=" * 80)
                                    _logger.info(f"CASE LENGTH - CUTTING CALCULATION")
                                    _logger.info(f"Product: {line.product_id.name}")
                                    _logger.info(f"Stock Length: {selected_stock_length}mm")
                                    _logger.info(f"Requested Length: {line.requested_length}mm")
                                    _logger.info(f"Total Quantity Needed: {line.quantity} pieces")
                                    _logger.info(f"Quantity Done So Far: {quantity_done} pieces")
                                    _logger.info(f"Remaining Length Sum: {length_sum}mm")
                                    _logger.info(f"Pieces Per Stock: {pieces_per_stock} pieces")
                                    _logger.info(f"Pieces Still Needed: {pieces_needed} pieces")
                                    _logger.info(f"Available Stock Quantity: {selected_stock['quantity']} stocks")
                                    
                                    if pieces_per_stock > 0:
                                        # Calculate how many stocks we need to consume
                                        stocks_needed = int(pieces_needed / pieces_per_stock)
                                        if pieces_needed % pieces_per_stock > 0:
                                            stocks_needed += 1
                                        
                                        # Don't consume more stocks than available
                                        stocks_to_consume = min(stocks_needed, selected_stock['quantity'])
                                        
                                        # Calculate actual pieces we can cut from these stocks
                                        total_pieces_cut = stocks_to_consume * pieces_per_stock
                                        
                                        # If we're cutting more than needed, adjust
                                        if total_pieces_cut > pieces_needed:
                                            total_pieces_cut = pieces_needed
                                        
                                        _logger.info(f"→ Stocks Needed: {stocks_needed} stocks")
                                        _logger.info(f"→ Stocks to Consume: {stocks_to_consume} stocks")
                                        _logger.info(f"→ Total Pieces Cut: {total_pieces_cut} pieces")
                                        
                                        # Decrease stock quantity
                                        list(filter(lambda x: x['id'] == selected_stock['id'], stocks))[0]['quantity'] -= stocks_to_consume
                                        
                                        # Calculate remaining length after cutting all pieces
                                        # Balance should be from the LAST stock used
                                        pieces_from_last_stock = total_pieces_cut % pieces_per_stock
                                        if pieces_from_last_stock == 0:
                                            # All stocks fully consumed (exact multiple)
                                            pieces_from_last_stock = pieces_per_stock
                                        
                                        selected_stock_length = round(selected_stock_length - (pieces_from_last_stock * line.requested_length), 2)
                                        
                                        # Decrease the total length sum needed
                                        length_sum -= round(total_pieces_cut * line.requested_length, 2)
                                        length_sum = round(length_sum, 2)
                                        
                                        quantity_done += total_pieces_cut
                                        
                                        _logger.info(f"→ Length Balance: {selected_stock_length}mm")
                                        _logger.info(f"→ Remaining Length Sum: {length_sum}mm")
                                        _logger.info(f"→ Total Quantity Done: {quantity_done} pieces")
                                        _logger.info(f"→ Stock Quantity After: {list(filter(lambda x: x['id'] == selected_stock['id'], stocks))[0]['quantity']} stocks")
                                    else:
                                        # If we can't cut any pieces, skip this stock
                                        break

                                if stocks_to_consume > 0:
                                    product = self.env['product.product'].browse(selected_stock['product'])
                                    
                                    _logger.info(f"✓ Creating cutting records:")
                                    _logger.info(f"  Stock ID: {selected_stock['id']}")
                                    _logger.info(f"  Stock Product: {product.name}")
                                    _logger.info(f"  Stocks to Consume: {stocks_to_consume} stocks")
                                    _logger.info(f"  Pieces per Stock: {pieces_per_stock} pieces")
                                    _logger.info(f"  Length Balance (from last stock): {selected_stock_length}mm")
                                    
                                    # Create separate cutting records for each stock consumed
                                    for stock_idx in range(int(stocks_to_consume)):
                                        # For all stocks except the last one, balance should be 0 (fully consumed)
                                        # For the last stock, use the calculated balance
                                        is_last_stock = (stock_idx == int(stocks_to_consume) - 1)
                                        stock_balance = selected_stock_length if is_last_stock else 0
                                        
                                        # Calculate pieces cut from THIS stock
                                        # If it's the last stock and we have remainder, use that
                                        # Otherwise use full pieces_per_stock
                                        pieces_from_this_stock = pieces_per_stock
                                        if is_last_stock:
                                            remaining_pieces = pieces_needed - (stock_idx * pieces_per_stock)
                                            pieces_from_this_stock = min(remaining_pieces, pieces_per_stock)
                                        
                                        cutting_record = {
                                            'job_order_id_char': int(job_order.id),
                                            'job_order_line_id': line.id,
                                            'stock_quantity_id': selected_stock['id'],
                                            'done_quantity': pieces_from_this_stock,  # Number of PIECES cut from this stock
                                            'warehouse_id': selected_stock['warehouse_id'],

                                            'length_balance': stock_balance,
                                            'width_balance': product.width,
                                            'diameter_balance': product.diameter,
                                            'thickness_balance': product.thickness,
                                            'kg_balance': product.kg,
                                            'across_flat_balance': product.across_flat ,
                                            'mesh_number_balance': product.mesh_number ,
                                            'mesh_size_balance': product.mesh_size ,
                                            'hole_diameter_balance': product.hole_diameter ,
                                            'width_2_balance': product.width_2 ,
                                            'pitch_balance': product.pitch ,
                                            'inner_diameter_balance': product.inner_diameter,
                                        }
                                        
                                        _logger.info(f"  Record {stock_idx + 1}/{int(stocks_to_consume)}: done_quantity={pieces_from_this_stock} pieces, balance={stock_balance}mm")
                                        job_order_cutting_ids.append(cutting_record)
                                    
                                    _logger.info(f"  ✓ APPENDED {int(stocks_to_consume)} cutting records, total pieces={total_pieces_cut}")
                                    _logger.info("=" * 80)

                                    if selected_stock['lot_name'] and stocks_to_consume > 0:
                                        if not line.custom_order_line_id.batch_number:
                                            line.custom_order_line_id.batch_number = selected_stock['lot_name'] + ';'
                                        else:
                                            if not line.custom_order_line_id.batch_number.find(selected_stock['lot_name']) != -1:
                                                line.custom_order_line_id.batch_number += selected_stock['lot_name'] + ';'


                        elif line.is_have_width and line.parent_product_id.product_tmpl_id.width == 0:
                            ''' if selected product have only width and width of its parent product is 0 '''
                            width_sum = line.requested_width * line.quantity
                            fil_stocks = list(filter(lambda x: x['parent_product'] == line.product_id.parent_product_id.id , stocks))

                            quantity_done = 0

                            while width_sum > 0 and len(fil_stocks) > 0:
                                fil_stocks = list(filter(lambda x: x['parent_product'] == line.product_id.parent_product_id.id and x['quantity'] > 0, stocks))

                                if len(list(filter(lambda x: x['parent_product'] == line.product_id.parent_product_id.id and x['quantity'] > 0 and x['lot_name'] in lot, stocks))) > 0:
                                    fil_stocks = list(filter(lambda x: x['parent_product'] == line.product_id.parent_product_id.id and x['quantity'] > 0 and x['lot_name'] in lot, stocks))
                                else:
                                    fit_stocks = sorted(list(filter(lambda x: x['product_width'] == line.requested_width, fil_stocks)), key=lambda x: x['id'])

                                    if fit_stocks:
                                        fit_stock_alpha = sorted([x for x in fit_stocks if x['lot_name_check'].isalpha()], key=lambda x: (x['lot_name_check'], x['quantity'])) 
                                        fit_stock_alnum = sorted([x for x in fit_stocks if x['lot_name_check'].isalnum() and not x['lot_name_check'].isalpha() and not x['lot_name_check'].isnumeric()], key=lambda x: (x['lot_name_check'], x['quantity'])) 

                                        fit_stock_alnum_start = sorted([x for x in fit_stock_alnum if x['lot_name_check'][0].isalpha() and not x['lot_name_check'][-1].isalpha()], key=lambda x: x['lot_name_check'])
                                        fit_stock_alnum_end = sorted([x for x in fit_stock_alnum if not x['lot_name_check'][0].isalpha() and x['lot_name_check'][-1].isalpha()], key=lambda x: x['lot_name_check'])

                                        fit_stock_num = sorted([x for x in fit_stocks if x['lot_name_check'].isnumeric()], key=lambda x: (x['lot_name_check'], x['quantity'])) 

                                        for x in fit_stock_num:
                                            x['lot_name_check'] = int(x['lot_name_check'])

                                        fit_stock_num = sorted(fit_stock_num, key=lambda x: x['lot_name_check'])

                                        for x in fit_stock_num:
                                            x['lot_name_check'] = str(x['lot_name_check'])

                                        fit_stocks = fit_stock_alpha + fit_stock_alnum_start + fit_stock_num + fit_stock_alnum_end 

                                    fil_stocks = fit_stocks + sorted(list(filter(lambda x: (x['product_width'] > line.requested_width), fil_stocks)), key=lambda x: (x['product_width'], x['id']))

                                if not fil_stocks:
                                    continue

                                selected_stock = fil_stocks[0]
                                selected_stock_width = fil_stocks[0]['product_width']
                                # Track how many stocks we need to consume for this cutting operation
                                stocks_to_consume = 0
                                # Track total pieces cut from all stocks
                                total_pieces_cut = 0

                                if selected_stock_width == line.requested_width:
                                    if selected_stock['quantity'] >= line.quantity:
                                        stocks_to_consume = line.quantity - quantity_done
                                        list(filter(lambda x: x['id'] == selected_stock['id'], stocks))[0]['quantity'] -= stocks_to_consume
                                        width_sum = 0
                                        quantity_done = line.quantity
                                        total_pieces_cut = stocks_to_consume

                                    else:
                                        stocks_to_consume = selected_stock['quantity']
                                        list(filter(lambda x: x['id'] == selected_stock['id'], stocks))[0]['quantity'] = 0
                                        width_sum -= (stocks_to_consume * line.requested_width)
                                        quantity_done += stocks_to_consume
                                        total_pieces_cut = stocks_to_consume

                                    selected_stock_width = 0

                                else:
                                    ''' stock quantity doesn't match with selected quantity - need to cut multiple pieces from stock '''
                                    # Calculate how many pieces can be cut from ONE stock
                                    pieces_per_stock = int(selected_stock_width / line.requested_width)
                                    
                                    # Calculate how many pieces we still need
                                    pieces_needed = int(width_sum / line.requested_width)
                                    if width_sum % line.requested_width > 0:
                                        pieces_needed += 1
                                    
                                    if pieces_per_stock > 0:
                                        # Calculate how many stocks we need to consume
                                        stocks_needed = int(pieces_needed / pieces_per_stock)
                                        if pieces_needed % pieces_per_stock > 0:
                                            stocks_needed += 1
                                        
                                        # Don't consume more stocks than available
                                        stocks_to_consume = min(stocks_needed, selected_stock['quantity'])
                                        
                                        # Calculate actual pieces we can cut from these stocks
                                        total_pieces_cut = stocks_to_consume * pieces_per_stock
                                        
                                        # If we're cutting more than needed, adjust
                                        if total_pieces_cut > pieces_needed:
                                            total_pieces_cut = pieces_needed
                                        
                                        # Decrease stock quantity
                                        list(filter(lambda x: x['id'] == selected_stock['id'], stocks))[0]['quantity'] -= stocks_to_consume
                                        
                                        # Calculate remaining width after cutting all pieces
                                        # Balance should be from the LAST stock used
                                        pieces_from_last_stock = total_pieces_cut % pieces_per_stock
                                        if pieces_from_last_stock == 0:
                                            # All stocks fully consumed (exact multiple)
                                            pieces_from_last_stock = pieces_per_stock
                                        
                                        selected_stock_width = round(selected_stock_width - (pieces_from_last_stock * line.requested_width), 2)
                                        
                                        # Decrease the total width sum needed
                                        width_sum -= round(total_pieces_cut * line.requested_width, 2)
                                        width_sum = round(width_sum, 2)
                                        
                                        quantity_done += total_pieces_cut
                                    else:
                                        # If we can't cut any pieces, skip this stock
                                        break

                                if stocks_to_consume > 0:
                                    product = self.env['product.product'].browse(selected_stock['product'])

                                    job_order_cutting_ids.append({
                                        'job_order_id_char': int(job_order.id),
                                        'job_order_line_id': line.id,
                                        'stock_quantity_id': selected_stock['id'],
                                        'done_quantity': stocks_to_consume,
                                        'warehouse_id': selected_stock['warehouse_id'],

                                        'length_balance': product.length,
                                        'width_balance': selected_stock_width,
                                        'diameter_balance': product.diameter,
                                        'thickness_balance': product.thickness,
                                        'kg_balance': product.kg,
                                        'across_flat_balance': product.across_flat ,
                                        'mesh_number_balance': product.mesh_number ,
                                        'mesh_size_balance': product.mesh_size ,
                                        'hole_diameter_balance': product.hole_diameter ,
                                        'width_2_balance': product.width_2 ,
                                        'pitch_balance': product.pitch ,
                                        'inner_diameter_balance': product.inner_diameter,
                                    })

                                    if selected_stock['lot_name'] and stocks_to_consume > 0:
                                        if not line.custom_order_line_id.batch_number:
                                            line.custom_order_line_id.batch_number = selected_stock['lot_name'] + ';'
                                        else:
                                            if not line.custom_order_line_id.batch_number.find(selected_stock['lot_name']) != -1:
                                                line.custom_order_line_id.batch_number += selected_stock['lot_name'] + ';'


                        elif line.is_have_kg and line.parent_product_id.product_tmpl_id.kg == 0:
                            ''' if selected product have only kg and kg of its parent product is 0 '''
                            kg_sum = line.requested_kg * line.quantity
                            fil_stocks = list(filter(lambda x: x['parent_product'] == line.product_id.parent_product_id.id , stocks))

                            quantity_done = 0

                            while kg_sum > 0 and len(fil_stocks) > 0:
                                fil_stocks = list(filter(lambda x: x['parent_product'] == line.product_id.parent_product_id.id and x['quantity'] > 0, stocks))

                                if len(list(filter(lambda x: x['parent_product'] == line.product_id.parent_product_id.id and x['quantity'] > 0 and x['lot_name'] in lot, stocks))) > 0:
                                    fil_stocks = list(filter(lambda x: x['parent_product'] == line.product_id.parent_product_id.id and x['quantity'] > 0 and x['lot_name'] in lot, stocks))
                                else:
                                    fit_stocks = sorted(list(filter(lambda x: x['product_kg'] == line.requested_kg, fil_stocks)), key=lambda x: x['id'])

                                    if fit_stocks:
                                        fit_stock_alpha = sorted([x for x in fit_stocks if x['lot_name_check'].isalpha()], key=lambda x: (x['lot_name_check'], x['quantity'])) 
                                        fit_stock_alnum = sorted([x for x in fit_stocks if x['lot_name_check'].isalnum() and not x['lot_name_check'].isalpha() and not x['lot_name_check'].isnumeric()], key=lambda x: (x['lot_name_check'], x['quantity'])) 

                                        fit_stock_alnum_start = sorted([x for x in fit_stock_alnum if x['lot_name_check'][0].isalpha() and not x['lot_name_check'][-1].isalpha()], key=lambda x: x['lot_name_check'])
                                        fit_stock_alnum_end = sorted([x for x in fit_stock_alnum if not x['lot_name_check'][0].isalpha() and x['lot_name_check'][-1].isalpha()], key=lambda x: x['lot_name_check'])

                                        fit_stock_num = sorted([x for x in fit_stocks if x['lot_name_check'].isnumeric()], key=lambda x: (x['lot_name_check'], x['quantity'])) 

                                        for x in fit_stock_num:
                                            x['lot_name_check'] = int(x['lot_name_check'])

                                        fit_stock_num = sorted(fit_stock_num, key=lambda x: x['lot_name_check'])

                                        for x in fit_stock_num:
                                            x['lot_name_check'] = str(x['lot_name_check'])

                                        fit_stocks = fit_stock_alpha + fit_stock_alnum_start + fit_stock_num + fit_stock_alnum_end 

                                    fil_stocks = fit_stocks + sorted(list(filter(lambda x: (x['product_kg'] > line.requested_kg), fil_stocks)), key=lambda x: (x['product_kg'], x['id']))

                                if not fil_stocks:
                                    continue

                                selected_stock = fil_stocks[0]
                                selected_stock_kg = fil_stocks[0]['product_kg']
                                done_quantity = 0

                                if selected_stock_kg == line.requested_kg:
                                    if selected_stock['quantity'] >= line.quantity:
                                        done_quantity = line.quantity - quantity_done
                                        list(filter(lambda x: x['id'] == selected_stock['id'], stocks))[0]['quantity'] -= line.quantity
                                        kg_sum = 0
                                        quantity_done = line.quantity

                                    else:
                                        done_quantity += selected_stock['quantity']
                                        list(filter(lambda x: x['id'] == selected_stock['id'], stocks))[0]['quantity'] = 0
                                        kg_sum -= (done_quantity * line.requested_kg)
                                        quantity_done += done_quantity

                                    selected_stock_kg = 0

                                else:
                                    list(filter(lambda x: x['id'] == selected_stock['id'], stocks))[0]['quantity'] -= 1

                                    while selected_stock_kg >= line.requested_kg and kg_sum > 0:
                                        selected_stock_kg -= round(line.requested_kg, 2)
                                        selected_stock_kg = round(selected_stock_kg, 2)
                                        kg_sum -= round(line.requested_kg, 2)
                                        kg_sum = round(kg_sum, 2)
                                        done_quantity += 1

                                if done_quantity > 0:
                                    product = self.env['product.product'].browse(selected_stock['product'])

                                    job_order_cutting_ids.append({
                                        'job_order_id_char': int(job_order.id),
                                        'job_order_line_id': line.id,
                                        'stock_quantity_id': selected_stock['id'],
                                        'done_quantity': done_quantity,
                                        'warehouse_id': selected_stock['warehouse_id'],

                                        'length_balance': product.length,
                                        'width_balance': product.width,
                                        'diameter_balance': product.diameter,
                                        'thickness_balance': product.thickness,
                                        'kg_balance': selected_stock_kg,
                                        'across_flat_balance': product.across_flat ,
                                        'mesh_number_balance': product.mesh_number ,
                                        'mesh_size_balance': product.mesh_size ,
                                        'hole_diameter_balance': product.hole_diameter ,
                                        'width_2_balance': product.width_2 ,
                                        'pitch_balance': product.pitch ,
                                        'inner_diameter_balance': product.inner_diameter,
                                    })

                                    if selected_stock['lot_name'] and done_quantity > 0:
                                        if not line.custom_order_line_id.batch_number:
                                            line.custom_order_line_id.batch_number = selected_stock['lot_name'] + ';'
                                        else:
                                            if not line.custom_order_line_id.batch_number.find(selected_stock['lot_name']) != -1:
                                                line.custom_order_line_id.batch_number += selected_stock['lot_name'] + ';'

                        
                        else:
                            pass


            multi_location = False
            locations = []
            check_arr = []
            is_partial = False

            if not self.is_force_jo and len(job_order_cutting_ids) == 0:
                raise ValidationError("Product not sufficient for all the requested product.")

            for job in job_order_cutting_ids:
                ''' To check multi location and if done quantity more than required quantity '''
                if job['warehouse_id'] not in locations:
                    locations.append(job['warehouse_id'])

                joli = self.env['job.order.line'].browse(job['job_order_line_id'])

                if job['done_quantity'] > 0:
                    is_partial = True

                if len(check_arr) == 0:
                    check_arr.append({
                        'done_quantity': job['done_quantity'],
                        'sale_order_custom_line_id': joli.custom_order_line_id.id,
                        'required_quantity': joli.quantity,
                        'product_name': joli.custom_order_line_id.parent_product_id.name,
                    })

                else:
                    if len(list(filter(lambda x: x['sale_order_custom_line_id'] == joli.custom_order_line_id.id, check_arr))) > 0:
                        list(filter(lambda x: x['sale_order_custom_line_id'] == joli.custom_order_line_id.id, check_arr))[0]['done_quantity'] += job['done_quantity']

                    else:
                        check_arr.append({
                            'done_quantity': job['done_quantity'],
                            'sale_order_custom_line_id': joli.custom_order_line_id.id,
                            'required_quantity': joli.quantity,
                            'product_name': joli.custom_order_line_id.parent_product_id.name,
                        })

            for line in self.custom_dimension_line_ids:
                if len(list(filter(lambda x: x['sale_order_custom_line_id'] ==line.id, check_arr))) == 0:
                    check_arr.append({
                        'done_quantity': 0,
                        'sale_order_custom_line_id': line.id,
                        'required_quantity': line.quantity,
                        'product_name': line.description,
                    })

            if len(locations) == 1:
                if locations[0] != self.warehouse_id.id:
                    self.warehouse_id = locations[0]
            elif len(locations) > 1:
                multi_location = True

            quantity_not_satisfied = ''

            for arr in check_arr:
                if arr['done_quantity'] < arr['required_quantity']:
                    line_obj = self.env['sale.order.custom.dimension.line'].browse(arr['sale_order_custom_line_id'])
                    
                    if line_obj.parent_product_id.type == 'product':
                        shortage = int(arr['required_quantity'] - arr['done_quantity'])
                        msg = f"<br>- {arr['product_name']} required {shortage} more"
                        quantity_not_satisfied += msg

            if quantity_not_satisfied:
                if not self.is_force_jo or not self.is_partial:
                    if self.is_force_jo:
                        # Explicit handling when force_jo is True
                        # Optional: Log or create a record for backorders or shortfalls
                        # self.env.cr.rollback()
                        s_log = self.env['shortfall.log'].create({
                            'order_id': self.id,
                            'details': quantity_not_satisfied,
                        })
                        # job_order.unlink()
                        self.env['ir.sequence'].sudo().search([('name', '=', 'Job Order')], limit=1).number_next_actual -= 1
                        return super(SaleOrder, self).action_confirm()
                        # Allow the process to continue
                    else:
                        self.env.cr.rollback()
                        self.env['ir.sequence'].sudo().search([('name', '=', 'Job Order')], limit=1).number_next_actual -= 1

                        if is_partial:
                            self.is_partial = True

                        return {
                            'name': _('Error'),
                            'view_mode': 'form',
                            'res_model': 'teckleong.notification.wizard',
                            'type': 'ir.actions.act_window',
                            'target': 'new',
                            'context': {'text': "The requested product quantity not sufficient" + quantity_not_satisfied}
                        }


            if not multi_location:
                _logger.info(f"\n{'='*80}")
                _logger.info(f"CREATING JOB ORDER CUTTING RECORDS (Single Location)")
                _logger.info(f"Total cutting records to create: {len(job_order_cutting_ids)}")
                
                for idx, job in enumerate(job_order_cutting_ids):
                    _logger.info(f"\n--- Creating Cutting Record {idx+1}/{len(job_order_cutting_ids)} ---")
                    _logger.info(f"  Stock Quantity ID: {job['stock_quantity_id']}")
                    _logger.info(f"  Done Quantity: {job['done_quantity']}")
                    _logger.info(f"  Length Balance: {job.get('length_balance', 'N/A')}")
                    
                    balance_ids = []

                    stock_id = self.env['stock.quant'].browse(job['stock_quantity_id'])
                    stock_product = self.env['product.product'].browse(stock_id.product_id.id)
                    skip_balance = False

                    if stock_product.categ_id.is_have_length == True and stock_product.parent_product_id.product_tmpl_id.length == 0 and job['length_balance'] <= 0:
                        skip_balance = True

                    if stock_product.categ_id.is_have_width == True and stock_product.parent_product_id.product_tmpl_id.width == 0 and job['width_balance'] <= 0:
                        skip_balance = True

                    if stock_product.categ_id.is_have_kg == True and stock_product.parent_product_id.product_tmpl_id.kg == 0 and job['kg_balance'] <= 0:
                        skip_balance = True

                    if stock_product == stock_product.parent_product_id:
                        skip_balance = True

                    if not skip_balance:
                        balance_ids.append((0, 0, {
                            'length_balance': job['length_balance'],
                            'width_balance': job['width_balance'],
                            'diameter_balance': job['diameter_balance'],
                            'thickness_balance': job['thickness_balance'],
                            'kg_balance': job['kg_balance'],
                            'across_flat_balance': job['across_flat_balance'] ,
                            'mesh_number_balance': job['mesh_number_balance'] ,
                            'mesh_size_balance': job['mesh_size_balance'] ,
                            'hole_diameter_balance': job['hole_diameter_balance'] ,
                            'width_2_balance': job['width_2_balance'] ,
                            'pitch_balance': job['pitch_balance'] ,
                            'inner_diameter_balance': job['inner_diameter_balance'] ,
                            'lot_name': stock_id.lot_id.name,
                            'receipt_location_id': stock_id.location_id.id,
                        }))

                    if job.get('length_balance_2'):
                        if job['length_balance_2'] > 0 and job['width_balance_2'] > 0:
                            balance_ids.append((0, 0, {
                                'length_balance': job['length_balance_2'],
                                'width_balance': job['width_balance_2'],
                                'diameter_balance': job['diameter_balance'],
                                'thickness_balance': job['thickness_balance'],
                                'kg_balance': job['kg_balance'],
                                'across_flat_balance': job['across_flat_balance'] ,
                                'mesh_number_balance': job['mesh_number_balance'] ,
                                'mesh_size_balance': job['mesh_size_balance'] ,
                                'hole_diameter_balance': job['hole_diameter_balance'] ,
                                'width_2_balance': job['width_2_balance'] ,
                                'pitch_balance': job['pitch_balance'] ,
                                'inner_diameter_balance': job['inner_diameter_balance'] ,
                                'lot_name': stock_id.lot_id.name,
                                'receipt_location_id': stock_id.location_id.id,

                            }))

                    job_order.job_order_cutting_ids = [(0, 0, {
                        'stock_quantity_id': job['stock_quantity_id'],
                        'line_ids': [(0, 0, {
                            'job_order_line_id': job['job_order_line_id'],
                            'done_quantity': job['done_quantity'],
                        })],
                        'balance_ids': balance_ids,
                        'job_order_id_char': job['job_order_id_char'],
                    })]

                    job_order.location_id = self.warehouse_id

                    for line in job_order.job_order_line_ids:
                        line.receipt_location_id = self.warehouse_id.lot_stock_id.id

            else:
                job_order.type = 'multiple_location'

                job_order.action_confirm()

                i = 0

                for job in job_order_cutting_ids:
                    stock_id = self.env['stock.quant'].browse(job['stock_quantity_id'])
                    stock_product = self.env['product.product'].browse(stock_id.product_id.id)
                    skip_balance = False

                    if stock_product.categ_id.is_have_length == True and stock_product.parent_product_id.product_tmpl_id.length == 0 and job['length_balance'] <= 0:
                        skip_balance = True

                    if stock_product.categ_id.is_have_width == True and stock_product.parent_product_id.product_tmpl_id.width == 0 and job['width_balance'] <= 0:
                        skip_balance = True

                    if stock_product.categ_id.is_have_kg == True and stock_product.parent_product_id.product_tmpl_id.kg == 0 and job['kg_balance'] <= 0:
                        skip_balance = True

                    if stock_product == stock_product.parent_product_id:
                        skip_balance = True

                    if len(job_order.job_order_child_ids.filtered(lambda x: x.location_id.id == job['warehouse_id'])) == 0:
                        i += 1

                        job_order.job_order_child_ids.create({
                            'name': job_order.name + '-' + str(i),
                            'type': 'single_location',
                            'is_child': True,
                            'job_order_parent_id': job_order.id,
                            'location_id': job['warehouse_id'],
                            'datetime': job_order.datetime,
                            'sale_order_id': job_order.sale_order_id.id,
                            'job_order_line_id': job['job_order_line_id'],
                        })

                    job_order_child = job_order.job_order_child_ids.filtered(lambda x: x.location_id.id == job['warehouse_id'])[0]

                    job_order_line1 = self.env['job.order.line'].browse(job['job_order_line_id'])

                    if len(job_order_child.job_order_line_ids.filtered(lambda x: (x.product_id == job_order_line1.product_id and x.custom_order_line_id == job_order_line1.custom_order_line_id))) == 0:
                        job_order_child.job_order_line_ids = [(0, 0, {
                            'product_id': job_order_line1.product_id.id,
                            'requested_width': job_order_line1.requested_width,
                            'requested_length': job_order_line1.requested_length,
                            'requested_kg': job_order_line1.requested_kg,
                            'requested_diameter': job_order_line1.requested_diameter,
                            'requested_thickness': job_order_line1.requested_thickness,
                            'requested_across_flat' : job_order_line1.requested_across_flat,
                            'requested_width_2' : job_order_line1.requested_width_2,
                            'requested_mesh_number' : job_order_line1.requested_mesh_number,
                            'requested_mesh_size' : job_order_line1.requested_mesh_size,
                            'requested_hole_diameter' : job_order_line1.requested_hole_diameter,
                            'requested_pitch' : job_order_line1.requested_pitch,
                            'requested_inner_diameter' : job_order_line1.requested_inner_diameter,
                            'quantity': job['done_quantity'],
                            'product_uom_id': job_order_line1.product_uom_id.id,
                            'receipt_location_id': self.warehouse_id.lot_stock_id.id,
                            'custom_order_line_id': job_order_line1.custom_order_line_id.id,
                            'electrode_number': job_order_line1.electrode_number,
                        })]
                    else:
                        job_order_child.job_order_line_ids.filtered(lambda x: (x.product_id == job_order_line1.product_id and x.custom_order_line_id == job_order_line1.custom_order_line_id))[0].quantity += job['done_quantity']

                    balance_ids = []

                    if not skip_balance:
                        balance_ids.append((0, 0, {
                            'length_balance': job['length_balance'],
                            'width_balance': job['width_balance'],
                            'diameter_balance': job['diameter_balance'],
                            'thickness_balance': job['thickness_balance'],
                            'kg_balance': job['kg_balance'],
                            'across_flat_balance': job['across_flat_balance'] ,
                            'mesh_number_balance': job['mesh_number_balance'] ,
                            'mesh_size_balance': job['mesh_size_balance'] ,
                            'hole_diameter_balance': job['hole_diameter_balance'] ,
                            'width_2_balance': job['width_2_balance'] ,
                            'pitch_balance': job['pitch_balance'] ,
                            'inner_diameter_balance': job['inner_diameter_balance'] ,
                            'lot_name': stock_id.lot_id.name,
                            'receipt_location_id': stock_id.location_id.id,

                        }))

                    if job.get('length_balance_2'):
                        if job['length_balance_2'] > 0 and job['width_balance_2'] > 0:
                            balance_ids.append((0, 0, {
                                'length_balance': job['length_balance_2'],
                                'width_balance': job['width_balance_2'],
                                'diameter_balance': job['diameter_balance'],
                                'thickness_balance': job['thickness_balance'],
                                'kg_balance': job['kg_balance'],
                                'across_flat_balance': job['across_flat_balance'] ,
                                'mesh_number_balance': job['mesh_number_balance'] ,
                                'mesh_size_balance': job['mesh_size_balance'] ,
                                'hole_diameter_balance': job['hole_diameter_balance'] ,
                                'width_2_balance': job['width_2_balance'] ,
                                'pitch_balance': job['pitch_balance'] ,
                                'inner_diameter_balance': job['inner_diameter_balance'] ,
                                'lot_name': stock_id.lot_id.name,
                                'receipt_location_id': stock_id.location_id.id,
                                
                            }))

                    job_order_child.job_order_cutting_ids = [(0, 0, {
                        'stock_quantity_id': job['stock_quantity_id'],
                        'line_ids': [(0, 0, {
                            'job_order_line_id': job_order_child.job_order_line_ids.filtered(lambda x: (x.product_id == job_order_line1.product_id and x.custom_order_line_id == job_order_line1.custom_order_line_id))[0].id,
                            'done_quantity': job['done_quantity'],
                        })],
                        'balance_ids': balance_ids,
                        'job_order_id_char': job_order_child.id,
                    })]

        for line in self.custom_dimension_line_ids:
            if line.batch_number:
                line.batch_number = line.batch_number[:-1]

        # for job_order in self.job_order_ids.filtered(lambda order: order.type == 'single_location'):
        #     job_order.merge_cutting_line_ids()

        res = super(SaleOrder, self).action_confirm()

        return res

    def action_cancel(self):
        self.is_confirming = False

        res = super(SaleOrder, self).action_cancel()

        job_orders = self.env['job.order'].search([('sale_order_id', '=', self.id)])

        for job in job_orders:
            if job.state != 'done':
                job.state = 'cancel'

        return res

    def action_view_job_order(self):
        self.ensure_one()

        return {
            'name': 'Job Order',
            'type': 'ir.actions.act_window',
            'view_mode': 'tree,form',
            'res_model': 'job.order',
            'domain': [('sale_order_id', '=', self.id)],
            'target': 'current',
        }

    def action_view_purchase(self):
        self.ensure_one()

        return {
            'name': 'Purchase',
            'type': 'ir.actions.act_window',
            'view_mode': 'tree,form',
            'res_model': 'purchase.order',
            'domain': [('sale_order_id', '=', self.id)],
            'target': 'current',
        }

    @api.depends('custom_dimension_line_ids.price_total')
    def _amount_all_custom(self):
        """
        Compute the total amounts of the SO.
        """
        for order in self:
            amount_untaxed = amount_tax = 0.0
            for line in order.custom_dimension_line_ids:
                amount_untaxed += line.subtotal
                amount_tax += line.price_tax
            order.update({
                'custom_amount_untaxed': amount_untaxed,
                'custom_amount_tax': amount_tax,
                'custom_amount_total': amount_untaxed + amount_tax,
            })

    def _compute_amount_undiscounted(self):
        for order in self:
            total = 0.0
            for line in order.order_line:
                discount = (line.discount or 0.0) / 100.0
                discount = (line.discount_overall or 0.0) / 100.0

                total += line.price_subtotal + line.price_unit * discount * line.product_uom_qty  # why is there a discount in a field named amount_undiscounted ??
            order.amount_undiscounted = total

    @api.depends('order_line.tax_id', 'order_line.price_unit', 'amount_total', 'amount_untaxed')
    def _compute_tax_totals_json(self):
        def compute_taxes(order_line):
            price = order_line.price_unit * (1 - (order_line.discount or 0.0) / 100.0)
            price = price * (1 - (order_line.discount_overall or 0.0) / 100.0)
            order = order_line.order_id
            return order_line.tax_id._origin.compute_all(price, order.currency_id, order_line.product_uom_qty, product=order_line.product_id, partner=order.partner_shipping_id)

        account_move = self.env['account.move']
        for order in self:
            tax_lines_data = account_move._prepare_tax_lines_data_for_totals_from_object(order.order_line, compute_taxes)
            tax_totals = account_move._get_tax_totals(order.partner_id, tax_lines_data, order.amount_total, order.amount_untaxed, order.currency_id)
            order.tax_totals_json = json.dumps(tax_totals)

    @api.depends('custom_dimension_line_ids.tax_ids', 'custom_dimension_line_ids.unit_price','custom_amount_tax','custom_amount_total')
    def _compute_tax_totals_json2(self):
        def compute_taxes1(custom_dimension_line_ids):
            order_line = custom_dimension_line_ids
            price = order_line.unit_price * (1 - (order_line.discount or 0.0) / 100.0)
            price = price * (1 - (order_line.discount_overall or 0.0) / 100.0)
            order = order_line.id
            return order_line.tax_ids._origin.compute_all(price, self.currency_id, order_line.quantity, product=order_line.parent_product_id, partner=self.partner_shipping_id)
        
        account_move = self.env['account.move']
        for order in self:
            tax_lines_data = account_move._prepare_tax_lines_data_for_totals_from_object(order.custom_dimension_line_ids, compute_taxes1)
            tax_totals = account_move._get_tax_totals(order.partner_id,tax_lines_data, order.custom_amount_total, order.custom_amount_untaxed, order.currency_id)
            
            order.tax_totals_json2 = json.dumps(tax_totals)
               
    def _prepare_invoice(self):
        ovds = super(SaleOrder, self)._prepare_invoice()

        ovds.update({
            'discount_overall':self.discount_overall,
            'narration': self.remarks,
            # 'ref': self.client_order_ref,
            'po_ref': self.po_ref,
        })

        return ovds

    @api.depends('tax_totals_json2', 'amount_total', 'state')
    def _compute_substitute_total(self):
        for sale in self:
            if sale.state in ['draft', 'sent', 'cancel']:
                sale.substitute_total = sale.custom_amount_total
            else:
                sale.substitute_total = sale.amount_total

    def _compute_delivery_state(self):
        for sale in self:
            delivery_state = 'no_delivery'

            if sale.state in ['sale', 'done']:
                do = sale.env['stock.picking'].search([('origin', '=', sale.name), ('state', '!=', 'cancel')])

                if len(do) == 1:
                    if do.state == 'done':
                        delivery_state = 'delivered'
                    else:
                        delivery_state = 'wait'
                else:
                    done = len(do.filtered(lambda x: x.state == 'done'))
                    waiting = len(do.filtered(lambda x: x.state != 'done'))

                    if done > 0 and waiting == 0:
                        delivery_state = 'delivered'

                    elif done > 0 and waiting > 0:
                        delivery_state = 'partial'

                    elif done == 0 and waiting > 0:
                        delivery_state = 'wait' 

            sale.delivery_state = delivery_state

    def _compute_purchase_move_line_ids(self):
        for sale in self:
            purchase_move_line = self.env['stock.move.line']

            for purchase in sale.purchase_ids:
                for picking in purchase.picking_ids:
                    for move in picking.move_ids_without_package:
                        purchase_move_line += move.move_line_ids

            sale.purchase_move_line_ids = purchase_move_line

    custom_amount_untaxed = fields.Monetary(string='Custom Untaxed Amount', store=True, compute='_amount_all_custom', tracking=5)
    custom_amount_tax = fields.Monetary(string='Custom Taxes', store=True, compute='_amount_all_custom')
    custom_amount_total = fields.Monetary(string='Custom Total', store=True, compute='_amount_all_custom', tracking=4)
    po_ref = fields.Char('PO Ref')
    custom_dimension_line_ids = fields.One2many('sale.order.custom.dimension.line', 'order_ids', string='Custom Dimension Line', copy=True)
    job_order_ids = fields.One2many('job.order', 'sale_order_id', string='Job Order')
    is_subcontractor = fields.Boolean('Subcontractor')
    discount_overall = fields.Float('Overall Discount %')
    tax_totals_json2 = fields.Char(compute='_compute_tax_totals_json2')
    remarks = fields.Html('Remarks')
    self_collection_location = fields.Selection([
        ('amk','AMK'),
        ( 'kel', 'KEL'),
        ('tuas', 'TUAS'),
    ],string='Self Collection location')
    substitute_total = fields.Float(string='Total', compute='_compute_substitute_total', store=True, digits=(12, 2))
    delivery_state = fields.Selection([
        ('wait', 'Waiting'),
        ('partial', 'Partially Delivered'),
        ('delivered', 'Delivered'),
        ('no_delivery', 'No Delivery')
    ], string='Delivery Status', compute='_compute_delivery_state')
    is_partial = fields.Boolean('Is Partial')
    is_force_jo = fields.Boolean('Force JO')

    purchase_ids = fields.Many2many('purchase.order', string='Purchases', copy=False)
    purchase_move_line_ids = fields.Many2many('stock.move.line', string='Purchase Move Line', compute='_compute_purchase_move_line_ids')

    is_woocommerce = fields.Boolean('Is Woocomerce')
    is_confirming = fields.Boolean('Is Confirming')

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _prepare_procurement_values(self, group_id=False):
        res = super(SaleOrderLine, self)._prepare_procurement_values(group_id)
        # I am assuming field name in both sale.order.line and in stock.move are same and called 'YourField'
        res.update({
            'electrode_number': self.electrode_number,
            'notes': self.notes,
            'name': self.name,
        })
        return res

    def _prepare_invoice_line(self, **optional_values):
        invoice_lines = super(SaleOrderLine, self)._prepare_invoice_line()

        invoice_lines.update({
            'discount_overall_id':self.discount_overall,
            'electrode_number': self.electrode_number,
            'custom_order_line_id': self.custom_order_line_id.id,
        })

        return invoice_lines

    @api.depends('product_uom_qty', 'discount', 'price_unit', 'tax_id','discount_overall')
    def _compute_amount(self):
        """
        Compute the amounts of the SO line.
        """
        for line in self:
            
            price = line.price_unit * (1 - (line.discount  or 0.0) / 100.0)
            price2 = price * (1 - (line.discount_overall  or 0.0) / 100.0)
            taxes = line.tax_id.compute_all(price2, line.order_id.currency_id, line.product_uom_qty, product=line.product_id, partner=line.order_id.partner_shipping_id)
            line.update({
                # 'price_tax': taxes['total_included'] - taxes['total_excluded'],
                'price_tax': sum(t.get('amount', 0.0) for t in taxes.get('taxes', [])),
                'price_total': taxes['total_included'],
                'price_subtotal': taxes['total_excluded'],
            })
            if self.env.context.get('import_file', False) and not self.env.user.user_has_groups('account.group_account_manager'):
                line.tax_id.invalidate_cache(['invoice_repartition_line_ids'], [line.tax_id.id])

    @api.depends('price_unit', 'discount', 'discount_overall')
    def _compute_price_reduce(self):
        for line in self:
            line.price_reduce = line.price_unit * (1.0 - line.discount / 100.0)
            line.price_reduce = line.price_reduce * (1.0 - line.discount_overall / 100.0)

    @api.depends('order_line.tax_id', 'order_line.price_unit', 'amount_total', 'amount_untaxed')
    def _compute_tax_totals_json(self):
        def compute_taxes(order_line):
            price = order_line.price_unit * (1 - (order_line.discount or 0.0) / 100.0)
            price = price * (1 - (order_line.discount_overall or 0.0) / 100.0)
            order = order_line.order_id
            return order_line.tax_id._origin.compute_all(price, order.currency_id, order_line.product_uom_qty, product=order_line.product_id, partner=order.partner_shipping_id)

        account_move = self.env['account.move']
        for order in self:
            tax_lines_data = account_move._prepare_tax_lines_data_for_totals_from_object(order.order_line, compute_taxes)
            tax_totals = account_move._get_tax_totals(order.partner_id, tax_lines_data, order.amount_total, order.amount_untaxed, order.currency_id)
            order.tax_totals_json = json.dumps(tax_totals)

    @api.depends('state', 'price_reduce', 'product_id', 'untaxed_amount_invoiced', 'qty_delivered', 'product_uom_qty')
    def _compute_untaxed_amount_to_invoice(self):
        """ Total of remaining amount to invoice on the sale order line (taxes excl.) as
                total_sol - amount already invoiced
            where Total_sol depends on the invoice policy of the product.

            Note: Draft invoice are ignored on purpose, the 'to invoice' amount should
            come only from the SO lines.
        """
        for line in self:
            amount_to_invoice = 0.0
            if line.state in ['sale', 'done']:
                # Note: do not use price_subtotal field as it returns zero when the ordered quantity is
                # zero. It causes problem for expense line (e.i.: ordered qty = 0, deli qty = 4,
                # price_unit = 20 ; subtotal is zero), but when you can invoice the line, you see an
                # amount and not zero. Since we compute untaxed amount, we can use directly the price
                # reduce (to include discount) without using `compute_all()` method on taxes.
                price_subtotal = 0.0
                uom_qty_to_consider = line.qty_delivered if line.product_id.invoice_policy == 'delivery' else line.product_uom_qty
                price_reduce = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
                price_reduce = price_reduce * (1 - (line.discount_overall or 0.0) / 100.0)
                price_subtotal = price_reduce * uom_qty_to_consider
                if len(line.tax_id.filtered(lambda tax: tax.price_include)) > 0:
                    # As included taxes are not excluded from the computed subtotal, `compute_all()` method
                    # has to be called to retrieve the subtotal without them.
                    # `price_reduce_taxexcl` cannot be used as it is computed from `price_subtotal` field. (see upper Note)
                    price_subtotal = line.tax_id.compute_all(
                        price_reduce,
                        currency=line.order_id.currency_id,
                        quantity=uom_qty_to_consider,
                        product=line.product_id,
                        partner=line.order_id.partner_shipping_id)['total_excluded']
                inv_lines = line._get_invoice_lines()
                if any(inv_lines.mapped(lambda l: l.discount != line.discount)):
                    # In case of re-invoicing with different discount we try to calculate manually the
                    # remaining amount to invoice
                    amount = 0
                    for l in inv_lines:
                        if len(l.tax_ids.filtered(lambda tax: tax.price_include)) > 0:
                            amount += l.tax_ids.compute_all(l.currency_id._convert(l.price_unit, line.currency_id, line.company_id, l.date or fields.Date.today(), round=False) * l.quantity)['total_excluded']
                        else:
                            amount += l.currency_id._convert(l.price_unit, line.currency_id, line.company_id, l.date or fields.Date.today(), round=False) * l.quantity

                    amount_to_invoice = max(price_subtotal - amount, 0)
                else:
                    amount_to_invoice = price_subtotal - line.untaxed_amount_invoiced

            line.untaxed_amount_to_invoice = amount_to_invoice

    electrode_number = fields.Char('Electrode Number', copy=False)
    batch_number = fields.Char('Batch Number', related='custom_order_line_id.batch_number')
    discount_overall = fields.Float('Overall Discount %')
    custom_order_line_id = fields.Many2one('sale.order.custom.dimension.line', string='Order Line')
    notes = fields.Text('Notes')
    
    is_woocommerce = fields.Boolean('Is Woocomerce')

class SaleOrderCustomDimensionLine(models.Model):
    _name = "sale.order.custom.dimension.line"
    _description = "Sale Order Custom Dimension Line"
    _order = 'order_ids, sequence, id'

    # @api.model
    # def fields_view_get(self, view_id=None, view_type='tree', toolbar=False, submenu=False):
    #     result = super(SaleOrderCustomDimensionLine, self).fields_view_get(view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)

    #     if view_type == 'tree':
    #         fields_to_hide = [
    #             'master_width',
    #             'master_length',
    #             'master_diameter',
    #             'master_thickness',
    #             'master_kg',
    #             'master_across_flat',
    #             'master_mesh_number',
    #             'master_mesh_size',
    #             'master_hole_diameter',
    #             'master_width_2',
    #             'master_pitch',
    #             'master_inner_diameter',
    #             'is_have_diameter',
    #             'is_have_width',
    #             'is_have_thickness',
    #             'is_have_length',
    #             'is_have_kg',
    #             'is_have_across_flat',
    #             'is_have_mesh_number',
    #             'is_have_mesh_size',
    #             'is_have_hole_diameter',
    #             'is_have_width_2',
    #             'is_have_pitch',
    #             'is_have_inner_diameter',
    #         ]

    #         for field_name in fields_to_hide:
    #             if result.get('fields', {}).get(field_name):
    #                 result['fields'][field_name]['selectable'] = False

    #     return result

    @api.model
    def create(self, vals):
        product = self.env['product.product'].browse(vals['parent_product_id'])

        is_woocommerce = False

        if vals.get('is_woocommerce'):
            if vals['is_woocommerce']:
                is_woocommerce = True

        if is_woocommerce:
            vals['description'] = product.name
            vals['dimension_uom_id'] = product.dimension_uom_id.id
            vals['product_uom_id'] = product.uom_id.id
            vals['tax_ids'] = product.taxes_id._ids
            vals['diameter'] = product.product_tmpl_id.diameter
            vals['thickness'] = product.product_tmpl_id.thickness
            vals['width'] = round(product.product_tmpl_id.width, 2)
            vals['length'] = round(product.product_tmpl_id.length, 2)
            vals['kg'] = round(product.product_tmpl_id.kg, 2)
            vals['across_flat'] = product.product_tmpl_id.across_flat
            vals['mesh_number'] = product.product_tmpl_id.mesh_number
            vals['mesh_size'] = product.product_tmpl_id.mesh_size
            vals['hole_diameter'] = product.product_tmpl_id.hole_diameter
            vals['width_2'] = product.product_tmpl_id.width_2
            vals['pitch'] = product.product_tmpl_id.pitch
            vals['inner_diameter'] = product.product_tmpl_id.inner_diameter
            vals['is_parent_id'] = product.product_tmpl_id.is_parent_product
            vals['is_have_diameter'] = product.product_tmpl_id.categ_id.is_have_diameter
            vals['is_have_width'] = product.product_tmpl_id.categ_id.is_have_width
            vals['is_have_thickness'] = product.product_tmpl_id.categ_id.is_have_thickness
            vals['is_have_length'] = product.product_tmpl_id.categ_id.is_have_length
            vals['is_have_kg'] = product.product_tmpl_id.categ_id.is_have_kg
            vals['is_have_across_flat'] = product.product_tmpl_id.categ_id.is_have_across_flat
            vals['is_have_mesh_number'] = product.product_tmpl_id.categ_id.is_have_mesh_number
            vals['is_have_mesh_size'] = product.product_tmpl_id.categ_id.is_have_mesh_size
            vals['is_have_hole_diameter'] = product.product_tmpl_id.categ_id.is_have_hole_diameter
            vals['is_have_width_2'] = product.product_tmpl_id.categ_id.is_have_width_2
            vals['is_have_pitch'] = product.product_tmpl_id.categ_id.is_have_pitch
            vals['is_have_inner_diameter'] = product.product_tmpl_id.categ_id.is_have_inner_diameter
            vals['master_width'] = product.product_tmpl_id.width
            vals['master_length'] = product.product_tmpl_id.length
            vals['master_diameter'] = product.product_tmpl_id.diameter
            vals['master_thickness'] = product.product_tmpl_id.thickness
            vals['master_kg'] = product.product_tmpl_id.kg
            vals['master_across_flat'] = product.product_tmpl_id.across_flat
            vals['master_mesh_number'] = product.product_tmpl_id.mesh_number
            vals['master_mesh_size'] = product.product_tmpl_id.mesh_size
            vals['master_hole_diameter'] = product.product_tmpl_id.hole_diameter
            vals['master_width_2'] = product.product_tmpl_id.width_2
            vals['master_pitch'] = product.product_tmpl_id.pitch
            vals['master_inner_diameter'] = product.product_tmpl_id.inner_diameter

        if product.is_parent_product:
            if product.categ_id.is_have_length and product.length == 0:
                if vals['length'] <= 0:
                    raise ValidationError("Custom Dimension cannot be zero or lower.(%s %s)" %(product.name, product.categ_id.name))
            if product.categ_id.is_have_width and product.width == 0:
                if vals['width'] <= 0:
                    raise ValidationError("Custom Dimension cannot be zero or lower.(%s %s)" %(product.name, product.categ_id.name))
            elif product.categ_id.is_have_kg and product.kg == 0:
                if vals['kg'] <= 0:
                    raise ValidationError("Custom Dimension cannot be zero or lower.(%s %s)" %(product.name, product.categ_id.name))

        res = super(SaleOrderCustomDimensionLine, self).create(vals)

        return res

    def write(self, vals):
        product = self.env['product.product'].browse(vals['parent_product_id']) if vals.get('parent_product_id') else self.parent_product_id

        if product.is_parent_product:
            if product.categ_id.is_have_length and product.length == 0:
                if vals.get('length') != None:
                    if vals['length'] <= 0 and self.length > 0:
                        raise ValidationError("Custom Dimension cannot be zero or lower L.(%s %s)" %(product.name, product.categ_id.name))
            
            if product.categ_id.is_have_width and product.width == 0:
                if vals.get('width') != None:
                    if vals['width'] <= 0 and self.width > 0:
                        raise ValidationError("Custom Dimension cannot be zero or lower W.(%s %s)" %(product.name, product.categ_id.name))
            
            if product.categ_id.is_have_kg and product.kg == 0:
                if vals.get('kg') != None:
                    if vals['kg'] <= 0 and self.kg > 0:
                        raise ValidationError("Custom Dimension cannot be zero or lower Kg.(%s %s)" %(product.name, product.categ_id.name))

        res = super(SaleOrderCustomDimensionLine, self).write(vals)

        return res

    def unlink(self):
        for sale_order_line in self.order_ids.order_line:
            if sale_order_line.custom_order_line_id == self:
                if sale_order_line._check_line_unlink():
                    raise ValidationError('You can not remove an order line once the sales order is confirmed.\nYou should rather set the quantity to 0.')
                else:
                    sale_order_line.unlink()

        res = super(SaleOrderCustomDimensionLine, self).unlink()

        return res

    @api.depends('quantity', 'discount', 'unit_price', 'tax_ids','discount_overall')
    def _compute_amount(self):
        """
        Compute the amounts of the SO line.
        """
        for line in self:
            
            price = line.unit_price * (1 - (line.discount  or 0.0) / 100.0)
            price2 = price * (1 - (line.discount_overall  or 0.0) / 100.0)
            taxes = line.tax_ids.compute_all(price2, line.order_ids.currency_id, line.quantity, product=line.parent_product_id, partner=line.order_ids.partner_shipping_id)
            line.update({
                # 'price_tax': taxes['total_included'] - taxes['total_excluded'],
                'price_tax': sum(t.get('amount', 0.0) for t in taxes.get('taxes', [])),
                'price_total': taxes['total_included'],
                'subtotal': taxes['total_excluded'],
            })
            if self.env.context.get('import_file', False) and not self.env.user.user_has_groups('account.group_account_manager'):
                line.tax_ids.invalidate_cache(['invoice_repartition_line_ids'], [line.tax_ids.id])

    @api.onchange('parent_product_id')
    def onchange_parent_product_id(self):
        for sale_order_line in self.order_ids.order_line:
            if sale_order_line.custom_order_line_id.id == self._origin.id and sale_order_line.custom_order_line_id.id and self._origin.id:
                raise ValidationError("You cannot change product for line that have been confirmed.")

        self.diameter = self.parent_product_id.product_tmpl_id.diameter
        self.thickness = self.parent_product_id.product_tmpl_id.thickness
        self.width = round(self.parent_product_id.product_tmpl_id.width, 2)
        self.length = round(self.parent_product_id.product_tmpl_id.length, 2)
        self.kg = round(self.parent_product_id.product_tmpl_id.kg, 2)
        self.across_flat = self.parent_product_id.product_tmpl_id.across_flat
        self.mesh_number = self.parent_product_id.product_tmpl_id.mesh_number
        self.mesh_size = self.parent_product_id.product_tmpl_id.mesh_size
        self.hole_diameter = self.parent_product_id.product_tmpl_id.hole_diameter
        self.width_2 = self.parent_product_id.product_tmpl_id.width_2
        self.pitch = self.parent_product_id.product_tmpl_id.pitch
        self.inner_diameter = self.parent_product_id.product_tmpl_id.inner_diameter
        self.product_uom_id = self.parent_product_id.product_tmpl_id.uom_id
        self.unit_price = self.parent_product_id.product_tmpl_id.list_price
        self.description = self.parent_product_id.product_tmpl_id.name
        self.dimension_uom_id = self.parent_product_id.product_tmpl_id.dimension_uom_id
        self.is_parent_id = self.parent_product_id.product_tmpl_id.is_parent_product
        self.is_have_diameter = self.parent_product_id.product_tmpl_id.categ_id.is_have_diameter
        self.is_have_width = self.parent_product_id.product_tmpl_id.categ_id.is_have_width
        self.is_have_thickness = self.parent_product_id.product_tmpl_id.categ_id.is_have_thickness
        self.is_have_length = self.parent_product_id.product_tmpl_id.categ_id.is_have_length
        self.is_have_kg = self.parent_product_id.product_tmpl_id.categ_id.is_have_kg
        self.is_have_across_flat = self.parent_product_id.product_tmpl_id.categ_id.is_have_across_flat
        self.is_have_mesh_number = self.parent_product_id.product_tmpl_id.categ_id.is_have_mesh_number
        self.is_have_mesh_size = self.parent_product_id.product_tmpl_id.categ_id.is_have_mesh_size
        self.is_have_hole_diameter = self.parent_product_id.product_tmpl_id.categ_id.is_have_hole_diameter
        self.is_have_width_2 = self.parent_product_id.product_tmpl_id.categ_id.is_have_width_2
        self.is_have_pitch = self.parent_product_id.product_tmpl_id.categ_id.is_have_pitch
        self.is_have_inner_diameter = self.parent_product_id.product_tmpl_id.categ_id.is_have_inner_diameter
        self.master_width = self.parent_product_id.product_tmpl_id.width
        self.master_length = self.parent_product_id.product_tmpl_id.length
        self.master_diameter = self.parent_product_id.product_tmpl_id.diameter
        self.master_thickness = self.parent_product_id.product_tmpl_id.thickness
        self.master_kg = self.parent_product_id.product_tmpl_id.kg
        self.master_across_flat = self.parent_product_id.product_tmpl_id.across_flat
        self.master_mesh_number = self.parent_product_id.product_tmpl_id.mesh_number
        self.master_mesh_size = self.parent_product_id.product_tmpl_id.mesh_size
        self.master_hole_diameter = self.parent_product_id.product_tmpl_id.hole_diameter
        self.master_width_2 = self.parent_product_id.product_tmpl_id.width_2
        self.master_pitch = self.parent_product_id.product_tmpl_id.pitch
        self.master_inner_diameter = self.parent_product_id.product_tmpl_id.inner_diameter

        self.tax_ids = self.parent_product_id.product_tmpl_id.taxes_id

        if self.order_ids.partner_id:
            property_account_position_id = self.order_ids.partner_id.property_account_position_id if self.order_ids.partner_id.property_account_position_id else self.order_ids.partner_id.parent_id.property_account_position_id
            
            if property_account_position_id:
                for line in property_account_position_id.tax_ids:
                    for tax in self.tax_ids:
                        if line.tax_src_id.id == tax._origin.id:
                            self.tax_ids = [(3, tax.id)]
                            self.tax_ids += line.tax_dest_id

    @api.depends('tax_ids')
    def _compute_tax_price(self):
        for line in self:
            tax_price = 0

            for tax in line.tax_ids:
                tax_price += line.unit_price * tax.amount / 100 * line.quantity

            line.tax_price = tax_price

    @api.depends('parent_product_id','width','length','kg')
    def _compute_child_product(self):
        for line in self:
            product_name = line.name

            if line.parent_product_id.is_parent_product:
                if (line.parent_product_id.product_tmpl_id.width) != line.width:
                    width = line.width

                    if width.is_integer():
                        width = int(width)

                    product_name += " x " + "(W)"+str((width))+ "mm"

                if line.parent_product_id.product_tmpl_id.length != line.length:
                    length = line.length

                    if length.is_integer():
                        length = int(length)

                    product_name += " x " + "(L)"+ str((length))+"mm"

                if line.parent_product_id.product_tmpl_id.kg != line.kg:
                    kg = line.kg

                    if kg.is_integer():
                        length = int(kg)

                    product_name += " x " +str(line.kg)+ "kg"

            line.child_product = product_name

    @api.onchange('width')
    def onchange_width(self):
        for sale_order_line in self.order_ids.order_line:
            if sale_order_line.custom_order_line_id.id == self._origin.id and sale_order_line.custom_order_line_id.id and self._origin.id:
                raise ValidationError("You cannot change product for line that have been confirmed.")

        if self.is_parent_id:
            if self.parent_product_id and self.parent_product_id.product_tmpl_id.categ_id:
                if self.parent_product_id.product_tmpl_id.categ_id.is_have_width:
                    if self.parent_product_id.product_tmpl_id.width > 0 and self.parent_product_id.product_tmpl_id.width != self.width:
                        self.width = 0
                        raise ValidationError("You Cannot change this Product Width.")

                    product_name = self.name

                    if self.parent_product_id.product_tmpl_id.width != self.width:
                        width = self.width

                        if width.is_integer():
                            width = int(width)

                        product_name += " x " + "(W)"+str((width))+ "mm"

                    if self.parent_product_id.product_tmpl_id.length != self.length:
                        length = self.length

                        if length.is_integer():
                            length = int(length)

                        product_name += " x " + "(L)"+ str((length))+"mm"

                    if self.parent_product_id.product_tmpl_id.kg != self.kg:
                        kg = self.kg

                        if kg.is_integer():
                            length = int(kg)

                        product_name += " x " +str(self.kg)+ "kg"

                    self.description = product_name

                else:
                    self.width = 0
                    # raise ValidationError("This Product doesn't have Width.")

    @api.onchange('length')
    def onchange_length(self):
        for sale_order_line in self.order_ids.order_line:
            if sale_order_line.custom_order_line_id.id == self._origin.id and sale_order_line.custom_order_line_id.id and self._origin.id:
                raise ValidationError("You cannot change product for line that have been confirmed.")

        if self.is_parent_id:
            if self.parent_product_id and self.parent_product_id.product_tmpl_id.categ_id:
                if self.parent_product_id.product_tmpl_id.categ_id.is_have_length:
                    if self.parent_product_id.product_tmpl_id.length > 0 and self.parent_product_id.product_tmpl_id.length != self.length:
                        self.length = 0
                        raise ValidationError("You Cannot change this Product Length.")

                    product_name = self.name

                    if self.parent_product_id.product_tmpl_id.width != self.width:
                        width = self.width

                        if width.is_integer():
                            width = int(width)

                        product_name += " x " + "(W)"+str((width))+ "mm"

                    if self.parent_product_id.product_tmpl_id.length != self.length:
                        length = self.length

                        if length.is_integer():
                            length = int(length)

                        product_name += " x " + "(L)"+ str((length))+"mm"

                    if self.parent_product_id.product_tmpl_id.kg != self.kg:
                        kg = self.kg

                        if kg.is_integer():
                            length = int(kg)

                        product_name += " x " +str(self.kg)+ "kg"

                    self.description = product_name

                else:
                    self.length = 0
                    # raise ValidationError("This Product doesn't have Length.")

    @api.onchange('kg')
    def onchange_kg(self):
        for sale_order_line in self.order_ids.order_line:
            if sale_order_line.custom_order_line_id.id == self._origin.id and sale_order_line.custom_order_line_id.id and self._origin.id:
                raise ValidationError("You cannot change product for line that have been confirmed.")

        if self.parent_product_id and self.parent_product_id.product_tmpl_id.categ_id:
            if self.parent_product_id.product_tmpl_id.categ_id.is_have_kg:
                if self.parent_product_id.product_tmpl_id.kg > 0 and self.parent_product_id.product_tmpl_id.kg != self.kg:
                    self.kg = 0
                    raise ValidationError("You Cannot change this Product kg.")

                product_name = self.name

                if self.parent_product_id.product_tmpl_id.width != self.width:
                    width = self.width

                    if width.is_integer():
                        width = int(width)

                    product_name += " x " + "(W)"+str((width))+ "mm"

                if self.parent_product_id.product_tmpl_id.length != self.length:
                    length = self.length

                    if length.is_integer():
                        length = int(length)

                    product_name += " x " + "(L)"+ str((length))+"mm"

                if self.parent_product_id.product_tmpl_id.kg != self.kg:
                    kg = self.kg

                    if kg.is_integer():
                        length = int(kg)

                    product_name += " x " +str(self.kg)+ "kg"

                self.description = product_name

            else:
                self.kg = 0
                # raise ValidationError("This Product doesn't have kg.")

    def _compute_quantity(self):
        for line in self:
            delivered_qty = 0
            invoiced_qty = 0

            for sale_order_line in line.order_ids.order_line:
                if line == sale_order_line.custom_order_line_id:
                    delivered_qty += sale_order_line.qty_delivered
                    invoiced_qty += sale_order_line.qty_invoiced

            line.delivered_qty = delivered_qty
            line.invoiced_qty = invoiced_qty

    def action_product_forecast_report(self):
        self.ensure_one()
        action = self.parent_product_id.action_product_forecast_report()
        action['context'] = {
            'active_id': self.parent_product_id.id,
            'active_model': 'product.product',
            # 'move_to_match_ids': self.ids,
        }
        # if self.picking_type_id.code in self._consuming_picking_types():
        #     warehouse = self.location_id.warehouse_id
        # else:
        #     warehouse = self.location_dest_id.warehouse_id

        # if warehouse:
        #     action['context']['warehouse'] = warehouse.id
        return action

    @api.onchange('unit_price')
    def onchange_unit_price(self):
        if self.parent_product_id:
            if not self.parent_product_id.is_parent_product:
                if self.unit_price != self.parent_product_id.list_price:
                    if self.unit_price < self.parent_product_id.standard_price:
                        self.env.user.notify_warning(message='Sale Price is lower than Cost Price.')

    @api.depends('order_ids', 'order_ids.date_order')
    def _compute_date_order(self):
        for line in self:
            line.date_order = line.order_ids.date_order

    sequence = fields.Integer('Sequence', defeault=10)

    parent_product_id = fields.Many2one('product.product', string='Parent Product')
    parent_product_categ_id = fields.Many2one('product.category', string='Product Category', related='parent_product_id.categ_id')
    name = fields.Char('Product',related='parent_product_id.product_tmpl_id.name')
    is_parent_id = fields.Boolean('Have Parent')
    description = fields.Text('Description')

    width = fields.Float('Width')
    length = fields.Float('Length')
    diameter = fields.Float('Diameter(OD)')
    thickness = fields.Float('Thickness')
    electrode_number = fields.Char('Electrode Number', copy=False)
    batch_number = fields.Char('Batch Number', copy=False)
    kg = fields.Float('Kg')
    across_flat = fields.Float('Across Flat')
    mesh_number = fields.Float('Mesh Number')
    mesh_size = fields.Float('Mesh Size')
    hole_diameter = fields.Float('Hole Diameter')
    width_2 = fields.Float('Width 2')
    pitch = fields.Float('Pitch')
    inner_diameter = fields.Float('Inner Diameter')
    discount = fields.Float('Discount %')

    master_width = fields.Float('Master Width')
    master_length = fields.Float('Master Length')
    master_diameter = fields.Float('Master Diameter(OD)')
    master_thickness = fields.Float('Master Thickness')
    master_kg = fields.Float('Master Kg')
    master_across_flat = fields.Float('Master Across Flat')
    master_mesh_number = fields.Float('Master Mesh Number')
    master_mesh_size = fields.Float('Master Mesh Size')
    master_hole_diameter = fields.Float('Master Hole Diameter')
    master_width_2 = fields.Float('Master Width 2')
    master_pitch = fields.Float('Master Pitch')
    master_inner_diameter = fields.Float('Master inner_diameter')

    order_ids = fields.Many2one('sale.order', string='Order Reference', ondelete='cascade', index=True, copy=False)
    currency_id = fields.Many2one(related='order_ids.currency_id', depends=['order_ids.currency_id'], store=True, string='Currency')
    dimension_uom_id = fields.Many2one('uom.uom', string='Dimension UoM')
    product_uom_id = fields.Many2one('uom.uom', string='UoM')
    unit_price = fields.Float('Unit Price')
    tax_ids = fields.Many2many('account.tax', string='Taxes')
    tax_price = fields.Float('Tax Price', compute='_compute_tax_price')
    child_product = fields.Char('Child Product', compute='_compute_child_product')
    discount = fields.Float(string='Discount (%)', digits='Discount', default=0.0)
    discount_overall = fields.Float('Overall Discount %',related='order_ids.discount_overall')
    quantity = fields.Float('Qty', default=1.0)
    subtotal = fields.Monetary(compute='_compute_amount',string='Subtotal',store=True,)
    price_total = fields.Float(compute='_compute_amount', string='Total', store=True)
    price_tax = fields.Float(compute='_compute_amount', string='Total Tax', store=True)
    
    is_have_diameter = fields.Boolean('Is Have Diameter(OD)')
    is_have_width = fields.Boolean('Is Have Width')
    is_have_thickness = fields.Boolean('Is Have Thickness')
    is_have_length = fields.Boolean('Is Have Length')
    is_have_kg = fields.Boolean('Is Have Kg')
    is_have_across_flat = fields.Boolean('Is Have Across Flat')
    is_have_mesh_number = fields.Boolean('Is Have Mesh Number')
    is_have_mesh_size = fields.Boolean('Is Have Mesh Size')
    is_have_hole_diameter = fields.Boolean('Is Have Hole Diameter')
    is_have_width_2 = fields.Boolean('Is Have Width 2')
    is_have_pitch = fields.Boolean('Is Have Pitch')
    is_have_inner_diameter = fields.Boolean('Is Have Inner Diameter')

    notes = fields.Text('Notes')

    qty_available = fields.Float('Available Qty', related='parent_product_id.qty_available')
    forecast_availability = fields.Float('Forecasted Qty', related='parent_product_id.virtual_available')

    delivered_qty = fields.Float('Delivered', compute='_compute_quantity')
    invoiced_qty = fields.Float('Invoiced', compute='_compute_quantity')

    product_type = fields.Selection(related='parent_product_id.detailed_type', readonly=True)

    partner_id = fields.Many2one('res.partner', string='Customer', related='order_ids.partner_id')
    date_order = fields.Datetime(string='Date', compute='_compute_date_order', store=True)
    user_id = fields.Many2one('res.users', string='Salesperson', related='order_ids.user_id')
    state = fields.Selection([
        ('draft', 'Quotation'),
        ('sent', 'Quotation Sent'),
        ('sale', 'Sales Order'),
        ('done', 'Locked'),
        ('cancel', 'Cancelled'),
        ], string='Status', related='order_ids.state')

    is_woocommerce = fields.Boolean('Is Woocomerce')

    total_length = fields.Float('Total Length', compute="_compute_total_length")
    
    @api.depends('quantity', 'length')
    def _compute_total_length(self):
        for res in self:
            if res.is_parent_id:
                res.total_length = res.quantity * res.length
            else:
                res.total_length = res.length
