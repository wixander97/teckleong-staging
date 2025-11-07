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
import copy
import itertools
from collections import defaultdict

import string
from itertools import combinations

import logging
_logger = logging.getLogger(__name__)

class JobOrder(models.Model):
    _name = "job.order"
    _description = "Job Order"

    def _rearrange_piece_after_cutting(self, optimal_cut_plan):
        for product, plans in optimal_cut_plan.items():
            for plan in plans:
                cutting_ids = self.job_order_cutting_ids.sorted(key=lambda cut: cut.balance_ids.length_balance).filtered(lambda cut: cut.original_length == plan['big_rod'] and cut.product_id.parent_product_id == product and cut.sequence != 100)
                cutting = cutting_ids[0]
                line_ids = []
                cut_pieces = {key: plan['cut_pieces'].count(key) for key in plan['cut_pieces']}
                for piece in cut_pieces:
                    line_id = self.job_order_line_ids.filtered(lambda line: line.requested_length == piece and line.product_id.parent_product_id == product)
                    line_ids.append((0, 0, {'job_order_line_id': line_id.id, 'done_quantity': cut_pieces[piece]}))

                cutting.line_ids = False
                cutting.write({
                    'sequence': 100,
                    'line_ids': line_ids
                })
                cutting.onchange_line_ids()
                if cutting.balance_ids.length_balance == 0:
                    cutting.balance_ids.unlink()
        remaining_cutting_ids = self.job_order_cutting_ids.filtered(lambda cut: cut.sequence != 100)
        remaining_cutting_ids.unlink()

    def _get_product_stock(self, parent_product):
        stocks = []
        stock_list = []
        product_arr = self.env['product.product'].search([
                ('parent_product_id', '=', parent_product.id),
                ('qty_available', '>', 0)])
        stock_quant = self.env['stock.quant'].search([
            ('product_id', 'in', product_arr._ids),
            ('quantity', '>', 0), ('on_hand', '=', True)])
        if self.type == 'single_location':
            stock_quant = stock_quant.filtered(lambda stock: stock.location_id.warehouse_id == self.location_id)

        for stock in stock_quant:
            product_length = round(stock.product_id.product_tmpl_id.length, 2)
            product_width = round(stock.product_id.product_tmpl_id.width, 2)
            stocks.append({
                'id': stock.id,
                'quantity': stock.quantity,
                'product': stock.product_id.id,
                'product_length': product_length,
                'product_width': product_width,
                'product_kg': round(stock.product_id.product_tmpl_id.kg, 2),
                'remaining_areas': [(0, 0, product_width, product_length)],
                'cuts': []
            })
        for item in stocks:
            stock_list.extend([copy.deepcopy(item) for _ in range(int(item['quantity']))])
        return stock_list
    
    def _set_length_width_products(self, length_width_requirement, requirements):
        
        def normalize_dimensions(width, length):
            return sorted((width, length))
        
        def sort_stock_list(stock_list):
            for index, sheet in enumerate(stock_list):
                width, length = normalize_dimensions(sheet['product_width'], sheet['product_length'])
                sheet['product_width'] = width
                sheet['product_length'] = length
                sheet['number'] = index
                for i, (x1, y1, rw, rh) in enumerate(sheet['remaining_areas']):
                    rw, rh = normalize_dimensions(rw, rh)
                    sheet['remaining_areas'][i] = (x1, y1, rw, rh)
            return stock_list
        
        def sort_requirement_list(requirement_list):
            for request in requirement_list:
                width, length = normalize_dimensions(request['requested_width'], request['requested_length'])
                request['requested_width'] = width
                request['requested_length'] = length
            return requirement_list

        def can_fit(sheet, panel):
            for index, (x, y, rw, rh) in enumerate(sheet['remaining_areas']):
                if panel['requested_width'] <= rw and panel['requested_length'] <= rh:
                    return True, index
            return False, -1
        
        def cut_panel(sheet, panel):
            can_cut, index = can_fit(sheet, panel)
            if not can_cut:
                panel['requested_width'], panel['requested_length'] = panel['requested_length'], panel['requested_width']
                can_cut, index = can_fit(sheet, panel)
                if not can_cut:
                    return False

            x, y, rw, rh = sheet['remaining_areas'].pop(index)
            pw, ph = panel['requested_width'], panel['requested_length']

            if rw - pw > 0:
                sheet['remaining_areas'].append((x + pw, y, rw - pw, ph))
            if rh - ph > 0:
                sheet['remaining_areas'].append((x, y + ph, rw, rh - ph))

            sheet['cuts'].append({'panel': panel.copy(), 'position': (x, y)})
            return True
        
        def cut_panel_optimized(sheet, panel):
            best_fit = None
            best_area_index = -1
            for index, (x, y, rw, rh) in enumerate(sheet['remaining_areas']):
                for rotation in [(panel['requested_width'], panel['requested_length']),
                                (panel['requested_length'], panel['requested_width'])]:
                    pw, ph = rotation
                    if pw <= rw and ph <= rh:
                        remaining_area = (rw - pw) * rh + rw * (rh - ph)
                        if best_fit is None or remaining_area < best_fit:
                            best_fit = remaining_area
                            best_area_index = index
                            panel['requested_width'], panel['requested_length'] = pw, ph
            if best_area_index == -1:
                return False

            x, y, rw, rh = sheet['remaining_areas'].pop(best_area_index)
            pw, ph = panel['requested_width'], panel['requested_length']

            if rw - pw > 0:
                sheet['remaining_areas'].append((x + pw, y, rw - pw, ph))
            if rh - ph > 0:
                sheet['remaining_areas'].append((x, y + ph, rw, rh - ph))
            
            sheet['cuts'].append({'panel': panel.copy(), 'position': (x, y)})
            return True
        
        def cut_panels_on_sheets_v1(panels, sheets):
            sheets.sort(key=lambda s: s['product_width'] * s['product_length'])
            unfitted_panels = []

            for panel in panels:
                fitted = False
                for sheet in sheets:
                    if cut_panel(sheet, panel):
                        fitted = True
                        break
                if not fitted:
                    unfitted_panels.append(panel)
            
            return sheets, unfitted_panels

        def cut_panels_on_sheets_v2(panels, sheets):
            panels.sort(key=lambda p: p['requested_width'] * p['requested_length'], reverse=True)
            sheets.sort(key=lambda s: s['product_width'] * s['product_length'])
            unfitted_panels = []
            used_sheets = []
            
            for panel in panels:
                fitted = False
                for sheet in sheets:
                    if sheet in used_sheets or len(used_sheets) < 2:
                        if cut_panel(sheet, panel):
                            fitted = True
                            if sheet not in used_sheets:
                                used_sheets.append(sheet)
                            break
                if not fitted:
                    unfitted_panels.append(panel)
            
            return sheets, unfitted_panels
        
        def cut_panels_with_rotation(panels, sheets):
            sheets.sort(key=lambda s: s['product_width'] * s['product_length'])
            unfitted_panels = []
            for panel in panels:
                fitted = False
                for sheet in sheets:
                    if cut_panel_optimized(sheet, panel):
                        fitted = True
                        break
                if not fitted:
                    unfitted_panels.append(panel)
            return sheets, unfitted_panels

        def calculate_wastage(sheets):
            total_wastage = 0
            for sheet in sheets:
                total_area = sheet['product_width'] * sheet['product_length']
                used_area = sum(
                    cut['panel']['requested_width'] * cut['panel']['requested_length'] for cut in sheet['cuts']
                )
                total_wastage += ((total_area - used_area) / total_area) * 100 if total_area > 0 else 0
            return total_wastage / len(sheets)
	  

        def calculate_weighted_wastage(sheets, wastage, unfitted_panels_count, remaining_sheets):
            sheet_penalty = 5.0
            unfitted_penalty = 10.0
            remaining_area_penalty = 2.0

            sheets_used = len([sheet for sheet in sheets if sheet["cuts"]])

            return (
                wastage
                + (sheets_used - 1) * sheet_penalty
                + unfitted_panels_count * unfitted_penalty
                + remaining_area_penalty * remaining_sheets
            )

        def can_merge_area(x1, y1, w1, h1, x2, y2, w2, h2):
            if (x1 + w1 == x2 and y1 == y2) or (x2 + w2 == x1 and y2 == y1):
                return True
            if (y1 + h1 == y2 and x1 == x2) or (y2 + h2 == y1 and x2 == x1):
                return True
            return False

        def process_remaining_areas(sheets):
            for sheet in sheets:
                sheet['remaining_areas'] = sorted(sheet['remaining_areas'], key=lambda x: x[2] * x[3], reverse=True)

                merged_areas = []

                for area in sheet['remaining_areas']:
                    x, y, rw, rh = area
                    merged = False
                    for i, (mx, my, mrw, mrh) in enumerate(merged_areas):
                        if can_merge_area(x, y, rw, rh, mx, my, mrw, mrh):
                            new_mrw = max(mx + mrw, x + rw) - mx
                            new_mrh = max(my + mrh, y + rh) - my
                            merged_areas[i] = (mx, my, new_mrw, new_mrh)
                            merged = True
                            break
                    if not merged:
                        merged_areas.append(area)

                sheet['remaining_areas'] = merged_areas

            return sheets

        def optimal_cut_panels(panels, sheets):
            sheets_scenario_1 = copy.deepcopy(sheets)
            sheets_used_1, unfitted_panels_1 = cut_panels_on_sheets_v1(panels, sheets_scenario_1)
            wastage_1 = calculate_wastage(sheets_used_1)
            remaining_sheets_1 = sum(len(sheet['remaining_areas']) for sheet in sheets_used_1)
            weighted_wastage_1 = calculate_weighted_wastage(sheets_used_1, wastage_1, len(unfitted_panels_1), remaining_sheets_1)

            sheets_scenario_2 = copy.deepcopy(sheets)
            sheets_used_2, unfitted_panels_2 = cut_panels_on_sheets_v2(panels, sheets_scenario_2)
            wastage_2 = calculate_wastage(sheets_used_2)
            remaining_sheets_2 = sum(len(sheet['remaining_areas']) for sheet in sheets_used_2)
            weighted_wastage_2 = calculate_weighted_wastage(sheets_used_2, wastage_2, len(unfitted_panels_2), remaining_sheets_2)

            sheets_scenario_3 = copy.deepcopy(sheets)
            sheets_used_3, unfitted_panels_3 = cut_panels_with_rotation(panels, sheets_scenario_3)
            wastage_3 = calculate_wastage(sheets_used_3)
            remaining_sheets_3 = sum(len(sheet['remaining_areas']) for sheet in sheets_used_3)
            weighted_wastage_3 = calculate_weighted_wastage(sheets_used_3, wastage_3, len(unfitted_panels_3), remaining_sheets_3)

            if weighted_wastage_1 <= weighted_wastage_2 and weighted_wastage_1 <= weighted_wastage_3:
                return sheets_used_1, unfitted_panels_1, wastage_1
            elif weighted_wastage_2 <= weighted_wastage_1 and weighted_wastage_2 <= weighted_wastage_3:
                return sheets_used_2, unfitted_panels_2, wastage_2
            else:
                return sheets_used_3, unfitted_panels_3, wastage_3

        
        for cutting in self.job_order_cutting_ids:
            cutting.write({'sequence': 0})
        
        for parent_product in length_width_requirement:
            stock_list = self._get_product_stock(parent_product)

            if not stock_list:
                raise ValidationError(f"There is no stock available to fulfill these requirements !!!")

            data = requirements[parent_product]
            requirement_list = []
            for item in data:
                requirement_list.extend([{**item} for _ in range(int(item['quantity']))])
            panels = sort_requirement_list(requirement_list)
            sheets = sort_stock_list(stock_list)
            
            
            fitted_sheet_data, unfitted_sheet_data, wastage = optimal_cut_panels(panels, sheets)
            quantity_not_satisfied = ''
            if unfitted_sheet_data:
                for unfitted_sheet in unfitted_sheet_data:
                    unfitted_product = self.env['product.product'].browse(unfitted_sheet['product_id'])
                    quantity_not_satisfied += '\n- ' + unfitted_product.name + ' required ' + str(unfitted_sheet['quantity']) + " more"
                raise ValidationError(f"The re-quested product quantity not sufficient {quantity_not_satisfied}")
            fitted_sheets = [item for item in fitted_sheet_data if item['cuts']]
            fitted_sheets = process_remaining_areas(fitted_sheets)
            self.sync_2D_cutting_output(fitted_sheets)
        
        for cutting in self.job_order_cutting_ids:
            if cutting.sequence != 99 and cutting.is_have_width and cutting.is_have_width:
                cutting.unlink()
    
    def sync_2D_cutting_output(self, cutting_data):
        job_order_cutting_ids = []

        def merge_data(data):
            merged = defaultdict(lambda: {
                "quantity": 0.0,
                "remaining_areas": [],
                "cuts": [],
            })

            for item in data:
                key = (item['id'], item['product'], item['product_length'], item['product_width'])
                merged[key]['quantity'] += item['quantity']
                merged[key]['remaining_areas'].extend(item['remaining_areas'])
                merged[key]['cuts'].extend(item['cuts'])
                for static_field in ['product_kg']:
                    if static_field not in merged[key]:
                        merged[key][static_field] = item[static_field]

            result = []
            for key, value in merged.items():
                id_, product, product_length, product_width = key
                result.append({
                    "id": id_,
                    "product": product,
                    "product_length": product_length,
                    "product_width": product_width,
                    "quantity": value['quantity'],
                    "remaining_areas": value['remaining_areas'],
                    "cuts": value['cuts'],
                    "product_kg": value['product_kg'],
                })

            return result

        cutting_data = merge_data(cutting_data)

        for cutting in cutting_data:
            line_ids = []
            balance_ids = []
            panel_quantity_map = {}
        
            for cuts in cutting['cuts']:
                panel_id = cuts['panel']['id']
                panel_quantity = 1
                
                if panel_id in panel_quantity_map:
                    panel_quantity_map[panel_id] += panel_quantity
                else:
                    panel_quantity_map[panel_id] = panel_quantity

            stock_id = self.env['stock.quant'].browse(cutting['id'])
            remaining_area_dict = defaultdict(int)

            for tup in cutting['remaining_areas']:
                remaining_area_dict[tup] += 1

            remaining_area_dict = dict(remaining_area_dict)

            for (x, y, rw, rh), qty in remaining_area_dict.items():
                balance_ids.append((0, 0, {
                    'length_balance': rh,
                    'width_balance': rw,
                    'qty': qty,
                    'lot_name': stock_id.lot_id.name,
                    'receipt_location_id': stock_id.location_id.id,
                }))
            
            for panel_id, total_quantity in panel_quantity_map.items():
                line_ids.append((0, 0, {
                    'job_order_line_id': panel_id,
                    'done_quantity': total_quantity,
                }))

            job_order_cutting_ids.append((0, 0, {
                'job_order_id_char': int(self.id),
                'job_order_id': int(self.id),
                'stock_quantity_id': cutting['id'],
                'line_ids': line_ids,
                'balance_ids': balance_ids,
                'sequence': 99,
            }))
        self.write({'job_order_cutting_ids': job_order_cutting_ids})
    
    def action_best_cut(self):
        
        for job_order in self:
            requested_parent_products = job_order.job_order_line_ids.mapped('product_id.parent_product_id')
            requirements = {}
            for requested_product in requested_parent_products:
                cutting_ids = job_order.job_order_line_ids.filtered(lambda c: c.product_id.parent_product_id == requested_product).sorted(key=lambda cut: cut.requested_length)
                requirements[requested_product] = []
                for requirement_cutting in cutting_ids:
                    requirements[requested_product].append({
                        'id': requirement_cutting.id,
                        'requested_width': requirement_cutting.requested_width,
                        'requested_length': requirement_cutting.requested_length,
                        'requested_thickness': requirement_cutting.requested_thickness,
                        'requested_diameter': requirement_cutting.requested_diameter,
                        'requested_kg': requirement_cutting.requested_kg,
                        'quantity': requirement_cutting.quantity,
                        'product_id': requirement_cutting.product_id.id,
                        'is_have_width': requirement_cutting.is_have_width,
                        'is_have_length': requirement_cutting.is_have_length,
                        'is_have_kg': requirement_cutting.is_have_kg,
                    })
            length_requirement = list(filter(lambda x: x['is_have_length'] and not x['is_have_width'], requirements))
            width_requirement = list(filter(lambda x: x['is_have_width'] and not x['is_have_length'], requirements))
            length_width_requirement = list(filter(lambda x: x['is_have_length'] and x['is_have_width'], requirements))
            kg_requirement = list(filter(lambda x: x['is_have_kg'], requirements))
        if bool(length_requirement):
            pass
        if bool(width_requirement):
            pass
        if bool(length_width_requirement):
            self._set_length_width_products(length_width_requirement, requirements)
        if bool(kg_requirement):
            pass

    def merge_cutting_line_ids(self):

        def find_best_fit(pieces, rod):
            best_fit = []
            min_waste = rod

            for i in range(1, len(pieces) + 1):
                for comb in combinations(pieces, i):
                    if sum(comb) <= rod and rod - sum(comb) < min_waste:
                        best_fit = comb
                        min_waste = rod - sum(comb)

            return best_fit, min_waste

        products = self.job_order_cutting_ids.mapped('product_id.parent_product_id')
        cuttings = {product : {} for product in products}
        for product in cuttings:
            big_rods = self.job_order_cutting_ids.filtered(lambda c: c.product_id.parent_product_id == product).sorted(key=lambda cut: cut.original_length).mapped('original_length')
            small_pieces = []
            for cut in self.job_order_line_ids.filtered(lambda c: c.product_id.parent_product_id == product).sorted(key=lambda cut: cut.requested_length):
                small_pieces.extend([cut.requested_length] * int(cut.quantity))
            cuttings[product] = {
                'dimension_type': '1D' if product.is_have_length and product.is_have_diameter else '2D' if product.is_have_length and product.is_have_width and product.is_have_thickness else '',
                'big_rods': big_rods,
                'small_pieces': small_pieces,
            }

        cut_plan = {product : [] for product in products}
        for cuts in cuttings:
            big_rods = cuttings[cuts]['big_rods']
            small_pieces = cuttings[cuts]['small_pieces']

            big_rods.sort()

            optimal_cut_plan = []

            for rod in big_rods:
                best_cut, waste = find_best_fit(small_pieces, rod)

                for piece in best_cut:
                    small_pieces.remove(piece)


                if rod != waste:
                    optimal_cut_plan.append({
                        "big_rod": rod,
                        "cut_pieces": list(best_cut),
                        "remaining_length": waste
                    })
            cut_plan[cuts] = optimal_cut_plan


        self._rearrange_piece_after_cutting(cut_plan)

    def action_get_line_ids_value(self):
        for job in self:
            for line in job.job_order_line_ids:
                line.write({
                    'requested_width': line.product_id.width,
                    'requested_length': line.product_id.length,
                    'requested_kg': line.product_id.kg,
                    'requested_diameter': line.product_id.diameter,
                    'requested_thickness': line.product_id.thickness,
                    'requested_across_flat' : line.product_id.across_flat,
                    'requested_width_2' : line.product_id.width_2,
                    'requested_mesh_number' : line.product_id.mesh_number,
                    'requested_mesh_size' : line.product_id.mesh_size,
                    'requested_hole_diameter' : line.product_id.hole_diameter,
                    'requested_pitch' : line.product_id.pitch,
                    'requested_inner_diameter' : line.product_id.inner_diameter,
                    'product_uom_id': line.product_id.uom_id.id,
                })

    def action_set_balance_qty(self):
        for job in self:
            for cutting in job.job_order_cutting_ids:
                for balance in cutting.balance_ids:
                    balance.qty = 1

    def action_get_do_id_stored(self):
        for job in self:
            job.do_id_stored = job.do_id

    def action_get_stored_field(self):
        for job in self:
            for cutting in job.job_order_cutting_ids:
                stock_quantity_id_stored = ''

                if cutting.stock_quantity_id:
                    stock_quantity_id_stored = cutting.stock_quantity_id.product_id.name + "(" + cutting.stock_quantity_id.lot_id.name + ")"

                cutting.write({
                    'on_hand_quantity_stored': cutting.on_hand_quantity,
                    'stock_quantity_id_stored': stock_quantity_id_stored,
                    'product_id_stored': cutting.product_id.id,
                    'lot_id_stored': cutting.lot_id.name,
                    'lot_location_id_stored': cutting.lot_location_id.complete_name,
                })

    @api.model
    def create(self, vals):
        if not vals.get('name'):
            vals['name'] = self.env['ir.sequence'].next_by_code('job.order')

        vals['do_id_stored'] = self.do_id.id

        res = super(JobOrder, self).create(vals)

        return res

    @api.returns('self', lambda value: value.id)
    def copy(self, default=None):
        default = dict(default or {})

        if self.name:
            default['name'] = self.name + "-C"

        return super(JobOrder, self).copy(default)

    def action_confirm(self):
        self.do_id_stored = self.do_id
        self.state = 'confirm'

        if self.type == 'single_location':
            if self.job_order_parent_id:
                batch_number = []

                for job in self.job_order_parent_id.job_order_child_ids:
                    for line in job.job_order_line_ids:
                        if line.custom_order_line_id:
                            batch = list(filter(lambda x: x['custom_line_id'] == line.custom_order_line_id.id ,batch_number))

                            if batch:
                                if line.batch_number:
                                    current_batch = line.batch_number.split(";")

                                    for batch_line in current_batch:
                                        if not batch[0]['lot_name'].find(batch_line) != -1:
                                            batch[0]['lot_name'] += line.batch_number

                            else:
                                if line.batch_number:
                                    batch_number.append({
                                        'custom_line_id': line.custom_order_line_id.id,
                                        'lot_name': line.batch_number
                                    })

                for rec in batch_number:
                    self.env['sale.order.custom.dimension.line'].browse(rec['custom_line_id']).batch_number = rec['lot_name'][:-1]

            else:
                for line in self.job_order_line_ids:
                    line.custom_order_line_id.batch_number = ''

                    if line.custom_order_line_id:
                        batch_number = False

                        if not line.custom_order_line_id.batch_number:
                            line.custom_order_line_id.batch_number = line.batch_number
                        else:
                            batch_number = line.batch_number.split(";")

                            for batch in batch_number:
                                if not line.custom_order_line_id.batch_number.find(batch) != -1:
                                    line.custom_order_line_id.batch_number += batch + ';'

                    line.custom_order_line_id.batch_number = line.custom_order_line_id.batch_number[:-1]

    def action_done(self):
        """Mark the Job Order as done and handle stock operations."""
        self.ensure_one()
        self.do_id_stored = self.do_id
        self.state = 'done'

        if self.type == 'single_location':
            # Validate stock availability before proceeding
            self._validate_stock_availability()

            # Update batch numbers
            self._update_batch_numbers()

            # Get picking types for DO and receipts
            do_picking, receipt_picking = self._get_picking_types()

            # Create the DO picking
            do = self._create_picking(do_picking)

            receipts = self.env['stock.picking']
            for cutting in self.job_order_cutting_ids:
                # Process cutting data and create move lines
                self._process_cutting(cutting, do, receipts, do_picking, receipt_picking)

            # Assign pickings to the job order
            self.picking_ids = receipts + do

            # Validate pickings only if stock is available
            self._validate_and_update_pickings()

    def _validate_stock_availability(self):
        """Ensure sufficient stock is available before proceeding."""
        for line in self.job_order_line_ids:
            if line.quantity > line.product_id.qty_available:
                raise ValidationError(
                    _("Insufficient stock for product '%s'. Available: %s, Required: %s.") %
                    (line.product_id.display_name, line.product_id.qty_available, line.quantity)
                )

    def _process_cutting(self, cutting, do, receipts, do_picking, receipt_picking):
        """Process cutting data and create move lines."""
        self._store_cutting_data(cutting)
        self._create_do_move_lines(do, cutting, do_picking)
        receipts = self._process_cutting_lines(cutting, receipts, receipt_picking)
        self._process_cutting_balances(cutting, receipts, receipt_picking)

    def _create_do_move_lines(self, do, cutting, do_picking):
        """Create move lines for the Delivery Order."""
        qty_done = sum(line.done_quantity for line in cutting.line_ids) if cutting.is_no_cutting else 1

        # Ensure stock is available before creating move lines
        if qty_done > cutting.product_id.qty_available:
            raise ValidationError(
                _("Insufficient stock for product '%s'. Available: %s, Required: %s.") %
                (cutting.product_id.display_name, cutting.product_id.qty_available, qty_done)
            )

        do.move_line_ids_without_package = [(0, 0, {
            'product_id': cutting.product_id.id,
            'location_id': cutting.lot_location_id.id,
            'location_dest_id': do_picking.default_location_dest_id.id,
            'lot_id': cutting.lot_id.id,
            'qty_done': qty_done,
            'product_uom_id': cutting.parent_product_id.uom_id.id,
        })]

    def _validate_and_update_pickings(self):
        """Validate and update all pickings."""
        for picking in self.picking_ids:
            if any(line.qty_done > line.product_id.qty_available for line in picking.move_line_ids_without_package):
                raise ValidationError(
                    _("Insufficient stock for one or more products in the Job Order. Please check stock levels.")
                )
            picking.action_confirm()
            picking.button_validate()
        self._update_move_lines()

    def action_draft(self):
        self.state = 'draft'

    def action_cancel(self):
        self.state = 'cancel'

        if self.type == 'single_location':
            if self.do_id.state == 'done':
                raise ValidationError("Cannot cancel Job Order that already done.")

            for cutting in self.job_order_cutting_ids:
                for cutting_line in cutting.line_ids:
                    selected_move = self.do_id.move_ids_without_package.filtered(lambda x: x.sale_line_id.custom_order_line_id == cutting_line.job_order_line_id.custom_order_line_id)                    
                    selected_lot = self.env['stock.production.lot'].search([('name', '=', cutting.lot_id.name), ('product_id', '=', cutting_line.job_order_line_id.product_id.id)])

                    for move_line in selected_move.move_line_ids:
                        if move_line.lot_id == selected_lot:
                            move_line.unlink()

            do_move_line = self.env['stock.move.line']
            receipt_move_line = self.env['stock.move.line']

            for picking in self.picking_ids:
                if picking.picking_type_id.code == 'outgoing':
                    do_move_line += picking.move_line_ids_without_package

                elif picking.picking_type_id.code == 'incoming':
                    for move in picking.move_ids_without_package:
                        for move_line in move.move_line_ids:
                            if move_line.lot_id and move_line.qty_done > 0:
                                receipt_move_line += move_line

            picking_obj = self.env['stock.picking.type']
            receipt_picking = picking_obj.search([('code', '=', 'incoming'), ('warehouse_id', '=', self.location_id.id), ('sequence_code', '=', 'JO-IN')])
            do_picking = picking_obj.search([('code', '=', 'outgoing'), ('warehouse_id', '=', self.location_id.id), ('sequence_code', '=', 'JO-OUT')])

            do = self.env['stock.picking'].create({
                'origin': self.name,
                'picking_type_id': do_picking.id,
                'location_id': do_picking.default_location_src_id.id,
                'location_dest_id': do_picking.default_location_dest_id.id,
                'immediate_transfer': True,
            })

            receipt = self.env['stock.picking'].create({
                'origin': self.name,
                'picking_type_id': receipt_picking.id,
                'location_id': receipt_picking.default_location_src_id.id,
                'location_dest_id': receipt_picking.default_location_dest_id.id,
                'immediate_transfer': True,
            })

            for receipt_line in receipt_move_line:
                do.move_line_ids_without_package = [(0, 0, {
                    'product_id': receipt_line.product_id.id,
                    'location_id':  receipt_line.location_dest_id.id,
                    'location_dest_id': do_picking.default_location_dest_id.id,
                    'lot_id': receipt_line.lot_id.id,
                    'qty_done': receipt_line.qty_done,
                    'product_uom_id': receipt_line.product_id.uom_id.id,
                })]

            for do_line in do_move_line:
                receipt.move_ids_without_package = [(0, 0, {
                    'name': do_line.product_id.partner_ref,
                    'product_uom': do_line.product_id.uom_id.id,
                    'location_id': receipt.location_id.id,
                    'location_dest_id': receipt.location_dest_id.id,
                    'product_id': do_line.product_id.id,
                    'move_line_nosuggest_ids': [(0, 0, {
                        'qty_done': do_line.qty_done,
                        'product_id': do_line.product_id.id,
                        'product_uom_id': do_line.product_id.uom_id.id,
                        'location_id': receipt.location_id.id,
                        'location_dest_id': do_line.location_id.id,
                        'picking_id': receipt.id,
                        'lot_name': do_line.lot_id.name,
                    })]
                })]

            operations = receipt + do

            for operation in operations:
                operation.action_confirm()
                operation.button_validate()

    def action_view_receipt(self):
        self.ensure_one()

        return {
            'name': 'Receipts',
            'type': 'ir.actions.act_window',
            'view_mode': 'tree,form',
            'res_model': 'stock.picking',
            'domain': [('id', 'in', self.mapped('picking_ids').ids)],
        }

    @api.depends('name')
    def _compute_job_order_id_char(self):
        for job in self:
            if job.id:
                job.job_order_id_char = int(job.id)
            else:
                job.job_order_id_char = False

    @api.depends('sale_order_id')
    def _compute_do_id(self):
        for job in self:
            do_id = False

            if job.sale_order_id:
                do_id = self.env['stock.picking'].search([('origin', '=', job.sale_order_id.name), ('state', 'in', ['confirmed', 'assigned'])], limit=1)

            job.do_id = do_id

    @api.depends('job_order_cutting_ids')
    def _compute_validation_status(self):
        for job in self:
            validation_status = 'clear'

            for cutting in job.job_order_cutting_ids:
                if cutting.is_exceed_deviation:
                    validation_status = 'check'

                    break;

                for cutting_balance in cutting.balance_ids:
                    if not cutting_balance.is_validate:
                        validation_status = 'check'

                        break;

            job.validation_status = validation_status

    @api.onchange('location_id')
    def onchange_location_id(self):
        self.job_order_cutting_ids = False

    def _compute_delivery_date(self):
        for job in self:
            delivery_date = False

            if job.do_id:
                delivery_date = job.do_id.scheduled_date

            elif job.do_id_stored:
                delivery_date = job.do_id_stored.scheduled_date

            job.delivery_date = delivery_date

    def compute_driver(self):
        for job in self:
            driver = ''

            if job.do_id:
                if job.do_id.driver == 'driver_a':
                    driver = 'Driver A'

                if job.do_id.driver == 'driver_b':
                    driver ='Driver B'

                if job.do_id.driver == 'driver_c':
                    driver = 'Driver C'

                if job.do_id.driver == 'driver_d':
                    driver = 'Driver D'

            elif job.do_id_stored:
                if job.do_id_stored.driver == 'driver_a':
                    driver = 'Driver A'

                if job.do_id_stored.driver == 'driver_b':
                    driver ='Driver B'

                if job.do_id_stored.driver == 'driver_c':
                    driver = 'Driver C'

                if job.do_id_stored.driver == 'driver_d':
                    driver = 'Driver D'

            job.driver = driver

    name = fields.Char('Reference')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirm', 'Confirm'),
        ('done', 'Done'),
        ('cancel', 'Cancel'),
    ], string='Job Status', default='draft')
    type = fields.Selection([
        ('single_location', 'Single Location'),
        ('multiple_location', 'Multiple Location')
    ], string='Type', default='single_location')
    job_order_child_ids = fields.One2many('job.order', 'job_order_parent_id', string='Job Order Child')
    job_order_parent_id = fields.Many2one('job.order', string='Job Order Parent')
    job_order_line_ids = fields.One2many('job.order.line', 'job_order_id', string='Job Order Line', copy=True)
    location_id = fields.Many2one('stock.warehouse', string='Location')
    sale_order_id = fields.Many2one(comodel_name='sale.order', string='Sale Order')
    is_child = fields.Boolean('Is Child')
    datetime = fields.Datetime('Datetime')
    picking_ids = fields.Many2many('stock.picking', string='Pickings')
    is_delivered = fields.Boolean('Delivered')
    job_order_cutting_ids = fields.One2many('job.order.cutting', 'job_order_id', string='Job Order Cutting', copy=True)
    job_order_id_char = fields.Integer('Job Order Char', compute='_compute_job_order_id_char')
    job_order_line_id = fields.Many2one('job.order.line', 'Job Order Line Id')
    customer_id = fields.Many2one('res.partner', 'Customer', related='sale_order_id.partner_id')
    do_id = fields.Many2one('stock.picking', 'Delivery Order', compute='_compute_do_id', store=False)
    do_id_stored = fields.Many2one('stock.picking', string='Delivery')
    validation_status = fields.Selection([
        ('clear', 'Clear'),
        ('check', 'Please Check'),
    ], string='Validation Status', compute='_compute_validation_status', store=True)
    delivery_date = fields.Datetime(string='Delivery Date', compute='_compute_delivery_date')
    driver = fields.Char(string='Driver', compute='compute_driver')

class JobOrderLine(models.Model):
    _name = "job.order.line"
    _description = "Job Order Line"

    def name_get(self):
        job_order_line_list = []

        for record in self:
            name = ''

            if record.product_id:
                name += record.product_id.name

            job_order_line_list.append((record.id, name))

        return job_order_line_list

    def _compute_done_quantity(self):
        for line in self:
            done_quantity = 0

            if line.job_order_id.type == 'single_location':
                for cutting in line.job_order_id.job_order_cutting_ids:
                    if line.parent_product_id == cutting.parent_product_id:
                        for cutting_line in cutting.line_ids:
                            if line == cutting_line.job_order_line_id:
                                done_quantity += cutting_line.done_quantity
            else:
                for child in line.job_order_id.job_order_child_ids:                    
                    for cutting in child.job_order_cutting_ids:
                        if line.parent_product_id == cutting.parent_product_id:
                            for cutting_line in cutting.line_ids:
                                if line.custom_order_line_id == cutting_line.job_order_line_id.custom_order_line_id:
                                    done_quantity += cutting_line.done_quantity

            line.done_quantity = done_quantity

    def _compute_batch_number(self):
        for line in self:
            batch_number_arr = []
            batch_number = ''

            for cutting in line.job_order_id.job_order_cutting_ids:
                if line.parent_product_id == cutting.parent_product_id:
                    for cutting_line in cutting.line_ids:
                        if line == cutting_line.job_order_line_id:
                            if cutting.lot_id:
                                batch_number_arr.append(str(cutting.lot_id.name))
                            else:
                                batch_number = str(cutting.lot_id_stored)

            batch_number_arr = list(dict.fromkeys(batch_number_arr))

            for x in batch_number_arr:
                batch_number += x + ';'

            line.batch_number = batch_number

    name = fields.Char('Reference')
    requested_width = fields.Float('Requested Width', digits=(12,2))
    requested_length = fields.Float('Requested Length', digits=(12,2))
    requested_diameter = fields.Float('Requested Diameter', digits=(12,2))
    requested_thickness = fields.Float('Requested Thickness', digits=(12,2))
    requested_kg = fields.Float('Requested Kg', digits=(12,2))
    requested_across_flat = fields.Float('Requested Across Flat', digits=(12,2))
    requested_width_2 = fields.Float('Requested Width 2', digits=(12,2))
    requested_mesh_number = fields.Float('Requested Mesh Number', digits=(12,2))
    requested_mesh_size = fields.Float('Requested Mesh Size', digits=(12,2))
    requested_hole_diameter = fields.Float('Requested Hole Diameter', digits=(12,2))
    requested_pitch = fields.Float('Requested Pitch', digits=(12,2))
    requested_inner_diameter = fields.Float('Requested Inner Diameter', digits=(12,2))
    product_uom_id = fields.Many2one('uom.uom', string='UoM')
    quantity = fields.Float('Qty')
    done_quantity = fields.Float(string='Done Qty', compute='_compute_done_quantity')
    location_id = fields.Many2one('stock.warehouse', string='Location')
    product_id = fields.Many2one('product.product', string='Customer Requested Product')
    parent_product_id = fields.Many2one('product.product', string='Parent Product', related='product_id.parent_product_id')
    parent_product_categ_id = fields.Many2one('product.category', string='Parent Product Category', related='parent_product_id.categ_id')
    is_have_diameter = fields.Boolean('Have Diameter', related='parent_product_categ_id.is_have_diameter')
    is_have_width = fields.Boolean('Have Width', related='parent_product_categ_id.is_have_width')
    is_have_thickness = fields.Boolean('Have Thickness', related='parent_product_categ_id.is_have_thickness')
    is_have_length = fields.Boolean('Have Length', related='parent_product_categ_id.is_have_length')
    is_have_kg = fields.Boolean('Have Kg', related='parent_product_categ_id.is_have_kg')
    is_have_across_flat = fields.Boolean('Have Across Flat', related='parent_product_categ_id.is_have_across_flat')
    is_have_width_2 = fields.Boolean('Have Width 2', related='parent_product_categ_id.is_have_width_2')
    is_have_mesh_number = fields.Boolean('Have Mesh Number', related='parent_product_categ_id.is_have_mesh_number')
    is_have_mesh_size = fields.Boolean('Have Mesh Size', related='parent_product_categ_id.is_have_mesh_size')
    is_have_hole_diameter = fields.Boolean('Have Hole Diameter', related='parent_product_categ_id.is_have_hole_diameter')
    is_have_pitch = fields.Boolean('Have Pitch', related='parent_product_categ_id.is_have_pitch')
    is_have_inner_diameter = fields.Boolean('Have Pitch', related='parent_product_categ_id.is_have_inner_diameter')
    receipt_location_id = fields.Many2one('stock.location', string='Receipt Location')
    electrode_number = fields.Char('Electrode Number')
    batch_number = fields.Char('Batch Number', compute='_compute_batch_number')
    custom_order_line_id = fields.Many2one('sale.order.custom.dimension.line', string='Order Line')

    job_order_id = fields.Many2one('job.order', 'Job Order')

class JobOrderLineCutting(models.Model):
    _name = "job.order.cutting"
    _description = "Job Order Cutting"
    _order = "sequence desc"

    @api.onchange('product_id')
    def onchange_product_id(self):
        self.line_ids = False
        self.balance_ids = False

    @api.depends('job_order_id.job_order_line_ids')
    def _compute_product_ids(self):
        for cutting in self:
            if cutting.job_order_id.job_order_line_ids:
                for line in cutting.job_order_id.job_order_line_ids:
                    cutting.product_ids += line.product_id
                    cutting.product_ids_parent_product_ids += line.product_id.parent_product_id

                    if not line.product_id.parent_product_id:
                        cutting.product_ids_parent_product_ids += line.product_id

            else:
                cutting.product_ids = False
                cutting.product_ids_parent_product_ids = False
                
    @api.onchange('line_ids')
    def onchange_line_ids(self):
        if self.is_no_cutting:
            qty_used = 0

            for line in self.line_ids:
                qty_used += line.done_quantity

            if qty_used > self.on_hand_quantity:
                raise ValidationError("Done Quantity can't exceed On-Hand Quantity.")

        else:
            self.balance_ids = False
            length = round(self.original_length, 2)
            width = round(self.original_width, 2)
            kg = round(self.original_kg, 2)

            is_length = self.parent_product_id.product_tmpl_id.length == 0 and self.parent_product_id.categ_id.is_have_length
            is_width = self.parent_product_id.product_tmpl_id.width == 0  and self.parent_product_id.categ_id.is_have_width
            is_kg = self.parent_product_id.product_tmpl_id.kg == 0  and self.parent_product_id.categ_id.is_have_kg

            balances = []

            balances.append({
                'length': length,
                'width': width,
            })

            for line in self.line_ids:
                if line.done_quantity < 1:
                    break;

                if is_length and is_width:
                    for i in range(int(line.done_quantity)):
                        is_satisfied = False
                        element_no = 0

                        for balance in balances:
                            if is_satisfied:
                                break;

                            is_not_skip = False

                            length_1_balance = 0
                            width_1_balance = 0
                            length_2_balance = 0
                            width_2_balance = 0

                            if balance['length'] > balance['width']:
                                lowest = round(line.requested_width, 2)
                                highest = round(line.requested_length, 2)
                            else:
                                lowest = round(line.requested_length, 2) 
                                highest = round(line.requested_width, 2)

                            balance['length'] = round(balance['length'], 2)
                            balance['width'] = round(balance['width'], 2)

                            if (balance['width'] == lowest and balance['length'] == highest) or (balance['width'] == highest and balance['length'] == lowest):
                                balances.remove(balance)
                                is_satisfied = True
                                element_no += 1
                                continue;

                            elif balance['width'] == lowest and balance['length'] >= highest:
                                length_1_balance = balance['length']  - highest
                                width_1_balance = balance['width']

                                length_2_balance =  balance['length']
                                width_2_balance = 0

                            elif balance['length'] == lowest and balance['width'] >= highest:
                                length_1_balance = balance['length'] 
                                width_1_balance = balance['width'] - highest

                                length_2_balance =  0
                                width_2_balance = balance['width']

                            elif balance['width'] == highest and balance['length'] >= lowest:
                                length_1_balance = balance['length'] - lowest
                                width_1_balance = balance['width']

                                length_2_balance =  balance['length']
                                width_2_balance = 0

                            elif balance['length'] == highest and balance['width'] >= lowest:
                                length_1_balance = balance['length'] 
                                width_1_balance = balance['width'] - lowest

                                length_2_balance =  0
                                width_2_balance = balance['width']

                            elif (balance['width'] >= lowest and balance['length'] >= highest):
                                length_1_balance = balance['length'] - highest
                                width_1_balance = balance['width'] 

                                length_2_balance =  balance['length'] - (balance['length'] - highest)
                                width_2_balance = balance['width'] - lowest

                            elif (balance['length'] >= lowest and balance['width'] >= highest):
                                length_1_balance = balance['length']
                                width_1_balance = balance['width'] - highest

                                length_2_balance =  balance['length'] - lowest
                                width_2_balance = balance['width'] - (balance['width'] - highest)

                            if length_1_balance or width_1_balance or length_2_balance or width_2_balance:

                                if length_1_balance > 0 and width_1_balance > 0:
                                    balances.append({
                                        'length': round(length_1_balance, 2),
                                        'width': round(width_1_balance, 2),
                                    })

                                if length_2_balance > 0 and width_2_balance > 0:
                                    balances.append({
                                        'length': round(length_2_balance, 2),
                                        'width': round(width_2_balance, 2),
                                    })

                                balances.pop(element_no)

                                is_satisfied = True

                            element_no += 1

                        if not is_satisfied:
                            raise ValidationError("The Original Dimension is less than the total Requested Dimension")

            if is_length and is_width:
                for balance in balances:
                    if balance['length'] > 0 and balance['width'] > 0:
                        self.balance_ids.create({
                            'cutting_id': self.id,
                            'length_balance': balance['length'] if balance['length'] > balance['width'] else balance['width'],
                            'width_balance': balance['width'] if balance['width'] < balance['length'] else balance['length'],
                            'thickness_balance': self.product_id.thickness,
                            'kg_balance': self.product_id.kg,
                            'diameter_balance': self.product_id.diameter,
                            'across_flat_balance': self.product_id.across_flat,
                            'width_2_balance': self.product_id.width_2,
                            'mesh_number_balance': self.product_id.mesh_number,
                            'mesh_size_balance': self.product_id.mesh_size,
                            'hole_diameter_balance': self.product_id.hole_diameter,
                            'pitch_balance': self.product_id.pitch,
                            'inner_diameter_balance': self.product_id.inner_diameter,
                            'lot_name': self.lot_id.name,
                            'receipt_location_id': self.stock_quantity_id.location_id.id,
                        })

    @api.depends('line_ids', 'balance_ids')
    def _compute_is_exceed_deviation(self):
        for cutting in self:
            is_exceed_deviation = False

            if not cutting.is_no_cutting:
                if cutting.parent_product_id.product_tmpl_id.length == 0 and cutting.parent_product_id.categ_id.is_have_length:
                    length_upper_deviation = 0
                    length_lower_deviation = 0
                    length_balance = 0
                    length_used = 0
                    deviation = 0

                    for line in cutting.line_ids:
                        length_used += line.requested_length * line.done_quantity

                    for balance in cutting.balance_ids:
                        length_balance += balance.length_balance * balance.qty

                    if length_used < 100:
                        deviation = 10
                    else:
                        deviation = 5

                    length_upper_deviation = cutting.original_length - (length_used - (length_used * deviation / 100))
                    length_lower_deviation = cutting.original_length - (length_used + (length_used * deviation / 100))

                    if not (length_balance > length_lower_deviation and length_balance < length_upper_deviation):
                        is_exceed_deviation = True

                if cutting.parent_product_id.product_tmpl_id.width == 0 and cutting.parent_product_id.categ_id.is_have_width:
                    width_upper_deviation = 0
                    width_lower_deviation = 0
                    width_balance = 0
                    width_used = 0
                    deviation = 0

                    for line in cutting.line_ids:
                        width_used += line.requested_width * line.done_quantity

                    for balance in cutting.balance_ids:
                        width_balance += balance.width_balance * balance.qty

                    if width_used < 100:
                        deviation = 10
                    else:
                        deviation = 5

                    width_upper_deviation = cutting.original_width - (width_used - (width_used * deviation / 100))
                    width_lower_deviation = cutting.original_width - (width_used + (width_used * deviation / 100))

                    if not (width_balance > width_lower_deviation and width_balance < width_upper_deviation):
                        is_exceed_deviation = True

                if cutting.parent_product_id.product_tmpl_id.kg == 0 and cutting.parent_product_id.categ_id.is_have_kg:
                    kg_upper_deviation = 0
                    kg_lower_deviation = 0
                    kg_balance = 0
                    kg_used = 0
                    deviation = 0

                    for line in cutting.line_ids:
                        kg_used += line.requested_kg * line.done_quantity

                    for balance in cutting.balance_ids:
                        kg_balance += balance.kg_balance * balance.qty

                    if kg_used < 100:
                        deviation = 10
                    else:
                        deviation = 5

                    kg_upper_deviation = cutting.original_kg - (kg_used - (kg_used * deviation / 100))
                    kg_lower_deviation = cutting.original_kg - (kg_used + (kg_used * deviation / 100))

                    if not (kg_balance > kg_lower_deviation and kg_balance < kg_upper_deviation):
                        is_exceed_deviation = True

                if cutting.parent_product_id.product_tmpl_id.length == 0 and cutting.parent_product_id.categ_id.is_have_length and cutting.parent_product_id.product_tmpl_id.width == 0 and cutting.parent_product_id.categ_id.is_have_width:
                    is_exceed_deviation = False

            cutting.is_exceed_deviation = is_exceed_deviation

    @api.depends('line_ids', 'stock_quantity_id')
    def _compute_is_no_cutting(self):
        for cutting in self:
            if len(cutting.line_ids) == 1 and cutting.line_ids[0].job_order_line_id.product_id == cutting.product_id:
                cutting.is_no_cutting = True
            elif len(cutting.line_ids) == 1 and cutting.line_ids[0].job_order_line_id.product_id == cutting.product_id_stored:
                cutting.is_no_cutting = True
            else:
                cutting.is_no_cutting = False

    @api.depends('line_ids')
    def _compute_requested_product(self):
        for cutting in self:
            if len(cutting.line_ids) > 0:
                for line in cutting.line_ids:
                    cutting.requested_product_ids += line.job_order_line_id
            else:
                cutting.requested_product_ids = False

    @api.depends('stock_quantity_id')
    def _compute_field_tree(self):
        for cutting in self:
            if cutting.product_id:
                cutting.product_id_tree = cutting.product_id.display_name
            else:
                cutting.product_id_tree = cutting.product_id_stored.display_name

            if cutting.lot_id:
                cutting.lot_id_tree = cutting.lot_id.name
            else:
                cutting.lot_id_tree = cutting.lot_id_stored

            if cutting.lot_location_id:
                cutting.lot_location_id_tree = cutting.lot_location_id.complete_name
            else:        
                cutting.lot_location_id_tree = cutting.lot_location_id_stored

    @api.depends('stock_quantity_id')
    def _compute_parent_product_id(self):
        for cutting in self:
            parent_product_id = False

            if cutting.product_id:
                parent_product_id = cutting.product_id.parent_product_id
            else:
                parent_product_id = cutting.product_id_stored.parent_product_id

            cutting.parent_product_id = parent_product_id

    @api.depends('stock_quantity_id')
    def _compute_original_product_dimension(self):
        for cutting in self:
            if cutting.product_id:
                cutting.original_width = cutting.product_id.width
                cutting.original_length = cutting.product_id.length
                cutting.original_thickness = cutting.product_id.thickness
                cutting.original_diameter = cutting.product_id.diameter
                cutting.original_kg = cutting.product_id.kg
                cutting.original_across_flat = cutting.product_id.across_flat
                cutting.original_width_2 = cutting.product_id.width_2
                cutting.original_mesh_number = cutting.product_id.mesh_number
                cutting.original_mesh_size = cutting.product_id.mesh_size
                cutting.original_hole_diameter = cutting.product_id.hole_diameter
                cutting.original_pitch = cutting.product_id.pitch
                cutting.original_inner_diameter = cutting.product_id.inner_diameter
            else:
                cutting.original_width = cutting.product_id_stored.width
                cutting.original_length = cutting.product_id_stored.length
                cutting.original_thickness = cutting.product_id_stored.thickness
                cutting.original_diameter = cutting.product_id_stored.diameter
                cutting.original_kg = cutting.product_id_stored.kg
                cutting.original_across_flat = cutting.product_id_stored.across_flat
                cutting.original_width_2 = cutting.product_id_stored.width_2
                cutting.original_mesh_number = cutting.product_id_stored.mesh_number
                cutting.original_mesh_size = cutting.product_id_stored.mesh_size
                cutting.original_hole_diameter = cutting.product_id_stored.hole_diameter
                cutting.original_pitch = cutting.product_id_stored.pitch
                cutting.original_inner_diameter = cutting.product_id_stored.inner_diameter

    name = fields.Char('Reference')
    sequence = fields.Integer('Sequence')
    product_id = fields.Many2one(comodel_name='product.product', string='Product', related='stock_quantity_id.product_id')
    product_id_stored = fields.Many2one('product.product', string='Product Stored')
    product_id_tree = fields.Char(string='Product Tree', compute='_compute_field_tree')

    lot_id = fields.Many2one('stock.production.lot' ,string='Lot Number', related='stock_quantity_id.lot_id')
    lot_id_stored = fields.Char(string='Lot Number')
    lot_id_tree = fields.Char(string='Lot Number Tree', compute='_compute_field_tree')

    lot_location_id = fields.Many2one('stock.location', string='Lot Location', related='stock_quantity_id.location_id')
    lot_location_id_stored = fields.Char(string='Lot Location Stored')
    lot_location_id_tree = fields.Char(string='Lot Location Stored Tree', compute='_compute_field_tree')

    on_hand_quantity = fields.Float('On-Hand Qty', related='stock_quantity_id.quantity')
    on_hand_quantity_stored = fields.Float('On-Hand Qty Stored')

    original_width = fields.Float('Original Width', compute='_compute_original_product_dimension', digits=(12,2))
    original_length = fields.Float('Original Length', compute='_compute_original_product_dimension', digits=(12,2))
    original_thickness = fields.Float('Original Thickness', compute='_compute_original_product_dimension', digits=(12,2))
    original_diameter = fields.Float('Original Diameter', compute='_compute_original_product_dimension', digits=(12,2))
    original_kg = fields.Float('Original Kg', compute='_compute_original_product_dimension', digits=(12,2))
    original_across_flat = fields.Float('Original Across Flat', compute='_compute_original_product_dimension', digits=(12,2))
    original_width_2 = fields.Float('Original Width 2', compute='_compute_original_product_dimension', digits=(12,2))
    original_mesh_number = fields.Float('Original Mesh Number', compute='_compute_original_product_dimension', digits=(12,2))
    original_mesh_size = fields.Float('Original Mesh Size', compute='_compute_original_product_dimension', digits=(12,2))
    original_hole_diameter = fields.Float('Original Hole Diameter', compute='_compute_original_product_dimension', digits=(12,2))
    original_pitch = fields.Float('Original Pitch', compute='_compute_original_product_dimension', digits=(12,2))
    original_inner_diameter = fields.Float('Original Inner Diameter', compute='_compute_original_product_dimension', digits=(12,2))

    product_ids = fields.Many2many('product.product', 'cutting_products_rel', string='Products', compute='_compute_product_ids')
    product_ids_parent_product_ids = fields.Many2many('product.product', 'cutting_products_parents_rel', string='Products Parents', compute='_compute_product_ids')

    parent_product_id = fields.Many2one('product.product', string='Parent Product', compute='_compute_parent_product_id')
    parent_product_length = fields.Float('Parent Product Length', related='parent_product_id.product_tmpl_id.length')
    parent_product_width = fields.Float('Parent Product Width', related='parent_product_id.product_tmpl_id.width')
    parent_product_kg = fields.Float('Parent Product Kg', related='parent_product_id.product_tmpl_id.kg')
    parent_product_categ_id = fields.Many2one('product.category', string='Parent Product Category', related='parent_product_id.categ_id')
    is_have_diameter = fields.Boolean('Have Diameter', related='parent_product_categ_id.is_have_diameter')
    is_have_width = fields.Boolean('Have Width', related='parent_product_categ_id.is_have_width')
    is_have_thickness = fields.Boolean('Have Thickness', related='parent_product_categ_id.is_have_thickness')
    is_have_length = fields.Boolean('Have Length', related='parent_product_categ_id.is_have_length') 
    is_have_kg = fields.Boolean('Have Kg', related='parent_product_categ_id.is_have_kg')
    is_have_across_flat = fields.Boolean('Have Across Flat', related='parent_product_categ_id.is_have_across_flat')
    is_have_width_2 = fields.Boolean('Have Width 2', related='parent_product_categ_id.is_have_width_2')
    is_have_mesh_number = fields.Boolean('Have Mesh Number', related='parent_product_categ_id.is_have_mesh_number')
    is_have_mesh_size = fields.Boolean('Have Mesh Size', related='parent_product_categ_id.is_have_mesh_size')
    is_have_hole_diameter = fields.Boolean('Have Hole Diameter', related='parent_product_categ_id.is_have_hole_diameter')
    is_have_pitch = fields.Boolean('Have Pitch', related='parent_product_categ_id.is_have_pitch')
    is_have_inner_diameter = fields.Boolean('Have Pitch', related='parent_product_categ_id.is_have_inner_diameter')

    line_ids = fields.One2many('job.order.cutting.line', 'cutting_id', string='Lines', copy=True)

    job_order_id = fields.Many2one('job.order', string='Job Order')
    job_order_warehouse_id = fields.Many2one('stock.warehouse', string='Job Order Warehouse', related='job_order_id.location_id')
    warehouse_location_id = fields.Many2one('stock.location', string='Lot Stock', related='job_order_warehouse_id.lot_stock_id')
    stock_quantity_id = fields.Many2one('stock.quant', string="Stocks / Lot Number")
    stock_quantity_id_stored = fields.Char(string="Stocks / Lot Number Stored")

    job_order_id_char = fields.Integer('Job Order Char')

    balance_ids = fields.One2many('job.order.cutting.balance', 'cutting_id', string='Balances', copy=True)

    is_exceed_deviation = fields.Boolean('Deviation Check', compute='_compute_is_exceed_deviation')

    warehouse_code = fields.Char('Warehouse Code', related='job_order_id.location_id.view_location_id.name')

    is_no_cutting = fields.Boolean('No Cutting', compute='_compute_is_no_cutting')

    requested_product_ids = fields.Many2many('job.order.line', string='Requested Products', compute='_compute_requested_product')

    job_order_state = fields.Selection([
        ('draft', 'Draft'),
        ('confirm', 'Confirm'),
        ('done', 'Done'),
        ('cancel', 'Cancel'),
    ], string='Job Status', related='job_order_id.state')

class JobOrderLineCuttingLine(models.Model):
    _name = "job.order.cutting.line"
    _description = "Job Order Cutting Line"

    @api.onchange('job_order_line_id')
    def onchange_job_order_line_id(self):
        self.done_quantity = 0

    @api.depends('job_order_line_id')
    def _compute_name(self):
        for rec in self:
            name = ''

            if rec.job_order_line_id:
                name = rec.job_order_line_id.product_id.name

            rec.name = name

    @api.onchange('done_quantity')
    def onchange_done_quantity(self):
        if self.job_order_line_id:
            qty_done = 0

            for cutting in self.job_order_id.job_order_cutting_ids:
                for cutting_line in cutting.line_ids:
                    if cutting_line.job_order_line_id == self.job_order_line_id:
                        if 'virtual' not in str(cutting_line.id):
                            qty_done += cutting_line.done_quantity

            if qty_done > self.job_order_line_id.quantity:
                raise ValidationError("Done Quantity cannot be more than Requested Quantity.")
            else:
                self.write({
                    'done_quantity': self.done_quantity,
                })

    cutting_id = fields.Many2one('job.order.cutting', string='Cutting')

    cutting_parent_product_id = fields.Many2one('product.product', string='Parent Product', related='cutting_id.parent_product_id')
    product_ids = fields.Many2many('product.product', string='Products', related='cutting_id.product_ids')
    job_order_id = fields.Many2one('job.order', string='Job Order', related='cutting_id.job_order_id')

    name = fields.Char('Reference', compute='_compute_name')
    job_order_line_id = fields.Many2one('job.order.line', 'Requested Product')
    product_id = fields.Many2one(comodel_name='product.product', string='Product', related='job_order_line_id.product_id')
    parent_product_categ_id = fields.Many2one('product.category', string='Parent Product Category', related='product_id.parent_product_id.categ_id')
    is_have_diameter = fields.Boolean('Have Diameter', related='parent_product_categ_id.is_have_diameter')
    is_have_width = fields.Boolean('Have Width', related='parent_product_categ_id.is_have_width')
    is_have_thickness = fields.Boolean('Have Thickness', related='parent_product_categ_id.is_have_thickness')
    is_have_length = fields.Boolean('Have Length', related='parent_product_categ_id.is_have_length') 
    is_have_kg = fields.Boolean('Have Kg', related='parent_product_categ_id.is_have_kg')
    is_have_across_flat = fields.Boolean('Have Across Flat', related='parent_product_categ_id.is_have_across_flat')
    is_have_width_2 = fields.Boolean('Have Width 2', related='parent_product_categ_id.is_have_width_2')
    is_have_mesh_number = fields.Boolean('Have Mesh Number', related='parent_product_categ_id.is_have_mesh_number')
    is_have_mesh_size = fields.Boolean('Have Mesh Size', related='parent_product_categ_id.is_have_mesh_size')
    is_have_hole_diameter = fields.Boolean('Have Hole Diameter', related='parent_product_categ_id.is_have_hole_diameter')
    is_have_pitch = fields.Boolean('Have Pitch', related='parent_product_categ_id.is_have_pitch')
    is_have_inner_diameter = fields.Boolean('Have Pitch', related='parent_product_categ_id.is_have_inner_diameter')

    requested_width = fields.Float(string='Requested Width', related='product_id.width', digits=(12,2))
    requested_length = fields.Float(string='Requested Length', related='product_id.length', digits=(12,2))
    requested_diameter = fields.Float('Requested Diameter', related='product_id.diameter', digits=(12,2))
    requested_thickness = fields.Float('Requested Thickness', related='product_id.thickness', digits=(12,2))
    requested_kg = fields.Float('Requested Kg', related='product_id.kg', digits=(12,2))
    requested_across_flat = fields.Float('Requested Across Flat', related='product_id.across_flat', digits=(12,2))
    requested_width_2 = fields.Float('Requested Width 2', related='product_id.width_2', digits=(12,2))
    requested_mesh_number = fields.Float('Requested Mesh Number', related='product_id.mesh_number', digits=(12,2))
    requested_mesh_size = fields.Float('Requested Mesh Size', related='product_id.mesh_size', digits=(12,2))
    requested_hole_diameter = fields.Float('Requested Hole Diameter', related='product_id.hole_diameter', digits=(12,2))
    requested_pitch = fields.Float('Requested Pitch', related='product_id.pitch', digits=(12,2))
    requested_inner_diameter = fields.Float('Requested Pitch', related='product_id.inner_diameter', digits=(12,2))
    electrode_number = fields.Char('Electrode Number')

    done_quantity = fields.Float('Done Qty')

class JobOrderLineCuttingBalance(models.Model):
    _name = "job.order.cutting.balance"
    _description = "Job Order Cutting Balance"

    def action_validate_balance(self):
        self.is_validate = not self.is_validate

    @api.depends('cutting_id.stock_quantity_id_stored')
    def _compute_parent_product_id(self):
        for balance in self:
            parent_product_id = False

            if balance.cutting_id.parent_product_id:
                parent_product_id = balance.cutting_id.parent_product_id
            elif balance.cutting_id.product_id_stored:
                parent_product_id = balance.cutting_id.product_id_stored.parent_product_id

            balance.parent_product_id = parent_product_id

    @api.onchange('qty')
    def onchange_qty(self):
        if self.qty < 1:
            raise ValidationError("Quantity cannot be lower than 1.")

    name = fields.Char('Reference')
    parent_product_id = fields.Many2one('product.product', string='Parent Product', compute='_compute_parent_product_id')
    width_balance = fields.Float('Width Balance', digits=(12,2))
    length_balance = fields.Float('Length Balance', digits=(12,2))
    thickness_balance = fields.Float('Thickness Balance', digits=(12,2))
    diameter_balance = fields.Float('Diameter Balance', digits=(12,2))
    kg_balance = fields.Float('Kg Balance', digits=(12,2))
    across_flat_balance = fields.Float('Across Flat Balance', digits=(12,2))
    width_2_balance = fields.Float('Width 2 Balance', digits=(12,2))
    mesh_number_balance = fields.Float('Mesh Number Balance', digits=(12,2))
    mesh_size_balance = fields.Float('Mesh Size Balance', digits=(12,2))
    hole_diameter_balance = fields.Float('Hole Diameter Balance', digits=(12,2))
    pitch_balance = fields.Float('Pitch Balance', digits=(12,2))
    inner_diameter_balance = fields.Float('Inner Diameter Balance', digits=(12,2))
    is_validate = fields.Boolean('Validate')
    receipt_location_id = fields.Many2one('stock.location', string='Receipt Location')
    lot_name = fields.Char('Lot Name')
    qty = fields.Float('Qty', default=1)

    cutting_id = fields.Many2one('job.order.cutting', string='Cutting')