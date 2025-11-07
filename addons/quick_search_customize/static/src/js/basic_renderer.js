odoo.define('quick_search_customize.BasicRenderer', function (require) {
"use strict";
    var BasicRenderer = require('web.BasicRenderer');
    var core = require('web.core');
    var time = require('web.time');
    var Domain = require('web.Domain');
    var QWeb = core.qweb;
    var _t = core._t;

    BasicRenderer.include({
        _renderQuickSearch: function() {
            var self = this;
            var def = $.Deferred();
            
            self._rpc({
                model: 'quick.search',
                method: 'search_read',
                domain: [['model_id.model', '=', this.state.model]],
                fields: ['id']
            }).then(function(qs){
                if(qs.length){
                    $(qs).each(function(){
                        self._rpc({
                            model: 'quick.search.line',
                            method: 'search_read',
                            domain: [['quick_search_id', '=', this.id]],
                            fields: ['id', 'name', 'field_id', 'field_name', 'field_type', 'operator_id', 'operator_value']
                        }).then(function(qsl){
                            if(qsl.length){
                                var searchView = self.getParent().searchModel;

                                function quickSearchSubmit(quickSearch) {
                                    var inputs = $(":input.form-control", quickSearch),
                                        fields = $('.quick_search_field', quickSearch);

                                    $(fields).each(function(){
                                        var $inputs = $(':input.form-control', this);
                                        if($inputs.length > 1) {
                                            var $input_from = $($inputs[0]),
                                                $input_to = $($inputs[1]);
                                            if($input_from.val() && $input_to.val()) {
                                                if($input_from.data('field-type') == 'date') {
                                                    var date_format = 'YYYY-MM-DD',
                                                        moment_format = time.getLangDateFormat();
                                                    var date_from_format = moment($input_from.val(), moment_format).format(date_format),
                                                        date_to_format = moment($input_to.val(), moment_format).format(date_format);
                                                } else if($input_from.data('field-type') == 'datetime') {
                                                    var date_format = 'YYYY-MM-DD HH:mm:ss',
                                                        moment_format = time.getLangDatetimeFormat();
                                                    var date_from_format = moment($input_from.val(), moment_format).add(-self.getSession().getTZOffset($inputs.val()), 'minutes').format(date_format),
                                                        date_to_format = moment($input_to.val(), moment_format).add(-self.getSession().getTZOffset($inputs.val()), 'minutes').format(date_format);
                                                }

                                                var domain = Domain.prototype.arrayToString([[$input_from.data('name'), '>=', date_from_format], [$input_to.data('name'), '<=', date_to_format]]);
                                                var filters = [{
                                                    type: 'filter',
                                                    description: _.str.sprintf('%(field)s %(operator)s "%(value1)s" and "%(value2)s"', {
                                                        field: self.state.fields[$input_from.data('name')].string,
                                                        operator: $input_from.data('operator-name'),
                                                        value1: $input_from.val(),
                                                        value2: $input_to.val()
                                                    }),
                                                    domain: domain,
                                                }];
                                                searchView.dispatch('createNewFilters', filters);
                                            }
                                        } else {
                                            var value = $inputs.val();
                                            if(value){
                                                if($inputs.data('field-type') == 'boolean') {
                                                    var value_string = $inputs.find('option:selected').html().toLowerCase();
                                                    var domain = Domain.prototype.arrayToString([[$inputs.data('name'), value, false]]);
                                                    var filters = [{
                                                        type: 'filter',
                                                        description: _.str.sprintf('%(field)s is %(operator)s', {
                                                            field: self.state.fields[$inputs.data('name')].string,
                                                            operator: value_string
                                                        }),
                                                        domain: domain,
                                                    }];
                                                } else {
                                                    var value_string = $inputs.val();
                                                    if($inputs.data('field-type') == 'selection') {
                                                        value_string = $inputs.find('option:selected').html();
                                                    }
                                                    if($inputs.data('field-type') == 'date') {
                                                        var date_format = 'YYYY-MM-DD',
                                                            moment_format = time.getLangDateFormat();
                                                        value = moment($inputs.val(), moment_format).format(date_format);
                                                    } else if($inputs.data('field-type') == 'datetime') {
                                                        var date_format = 'YYYY-MM-DD HH:mm:ss',
                                                            moment_format = time.getLangDatetimeFormat();
                                                        value = moment($inputs.val(), moment_format).add(-self.getSession().getTZOffset($inputs.val()), 'minutes').format(date_format);
                                                    }
                                                    var domain = Domain.prototype.arrayToString([[$inputs.data('name'), $inputs.data('operator'), value]]);
                                                    var filters = [{
                                                        type: 'filter',
                                                        description: _.str.sprintf('%(field)s %(operator)s "%(value)s"', {
                                                            field: self.state.fields[$inputs.data('name')].string,
                                                            operator: $inputs.data('operator-name'),
                                                            value: value_string
                                                        }),
                                                        domain: domain,
                                                    }];
                                                }
                                                searchView.dispatch('createNewFilters', filters);
                                            }
                                        }
                                    });
                                }

                                $(qsl).each(function(index){
                                    if(qsl[index].field_type == 'selection'){
                                        qsl[index].selection = self.state.fields[qsl[index].field_name].selection;
                                    }
                                });
                                if($('.quick_search').length) {
                                    $('.quick_search').remove();
                                }
                                self.$el.parents('.o_content:first').before(QWeb.render('QuickSearchCustomize', {widget: self, model: self.state.model, fields: qsl}));
                                var quickSearch = self.$el.parents('.o_content:first').siblings('.quick_search');
                                $("div[id^='quick_search_datepicker']", quickSearch).datetimepicker({
                                    locale: moment.locale(),
                                    format : time.getLangDateFormat(),
                                    minDate: moment({ y: 1900 }),
                                    maxDate: moment({ y: 9999, M: 11, d: 31 }),
                                    useCurrent: false,
                                    icons: {
                                        time: 'fa fa-clock-o',
                                        date: 'fa fa-calendar',
                                        up: 'fa fa-chevron-up',
                                        down: 'fa fa-chevron-down',
                                        previous: 'fa fa-chevron-left',
                                        next: 'fa fa-chevron-right',
                                        today: 'fa fa-calendar-check-o',
                                        clear: 'fa fa-delete',
                                        close: 'fa fa-check primary',
                                    },
                                    calendarWeeks: true,
                                    buttons: {
                                        showToday: false,
                                        showClear: false,
                                        showClose: true,
                                    },
                                    keyBinds: null,
                                    allowInputToggle: true
                                });
                                $("div[id^='quick_search_datetimepicker']", quickSearch).datetimepicker({
                                    locale: moment.locale(),
                                    format : time.getLangDatetimeFormat(),
                                    minDate: moment({ y: 1900 }),
                                    maxDate: moment({ y: 9999, M: 11, d: 31 }),
                                    useCurrent: false,
                                    icons: {
                                        time: 'fa fa-clock-o',
                                        date: 'fa fa-calendar',
                                        up: 'fa fa-chevron-up',
                                        down: 'fa fa-chevron-down',
                                        previous: 'fa fa-chevron-left',
                                        next: 'fa fa-chevron-right',
                                        today: 'fa fa-calendar-check-o',
                                        clear: 'fa fa-delete',
                                        close: 'fa fa-check primary',
                                    },
                                    calendarWeeks: true,
                                    buttons: {
                                        showToday: false,
                                        showClear: false,
                                        showClose: true,
                                    },
                                    keyBinds: null,
                                    allowInputToggle: true
                                });
                                $(quickSearch).on('click', '.quick_search_reset', function(){
                                    $(".quick_search_form").trigger("reset");
                                });
                                $(quickSearch).on('click', '.quick_search_submit', function(){
                                    quickSearchSubmit(quickSearch);
                                })
                                $(quickSearch).on('keyup', ':input.form-control', function(event){
                                    var keycode = (event.keyCode ? event.keyCode : event.which);
                                    if(keycode == '13'){
                                        quickSearchSubmit(quickSearch);
                                    }                                    
                                })
                                def.resolve();
                            } else {
                                def.reject();
                            }
                        });
                    });
                } else {
                    def.reject();
                }
            });
            return def;
        },
        async _render() {
            await this._super(...arguments);
            var self = this;
            if((self.viewType == 'list' && self.hasSelectors) || self.viewType == 'pivot') {
                self._renderQuickSearch();
            }
        }
    });
});