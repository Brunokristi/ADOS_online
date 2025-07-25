from flask import Blueprint, request, redirect, url_for, render_template, session, jsonify
from utils.database import get_db_connection
from routes.patients import get_patients_by_day
from routes.insurances import get_insurances
import requests
from math import radians, sin, cos, sqrt, atan2
import math
from datetime import datetime
import time
import os
import uuid
import json
import re

from flask_login import login_required

API_KEYS = [
    "5b3ce3597851110001cf62483e8009ec48d3457d8800432392507809",
    "5b3ce3597851110001cf624834beac90e22b4e7aae5bb2e22e93aa5d"
]

transport_bp = Blueprint("transport", __name__)

@transport_bp.route('/transport/menu', methods=['GET'])
@login_required
def transport_menu():
    poistovne = get_insurances()
    return render_template("transport/transport_menu.html", poistovne=poistovne)

@transport_bp.route('/transport', methods=['POST'])
@login_required
def transport():
    def haversine(lat1, lon1, lat2, lon2):
        R = 6371000
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
        return R * 2 * atan2(sqrt(a), sqrt(1 - a))

    def get_distance_km(start, end):
        for key in API_KEYS:
            try:
                res = requests.post(
                    "https://api.openrouteservice.org/v2/directions/driving-car/json",
                    headers={
                        "Authorization": key,
                        "Content-Type": "application/json"
                    },
                    json={
                        "coordinates": [[start[1], start[0]], [end[1], end[0]]]
                    }
                )
                if res.status_code == 429:
                    print(f"[{key}] Rate limit reached. Waiting 3 seconds...")
                    time.sleep(3)
                    continue
                res.raise_for_status()
                data = res.json()
                if "routes" in data:
                    distance_km = data["routes"][0]["summary"]["distance"] / 1000
                    return math.ceil(distance_km)
            except Exception as e:
                print(f"Error with API key {key}: {e}")
        print("⚠️ All API keys failed.")
        return 0

    data = request.get_json()
    poistovna_id = data.get("poistovna_id")
    month = session.get("month")
    month_number = month.get("mesiac")
    year_number = month.get("rok")
    month_id = month.get("id")
    nurse_id = session.get("nurse", {}).get("id")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            d.datum AS datum,
            p.id AS pacient_id,
            p.meno AS pacient_meno,
            p.rodne_cislo,
            po.kod AS kod_poistovne,
            diag.kod AS diagnoza,
            car.evc,
            a.ulica AS start_ulica,
            a.mesto AS start_obec,
            p.adresa AS end_ulica,
            p.latitude AS end_lat,
            p.longitude AS end_lon,
            '' AS end_obec,
            l.pzs AS odosielajuci_pzs,
            l.zpr AS odosielajuci_zpr,
            p.pohlavie
        FROM den_pacient dp
        LEFT JOIN dni d ON d.id = dp.den_id
        LEFT JOIN pacienti p ON p.id = dp.pacient_id
        LEFT JOIN mesiac_pacient mp ON mp.pacient_id = p.id
        LEFT JOIN sestry s ON s.id = p.sestra
        LEFT JOIN adosky a ON a.id = s.ados
        LEFT JOIN diagnozy diag ON diag.id = p.diagnoza
        LEFT JOIN poistovne po ON po.id = p.poistovna
        LEFT JOIN auta car ON car.id = s.vozidlo
        LEFT JOIN doktori l ON l.id = p.odosielatel
        WHERE strftime('%m', d.datum) = ?
        AND strftime('%Y', d.datum) = ?
        AND p.sestra = ?
        AND p.poistovna = ?
        AND mp.mesiac_id = ?
        ORDER BY d.datum, dp.vysetrenie
    """, (
        f"{int(month_number):02}",
        str(year_number),
        nurse_id,
        poistovna_id,
        month_id
    ))
    rows = cursor.fetchall()

    start_lat, start_lon = None, None
    if rows:
        start_address = f"{rows[0]['start_ulica']}, {rows[0]['start_obec']}"
        res = requests.get("https://api.openrouteservice.org/geocode/search", params={
            "api_key": "5b3ce3597851110001cf624834beac90e22b4e7aae5bb2e22e93aa5d",
            "text": start_address,
            "size": 1
        })
        geo_data = res.json()
        if geo_data.get("features"):
            coords = geo_data["features"][0]["geometry"]["coordinates"]
            start_lat, start_lon = coords[1], coords[0]

    processed_coords = {}
    final_rows = []
    sum_km = 0

    for idx, row in enumerate(rows, 1):
        end_lat, end_lon = row["end_lat"], row["end_lon"]
        datum = row["datum"]
        datum_day = datum.split("-")[2]
        km = 0
        if start_lat and end_lat and end_lon:
            if datum not in processed_coords:
                processed_coords[datum] = []
            if any(haversine(end_lat, end_lon, lat, lon) < 10 for lat, lon in processed_coords[datum]):
                km = 0
            else:
                processed_coords[datum].append((end_lat, end_lon))
                km = get_distance_km((start_lat, start_lon), (end_lat, end_lon))
                sum_km += km

        final_rows.append({
            "poradie": idx,
            "den": datum_day,
            "rodne_cislo": re.sub(r'\D', '', str(row["rodne_cislo"])) if row["rodne_cislo"] else '',
            "pacient_meno": row["pacient_meno"],
            "diagnoza": re.sub(r'\W', '', row["diagnoza"]) if row["diagnoza"] else '',
            "stav_pacienta": "",
            "sprievodca": "",
            "typ_prepravy": "ADOS",
            "osobokm": km,
            "odkial_obec": row["start_obec"],
            "odkial_ulica": row["start_ulica"],
            "kam_obec": extract_city_from_address(row["end_ulica"]),
            "kam_ulica": row["end_ulica"],
            "cislo_jazdy": idx,
            "evc": row["evc"],
            "pocet_prepravovanych": 0,
            "nahrady": "",
            "typ_odosielatela": "N",
            "kód_pzs": row["odosielajuci_pzs"],
            "kód_zpr": row["odosielajuci_zpr"],
            "clensky_stat": "SK",
            "id_poistenca": "",
            "pohlavie": row["pohlavie"]
        })


        cursor.execute("""
            SELECT s.kod AS kod_zp, s.uvazok, a.identifikator, a.kod AS kod_pzs
            FROM sestry s
            LEFT JOIN adosky a ON s.ados = a.id
            WHERE s.id = ?
        """, (nurse_id,))
        row = cursor.fetchone()

        sestra = {
        "identifikator_pzs": row["identifikator"],
        "kod_pzs": row["kod_pzs"],
        "kod_zp": row["kod_zp"],
        "uvazok": f'{row["uvazok"]:.2f}',
        "obdobie": f'{year_number}{int(month_number):02d}',
        "mena": "EUR"
    }

    cursor.execute("""
        SELECT a.ico AS ico_adosu, po.kod AS kod_poistovne
        FROM sestry s
        LEFT JOIN adosky a ON s.ados = a.id
        LEFT JOIN poistovne po ON po.id = ?
        WHERE s.id = ?
    """, (poistovna_id, nurse_id))
    row = cursor.fetchone()

    pobocka = {"25": "2521", "27": "2700", "24": "2400"}.get(row["kod_poistovne"], "0000")
    poistovna = {
        "typ_davky": "793n",
        "ico_odosielatela": row["ico_adosu"],
        "datum_odoslania": datetime.now().strftime('%Y%m%d'),
        "cislo_davky": "000002",
        "pocet_dokladov": len(final_rows),
        "pocet_medii": "002",
        "cislo_media": "002",
        "pobocka": pobocka,
        "kilometre": sum_km,
        "cena": 0.35 * sum_km,
    }

    file_id = str(uuid.uuid4())
    temp_path = f"/tmp/transport_data_{file_id}.json"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump({
            "data": final_rows,
            "sestra": sestra,
            "poistovna": poistovna
        }, f)

    return render_template("transport/transport.html", data=final_rows, sestra=sestra, poistovna=poistovna, file_id=file_id)

@transport_bp.route('/transport/generate', methods=['POST'])
@login_required
def transport_generate():
    data = request.get_json()
    cislo_faktury = data.get("cislo_faktury")
    charakter_davky = data.get("charakter_davky")
    file_id = data.get("file_id")

    try:
        with open(f"/tmp/transport_data_{file_id}.json", "r", encoding="utf-8") as f:
            saved_data = json.load(f)
        final_rows = saved_data["data"]
        sestra = saved_data["sestra"]
        poistovna = saved_data["poistovna"]
    except Exception as e:
        return jsonify({"success": False, "error": f"Chyba pri čítaní dát: {e}"}), 500

    filename = f"davka.{cislo_faktury}.txt"
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    folder = os.path.join(desktop, "ADOS_davky")
    os.makedirs(folder, exist_ok=True)
    full_path = os.path.join(folder, filename)

    try:
        with open(full_path, "w", encoding="utf-8") as file:
            file.write(
                f"{charakter_davky}|{poistovna['typ_davky']}|{poistovna['ico_odosielatela']}|{poistovna['datum_odoslania']}|"
                f"{poistovna['cislo_davky']}|{poistovna['pocet_dokladov']}|{poistovna['pocet_medii']}|{poistovna['cislo_media']}|"
                f"{poistovna['pobocka']}|\n"
            )
            file.write(
                f"{sestra['identifikator_pzs']}|{sestra['kod_pzs']}|{sestra['kod_zp']}|{sestra['uvazok']}|"
                f"{sestra['obdobie']}|{cislo_faktury}|{sestra['mena']}|\n"
            )
            for row in final_rows:
                file.write(
                    f"{row['poradie']}|{row['den']}|{row['rodne_cislo']}|{row['pacient_meno']}|{row['diagnoza']}|"
                    f"{row['stav_pacienta']}|{row['sprievodca']}|{row['typ_prepravy']}|{row['osobokm']}|"
                    f"{row['odkial_obec'][:20]}|{row['odkial_ulica'][:20]}|{row['kam_obec'][:20]}|{row['kam_ulica'][:20]}|"
                    f"{row['cislo_jazdy']}|{row['evc']}|{row['pocet_prepravovanych']}|{row['nahrady']}|"
                    f"{row['typ_odosielatela']}|{row['kód_pzs']}|{row['kód_zpr']}|{row['clensky_stat']}|"
                    f"{row['id_poistenca']}|{row['pohlavie']}|\n"
                )

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            os.remove(f"/tmp/transport_data_{file_id}.json")
        except Exception as e:
            print(f"Chyba pri mazaní dočasného súboru: {e}")

def extract_city_from_address(address: str) -> str:
    if not address:
        return ''

    parts = [p.strip() for p in address.split(',') if p.strip()]
    slovensko_index = next((i for i, p in enumerate(parts) if 'slovensko' in p.lower()), len(parts))

    for i in reversed(range(slovensko_index)):
        part = parts[i]
        if any(kw in part.lower() for kw in ['okres', 'kraj', 'slovensko', 'stredné', 'severné', 'západné', 'východné', 'južné', 'bc', 'banskobystrický']):
            continue
        if part.strip().isdigit() or re.match(r'^\d{3}\s?\d{2}$', part):
            continue
        return part

    return ''
