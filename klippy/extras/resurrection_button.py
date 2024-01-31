# Support for executing gcode when a hardware button is pressed or released.
#
# Copyright (C) 2024 Fabio Chini <fabiochini99@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging

class ResurrectionButton:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.pin = config.get('pin')
        self.last_state = 0
        buttons = self.printer.load_object(config, "buttons")
        if config.get('analog_range', None) is None:
            buttons.register_buttons([self.pin], self.button_callback)
        gcode_macro = self.printer.load_object(config, 'gcode_macro')
        self.press_template = gcode_macro.load_template(config, 'press_gcode')
        self.release_template = gcode_macro.load_template(config,
                                                          'release_gcode', '')
        self.gcode = self.printer.lookup_object('gcode')
        self.sdcard = self.printer.lookup_object('virtual_sdcard')

    def button_callback(self, eventtime, state):
        self.sdcard.cmd_SAVE_PROGRESS(self.gcode)
        self.sdcard.force_pause()
        self.gcode.respond_raw('!! Power alert!')
        self.last_state = state
        template = self.press_template
        if not state:
            template = self.release_template
        try:
            self.gcode.run_script(template.render())
        except:
            logging.exception("Script running error")

    def get_status(self, eventtime=None):
        if self.last_state:
            return {'state': "PRESSED"}
        return {'state': "RELEASED"}

def load_config(config):
    return ResurrectionButton(config)
