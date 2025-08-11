from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from collections import defaultdict
from datetime import date, datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer
from datetime import date
import mercadopago
import os

mp = mercadopago.SDK(os.environ.get("MERCADOPAGO_ACCESS_TOKEN"))

app = Flask(__name__)
app.secret_key = 'clave-secreta'  # Cambia esto por una clave secreta más segura
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///slots.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Configuración de mail (ajusta con tus datos reales)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'reservasclasesdepadel@gmail.com'
app.config['MAIL_PASSWORD'] = 'ebhrzlsemeswlgvj'
mail = Mail(app)
s = URLSafeTimedSerializer(app.secret_key)

db = SQLAlchemy(app)

# Modelo de ocupantes de turno
class SlotOccupant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    slot_id = db.Column(db.Integer, db.ForeignKey('slot.id'), nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    categoria = db.Column(db.String(50), nullable=False)

# Modelo de turnos
class Slot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.String(20), nullable=False)     # Ej: "2025-08-06"
    hora = db.Column(db.String(10), nullable=False)      # Ej: "14:00"
    reserved = db.Column(db.Boolean, default=False)
    reserved_by = db.Column(db.String(100), nullable=True)
    category = db.Column(db.String(50), nullable=True)
    occupants = db.relationship('SlotOccupant', backref='slot', cascade="all, delete-orphan")

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(128), nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    categoria = db.Column(db.String(50), nullable=True)
    confirmado = db.Column(db.Boolean, default=False)  # Para confirmar el registro por email

# Poblar la base de datos con todos los turnos posibles (lunes a viernes, 8:00 a 14:00, hasta dic 2025)
def poblar_turnos():
    fecha_inicio = datetime.today()
    fecha_fin = datetime(2025, 12, 31)
    horarios = [f"{h:02d}:00" for h in range(8, 15)]  # 8:00 a 14:00 inclusive

    fecha = fecha_inicio
    while fecha <= fecha_fin:
        if fecha.weekday() < 5:  # Solo lunes a viernes
            for hora in horarios:
                existe = Slot.query.filter_by(fecha=fecha.date().isoformat(), hora=hora).first()
                if not existe:
                    slot = Slot(fecha=fecha.date().isoformat(), hora=hora)
                    db.session.add(slot)
        fecha += timedelta(days=1)
    db.session.commit()

# Ruta principal: login
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['username']
        password = request.form['password']
        # Login admin hardcodeado
        if email == 'admin' and password == 'admin123':
            session['user'] = email
            session['category'] = 'admin'
            return redirect(url_for('admin_panel'))
        # Login usuario normal
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            if not user.confirmado:
                return render_template('login.html', error='Debes confirmar tu email antes de ingresar.')
            session['user'] = user.nombre
            session['category'] = user.categoria or 'usuario'
            session['email'] = user.email
            return redirect(url_for('turnos'))
        else:
            return render_template('login.html', error='Credenciales incorrectas')
    return render_template('login.html')

# Registro de usuario con validación por email
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        nombre = request.form['nombre']
        categoria = request.form['categoria']
        password = request.form['password']
        if User.query.filter_by(email=email).first():
            return render_template('register.html', error='El email ya está registrado')
        user = User(
            email=email,
            nombre=nombre,
            categoria=categoria,
            password=generate_password_hash(password),
            confirmado=False
        )
        db.session.add(user)
        db.session.commit()
        # Generar token y enviar mail de confirmación
        token = s.dumps(user.email, salt='email-confirm')
        confirm_url = url_for('confirmar_email', token=token, _external=True)
        msg = Message('Confirma tu cuenta', sender='tu_email@gmail.com', recipients=[user.email])
        msg.body = f'Hola {user.nombre}, confirma tu cuenta haciendo click aquí: {confirm_url}'
        msg.charset = 'utf-8'  # Asegura que el mensaje soporte caracteres especiales
        mail.send(msg)
        flash('Te enviamos un mail para confirmar tu cuenta.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

# Confirmar email
@app.route('/confirmar/<token>')
def confirmar_email(token):
    try:
        email = s.loads(token, salt='email-confirm', max_age=3600)  # 1 hora de validez
    except Exception:
        flash('El enlace de confirmación es inválido o expiró.', 'error')
        return redirect(url_for('login'))
    user = User.query.filter_by(email=email).first_or_404()
    if user.confirmado:
        flash('La cuenta ya fue confirmada.', 'info')
    else:
        user.confirmado = True
        db.session.commit()
        flash('¡Cuenta confirmada! Ya puedes iniciar sesión.', 'success')
    return redirect(url_for('login'))

# Panel de administración: ver y gestionar turnos
@app.route('/admin')
def admin_panel():
    if 'user' not in session or session.get('category') != 'admin':
        return redirect(url_for('login'))

    hoy = date.today()
    dias_hasta_viernes = (4 - hoy.weekday()) % 7
    if dias_hasta_viernes == 0:
        dias_hasta_viernes = 7
    viernes_proximo = hoy + timedelta(days=dias_hasta_viernes + 7)

    slots = Slot.query.filter(
        Slot.fecha >= hoy.isoformat(),
        Slot.fecha <= viernes_proximo.isoformat()
    ).order_by(Slot.fecha, Slot.hora).all()

    slots_por_fecha = defaultdict(list)
    for slot in slots:
        slots_por_fecha[slot.fecha].append(slot)

    return render_template('admin.html', slots_por_fecha=slots_por_fecha)

# Ocupar turno como admin (ocupa el turno completo)
@app.route('/admin/occupy/<int:slot_id>')
def admin_occupy(slot_id):
    if 'user' not in session or session.get('category') != 'admin':
        return redirect(url_for('login'))
    slot = Slot.query.get(slot_id)
    if slot and not slot.reserved:
        slot.reserved = True
        slot.reserved_by = "ADMIN"
        slot.category = "admin"
        # Borra ocupantes previos
        slot.occupants.clear()
        db.session.commit()
    return redirect(url_for('admin_panel'))

# Liberar turno (admin)
@app.route('/admin/cancel/<int:slot_id>')
def admin_cancel(slot_id):
    if 'user' not in session or session.get('category') != 'admin':
        return redirect(url_for('login'))
    slot = Slot.query.get(slot_id)
    if slot and slot.reserved:
        slot.reserved = False
        slot.reserved_by = None
        slot.category = None
        db.session.commit()
    return redirect(url_for('admin_panel'))

# Cerrar sesión
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

mp = mercadopago.SDK("TU_ACCESS_TOKEN")

# Página pública de turnos (solo muestra los turnos libres de las próximas dos semanas hasta el viernes siguiente)
@app.route("/turnos", methods=['GET', 'POST'])
def turnos():
    if request.method == 'POST':
        fecha_seleccionada = request.form.get('fecha')
    else:
        fecha_seleccionada = request.args.get('fecha')

    if not fecha_seleccionada:
        fecha_seleccionada = date.today().isoformat()

    turnos_del_dia = Slot.query.filter_by(fecha=fecha_seleccionada).order_by(Slot.hora).all()

    return render_template(
        "turnos.html",
        fecha_seleccionada=fecha_seleccionada,
        turnos_del_dia=turnos_del_dia,
        date=date  # <-- agrega esto
    )

# Reservar turno como usuario (agrega ocupante si hay lugar y no está ya en el mismo turno)
@app.route('/ocupar/<int:slot_id>', methods=['GET', 'POST'])
def ocupar_turno(slot_id):
    slot = Slot.query.get(slot_id)
    if not slot or slot.reserved:
        flash("Turno no disponible", "error")
        return redirect(url_for('turnos'))
    if request.method == 'POST':
        nombre = request.form['nombre']
        categoria = request.form['categoria']

        # Crea la preferencia de pago
        preference_data = {
            "items": [
                {
                    "title": f"Clase de pádel {slot.fecha} {slot.hora}",
                    "quantity": 1,
                    "currency_id": "ARS",
                    "unit_price": 15000
                }
            ],
            "payer": {
                "name": nombre
            },
            "back_urls": {
                "success": url_for('turnos', _external=True),
                "failure": url_for('turnos', _external=True),
                "pending": url_for('turnos', _external=True)
            },
            "notification_url": url_for('webhook_mp', _external=True),
            "external_reference": f"{slot.id}|{nombre}|{categoria}"
        }
        preference_response = mp.preference().create(preference_data)
        init_point = preference_response["response"]["init_point"]

        return render_template('pago.html', nombre=nombre, categoria=categoria, slot=slot, init_point=init_point)
    return render_template('ocupar_turno.html', slot=slot)

from flask import request

@app.route('/webhook_mp', methods=['POST'])
def webhook_mp():
    data = request.json
    if data and data.get("type") == "payment":
        payment_id = data.get("data", {}).get("id")
        payment_info = mp.payment().get(payment_id)
        status = payment_info["response"]["status"]
        external_reference = payment_info["response"]["external_reference"]
        if status == "approved":
            slot_id, nombre, categoria = external_reference.split("|")
            slot = Slot.query.get(int(slot_id))
            if slot and not slot.reserved and not SlotOccupant.query.filter_by(slot_id=slot.id, nombre=nombre).first():
                ocupante = SlotOccupant(slot_id=slot.id, nombre=nombre, categoria=categoria)
                db.session.add(ocupante)
                db.session.commit()
    return '', 200

@app.route('/confirmar_pago/<int:slot_id>', methods=['POST'])
def confirmar_pago(slot_id):
    slot = Slot.query.get(slot_id)
    if not slot or slot.reserved:
        flash("Turno no disponible", "error")
        return redirect(url_for('turnos'))
    nombre = request.form['nombre']
    categoria = request.form['categoria']
    # Aquí podrías validar el pago con la API de Mercado Pago si quieres hacerlo automático
    # Por ahora, solo reservamos el turno
    if SlotOccupant.query.filter_by(slot_id=slot.id, nombre=nombre).first():
        flash("Ya tienes un lugar reservado en este turno.", "error")
        return redirect(url_for('turnos'))
    if len(slot.occupants) < 4:
        ocupante = SlotOccupant(slot_id=slot.id, nombre=nombre, categoria=categoria)
        db.session.add(ocupante)
        db.session.commit()
        flash("Turno reservado correctamente. ¡Gracias por tu pago!", "success")
    else:
        flash("El turno ya está completo", "error")
    return redirect(url_for('turnos'))

# Liberar turno como usuario (elimina su ocupación)
@app.route('/liberar/<int:slot_id>/<nombre>')
def liberar_turno_usuario(slot_id, nombre):
    slot = Slot.query.get(slot_id)
    if not slot or slot.reserved:
        flash("No puedes liberar este turno", "error")
        return redirect(url_for('turnos'))
    ocupante = SlotOccupant.query.filter_by(slot_id=slot_id, nombre=nombre).first()
    if ocupante:
        db.session.delete(ocupante)
        db.session.commit()
        flash("Turno liberado", "success")
    return redirect(url_for('turnos'))

# Inicializar la base de datos y poblar los turnos si es necesario
with app.app_context():
    db.create_all()
    poblar_turnos()

if __name__ == '__main__':
    app.run(debug=True)