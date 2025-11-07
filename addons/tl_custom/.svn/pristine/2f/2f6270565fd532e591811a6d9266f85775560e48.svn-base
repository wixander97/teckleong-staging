# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.


from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError, AccessError

class TeckleongPurchaseCreationWizard(models.TransientModel):
    _name = 'teckleong.purchase.creation.wizard'
    _description = 'Purchase Creation Wizard'

    @api.model
    def default_get(self, fields):
        res = super(TeckleongPurchaseCreationWizard, self).default_get(fields)
        sale_obj = self.env['sale.order'].browse(self._context.get('active_ids'))
        res['sale_id'] = sale_obj
        res['line_ids'] = []
        context = self._context

        for line in sale_obj.custom_dimension_line_ids:
            if context.get('shown_product'):
                if line.id not in context.get('shown_product'):
                    continue;

            res['line_ids'].append((0, 0, {
                'product_id': line.parent_product_id.id,
                'quantity': line.quantity,
                'diameter': line.diameter,
                # 'height': line.height,
                'width': line.width,
                'thickness': line.thickness,
                'length': line.length, 
                'kg': line.kg, 
                'across_flat': line.across_flat,
                'width_2': line.width_2,
                'mesh_number': line.mesh_number,
                'mesh_size': line.mesh_size,
                'hole_diameter': line.hole_diameter,
                'pitch': line.pitch,
                'inner_diameter': line.inner_diameter,
                'is_parent_id': line.is_parent_id,
                'dimension_uom_id': line.dimension_uom_id.id,
                'product_uom_id': line.product_uom_id.id,
                'electrode_number': line.electrode_number,
                'batch_number': line.batch_number,
                'custom_dimension_line_id': line.id,
            }))

        return res

    def action_confirm(self):
        purchase_obj = self.env['purchase.order']
        order_line = []
        shown_product = []

        for line in self.line_ids:
            if line.is_check:
                if self.type == 'vendor':
                    if line.product_id and line.quantity > 0:
                        product = line.product_id

                        product_name = line.product_id.name
                        product_sku = ''

                        if line.product_id.default_code:
                            product_sku = line.product_id.default_code + '-'

                        if line.product_id.product_tmpl_id.width != line.width:
                            width_code = str(int(round(line.width)))

                            if not len(width_code) >= 4:
                                while len(width_code) != 4:
                                    width_code = '0' + width_code

                            product_name += " x " + str(line.width) + "mm"

                            product_sku += width_code

                        if line.product_id.product_tmpl_id.length != line.length:
                            length_code = str(int(round(line.length)))

                            if not len(length_code) >= 4:
                                while len(length_code) != 4:
                                    length_code = '0' + length_code

                            product_name += " x " + str(line.length) + "mm"

                            product_sku += length_code

                        if line.product_id.product_tmpl_id.kg != line.kg:
                            kg_code = str(int(line.kg * 1000))

                            max_len = 4

                            if len(str(int(line.kg))):
                                max_len = 5

                            if not len(kg_code) >= max_len:
                                while len(kg_code) != max_len:
                                    kg_code = '0' + kg_code

                            product_name += " x " + str(line.kg) + "kg"

                            product_sku += kg_code
                        
                        child_roduct = False

                        if line.product_id.is_parent_product:
                            child_roduct = self.env['product.product'].search([
                                ('default_code', '=', product_sku),
                                ('parent_product_id', '=', line.product_id.id),
                                ('width', '=', line.width),
                                ('length', '=', line.length),
                                ('kg', '=', line.kg),
                            ], limit= 1)
                        else:
                            child_roduct = line.product_id

                        if child_roduct:
                            product = child_roduct
                        else:
                            product = self.env['product.product'].create({
                                'name': product_name,
                                'default_code': product_sku,

                                'diameter': line.diameter,
                                'width': line.width,
                                'thickness': line.thickness,
                                'length': line.length,
                                'kg': line.kg,
                                'across_flat': line.across_flat,
                                'width_2': line.width_2,
                                'mesh_number': line.mesh_number,
                                'mesh_size': line.mesh_size,
                                'hole_diameter': line.hole_diameter,
                                'pitch': line.pitch,
                                'inner_diameter': line.inner_diameter,

                                'dimension_uom_id': line.dimension_uom_id.id,
                                'parent_product_id': line.product_id.id,
                                'uom_id': line.product_uom_id.id,
                                'uom_po_id': line.product_uom_id.id,
                                'detailed_type': 'product',
                                'tracking': 'lot',
                                'categ_id': line.product_id.categ_id.id,
                            })

                        order_line.append((0, 0, {
                            'name': line.custom_dimension_line_id.description,
                            'product_id': product.id,
                            'product_qty': line.quantity,
                            'elec_number': line.electrode_number,
                            # 'batch_number': line.batch_number,
                            'custom_order_line_id': line.custom_dimension_line_id.id,
                        }))

                        if line.custom_dimension_line_id.notes:
                            order_line.append((0, 0, {
                                'display_type': 'line_note',
                                'name': line.custom_dimension_line_id.notes,
                                'product_qty': 0,
                            }))
                else:
                    if line.product_id and line.quantity > 0:
                        fab_product = self.sale_id.company_id.fab_product_id

                        order_line.append((0, 0, {
                            'name': "FAB " + line.custom_dimension_line_id.parent_product_categ_id.name + " " + line.custom_dimension_line_id.description,
                            'product_id': fab_product.id,
                            'product_qty': line.quantity,
                            'custom_order_line_id': line.custom_dimension_line_id.id,
                        }))

            else:
                shown_product.append(line.custom_dimension_line_id.id)

        self_collection_id = False

        if self.shipping_term == 'self_collection':
            self_collection_id = self.partner_id.id

        if order_line:
            purchase = purchase_obj.create({
                'order_line': order_line,
                'partner_id': self.partner_id.id,
                'sale_order_id': self.sale_id.id,
                'notes': self.sale_id.remarks,
                'picking_type_id': self.picking_type_id.id,
                'origin': self.sale_id.name,
                'shipping_term': self.shipping_term,
                'self_collection_id': self_collection_id,
                'payment_term_id': self.partner_id.property_supplier_payment_term_id.id,
            })

            self.sale_id.purchase_ids += purchase

        
        if shown_product:
            return {
                'name': _('Create PO'),
                'view_mode': 'form',
                'res_model': 'teckleong.purchase.creation.wizard',
                'type': 'ir.actions.act_window',
                'context': {
                    'shown_product': shown_product, 
                    'active_ids': self.sale_id.id
                },
                'target': 'new'
            }

        # return {
        #     'name': _('Purchase'),
        #     'view_type': 'form',
        #     'view_mode': 'form',
        #     'res_model': 'purchase.order',
        #     'res_id': purchase.id,
        #     'type': 'ir.actions.act_window',
        #     'nodestroy': True,
        #     'target': 'current',
        # }




    name = fields.Char('Reference')
    partner_id = fields.Many2one('res.partner', string='Vendor')
    line_ids = fields.One2many('teckleong.purchase.creation.line.wizard', 'parent_id', string='Lines')
    sale_id = fields.Many2one('sale.order', string='Sale')
    company_id = fields.Many2one('res.company', string='Company', related='sale_id.company_id')
    picking_type_id = fields.Many2one('stock.picking.type', string="Deliver To")
    shipping_term = fields.Selection([
        ('self_collection','Self Collection'),
        ( 'delivery', 'Delivery'),
    ],string='Shipping Term', default='delivery')
    type = fields.Selection([
        ('vendor', 'Vendor Purchase'),
        ('subcontractor', 'Subcontractor Cutting')
    ], string='Type', default='vendor')

class TeckleongPurchaseCreationLineWizard(models.TransientModel):
    _name = 'teckleong.purchase.creation.line.wizard'
    _description = 'Purchase Creation Line Wizard'

    @api.onchange('diameter')
    def onchange_diameter(self):
        if self.is_parent_id:
            if self.product_id and self.product_id.product_tmpl_id.categ_id:
                if self.product_id.product_tmpl_id.categ_id.is_have_diameter:
                    if self.product_id.product_tmpl_id.diameter > 0 and self.product_id.product_tmpl_id.diameter != self.diameter:
                        self.diameter = 0
                        raise ValidationError("You Cannot change this Product Diameter.")
                

    # @api.onchange('height')
    # def onchange_height(self):
    #     if self.is_parent_id:
    #         if self.product_id and self.product_id.product_tmpl_id.categ_id:
    #             if self.product_id.product_tmpl_id.categ_id.is_have_height:
    #                 if self.product_id.product_tmpl_id.height > 0 and self.product_id.product_tmpl_id.height != self.height:
    #                     self.height = 0
    #                     raise ValidationError("You Cannot change this Product Height.")

    @api.onchange('width')
    def onchange_width(self):
        if self.is_parent_id:
            if self.product_id and self.product_id.product_tmpl_id.categ_id:
                if self.product_id.product_tmpl_id.categ_id.is_have_width:
                    if self.product_id.product_tmpl_id.width > 0 and self.product_id.product_tmpl_id.width != self.width:
                        self.width = 0
                        raise ValidationError("You Cannot change this Product Width.")
               

    @api.onchange('thickness')
    def onchange_thickness(self):
        if self.is_parent_id:
            if self.product_id and self.product_id.product_tmpl_id.categ_id:
                if self.product_id.product_tmpl_id.categ_id.is_have_thickness:
                    if self.product_id.product_tmpl_id.thickness > 0 and self.product_id.product_tmpl_id.thickness != self.thickness:
                        self.thickness = 0
                        raise ValidationError("You Cannot change this Product Thickness.")
               

    @api.onchange('length')
    def onchange_length(self):
        if self.is_parent_id:
            if self.product_id and self.product_id.product_tmpl_id.categ_id:
                if self.product_id.product_tmpl_id.categ_id.is_have_length:
                    if self.product_id.product_tmpl_id.length > 0 and self.product_id.product_tmpl_id.length != self.length:
                        self.length = 0
                        raise ValidationError("You Cannot change this Product Length.")
               

    @api.onchange('kg')
    def onchange_kg(self):
        if self.is_parent_id:
            if self.product_id and self.product_id.product_tmpl_id.categ_id:
                if self.product_id.product_tmpl_id.categ_id.is_have_kg:
                    if self.product_id.product_tmpl_id.kg > 0 and self.product_id.product_tmpl_id.kg != self.kg:
                        self.kg = 0
                        raise ValidationError("You Cannot change this Product kg.")

    @api.onchange('across_flat')
    def onchange_across_flat(self):
        if self.is_parent_id:
            if self.product_id and self.product_id.product_tmpl_id.categ_id:
                if self.product_id.product_tmpl_id.categ_id.across_flat:
                    if self.product_id.product_tmpl_id.kg > 0 and self.product_id.product_tmpl_id.across_flat != self.across_flat:
                        self.across_flat = 0
                        raise ValidationError("You Cannot change this Product Across Flat.")

    @api.onchange('width_2')
    def onchange_width_2(self):
        if self.is_parent_id:
            if self.product_id and self.product_id.product_tmpl_id.categ_id:
                if self.product_id.product_tmpl_id.categ_id.is_have_kg:
                    if self.product_id.product_tmpl_id.width_2 > 0 and self.product_id.product_tmpl_id.width_2 != self.width_2:
                        self.width_2 = 0
                        raise ValidationError("You Cannot change this Product Width 2.")

    @api.onchange('mesh_number')
    def onchange_mesh_number(self):
        if self.is_parent_id:
            if self.product_id and self.product_id.product_tmpl_id.categ_id:
                if self.product_id.product_tmpl_id.categ_id.is_have_kg:
                    if self.product_id.product_tmpl_id.mesh_number > 0 and self.product_id.product_tmpl_id.mesh_number != self.mesh_number:
                        self.mesh_number = 0
                        raise ValidationError("You Cannot change this Product Mesh Number.")

    @api.onchange('mesh_size')
    def onchange_mesh_size(self):
        if self.is_parent_id:
            if self.product_id and self.product_id.product_tmpl_id.categ_id:
                if self.product_id.product_tmpl_id.categ_id.is_have_kg:
                    if self.product_id.product_tmpl_id.mesh_number > 0 and self.product_id.product_tmpl_id.mesh_size != self.mesh_size:
                        self.mesh_size = 0
                        raise ValidationError("You Cannot change this Product Mesh Size.")

    @api.onchange('hole_diameter')
    def onchange_hole_diameter(self):
        if self.is_parent_id:
            if self.product_id and self.product_id.product_tmpl_id.categ_id:
                if self.product_id.product_tmpl_id.categ_id.is_have_kg:
                    if self.product_id.product_tmpl_id.hole_diameter > 0 and self.product_id.product_tmpl_id.hole_diameter != self.hole_diameter:
                        self.hole_diameter = 0
                        raise ValidationError("You Cannot change this Product Hole Diameter.")

    @api.onchange('pitch')
    def onchange_pitch(self):
        if self.is_parent_id:
            if self.product_id and self.product_id.product_tmpl_id.categ_id:
                if self.product_id.product_tmpl_id.categ_id.is_have_kg:
                    if self.product_id.product_tmpl_id.kg > 0 and self.product_id.product_tmpl_id.pitch != self.pitch:
                        self.pitch = 0
                        raise ValidationError("You Cannot change this Product Pitch.")

    @api.onchange('inner_diameter')
    def onchange_inner_diameter(self):
        if self.is_parent_id:
            if self.product_id and self.product_id.product_tmpl_id.categ_id:
                if self.product_id.product_tmpl_id.categ_id.is_have_kg:
                    if self.product_id.product_tmpl_id.kg > 0 and self.product_id.product_tmpl_id.inner_diameter != self.inner_diameter:
                        self.inner_diameter = 0
                        raise ValidationError("You Cannot change this Product Inner Diameter.")
               

    name = fields.Char('Reference')
    product_id = fields.Many2one('product.product', string='Product')
    quantity = fields.Float('Quantity')
    width = fields.Float('Width')
    length = fields.Float('Length')
    # height = fields.Float('Height')
    diameter = fields.Float('Diameter')
    thickness = fields.Float('Thickness')
    kg = fields.Float('Kg')
    across_flat = fields.Float('Across Flat')
    width_2 = fields.Float('Width 2')
    mesh_number = fields.Float('Mesh Number')
    mesh_size = fields.Float('Mesh Size')
    hole_diameter = fields.Float('Hole Diameter')
    pitch = fields.Float('Pitch')
    inner_diameter = fields.Float('Inner Diameter')
    is_parent_id = fields.Boolean('Have Parent')
    dimension_uom_id = fields.Many2one('uom.uom', string='Dimension UoM')
    product_uom_id = fields.Many2one('uom.uom', string='UoM')
    electrode_number = fields.Char('Electrode Number')
    batch_number = fields.Char('Batch Number')
    is_check = fields.Boolean('Check')
    custom_dimension_line_id = fields.Many2one('sale.order.custom.dimension.line', string='Custom Dimension Line')

    parent_id = fields.Many2one('teckleong.purchase.creation.wizard', string='Parent')