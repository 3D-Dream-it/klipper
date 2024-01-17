# Virtual sdcard support (print files directly from a host g-code file)
#
# Copyright (C) 2018  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import os, logging, io, json, re

VALID_GCODE_EXTS = ['gcode', 'g', 'gco']

class VirtualSD:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.printer.register_event_handler("klippy:shutdown",
                                            self.handle_shutdown)
        # sdcard state
        sd = config.get('path')
        self.sdcard_dirname = os.path.normpath(os.path.expanduser(sd))
        self.current_file = None
        self.file_position = self.file_size = 0
        # script to run before a resurrection
        raw_script = config.get('pre_resurrection', default='G28')
        self.pre_resurrection = raw_script.strip() + '\n'
        raw_script = config.get('post_resurrection', default='')
        self.post_resurrection = raw_script.strip()
        self.resurrect_file = os.path.join(self.sdcard_dirname, '.resurrect')
        # Print Stat Tracking
        self.print_stats = self.printer.load_object(config, 'print_stats')
        # Work timer
        self.reactor = self.printer.get_reactor()
        self.must_pause_work = self.cmd_from_sd = False
        self.next_file_position = 0
        self.work_timer = None
        # Error handling
        gcode_macro = self.printer.load_object(config, 'gcode_macro')
        self.on_error_gcode = gcode_macro.load_template(
            config, 'on_error_gcode', '')
        # Register commands
        self.gcode = self.printer.lookup_object('gcode')
        for cmd in ['M20', 'M21', 'M23', 'M24', 'M25', 'M26', 'M27']:
            self.gcode.register_command(cmd, getattr(self, 'cmd_' + cmd))
        for cmd in ['M28', 'M29', 'M30']:
            self.gcode.register_command(cmd, self.cmd_error)
        self.gcode.register_command(
            "SDCARD_RESET_FILE", self.cmd_SDCARD_RESET_FILE,
            desc=self.cmd_SDCARD_RESET_FILE_help)
        self.gcode.register_command(
            "SDCARD_PRINT_FILE", self.cmd_SDCARD_PRINT_FILE,
            desc=self.cmd_SDCARD_PRINT_FILE_help)
        self.gcode.register_command(
            "SAVE_PROGRESS", self.cmd_SAVE_PROGRESS,
            desc=self.cmd_SAVE_PROGRESS_help)
        wh = self.printer.lookup_object('webhooks')
        wh.register_endpoint("virtual_sdcard/resume_interrupted", self.handle_resume_interrupted)
        self.toolhead = None
        self.gcode_move = self.printer.lookup_object('gcode_move')
    def get_toolhead(self):
        if self.toolhead == None:
            self.toolhead = self.printer.lookup_object('toolhead')
        return self.toolhead
    def handle_shutdown(self):
        if self.work_timer is not None:
            self.must_pause_work = True
            try:
                readpos = max(self.file_position - 1024, 0)
                readcount = self.file_position - readpos
                self.current_file.seek(readpos)
                data = self.current_file.read(readcount + 128)
            except:
                logging.exception("virtual_sdcard shutdown read")
                return
            logging.info("Virtual sdcard (%d): %s\nUpcoming (%d): %s",
                         readpos, repr(data[:readcount]),
                         self.file_position, repr(data[readcount:]))
    def stats(self, eventtime):
        if self.work_timer is None:
            return False, ""
        return True, "sd_pos=%d" % (self.file_position,)
    def get_file_list(self, check_subdirs=False):
        if check_subdirs:
            flist = []
            for root, dirs, files in os.walk(
                    self.sdcard_dirname, followlinks=True):
                for name in files:
                    ext = name[name.rfind('.')+1:]
                    if ext not in VALID_GCODE_EXTS:
                        continue
                    full_path = os.path.join(root, name)
                    r_path = full_path[len(self.sdcard_dirname) + 1:]
                    size = os.path.getsize(full_path)
                    flist.append((r_path, size))
            return sorted(flist, key=lambda f: f[0].lower())
        else:
            dname = self.sdcard_dirname
            try:
                filenames = os.listdir(self.sdcard_dirname)
                return [(fname, os.path.getsize(os.path.join(dname, fname)))
                        for fname in sorted(filenames, key=str.lower)
                        if not fname.startswith('.')
                        and os.path.isfile((os.path.join(dname, fname)))]
            except:
                logging.exception("virtual_sdcard get_file_list")
                raise self.gcode.error("Unable to get file list")
    def get_status(self, eventtime):
        return {
            'file_path': self.file_path(),
            'progress': self.progress(),
            'is_active': self.is_active(),
            'file_position': self.file_position,
            'file_size': self.file_size,
            'can_resurrect': os.path.exists(self.resurrect_file)
        }
    def file_path(self):
        if self.current_file:
            return self.current_file.name
        return None
    def progress(self):
        if self.file_size:
            return float(self.file_position) / self.file_size
        else:
            return 0.
    def is_active(self):
        return self.work_timer is not None
    def do_pause(self):
        if self.work_timer is not None:
            self.must_pause_work = True
            while self.work_timer is not None and not self.cmd_from_sd:
                self.reactor.pause(self.reactor.monotonic() + .001)
    def do_resume(self):
        if self.work_timer is not None:
            raise self.gcode.error("SD busy")
        self.must_pause_work = False
        self.remove_resurrect_file()
        self.work_timer = self.reactor.register_timer(
            self.work_handler, self.reactor.NOW)
    def do_cancel(self):
        if self.current_file is not None:
            self.do_pause()
            self.current_file.close()
            self.current_file = None
            self.print_stats.note_cancel()
        self.file_position = self.file_size = 0.
    # G-Code commands
    def cmd_error(self, gcmd):
        raise gcmd.error("SD write not supported")
    def _reset_file(self):
        if self.current_file is not None:
            self.do_pause()
            self.current_file.close()
            self.current_file = None
        self.file_position = self.file_size = 0.
        self.print_stats.reset()
        self.printer.send_event("virtual_sdcard:reset_file")
    cmd_SDCARD_RESET_FILE_help = "Clears a loaded SD File. Stops the print "\
        "if necessary"
    def cmd_SDCARD_RESET_FILE(self, gcmd):
        if self.cmd_from_sd:
            raise gcmd.error(
                "SDCARD_RESET_FILE cannot be run from the sdcard")
        self._reset_file()
    cmd_SDCARD_PRINT_FILE_help = "Loads a SD file and starts the print.  May "\
        "include files in subdirectories."
    def cmd_SDCARD_PRINT_FILE(self, gcmd):
        if self.work_timer is not None:
            raise gcmd.error("SD busy")
        self._reset_file()
        filename = gcmd.get("FILENAME")
        if filename[0] == '/':
            filename = filename[1:]
        self._load_file(gcmd, filename, check_subdirs=True)
        self.do_resume()
    def cmd_M20(self, gcmd):
        # List SD card
        files = self.get_file_list()
        gcmd.respond_raw("Begin file list")
        for fname, fsize in files:
            gcmd.respond_raw("%s %d" % (fname, fsize))
        gcmd.respond_raw("End file list")
    def cmd_M21(self, gcmd):
        # Initialize SD card
        gcmd.respond_raw("SD card ok")
    def cmd_M23(self, gcmd):
        # Select SD file
        if self.work_timer is not None:
            raise gcmd.error("SD busy")
        self._reset_file()
        filename = gcmd.get_raw_command_parameters().strip()
        if filename.startswith('/'):
            filename = filename[1:]
        self._load_file(gcmd, filename)
    def _load_file(self, gcmd, filename, check_subdirs=False):
        files = self.get_file_list(check_subdirs)
        flist = [f[0] for f in files]
        files_by_lower = { fname.lower(): fname for fname, fsize in files }
        fname = filename
        try:
            if fname not in flist:
                fname = files_by_lower[fname.lower()]
            fname = os.path.join(self.sdcard_dirname, fname)
            f = io.open(fname, 'r', newline='')
            f.seek(0, os.SEEK_END)
            fsize = f.tell()
            f.seek(0)
        except:
            logging.exception("virtual_sdcard file open")
            raise gcmd.error("Unable to open file")
        gcmd.respond_raw("File opened:%s Size:%d" % (filename, fsize))
        gcmd.respond_raw("File selected")
        self.current_file = f
        self.file_position = 0
        self.file_size = fsize
        self.print_stats.set_current_file(filename)
    def cmd_M24(self, gcmd):
        # Start/resume SD print
        self.do_resume()
    def cmd_M25(self, gcmd):
        # Pause SD print
        self.do_pause()
    def cmd_M26(self, gcmd):
        # Set SD position
        if self.work_timer is not None:
            raise gcmd.error("SD busy")
        pos = gcmd.get_int('S', minval=0)
        self.file_position = pos
    def cmd_M27(self, gcmd):
        # Report SD print status
        if self.current_file is None:
            gcmd.respond_raw("Not SD printing.")
            return
        gcmd.respond_raw("SD printing byte %d/%d"
                         % (self.file_position, self.file_size))
    cmd_SAVE_PROGRESS_help = "save the file progress into a file in order to recover a print after a power failure"
    def cmd_SAVE_PROGRESS(self, gcmd):
        resurrect = os.path.join(self.sdcard_dirname, '.resurrect')
        current_print = self.file_path()
        if current_print:
            with open(resurrect, 'w') as f:
                json.dump({
                    "file_position": self.get_file_position(),
                    "filename": current_print,
                    "gcode_state": self.gcode_move.create_gcode_state(),
                    "extruder": self.get_toolhead().get_extruder().get_name()
                }, f)
        else:
            gcmd.respond_raw("Can't save the progress, no files are selected!")
    cmd_RESUME_INTERRUPTED_help = "loads the file progress from a file and resume a print after a power failure"
    def handle_resume_interrupted(self, web_request):
        if not os.path.exists(self.resurrect_file):
            self.gcode.respond_raw('There is no interrupted print to resume')
            return
        with open(self.resurrect_file, 'r') as f:
            try:
                data = json.load(f)
                pos = data['file_position']
                filename = data['filename']
                extruder = data['extruder']
                gcode_state = data['gcode_state']
            except:
                self.gcode.respond_raw("Can't resume the print")
                return

        self.gcode.respond_raw('Stampa precendetemente interrotta: ' + os.path.basename(filename))
        self.gcode.run_script('ACTIVATE_EXTRUDER EXTRUDER=%s' % extruder)
        restore_state_script = self.pre_resurrection + self._create_restore_state_script(filename, pos) + self.post_resurrection
        self.gcode.respond_raw('Running restore script:\n' + str(restore_state_script))
        self.gcode.run_script(restore_state_script)

        self.gcode.respond_raw('Ripristino posizione')
        self.gcode_move.add_gcode_state(gcode_state, 'RESURRECT')
        self.gcode.run_script('RESTORE_GCODE_STATE NAME=RESURRECT MOVE=1')

        self._reset_file()
        self._load_file(self.gcode, os.path.basename(filename))
        self.override_file_position(pos)
        self.do_resume()
    def remove_resurrect_file(self):
        if os.path.exists(self.resurrect_file):
            os.remove(self.resurrect_file)
    def get_file_position(self):
        return self.next_file_position
    def set_file_position(self, pos):
        self.next_file_positiongithub = pos
    def override_file_position(self, pos):
        self.file_position = pos
    def is_cmd_from_sd(self):
        return self.cmd_from_sd
    def _create_restore_state_script(self, filename, size):
        all_re = "|".join([
            r"((M106) S(\d+) P(\d+))",
            r"((M104) S(\d+) T(\d+))",
            r"((M109) S(\d+) T(\d+))",
            r"((M140) S(\d+))",
            r"((M190) S(\d+))",
            r"((M141) S(\d+))",
            r"((M191) S(\d+))",
            r"((G90))",
            r"((G91))",
        ])
        with open(filename, 'r') as f:
            haystack = f.read(size)
        raw_state = {}
        for match in re.findall(all_re, haystack):
            for match in re.findall(all_re, haystack):
                match = [x for x in match if x != '']
                match.pop(0)
                if match[0] == 'M106':
                    p = match[2]
                    raw_state['fan%s_speed' % p] = 'M106 S%s P%s' % (match[1], p)
                elif match[0] == 'M104':
                    t = match[2]
                    raw_state['tool%s_temp' % t] = 'M109 S%s T%s' % (match[1], t)
                elif match[0] == 'M109':
                    t = match[2]
                    raw_state['tool%s_temp' % t] = 'M109 S%s T%s' % (match[1], t)
                elif match[0] == 'M140':
                    raw_state['bed_temp'] = 'M190 S%s' % match[1]
                elif match[0] == 'M190':
                    raw_state['bed_temp'] = 'M190 S%s' % match[1]
                elif match[0] == 'M141':
                    raw_state['chamber_temp'] = 'M141 S%s' % match[1]
                elif match[0] == 'M191':
                    raw_state['chamber_temp'] = 'M141 S%s' % match[1]
                elif match[0] == 'G91':
                    raw_state['mode'] = 'G90'
                elif match[0] == 'G90':
                    raw_state['mode'] = 'G91'

        return '\n'.join([v for k, v in raw_state.items()])
            
    # Background work timer
    def work_handler(self, eventtime):
        logging.info("Starting SD card print (position %d)", self.file_position)
        self.reactor.unregister_timer(self.work_timer)
        try:
            self.current_file.seek(self.file_position)
        except:
            logging.exception("virtual_sdcard seek")
            self.work_timer = None
            return self.reactor.NEVER
        self.print_stats.note_start()
        gcode_mutex = self.gcode.get_mutex()
        partial_input = ""
        lines = []
        error_message = None
        while not self.must_pause_work:
            if not lines:
                # Read more data
                try:
                    data = self.current_file.read(8192)
                except:
                    logging.exception("virtual_sdcard read")
                    break
                if not data:
                    # End of file
                    self.current_file.close()
                    self.current_file = None
                    logging.info("Finished SD card print")
                    self.gcode.respond_raw("Done printing file")
                    break
                lines = data.split('\n')
                lines[0] = partial_input + lines[0]
                partial_input = lines.pop()
                lines.reverse()
                self.reactor.pause(self.reactor.NOW)
                continue
            # Pause if any other request is pending in the gcode class
            if gcode_mutex.test():
                self.reactor.pause(self.reactor.monotonic() + 0.100)
                continue
            # Dispatch command
            self.cmd_from_sd = True
            line = lines.pop()
            next_file_position = self.file_position + len(line) + 1
            self.next_file_position = next_file_position
            try:
                self.gcode.run_script(line)
            except self.gcode.error as e:
                error_message = str(e)
                try:
                    self.gcode.run_script(self.on_error_gcode.render())
                except:
                    logging.exception("virtual_sdcard on_error")
                break
            except:
                logging.exception("virtual_sdcard dispatch")
                break
            self.cmd_from_sd = False
            self.file_position = self.next_file_position
            self.cmd_SAVE_PROGRESS(self.gcode)
            # Do we need to skip around?
            if self.next_file_position != next_file_position:
                try:
                    self.current_file.seek(self.file_position)
                except:
                    logging.exception("virtual_sdcard seek")
                    self.work_timer = None
                    return self.reactor.NEVER
                lines = []
                partial_input = ""
        logging.info("Exiting SD card print (position %d)", self.file_position)
        self.work_timer = None
        self.cmd_from_sd = False
        if error_message is not None:
            self.print_stats.note_error(error_message)
        elif self.current_file is not None:
            self.print_stats.note_pause()
        else:
            self.print_stats.note_complete()
        return self.reactor.NEVER

def load_config(config):
    return VirtualSD(config)
