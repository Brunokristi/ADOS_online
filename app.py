from flask import Flask
from flask_cors import CORS
from routes.main_routes import main
from routes.macros import macro_bp
from routes.cars import car_bp
from routes.companies import company_bp
from routes.nurses import nurse_bp
from routes.doctors import doctor_bp
from routes.diagnoses import diagnosis_bp
from routes.patients import patient_bp
from routes.insurances import insurance_bp
from routes.months import month_bp
from routes.schedules import schedule_bp

from utils.database import DATABASE_FILE, check_db
import threading
import webbrowser
import os


app = Flask(__name__)
app.secret_key = "a3f8d3e87b5a4e5f9c6d4b2f6a1e8c3d"
CORS(app)

app.register_blueprint(main)
app.register_blueprint(macro_bp)
app.register_blueprint(car_bp)
app.register_blueprint(company_bp)
app.register_blueprint(nurse_bp)
app.register_blueprint(doctor_bp)
app.register_blueprint(diagnosis_bp)
app.register_blueprint(patient_bp)
app.register_blueprint(insurance_bp)
app.register_blueprint(month_bp)
app.register_blueprint(schedule_bp)


def open_browser():
    webbrowser.open_new("http://127.0.0.1:5000/")

if __name__ == "__main__":
    check_db()
    threading.Timer(1.5, open_browser).start()
    app.run(host="127.0.0.1", port=5000, debug=True)

