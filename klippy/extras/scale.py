class Scale():
    def __init__(self, config):
        self.printer = config.get_printer()
        names = config.getlist('sensors')
        self.sensors = [self.printer.lookup_object('hx711 ' + n) for n in names]
        self.tare = config.getfloat('tare', 0)
        self.diameter = config.getfloat('diameter', 0)
        self.density = config.getfloat('density', 0)
        
        self.reactor = self.printer.get_reactor()
        self.chekc_spool_timer = self.reactor.register_timer(self._check_spool_timer, 5.)

    def _check_spool_timer(self, eventtime):
        all_values = [s.get_values() for s in self.sensors]
        i_stop = min([len(x) for x in all_values])
        mean_values = []
        for i in range(i_stop):
            temp = sum([x[i] for x in all_values])
            mean_values.append(temp / len(all_values))
        
        if len(mean_values) > 1 and (mean_values[-2] - mean_values[-1]) > self.tare * .8:
            gcode = self.printer.lookup_object('gcode')
            gcode._respond_error("Errore: La bobina e' stata sollevata!")
            print_stats = self.printer.lookup_object('print_stats')
            if print_stats and print_stats.get_status(eventtime)['state'] == 'printing':
                gcode.run_script_from_command("PAUSE")

        measured_time = self.reactor.monotonic()
        return measured_time + 5.

    def get_weight(self):
        values = [s.get_weight() for s in self.sensors]
        return sum(values) / len(values) if len(values) > 0 else 0

    def get_status(self, eventtime):
        return {
            "weight": self.get_weight(),
            "tare": float(self.tare),
            "diameter": float(self.diameter),
            "density": float(self.density),
        }
    
    def empty_calibration(self):
        for s in self.sensors:
            s.empty_calibration()

    def weight_calibration(self, value):
        for s in self.sensors:
            s.weight_calibration(value)

class ScaleMaster():
    def __init__(self, config):
        self.printer = config.get_printer()
        self.tare_preset = config.getlist('tare_preset')
        self.diameter_preset = config.getlist('diameter_preset')
        self.density_preset = config.getlist('density_preset')
        self.devices = config.get_printer().lookup_objects('scale')
        self.devices = { key: value for (key, value) in self.devices }
        gcode = self.printer.lookup_object('gcode')
        gcode.register_command('UPDATE_SCALE', self.cmd_UPDATE_SCALE)
        gcode.register_command('EMPTY_CALIBRATION', self.cmd_EMPTY_CALIBRATION)
        gcode.register_command('WEIGHT_CALIBRATION', self.cmd_WEIGHT_CALIBRATION)

    def cmd_UPDATE_SCALE(self, gcmd):
        device = gcmd.get('DEVICE')
        target = gcmd.get('TARGET')
        value = gcmd.get_float('VALUE')

        if device not in self.devices:
            raise gcmd.error("Unknown device: %s | %s" % (device, self.devices))
        
        if target not in ['tare', 'diameter', 'density']:
            raise gcmd.error("Unknown parameter: %s" % target)
        
        scale = self.devices[device]
        setattr(scale, target, value)
        
        configfile = self.printer.lookup_object('configfile')
        configfile.set(device, target, value)

    def cmd_EMPTY_CALIBRATION(self, gcmd):
        device = gcmd.get('DEVICE')

        if device not in self.devices:
            raise gcmd.error("Unknown device: %s | %s" % (device, self.devices))
        
        self.devices[device].empty_calibration()


    def cmd_WEIGHT_CALIBRATION(self, gcmd):
        device = gcmd.get('DEVICE')
        value = gcmd.get_float('VALUE', 0.)

        if device not in self.devices:
            raise gcmd.error("Unknown device: %s | %s" % (device, self.devices))
        
        scale = self.devices[device]
        scale.empty_calibration()

    def cmd_WEIGHT_CALIBRATION(self, gcmd):
        device = gcmd.get('DEVICE')
        value = gcmd.get_float('VALUE', 0.)

        if device not in self.devices:
            raise gcmd.error("Unknown device: %s | %s" % (device, self.devices))
        
        scale = self.devices[device]
        scale.weight_calibration(value)


def load_config_prefix(config):
    return Scale(config)

def load_config(config):
    return ScaleMaster(config)