import os
from dotenv import load_dotenv
load_dotenv()
import json
import uuid
import smtplib
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, session
import stripe

app = Flask(__name__)
app.secret_key = str(uuid.uuid4())
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "orders.json")

GMAIL_USER = os.getenv("GMAIL_USER", "davidnavarrosereno15@gmail.com")
GMAIL_PASS = os.getenv("GMAIL_PASS", "")

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
YOUR_DOMAIN = os.getenv("YOUR_DOMAIN", "http://192.168.0.32:8080")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "https://discord.com/api/webhooks/1520856436496666628/epg5o3dy0wxiANvlg2SsuNo2drn2vu0pYhI4RxYBCS-SCIMPcqzagE-slTuuMXO-lcE2")


def load_orders():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_order(order):
    orders = load_orders()
    orders.append(order)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(orders, f, ensure_ascii=False, indent=2)


def send_email(order):
    tipo = "COMPRA ONLINE" if order["type"] == "buy" else "RESERVA EN TIENDA"
    c = order["customer"]
    items_text = "\n".join([f"  - {i['name']} ({i['type']}) - {i['price']} \u20ac" for i in order["items"]])

    pago = ""
    if order.get("stripe_payment_id"):
        pago = f"<p style='color:#4caf50'><strong>Pago Stripe:</strong> {order['stripe_payment_id']}</p>"

    html = f"""
    <div style="font-family:Arial;max-width:600px;margin:0 auto;background:#1a1a1a;color:#e0d6a8;border-radius:12px;overflow:hidden">
      <div style="background:linear-gradient(135deg,#6b3fa0,#c9a44b);padding:24px;text-align:center">
        <h1 style="color:#111016;margin:0;font-family:Georgia">{tipo}</h1>
        <p style="color:#111016;margin:8px 0 0">Ref: <strong>{order['id']}</strong></p>
        {pago}
      </div>
      <div style="padding:24px">
        <h2 style="color:#c9a44b;margin:0 0 16px">Datos del cliente</h2>
        <p><strong>Nombre:</strong> {c['name']}</p>
        <p><strong>Email:</strong> {c['email']}</p>
        <p><strong>Telefono:</strong> {c['phone']}</p>
        {"<p><strong>Direccion:</strong> " + c.get('address','') + "</p>" if c.get('address') else ""}
        {"<p><strong>Ciudad:</strong> " + c.get('city','') + " - " + c.get('postal','') + "</p>" if c.get('city') else ""}
        {"<p><strong>Notas:</strong> " + c.get('notes','') + "</p>" if c.get('notes') else ""}
        <hr style="border-color:#333;margin:20px 0">
        <h2 style="color:#c9a44b;margin:0 0 16px">Productos</h2>
        <pre style="color:#e0d6a8;font-size:14px">{items_text}</pre>
        <hr style="border-color:#333;margin:20px 0">
        <p style="font-size:20px;color:#c9a44b"><strong>Total: {order['total']} \u20ac</strong></p>
        <p style="color:#888;font-size:12px;margin-top:24px">{order['date']}</p>
      </div>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[La Guarida del Tiempo] {tipo} - {c['name']} (#{order['id']})"
    msg["From"] = GMAIL_USER
    msg["To"] = GMAIL_USER
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(GMAIL_USER, GMAIL_PASS.replace(" ", ""))
            server.sendmail(GMAIL_USER, GMAIL_USER, msg.as_string())
        app.logger.info(f"Email enviado para pedido {order['id']}")
    except smtplib.SMTPAuthenticationError:
        app.logger.error(f"Error autenticacion Gmail - verifica GMAIL_USER y GMAIL_PASS")
    except smtplib.SMTPConnectError:
        app.logger.error(f"No se pudo conectar a smtp.gmail.com - posible bloqueo del proveedor")
    except Exception as e:
        app.logger.error(f"Error enviando email: {e}")


def send_discord(order):
    if not DISCORD_WEBHOOK:
        app.logger.warning("DISCORD_WEBHOOK no configurado")
        return
    tipo = "COMPRA ONLINE" if order["type"] == "buy" else "RESERVA EN TIENDA"
    c = order["customer"]
    items_text = "\n".join([f"• {i['name']} ({i['type']}) - {i['price']} €" for i in order["items"]])
    estado = order.get("status", "pendiente")
    pago_id = order.get("stripe_payment_id", "N/A")

    color = 0x2a6e3f if estado == "pagado" else 0x8b6914 if estado == "pendiente" else 0x8f2a2a

    payload = {
        "embeds": [{
            "title": f"🛒 {tipo} - #{order['id']}",
            "color": color,
            "fields": [
                {"name": "Cliente", "value": c.get("name", ""), "inline": True},
                {"name": "Email", "value": c.get("email", ""), "inline": True},
                {"name": "Teléfono", "value": c.get("phone", ""), "inline": True},
                {"name": "Productos", "value": items_text or "Ninguno", "inline": False},
                {"name": "Total", "value": f"{order.get('total', 0)} €", "inline": True},
                {"name": "Estado", "value": estado.upper(), "inline": True},
                {"name": "Stripe ID", "value": pago_id, "inline": False},
            ],
            "footer": {"text": f"La Guarida del Tiempo - {order.get('date', '')[:10]}"}
        }]
    }

    try:
        import urllib.request
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            DISCORD_WEBHOOK,
            data=data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10):
            app.logger.info(f"Discord notif enviado para pedido {order['id']}")
    except Exception as e:
        app.logger.error(f"Error Discord: {e}")


@app.route("/")
def index():
    return render_template("index.html", stripe_key=os.getenv("STRIPE_PUBLISHABLE_KEY", ""))


@app.route("/create-checkout", methods=["POST"])
def create_checkout():
    data = request.json

    order_id = str(uuid.uuid4())[:8]
    total = round(sum(float(i["price"]) for i in data.get("items", [])), 2)

    order = {
        "id": order_id,
        "type": "buy",
        "customer": {
            "name": data.get("name", ""),
            "email": data.get("email", ""),
            "phone": data.get("phone", ""),
            "address": data.get("address", ""),
            "city": data.get("city", ""),
            "postal": data.get("postal", ""),
            "notes": data.get("notes", "")
        },
        "items": data.get("items", []),
        "total": total
    }

    temp_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"pending_{order_id}.json")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(order, f, ensure_ascii=False)

    line_items = []
    for item in data["items"]:
        line_items.append({
            "price_data": {
                "currency": "eur",
                "product_data": {"name": item["name"]},
                "unit_amount": round(float(item["price"]) * 100),
            },
            "quantity": 1,
        })

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=line_items,
            mode="payment",
            success_url=YOUR_DOMAIN + "/success?session_id={CHECKOUT_SESSION_ID}&order_id=" + order_id,
            cancel_url=YOUR_DOMAIN + "/",
            customer_email=data.get("email"),
            metadata={"order_id": order_id},
            shipping_address_collection={"allowed_countries": ["ES"]} if data.get("address") else None,
        )
        return jsonify({"url": checkout_session.url})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/success")
def success():
    session_id = request.args.get("session_id")
    order_id = request.args.get("order_id")

    temp_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"pending_{order_id}.json")
    if os.path.exists(temp_file):
        with open(temp_file, "r", encoding="utf-8") as f:
            order = json.load(f)
        os.remove(temp_file)

        order["date"] = datetime.now().isoformat()
        order["status"] = "pagado"
        order["stripe_payment_id"] = session_id
        save_order(order)
        threading.Thread(target=send_email, args=(order,), daemon=True).start()
        threading.Thread(target=send_discord, args=(order,), daemon=True).start()

    return render_template("success.html", order_id=order_id or "?")


@app.route("/cancel")
def cancel():
    order_id = request.args.get("order_id")
    orders = load_orders()
    for o in orders:
        if o["id"] == order_id:
            o["status"] = "cancelado"
            break
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(orders, f, ensure_ascii=False, indent=2)
    return render_template("cancel.html")


@app.route("/reserve-order", methods=["POST"])
def reserve_order():
    data = request.json
    order_id = str(uuid.uuid4())[:8]
    total = round(sum(float(i["price"]) for i in data.get("items", [])), 2)
    order = {
        "id": order_id,
        "date": datetime.now().isoformat(),
        "type": "reserve",
        "customer": {
            "name": data.get("name", ""),
            "email": data.get("email", ""),
            "phone": data.get("phone", ""),
            "address": "",
            "city": "",
            "postal": "",
            "notes": data.get("notes", "")
        },
        "items": data.get("items", []),
        "total": total,
        "status": "pendiente"
    }
    save_order(order)
    threading.Thread(target=send_email, args=(order,), daemon=True).start()
    threading.Thread(target=send_discord, args=(order,), daemon=True).start()
    return jsonify({"id": order_id, "status": "pendiente"})


@app.route("/orders")
def get_orders():
    return jsonify(load_orders())


@app.route("/pedidos")
def pedidos():
    return render_template("pedidos.html", orders=load_orders())


@app.route("/test-email")
def test_email():
    import smtplib
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(GMAIL_USER, GMAIL_PASS.replace(" ", ""))
        return f"OK - Conexion SMTP exitosa con {GMAIL_USER}"
    except Exception as e:
        return f"ERROR SMTP: {e}", 500


@app.route("/test-discord")
def test_discord():
    test_order = {
        "id": "TEST001",
        "type": "reserve",
        "customer": {"name": "Test Cliente", "email": "test@test.com", "phone": "+34600000000"},
        "items": [{"name": "Dragon del Vacio Atemporal", "price": "1200", "type": "legendary"}],
        "total": 1200,
        "status": "pendiente",
        "date": datetime.now().isoformat()
    }
    try:
        send_discord(test_order)
        return "Discord test enviado, mira tu Discord"
    except Exception as e:
        return f"ERROR: {e}", 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
