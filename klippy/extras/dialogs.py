# Pause gcode waiting for a response
#
# Copyright (C) 2019-2021  Fabio Chini fabiochini99@gmail.com
#
# This file may be distributed under the terms of the GNU GPLv3 license.

class Dialog:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        self.abort = False
        self.block_exec = False
        self.gcode.register_command("DIALOG", self.cmd_DIALOG)
        webhooks = self.printer.lookup_object('webhooks')
        webhooks.register_endpoint("dialogs/ack", self._handle_ack)
        webhooks.register_endpoint("dialogs/abort", self._handle_abort)

        self.prefixes = {
            1: '*** ', # Only "Close" is displayed (non-blocking)
            2: '### ', # Only "OK" is displayed (blocking)
            3: '$$$ ', # "OK" and "Cancel" are displayed (blocking)
        }

    def cmd_DIALOG(self, gcmd):
        msg = gcmd.get("MSG", '')
        mode = gcmd.get_int("MODE", 3)
        message = msg if msg is not None else ""
        mode = mode if mode in self.prefixes.keys() else 3
        gcmd.respond_raw("%s%s" % (self.prefixes[mode], message))
        if mode == 1:
            return
        reactor = self.printer.get_reactor()
        eventtime = reactor.monotonic()
        self.block_exec = True
        while self.block_exec:
            try:
                eventtime = reactor.pause(eventtime + 0.2)
            except:
                gcmd.respond_raw("cannot pause")
        if mode != 3:
            self.abort = False
            return
        if self.abort:
            self.abort = False
            raise gcmd.error("Aborted")

    def get_status(self, eventtime):
        return {"blocking": self.block_exec}

    def _handle_ack(self, web_request):
        self.block_exec = False
        self.block_exec = False
        web_request.send({"result": "acked"})

    def _handle_abort(self, web_request):
        self.abort = True
        self.block_exec = False
        web_request.send({"result": "aborted"})


def load_config(config):
    return Dialog(config)