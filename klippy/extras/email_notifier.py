import smtplib, subprocess, socket
from email.message import EmailMessage
from jinja2 import Template

class EmailNotifier:
    def __init__(self, config):
        self.smtp_server = config.get("smtp_server")
        self.smtp_port = config.get("smtp_port")
        self.smtp_user = config.get("smtp_user")
        self.target_email = config.get("target_email")
        self.printer_name = config.get("printer_name", socket.gethostname())

        self.smtp_password = None
        self.load_password()

        self.printer = config.get_printer()
        self.print_stats = self.printer.lookup_object("print_stats")
        self.printer.register_event_handler("klippy:ready", self.handle_printer_ready)
        self.printer.register_event_handler("virtual_sdcard:printing", self.handle_print_start)
        self.printer.register_event_handler("virtual_sdcard:paused", self.handle_print_paused)
        self.printer.register_event_handler("virtual_sdcard:ended", self.handle_print_ended)
        self.printer.register_event_handler("virtual_sdcard:cancelled", self.handle_print_cancel)

        webhooks = self.printer.lookup_object("webhooks")
        webhooks.register_endpoint("email", self.handle_password)

    def load_password(self):
        result = subprocess.run(["pass", "show", "email_notifier"], capture_output=True)
        if result.returncode == 0:
            self.smtp_password = result.stdout.decode().strip()

    def store_password(self, password: str):
        result = subprocess.run(
            ["pass", "insert", "email_notifier"],
            capture_output=True,
            input=password.encode(),
        )
        return result.returncode == 0

    def handle_printer_ready(self):
        self.send_email("La stampante è pronta")

    def handle_print_start(self):
        self.send_email("Una stampa è stata avviata")

    def handle_print_paused(self):
        self.send_email("La stampa è pausa")

    def handle_print_ended(self):
        self.send_email("La stampa è terminata")

    def handle_print_cancel(self):
        self.send_email("La stampa è stata cancellata")

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

    def send_email(self, subject: str):
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = f"{self.printer_name} <{self.smtp_user}>"
        msg["To"] = self.target_email
        msg.set_content("Ricevi questa email perché hai attivato le notifiche email.")

        with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port) as smtp:
            if self.smtp_password == None:
                return
            smtp.login(self.smtp_user, self.smtp_password)
            smtp.send_message(msg)

def load_config(config):
    return EmailNotifier(config)
