class Scale():
    def __init__(self, config):
        names = config.getlist('sensors')
        self.sensors = [config.get_printer().lookup_object('hx711 ' + n) for n in names]
        self.tare = config.getfloat('tare', 0)
        self.diameter = config.getfloat('diameter', 0)
        self.density = config.getfloat('density', 0)

    def get_weight(self):
        values = [s.get_weight() for s in self.sensors]
        return sum(values) / len(values) if len(values) > 0 else 0

    def get_status(self, eventtime):
        return {
            "weight": self.get_weight(),
            "tare": self.tare,
            "diameter": self.diameter,
            "density": self.density,
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