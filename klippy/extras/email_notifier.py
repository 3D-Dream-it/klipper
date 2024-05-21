import smtplib, socket, logging, os
from base64 import b64encode as b64e, b64decode as b64d
from email.mime.text import MIMEText

class EmailNotifier:
    def __init__(self, config):
        self.smtp_server = config.get("smtp_server")
        self.smtp_port = config.get("smtp_port")
        self.smtp_user = config.get("smtp_user")
        self.target_email = config.get("target_email")
        self.printer_name = config.get("printer_name", socket.gethostname())

        self.smtp_password = None
        self.pass_path = os.path.expanduser("~/.email_notifier")
        self.load_password()

        self.printer = config.get_printer()
        webhooks = self.printer.lookup_object("webhooks")
        webhooks.register_endpoint("email", self.handle_password)
        self.gcode = self.printer.lookup_object("gcode")
        self.gcode.register_command("SEND_EMAIL", self.cmd_SEND_EMAIL,
                               desc="Send an email notification")

    def cmd_SEND_EMAIL(self, gcmd):
        subject = "La macchina " + self.printer_name + " ha bisogno di assistenza"
        self.send_email(subject)
        gcmd.respond_raw("Email inviata")

    def load_password(self):
        try:
            with open(self.pass_path, "r") as f:
                raw_data = f.read().strip()
                self.smtp_password = b64d(raw_data)
        except Exception as e:
            logging.error("Failed to load password")

    def store_password(self, password):
        try:
            if os.path.exists(self.pass_path):
                os.remove(self.pass_path)
            with open(self.pass_path, "w") as f:
                f.write(b64e(password))
            return True
        except Exception as e:
            logging.error("Failed to save password: " + str(e))
            return False

    def handle_password(self, web_request):
        password = web_request.get_str("password", default=None)
        if not password:
            raise web_request.error("Please, insert a password")
        self.smtp_password = password
        if self.store_password(password):
            web_request.send("Password Saved")
        else:
            raise web_request.error("Failed to save the password")

    def get_status(self, eventtime):
        return {
            "smtp_server": self.smtp_server,
            "smtp_port": self.smtp_port,
            "smtp_user": self.smtp_user,
            "target_email": self.target_email,
        }

    def send_email(self, subject):
        if not self.smtp_password:
            raise self.gcode.error("Password not set")

        msg = MIMEText("Ricevi questa email in quanto hai attivato le notifiche email.", 'plain')
        msg["Subject"] = subject
        msg["From"] = self.printer_name+" <"+self.smtp_user+">"
        msg["To"] = self.target_email

        try:
            server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port)
            server.login(self.smtp_user, self.smtp_password)
            body_text = msg.as_string()
            server.sendmail(self.smtp_user, self.target_email, body_text)
        except Exception as e:
            logging.error("Error sending email: " + str(e))
            raise self.gcode.error("Error sending email: " + str(e))

def load_config(config):
    return EmailNotifier(config)