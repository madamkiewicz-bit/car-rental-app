from flask import Flask, render_template, request
from datetime import datetime, date, timedelta
import sqlite3
# render test
app = Flask(__name__)





DB_NAME = "car_rental.db"


def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS cars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model TEXT NOT NULL,
            plate TEXT NOT NULL UNIQUE,
            inspection_date TEXT,
            insurance_date TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            car_id INTEGER NOT NULL,
            client TEXT NOT NULL,
            phone TEXT,
            notes TEXT,
            daily_rate REAL,
            total_price REAL,
            date_from TEXT NOT NULL,
            date_to TEXT NOT NULL,
            FOREIGN KEY (car_id) REFERENCES cars (id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS car_blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            car_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            date_from TEXT NOT NULL,
            date_to TEXT NOT NULL,
            notes TEXT,
            FOREIGN KEY (car_id) REFERENCES cars (id)
        )
    """)

    conn.commit()
    conn.close()


def clean_value(value):
    if value is None or value == "None":
        return ""
    return value


def format_phone(phone):
    phone = clean_value(phone).strip()

    if not phone:
        return ""

    digits = ""

    for char in phone:
        if char.isdigit():
            digits += char

    if digits.startswith("48") and len(digits) == 11:
        number = digits[2:]
        return f"+48 {number[0:3]} {number[3:6]} {number[6:9]}"

    if len(digits) == 9:
        return f"+48 {digits[0:3]} {digits[3:6]} {digits[6:9]}"

    if len(digits) >= 11:
        country_code = digits[:-9]
        number = digits[-9:]
        return f"+{country_code} {number[0:3]} {number[3:6]} {number[6:9]}"

    return phone


def count_days(date_from, date_to):
    start = datetime.strptime(date_from, "%Y-%m-%d").date()
    end = datetime.strptime(date_to, "%Y-%m-%d").date()
    return (end - start).days + 1


def calculate_total(date_from, date_to, daily_rate):
    return count_days(date_from, date_to) * daily_rate


def get_date_status(date_text, label):
    if not date_text:
        return {
            "status": "missing",
            "message": f"Brak daty: {label}",
            "days_left": None
        }

    today = date.today()
    target_date = datetime.strptime(date_text, "%Y-%m-%d").date()
    days_left = (target_date - today).days

    if days_left < 0:
        return {
            "status": "expired",
            "message": f"{label} minęło {abs(days_left)} dni temu",
            "days_left": days_left
        }

    if days_left <= 14:
        return {
            "status": "soon",
            "message": f"{label} za {days_left} dni",
            "days_left": days_left
        }

    return {
        "status": "ok",
        "message": f"OK, zostało {days_left} dni",
        "days_left": days_left
    }


def easter_date(year):
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1

    return date(year, month, day)


def polish_holidays(year):
    easter = easter_date(year)

    return {
        date(year, 1, 1): "Nowy Rok",
        date(year, 1, 6): "Trzech Króli",
        easter + timedelta(days=1): "Poniedziałek Wielkanocny",
        date(year, 5, 1): "Święto Pracy",
        date(year, 5, 3): "Święto Konstytucji",
        easter + timedelta(days=60): "Boże Ciało",
        date(year, 8, 15): "Wniebowzięcie",
        date(year, 11, 1): "Wszystkich Świętych",
        date(year, 11, 11): "Święto Niepodległości",
        date(year, 12, 25): "Boże Narodzenie",
        date(year, 12, 26): "Drugi dzień świąt",
    }


def get_reservation_for_day(car_id, day):
    conn = get_db_connection()

    reservations = conn.execute("""
        SELECT *
        FROM reservations
        WHERE car_id = ?
    """, (car_id,)).fetchall()

    conn.close()

    for reservation in reservations:
        date_from = datetime.strptime(reservation["date_from"], "%Y-%m-%d").date()
        date_to = datetime.strptime(reservation["date_to"], "%Y-%m-%d").date()

        if date_from <= day <= date_to:
            return reservation

    return None


def get_block_for_day(car_id, day):
    conn = get_db_connection()

    blocks = conn.execute("""
        SELECT *
        FROM car_blocks
        WHERE car_id = ?
    """, (car_id,)).fetchall()

    conn.close()

    for block in blocks:
        date_from = datetime.strptime(block["date_from"], "%Y-%m-%d").date()
        date_to = datetime.strptime(block["date_to"], "%Y-%m-%d").date()

        if date_from <= day <= date_to:
            return block

    return None


def reservation_has_conflict(conn, car_id, date_from, date_to, ignored_reservation_id=None):
    new_from = datetime.strptime(date_from, "%Y-%m-%d")
    new_to = datetime.strptime(date_to, "%Y-%m-%d")

    if ignored_reservation_id:
        reservations = conn.execute("""
            SELECT *
            FROM reservations
            WHERE car_id = ?
            AND id != ?
        """, (car_id, ignored_reservation_id)).fetchall()
    else:
        reservations = conn.execute("""
            SELECT *
            FROM reservations
            WHERE car_id = ?
        """, (car_id,)).fetchall()

    for reservation in reservations:
        old_from = datetime.strptime(reservation["date_from"], "%Y-%m-%d")
        old_to = datetime.strptime(reservation["date_to"], "%Y-%m-%d")

        if new_from <= old_to and new_to >= old_from:
            return True

    blocks = conn.execute("""
        SELECT *
        FROM car_blocks
        WHERE car_id = ?
    """, (car_id,)).fetchall()

    for block in blocks:
        block_from = datetime.strptime(block["date_from"], "%Y-%m-%d")
        block_to = datetime.strptime(block["date_to"], "%Y-%m-%d")

        if new_from <= block_to and new_to >= block_from:
            return True

    return False


def block_has_conflict(conn, car_id, date_from, date_to, ignored_block_id=None):
    new_from = datetime.strptime(date_from, "%Y-%m-%d")
    new_to = datetime.strptime(date_to, "%Y-%m-%d")

    reservations = conn.execute("""
        SELECT *
        FROM reservations
        WHERE car_id = ?
    """, (car_id,)).fetchall()

    for reservation in reservations:
        old_from = datetime.strptime(reservation["date_from"], "%Y-%m-%d")
        old_to = datetime.strptime(reservation["date_to"], "%Y-%m-%d")

        if new_from <= old_to and new_to >= old_from:
            return True

    if ignored_block_id:
        blocks = conn.execute("""
            SELECT *
            FROM car_blocks
            WHERE car_id = ?
            AND id != ?
        """, (car_id, ignored_block_id)).fetchall()
    else:
        blocks = conn.execute("""
            SELECT *
            FROM car_blocks
            WHERE car_id = ?
        """, (car_id,)).fetchall()

    for block in blocks:
        block_from = datetime.strptime(block["date_from"], "%Y-%m-%d")
        block_to = datetime.strptime(block["date_to"], "%Y-%m-%d")

        if new_from <= block_to and new_to >= block_from:
            return True

    return False


@app.route("/", methods=["GET", "POST"])

def home():
    message = ""
    edit_reservation = None
    edit_car = None
    edit_block = None

    conn = get_db_connection()

    if request.method == "POST":
        form_type = request.form.get("form_type")

        if form_type == "add_car":
            car_model = request.form.get("car_model", "").strip()
            car_plate = request.form.get("car_plate", "").strip().upper()
            inspection_date = request.form.get("inspection_date", "").strip()
            insurance_date = request.form.get("insurance_date", "").strip()

            if not car_model or not car_plate:
                message = "❌ Uzupełnij markę/model i numer rejestracyjny"
            else:
                existing_car = conn.execute("""
                    SELECT *
                    FROM cars
                    WHERE plate = ?
                """, (car_plate,)).fetchone()

                if existing_car:
                    message = "❌ Auto z taką rejestracją już istnieje"
                else:
                    conn.execute("""
                        INSERT INTO cars (
                            model,
                            plate,
                            inspection_date,
                            insurance_date
                        )
                        VALUES (?, ?, ?, ?)
                    """, (
                        car_model,
                        car_plate,
                        inspection_date,
                        insurance_date
                    ))

                    conn.commit()
                    message = "✅ Samochód dodany"

        if form_type == "edit_car":
            car_id = request.form.get("car_id")

            edit_car = conn.execute("""
                SELECT *
                FROM cars
                WHERE id = ?
            """, (car_id,)).fetchone()

            message = "✏️ Edytujesz samochód"

        if form_type == "update_car":
            car_id = request.form.get("car_id", "").strip()
            car_model = request.form.get("car_model", "").strip()
            car_plate = request.form.get("car_plate", "").strip().upper()
            inspection_date = request.form.get("inspection_date", "").strip()
            insurance_date = request.form.get("insurance_date", "").strip()

            if not car_id or not car_model or not car_plate:
                message = "❌ Uzupełnij dane samochodu"
            else:
                conn.execute("""
                    UPDATE cars
                    SET model = ?,
                        plate = ?,
                        inspection_date = ?,
                        insurance_date = ?
                    WHERE id = ?
                """, (
                    car_model,
                    car_plate,
                    inspection_date,
                    insurance_date,
                    car_id
                ))

                conn.commit()
                message = "✅ Samochód zaktualizowany"

        if form_type == "add_reservation":
            car_id = request.form.get("car_id", "").strip()
            client = request.form.get("client", "").strip()
            phone = format_phone(request.form.get("phone", "").strip())
            notes = request.form.get("notes", "").strip()
            daily_rate_text = request.form.get("daily_rate", "").strip().replace(",", ".")
            date_from = request.form.get("date_from", "").strip()
            date_to = request.form.get("date_to", "").strip()

            if not car_id or not client or not date_from or not date_to:
                message = "❌ Uzupełnij auto, klienta oraz daty"
            else:
                if not daily_rate_text:
                    daily_rate_text = "0"

                try:
                    daily_rate = float(daily_rate_text)

                    if daily_rate < 0:
                        message = "❌ Stawka nie może być ujemna"
                    elif datetime.strptime(date_to, "%Y-%m-%d") < datetime.strptime(date_from, "%Y-%m-%d"):
                        message = "❌ Błędny zakres dat"
                    elif reservation_has_conflict(conn, car_id, date_from, date_to):
                        message = "❌ Auto zajęte albo zablokowane w tym terminie"
                    else:
                        total_price = calculate_total(date_from, date_to, daily_rate)

                        conn.execute("""
                            INSERT INTO reservations (
                                car_id,
                                client,
                                phone,
                                notes,
                                daily_rate,
                                total_price,
                                date_from,
                                date_to
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            car_id,
                            client,
                            phone,
                            notes,
                            daily_rate,
                            total_price,
                            date_from,
                            date_to
                        ))

                        conn.commit()
                        message = "✅ Rezerwacja dodana"

                except ValueError:
                    message = "❌ Stawka musi być liczbą"

        if form_type == "edit_reservation":
            reservation_id = request.form.get("reservation_id")

            edit_reservation = conn.execute("""
                SELECT reservations.*, cars.model, cars.plate
                FROM reservations
                JOIN cars ON reservations.car_id = cars.id
                WHERE reservations.id = ?
            """, (reservation_id,)).fetchone()

            message = "✏️ Edytujesz rezerwację"

        if form_type == "update_reservation":
            reservation_id = request.form.get("reservation_id", "").strip()
            car_id = request.form.get("car_id", "").strip()
            client = request.form.get("client", "").strip()
            phone = format_phone(request.form.get("phone", "").strip())
            notes = request.form.get("notes", "").strip()
            daily_rate_text = request.form.get("daily_rate", "").strip().replace(",", ".")
            date_from = request.form.get("date_from", "").strip()
            date_to = request.form.get("date_to", "").strip()

            if not car_id or not client or not date_from or not date_to:
                message = "❌ Uzupełnij auto, klienta oraz daty"
            else:
                if not daily_rate_text:
                    daily_rate_text = "0"

                try:
                    daily_rate = float(daily_rate_text)

                    if daily_rate < 0:
                        message = "❌ Stawka nie może być ujemna"
                    elif datetime.strptime(date_to, "%Y-%m-%d") < datetime.strptime(date_from, "%Y-%m-%d"):
                        message = "❌ Błędny zakres dat"
                    elif reservation_has_conflict(conn, car_id, date_from, date_to, reservation_id):
                        message = "❌ Auto zajęte albo zablokowane w tym terminie"
                    else:
                        total_price = calculate_total(date_from, date_to, daily_rate)

                        conn.execute("""
                            UPDATE reservations
                            SET car_id = ?,
                                client = ?,
                                phone = ?,
                                notes = ?,
                                daily_rate = ?,
                                total_price = ?,
                                date_from = ?,
                                date_to = ?
                            WHERE id = ?
                        """, (
                            car_id,
                            client,
                            phone,
                            notes,
                            daily_rate,
                            total_price,
                            date_from,
                            date_to,
                            reservation_id
                        ))

                        conn.commit()
                        message = "✅ Rezerwacja zaktualizowana"

                except ValueError:
                    message = "❌ Stawka musi być liczbą"

        if form_type == "delete_reservation":
            reservation_id = request.form.get("reservation_id")

            conn.execute("""
                DELETE FROM reservations
                WHERE id = ?
            """, (reservation_id,))

            conn.commit()
            message = "🗑️ Rezerwacja usunięta"

        if form_type == "add_block":
            car_id = request.form.get("block_car_id", "").strip()
            reason = request.form.get("block_reason", "").strip()
            notes = request.form.get("block_notes", "").strip()
            date_from = request.form.get("block_date_from", "").strip()
            date_to = request.form.get("block_date_to", "").strip()

            if not car_id or not reason or not date_from or not date_to:
                message = "❌ Uzupełnij auto, powód blokady oraz daty"
            elif datetime.strptime(date_to, "%Y-%m-%d") < datetime.strptime(date_from, "%Y-%m-%d"):
                message = "❌ Błędny zakres dat blokady"
            elif block_has_conflict(conn, car_id, date_from, date_to):
                message = "❌ W tym terminie auto ma już rezerwację albo blokadę"
            else:
                conn.execute("""
                    INSERT INTO car_blocks (
                        car_id,
                        reason,
                        date_from,
                        date_to,
                        notes
                    )
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    car_id,
                    reason,
                    date_from,
                    date_to,
                    notes
                ))

                conn.commit()
                message = "✅ Blokada auta dodana"

        if form_type == "edit_block":
            block_id = request.form.get("block_id")

            edit_block = conn.execute("""
                SELECT car_blocks.*, cars.model, cars.plate
                FROM car_blocks
                JOIN cars ON car_blocks.car_id = cars.id
                WHERE car_blocks.id = ?
            """, (block_id,)).fetchone()

            message = "✏️ Edytujesz blokadę"

        if form_type == "update_block":
            block_id = request.form.get("block_id", "").strip()
            car_id = request.form.get("block_car_id", "").strip()
            reason = request.form.get("block_reason", "").strip()
            notes = request.form.get("block_notes", "").strip()
            date_from = request.form.get("block_date_from", "").strip()
            date_to = request.form.get("block_date_to", "").strip()

            if not block_id or not car_id or not reason or not date_from or not date_to:
                message = "❌ Uzupełnij wszystkie pola blokady"
            elif datetime.strptime(date_to, "%Y-%m-%d") < datetime.strptime(date_from, "%Y-%m-%d"):
                message = "❌ Błędny zakres dat blokady"
            elif block_has_conflict(conn, car_id, date_from, date_to, block_id):
                message = "❌ W tym terminie auto ma już rezerwację albo inną blokadę"
            else:
                conn.execute("""
                    UPDATE car_blocks
                    SET reason = ?,
                        date_from = ?,
                        date_to = ?,
                        notes = ?
                    WHERE id = ?
                """, (
                    reason,
                    date_from,
                    date_to,
                    notes,
                    block_id
                ))

                conn.commit()
                message = "✅ Blokada zaktualizowana"

        if form_type == "delete_block":
            block_id = request.form.get("block_id")

            conn.execute("""
                DELETE FROM car_blocks
                WHERE id = ?
            """, (block_id,))

            conn.commit()
            message = "🗑️ Blokada usunięta"

    raw_cars = conn.execute("""
        SELECT *
        FROM cars
        ORDER BY model
    """).fetchall()

    cars = []

    for car in raw_cars:
        car_dict = dict(car)
        car_dict["inspection_date"] = clean_value(car_dict.get("inspection_date"))
        car_dict["insurance_date"] = clean_value(car_dict.get("insurance_date"))
        car_dict["inspection_status"] = get_date_status(car_dict["inspection_date"], "Przegląd")
        car_dict["insurance_status"] = get_date_status(car_dict["insurance_date"], "OC")
        cars.append(car_dict)

    raw_reservations = conn.execute("""
        SELECT reservations.*, cars.model, cars.plate
        FROM reservations
        JOIN cars ON reservations.car_id = cars.id
        ORDER BY reservations.date_from
    """).fetchall()

    reservations = []

    for reservation in raw_reservations:
        reservation_dict = dict(reservation)
        reservation_dict["phone"] = clean_value(reservation_dict.get("phone"))
        reservation_dict["notes"] = clean_value(reservation_dict.get("notes"))
        reservation_dict["days_count"] = count_days(reservation_dict["date_from"], reservation_dict["date_to"])

        if reservation_dict["daily_rate"] is None:
            reservation_dict["daily_rate"] = 0

        if reservation_dict["total_price"] is None:
            reservation_dict["total_price"] = 0

        reservations.append(reservation_dict)

    blocks = conn.execute("""
        SELECT car_blocks.*, cars.model, cars.plate
        FROM car_blocks
        JOIN cars ON car_blocks.car_id = cars.id
        ORDER BY car_blocks.date_from
    """).fetchall()

    today = date.today()
    day_names = ["pon", "wt", "śr", "czw", "pt", "sob", "niedz"]

    calendar_days = []

    for i in range(21):
        current_day = today + timedelta(days=i)
        holidays = polish_holidays(current_day.year)

        calendar_days.append({
            "date": current_day,
            "day_name": day_names[current_day.weekday()],
            "day_number": current_day.strftime("%d"),
            "month": current_day.strftime("%m"),
            "is_sunday": current_day.weekday() == 6,
            "is_holiday": current_day in holidays,
            "holiday_name": holidays.get(current_day, "")
        })

    schedule = []

    for car in cars:
        row = {
            "car": car,
            "days": []
        }

        for day_data in calendar_days:
            reservation = get_reservation_for_day(car["id"], day_data["date"])
            block = get_block_for_day(car["id"], day_data["date"])

            row["days"].append({
                "reserved": reservation is not None,
                "blocked": block is not None and reservation is None,
                "client": clean_value(reservation["client"]) if reservation else "",
                "phone": clean_value(reservation["phone"]) if reservation else "",
                "block_reason": clean_value(block["reason"]) if block else "",
                "block_notes": clean_value(block["notes"]) if block else "",
            })

        schedule.append(row)

    if edit_reservation:
        edit_reservation = dict(edit_reservation)
        edit_reservation["phone"] = clean_value(edit_reservation.get("phone"))
        edit_reservation["notes"] = clean_value(edit_reservation.get("notes"))

    if edit_car:
        edit_car = dict(edit_car)
        edit_car["inspection_date"] = clean_value(edit_car.get("inspection_date"))
        edit_car["insurance_date"] = clean_value(edit_car.get("insurance_date"))

    if edit_block:
        edit_block = dict(edit_block)
        edit_block["notes"] = clean_value(edit_block.get("notes"))

    conn.close()

    return render_template(
        "index.html",
        cars=cars,
        reservations=reservations,
        blocks=blocks,
        message=message,
        calendar_days=calendar_days,
        schedule=schedule,
        today=today,
        edit_reservation=edit_reservation,
        edit_car=edit_car,
        edit_block=edit_block
    )


if __name__ == "__main__":
    init_db()
    app.run(debug=True)