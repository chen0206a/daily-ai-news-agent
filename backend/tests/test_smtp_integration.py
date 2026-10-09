"""Real smtplib TCP delivery to a loopback-only SMTP harness. No external recipient."""
import socketserver
import threading
from app.services.delivery import DeliveryService
from test_scheduler_delivery import seed_delivery


def test_real_smtp_transport_and_idempotency(setup):
    received = []

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write(b"220 local-test ESMTP\r\n")
            collecting = False
            message = bytearray()
            while True:
                line = self.rfile.readline()
                if not line:
                    return
                if collecting:
                    if line == b".\r\n":
                        received.append(bytes(message))
                        collecting = False
                        self.wfile.write(b"250 accepted\r\n")
                    else:
                        message.extend(line)
                    continue
                verb = line.split(b" ", 1)[0].strip().upper()
                if verb in (b"EHLO", b"HELO", b"MAIL", b"RCPT", b"RSET"):
                    self.wfile.write(b"250 OK\r\n")
                elif verb == b"DATA":
                    collecting = True
                    self.wfile.write(b"354 End with dot\r\n")
                elif verb == b"QUIT":
                    self.wfile.write(b"221 goodbye\r\n")
                    return
                else:
                    self.wfile.write(b"500 unsupported\r\n")

    ctx, _ = setup
    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        ctx.settings.smtp_host = "127.0.0.1"
        ctx.settings.smtp_port = server.server_address[1]
        ctx.settings.smtp_from = "local-test@example.com"
        ctx.settings.smtp_starttls = False
        ctx.settings.smtp_user = ""
        seed_delivery(ctx)
        service = DeliveryService(ctx.db, ctx.settings)
        service.deliver_pending()
        service.deliver_pending()
        assert len(received) == 1
        assert b"Message-ID:" in received[0]
        assert b"Fixture body" in received[0]
        assert ctx.db.one("SELECT status FROM deliveries")["status"] == "sent"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
