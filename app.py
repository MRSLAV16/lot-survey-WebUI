from flask import Flask, render_template, request, jsonify, redirect, url_for, session, abort
import csv
import sqlite3
import math
from pyproj import Transformer
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf.csrf import CSRFProtect

app = Flask(__name__)
app.secret_key = "replace_with_secure_key"

csrf = CSRFProtect(app)

DB = "users.db"

transformer = Transformer.from_crs("EPSG:4390", "EPSG:4326", always_xy=True)

LAT_CORR = 0.000033
LON_CORR = 0.000044


# ---------------------------
# DATABASE
# ---------------------------

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
        """)
        conn.commit()


init_db()


# ---------------------------
# AUTH ROUTES
# ---------------------------

@app.route("/login", methods=["GET","POST"])
def login():

    if request.method == "POST":

        username = request.form.get("username")
        password = request.form.get("password")

        if not username or not password:
            return render_template("login.html", error="Missing credentials")

        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT password FROM users WHERE username=?", (username,))
            row = cur.fetchone()

        if row and check_password_hash(row["password"], password):

            session["user"] = username
            return redirect(url_for("map_page"))

        return render_template("login.html", error="Invalid login")

    return render_template("login.html")


@app.route("/register", methods=["GET","POST"])
def register():

    if request.method == "POST":

        username = request.form.get("username")
        password = request.form.get("password")

        if not username or not password:
            return render_template("register.html", error="Missing fields")

        if len(password) < 6:
            return render_template("register.html", error="Password too short")

        hashed = generate_password_hash(password)

        try:
            with get_db() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO users(username,password) VALUES(?,?)",
                    (username, hashed)
                )
                conn.commit()

            return redirect(url_for("login"))

        except sqlite3.IntegrityError:
            return render_template("register.html", error="Username exists")

    return render_template("register.html")


@app.route("/change_password", methods=["GET","POST"])
def change_password():

    if "user" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":

        new_password = request.form.get("password")

        if not new_password or len(new_password) < 6:
            return render_template("forgot.html", error="Invalid password")

        hashed = generate_password_hash(new_password)

        with get_db() as conn:
            cur = conn.cursor()

            cur.execute(
                "UPDATE users SET password=? WHERE username=?",
                (hashed, session["user"])
            )

            conn.commit()

        return redirect(url_for("map_page"))

    return render_template("forgot.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------
# MAP PAGE
# ---------------------------

@app.route("/")
def map_page():

    if "user" not in session:
        return redirect(url_for("login"))

    return render_template("map.html", username=session["user"])


# ---------------------------
# UTILITY FUNCTIONS
# ---------------------------

def haversine(p1, p2):

    R = 6371000

    lat1 = math.radians(p1[1])
    lat2 = math.radians(p2[1])

    dlat = lat2 - lat1
    dlon = math.radians(p2[0] - p1[0])

    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    return R * c


def bearing(p1, p2):

    lat1 = math.radians(p1[1])
    lat2 = math.radians(p2[1])

    dlon = math.radians(p2[0] - p1[0])

    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1)*math.sin(lat2) - math.sin(lat1)*math.cos(lat2)*math.cos(dlon)

    brng = math.degrees(math.atan2(y, x))

    return (brng + 360) % 360


# ---------------------------
# CSV UPLOAD
# ---------------------------

@app.route("/upload_csv", methods=["POST"])
def upload_csv():

    if "user" not in session:
        abort(401)

    file = request.files.get("file")

    if not file:
        return jsonify({"error":"No file"}),400

    try:

        lines = file.read().decode("utf-8").splitlines()
        reader = csv.DictReader(lines)

        coords=[]

        for row in reader:

            e=float(row["E"])
            n=float(row["N"])

            lon,lat=transformer.transform(e,n)

            lat+=LAT_CORR
            lon+=LON_CORR

            coords.append([lon,lat])

        if coords[0]!=coords[-1]:
            coords.append(coords[0])

        edges=[]
        perimeter=0

        for i in range(len(coords)-1):

            p1=coords[i]
            p2=coords[i+1]

            dist=haversine(p1,p2)
            brg=bearing(p1,p2)

            perimeter+=dist

            edges.append({
                "distance":round(dist,2),
                "bearing":round(brg,2)
            })

        area=0

        for i in range(len(coords)-1):

            x1=coords[i][0]
            y1=coords[i][1]

            x2=coords[i+1][0]
            y2=coords[i+1][1]

            area+=x1*y2-x2*y1

        area=abs(area)/2*12300000000
        acre=area/4046.86

        geojson={
            "type":"Feature",
            "properties":{
                "owner":session["user"],
                "area_m2":round(area,2),
                "acre":round(acre,4),
                "perimeter":round(perimeter,2),
                "edges":edges
            },
            "geometry":{
                "type":"Polygon",
                "coordinates":[coords]
            }
        }

        return jsonify({"polygon":geojson})

    except Exception as e:

        return jsonify({"error":str(e)}),400


# ---------------------------
# RUN
# ---------------------------

if __name__=="__main__":
    app.run()