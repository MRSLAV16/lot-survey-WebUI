from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import csv
import sqlite3
from pyproj import Transformer
from werkzeug.security import generate_password_hash, check_password_hash


app = Flask(__name__)
app.secret_key = "replace_with_secure_key"

transformer = Transformer.from_crs("EPSG:4390", "EPSG:4326", always_xy=True)

LAT_CORR = 0.000033
LON_CORR = 0.000044

DB = "users.db"


def init_db():

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT
    )
    """)

    conn.commit()
    conn.close()


init_db()


@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        u = request.form.get("username")
        p = request.form.get("password")

        conn = sqlite3.connect(DB)
        cur = conn.cursor()

        cur.execute("SELECT password FROM users WHERE username=?", (u,))
        row = cur.fetchone()

        conn.close()

        if row and check_password_hash(row[0], p):

            session["user"] = u
            return redirect(url_for("map_page"))

        return render_template("login.html", error="Invalid username or password")

    return render_template("login.html")


@app.route("/register", methods=["GET","POST"])
def register():

    if request.method == "POST":

        username = request.form.get("username")
        password = request.form.get("password")

        hashed = generate_password_hash(password)

        try:

            conn = sqlite3.connect(DB)
            cur = conn.cursor()

            cur.execute(
                "INSERT INTO users(username,password) VALUES(?,?)",
                (username,hashed)
            )

            conn.commit()
            conn.close()

            return redirect(url_for("login"))

        except:

            return render_template("register.html", error="Username already exists")

    return render_template("register.html")


@app.route("/logout")
def logout():

    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def map_page():

    if "user" not in session:
        return redirect(url_for("login"))

    return render_template("map.html")


@app.route("/upload_csv", methods=["POST"])
def upload_csv():

    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    file = request.files.get("file")

    if not file or file.filename == "":
        return jsonify({"error": "Invalid file"}), 400

    try:

        lines = file.read().decode("utf-8").splitlines()
        reader = csv.DictReader(lines)

        coords = []
        stations = []

        for row in reader:

            e = float(row["E"])
            n = float(row["N"])

            lon, lat = transformer.transform(e, n)

            lat += LAT_CORR
            lon += LON_CORR

            coords.append([lon, lat])

            if "STN" in row:

                stations.append({
                    "stn": row["STN"],
                    "lat": lat,
                    "lon": lon
                })

        if coords and coords[0] != coords[-1]:
            coords.append(coords[0])

        polygon = {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [coords]
            }
        }

        return jsonify({
            "polygon": polygon,
            "stations": stations
        })

    except Exception as e:

        return jsonify({"error": str(e)}), 400


if __name__ == "__main__":
    app.run(debug=True)