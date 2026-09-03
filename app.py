import csv, io, json, os, re, secrets, sqlite3, time
from functools import wraps
from pathlib import Path
import bcrypt
from flask import Flask, abort, flash, g, jsonify, make_response, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    DATABASE=os.environ.get("DATABASE_PATH", str(Path(__file__).parent / "data" / "longlivelatin.db")),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "false").lower() == "true",
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
)
LOGIN_ATTEMPTS = {}

def db():
    if "db" not in g:
        Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(_=None):
    conn = g.pop("db", None)
    if conn: conn.close()

def init_db():
    conn=db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS levels(id INTEGER PRIMARY KEY, name TEXT NOT NULL, slug TEXT NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL DEFAULT 0, is_active INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS lessons(id INTEGER PRIMARY KEY, level_id INTEGER NOT NULL REFERENCES levels(id) ON DELETE CASCADE, title TEXT NOT NULL, slug TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL DEFAULT 0, is_active INTEGER NOT NULL DEFAULT 1, UNIQUE(level_id,slug));
    CREATE TABLE IF NOT EXISTS flashcards(id INTEGER PRIMARY KEY, lesson_id INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE, front TEXT NOT NULL, back TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0, is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE INDEX IF NOT EXISTS idx_lessons_level_position ON lessons(level_id,position);
    CREATE INDEX IF NOT EXISTS idx_cards_lesson_position ON flashcards(lesson_id,position);
    """)
    if conn.execute("SELECT count(*) FROM users").fetchone()[0] == 0:
        username=os.environ.get("ADMIN_USERNAME","").strip(); password_hash=os.environ.get("ADMIN_PASSWORD_HASH","").strip()
        if username and password_hash: conn.execute("INSERT INTO users(username,password_hash) VALUES(?,?)",(username,password_hash))
    if conn.execute("SELECT count(*) FROM levels").fetchone()[0] == 0:
        conn.execute("INSERT INTO levels(name,slug,description,position) VALUES(?,?,?,?)",("Latin Level 1","latin-1","Begin with essential Latin vocabulary.",1))
        lid=conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO lessons(level_id,title,slug,description,position) VALUES(?,?,?,?,?)",(lid,"Lesson 1 — Vocabulary","vocabulary","Five foundational nouns.",1))
        lesson=conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.executemany("INSERT INTO flashcards(lesson_id,front,back,position) VALUES(?,?,?,?)",[(lesson,a,b,i) for i,(a,b) in enumerate([("man","vir"),("woman","femina"),("boy","puer"),("girl","puella"),("water","aqua")],1)])
        for n in (2,3): conn.execute("INSERT INTO levels(name,slug,description,position) VALUES(?,?,?,?)",(f"Latin Level {n}",f"latin-{n}","Lessons coming soon.",n))
    conn.commit()

def slugify(value):
    base=re.sub(r"[^a-z0-9]+","-",value.lower()).strip("-") or "item"
    return f"{base}-{secrets.token_hex(2)}"

def csrf_token():
    if "csrf" not in session: session["csrf"]=secrets.token_urlsafe(24)
    return session["csrf"]
app.jinja_env.globals["csrf_token"]=csrf_token

@app.before_request
def bootstrap_and_csrf():
    init_db()
    if request.method in {"POST","PUT","PATCH","DELETE"} and request.endpoint not in {"login"}:
        token=request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not token or not secrets.compare_digest(token, session.get("csrf", "")): abort(400, "Invalid CSRF token")

def admin_required(fn):
    @wraps(fn)
    def wrapped(*a,**kw):
        if not session.get("admin"): return redirect(url_for("login", next=request.path))
        return fn(*a,**kw)
    return wrapped

@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"]="nosniff"; resp.headers["X-Frame-Options"]="DENY"
    resp.headers["Referrer-Policy"]="strict-origin-when-cross-origin"
    resp.headers["Content-Security-Policy"]="default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:"
    return resp

@app.get("/")
def home():
    levels=db().execute("SELECT l.*, count(DISTINCT CASE WHEN s.is_active=1 THEN s.id END) lesson_count, count(CASE WHEN s.is_active=1 AND f.is_active=1 THEN f.id END) card_count FROM levels l LEFT JOIN lessons s ON s.level_id=l.id LEFT JOIN flashcards f ON f.lesson_id=s.id WHERE l.is_active=1 GROUP BY l.id ORDER BY l.position,l.id").fetchall()
    return render_template("home.html",levels=levels)

@app.get("/level/<slug>")
def level(slug):
    level=db().execute("SELECT * FROM levels WHERE slug=? AND is_active=1",(slug,)).fetchone()
    if not level: abort(404)
    lessons=db().execute("SELECT s.*,count(CASE WHEN f.is_active=1 THEN 1 END) card_count FROM lessons s LEFT JOIN flashcards f ON f.lesson_id=s.id WHERE s.level_id=? AND s.is_active=1 GROUP BY s.id ORDER BY s.position,s.id",(level["id"],)).fetchall()
    return render_template("level.html",level=level,lessons=lessons)

@app.get("/study/<int:lesson_id>")
def study(lesson_id):
    lesson=db().execute("SELECT s.*,l.name level_name,l.slug level_slug FROM lessons s JOIN levels l ON l.id=s.level_id WHERE s.id=? AND s.is_active=1 AND l.is_active=1",(lesson_id,)).fetchone()
    if not lesson: abort(404)
    cards=[dict(x) for x in db().execute("SELECT id,front,back FROM flashcards WHERE lesson_id=? AND is_active=1 ORDER BY position,id",(lesson_id,)).fetchall()]
    return render_template("study.html",lesson=lesson,cards=cards)

@app.route("/admin/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        ip=request.remote_addr or "unknown"; now=time.time(); attempts=[t for t in LOGIN_ATTEMPTS.get(ip,[]) if now-t<900]; LOGIN_ATTEMPTS[ip]=attempts
        if len(attempts)>=5: return render_template("login.html",error="Too many attempts. Try again later."),429
        user=db().execute("SELECT * FROM users WHERE username=?",(request.form.get("username","").strip(),)).fetchone()
        valid=user and bcrypt.checkpw(request.form.get("password","").encode(),user["password_hash"].encode())
        if valid:
            session.clear(); session["admin"]=True; session["user_id"]=user["id"]; csrf_token(); LOGIN_ATTEMPTS.pop(ip,None); return redirect(url_for("admin"))
        attempts.append(now); flash("Incorrect username or password.","error")
    return render_template("login.html")

@app.post("/admin/logout")
@admin_required
def logout(): session.clear(); return redirect(url_for("home"))

@app.get("/admin")
@admin_required
def admin():
    levels=db().execute("SELECT l.*,count(DISTINCT s.id) lesson_count,count(f.id) card_count FROM levels l LEFT JOIN lessons s ON s.level_id=l.id LEFT JOIN flashcards f ON f.lesson_id=s.id GROUP BY l.id ORDER BY l.position,l.id").fetchall()
    return render_template("admin.html",levels=levels)

@app.post("/admin/password")
@admin_required
def change_password():
    current=request.form.get("current_password",""); new=request.form.get("new_password",""); confirm=request.form.get("confirm_password","")
    user=db().execute("SELECT * FROM users WHERE id=?",(session.get("user_id"),)).fetchone()
    if not user or not bcrypt.checkpw(current.encode(),user["password_hash"].encode()): flash("Current password is incorrect.","error")
    elif len(new)<8: flash("The new password must be at least 8 characters.","error")
    elif new!=confirm: flash("The new passwords do not match.","error")
    else:
        new_hash=bcrypt.hashpw(new.encode(),bcrypt.gensalt()).decode()
        db().execute("UPDATE users SET password_hash=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(new_hash,user["id"])); db().commit(); flash("Password changed successfully.","success")
    return redirect(url_for("admin")+"#security")

@app.post("/admin/levels")
@admin_required
def add_level():
    name=request.form.get("name","").strip()
    if name:
        p=db().execute("SELECT coalesce(max(position),0)+1 FROM levels").fetchone()[0]; db().execute("INSERT INTO levels(name,slug,description,position) VALUES(?,?,?,?)",(name,slugify(name),request.form.get("description","").strip(),p)); db().commit()
    return redirect(url_for("admin"))

@app.post("/admin/levels/<int:lid>")
@admin_required
def edit_level(lid):
    action=request.form.get("action","save"); conn=db()
    if action=="delete": conn.execute("DELETE FROM levels WHERE id=?",(lid,))
    elif action in {"up","down"}: conn.execute("UPDATE levels SET position=position+? WHERE id=?",(-1 if action=="up" else 1,lid))
    else: conn.execute("UPDATE levels SET name=?,description=?,is_active=? WHERE id=?",(request.form.get("name","").strip(),request.form.get("description","").strip(),1 if request.form.get("is_active") else 0,lid))
    conn.commit(); return redirect(url_for("admin"))

@app.get("/admin/levels/<int:lid>")
@admin_required
def admin_level(lid):
    level=db().execute("SELECT * FROM levels WHERE id=?",(lid,)).fetchone() or abort(404)
    lessons=db().execute("SELECT s.*,count(f.id) card_count FROM lessons s LEFT JOIN flashcards f ON f.lesson_id=s.id WHERE s.level_id=? GROUP BY s.id ORDER BY s.position,s.id",(lid,)).fetchall()
    all_levels=db().execute("SELECT id,name FROM levels ORDER BY position,id").fetchall()
    return render_template("admin_level.html",level=level,lessons=lessons,all_levels=all_levels)

@app.post("/admin/levels/<int:lid>/questions")
@admin_required
def add_level_question(lid):
    lesson_id=int(request.form.get("lesson_id",0)); front=request.form.get("front","").strip(); back=request.form.get("back","").strip()
    lesson=db().execute("SELECT id FROM lessons WHERE id=? AND level_id=?",(lesson_id,lid)).fetchone()
    if not lesson: abort(400,"Lesson does not belong to this level")
    if not front or not back: flash("Both the question and answer are required.","error")
    else:
        position=db().execute("SELECT coalesce(max(position),0)+1 FROM flashcards WHERE lesson_id=?",(lesson_id,)).fetchone()[0]
        db().execute("INSERT INTO flashcards(lesson_id,front,back,position) VALUES(?,?,?,?)",(lesson_id,front,back,position)); db().commit(); flash("Question and answer added.","success")
    return redirect(url_for("admin_level",lid=lid)+f"#lesson-{lesson_id}")

@app.post("/admin/lessons")
@admin_required
def add_lesson():
    lid=int(request.form["level_id"]); title=request.form.get("title","").strip()
    if title:
        p=db().execute("SELECT coalesce(max(position),0)+1 FROM lessons WHERE level_id=?",(lid,)).fetchone()[0]; db().execute("INSERT INTO lessons(level_id,title,slug,description,position) VALUES(?,?,?,?,?)",(lid,title,slugify(title),request.form.get("description","").strip(),p)); db().commit()
    return redirect(url_for("admin_level",lid=lid))

@app.post("/admin/lessons/<int:sid>")
@admin_required
def edit_lesson(sid):
    conn=db(); row=conn.execute("SELECT * FROM lessons WHERE id=?",(sid,)).fetchone() or abort(404); action=request.form.get("action","save")
    if action=="delete": conn.execute("DELETE FROM lessons WHERE id=?",(sid,)); dest=row["level_id"]
    elif action in {"up","down"}: conn.execute("UPDATE lessons SET position=position+? WHERE id=?",(-1 if action=="up" else 1,sid)); dest=row["level_id"]
    else:
        dest=int(request.form.get("level_id",row["level_id"])); conn.execute("UPDATE lessons SET level_id=?,title=?,description=?,is_active=? WHERE id=?",(dest,request.form.get("title","").strip(),request.form.get("description","").strip(),1 if request.form.get("is_active") else 0,sid))
    conn.commit(); return redirect(url_for("admin_level",lid=dest))

@app.get("/admin/lessons/<int:sid>/flashcards")
@admin_required
def admin_cards(sid):
    lesson=db().execute("SELECT s.*,l.name level_name FROM lessons s JOIN levels l ON l.id=s.level_id WHERE s.id=?",(sid,)).fetchone() or abort(404)
    cards=db().execute("SELECT * FROM flashcards WHERE lesson_id=? ORDER BY position,id",(sid,)).fetchall()
    return render_template("admin_cards.html",lesson=lesson,cards=cards)

@app.post("/admin/lessons/<int:sid>/flashcards")
@admin_required
def add_card(sid):
    front=request.form.get("front","").strip(); back=request.form.get("back","").strip()
    if front and back:
        p=db().execute("SELECT coalesce(max(position),0)+1 FROM flashcards WHERE lesson_id=?",(sid,)).fetchone()[0]; db().execute("INSERT INTO flashcards(lesson_id,front,back,position) VALUES(?,?,?,?)",(sid,front,back,p)); db().commit()
    return redirect(url_for("admin_cards",sid=sid)+"#add-card")

@app.post("/admin/cards/<int:cid>")
@admin_required
def edit_card(cid):
    conn=db(); row=conn.execute("SELECT * FROM flashcards WHERE id=?",(cid,)).fetchone() or abort(404); action=request.form.get("action","save")
    if action=="delete": conn.execute("DELETE FROM flashcards WHERE id=?",(cid,))
    elif action in {"up","down"}: conn.execute("UPDATE flashcards SET position=position+? WHERE id=?",(-1 if action=="up" else 1,cid))
    else: conn.execute("UPDATE flashcards SET front=?,back=?,is_active=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(request.form.get("front","").strip(),request.form.get("back","").strip(),1 if request.form.get("is_active") else 0,cid))
    conn.commit(); return redirect(url_for("admin_cards",sid=row["lesson_id"]))

@app.post("/admin/lessons/<int:sid>/import")
@admin_required
def bulk_import(sid):
    lines=request.form.get("bulk","").splitlines(); rows=[]
    for line in lines:
        parts=re.split(r"\s*[|,\t]\s*",line.strip(),maxsplit=1)
        if len(parts)==2 and all(parts): rows.append(parts)
    conn=db(); p=conn.execute("SELECT coalesce(max(position),0) FROM flashcards WHERE lesson_id=?",(sid,)).fetchone()[0]
    conn.executemany("INSERT INTO flashcards(lesson_id,front,back,position) VALUES(?,?,?,?)",[(sid,a,b,p+i) for i,(a,b) in enumerate(rows,1)]); conn.commit(); flash(f"Imported {len(rows)} cards.","success")
    return redirect(url_for("admin_cards",sid=sid))

@app.get("/admin/lessons/<int:sid>/export.csv")
@admin_required
def export_csv(sid):
    out=io.StringIO(); writer=csv.writer(out); writer.writerow(["front","back"]); writer.writerows(db().execute("SELECT front,back FROM flashcards WHERE lesson_id=? ORDER BY position,id",(sid,)).fetchall())
    resp=make_response(out.getvalue()); resp.headers["Content-Type"]="text/csv; charset=utf-8"; resp.headers["Content-Disposition"]=f"attachment; filename=lesson-{sid}.csv"; return resp

@app.get("/admin/backup")
@admin_required
def backup():
    data={t:[dict(r) for r in db().execute(f"SELECT * FROM {t} ORDER BY id")] for t in ("levels","lessons","flashcards")}
    resp=make_response(json.dumps({"version":1,"exported_at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),"data":data},ensure_ascii=False,indent=2)); resp.headers["Content-Type"]="application/json"; resp.headers["Content-Disposition"]="attachment; filename=long-live-latin-backup.json"; return resp

@app.post("/admin/restore")
@admin_required
def restore():
    try:
        payload=json.load(request.files["backup"]); data=payload["data"]; conn=db()
        with conn:
            conn.execute("DELETE FROM flashcards"); conn.execute("DELETE FROM lessons"); conn.execute("DELETE FROM levels")
            conn.executemany("INSERT INTO levels(id,name,slug,description,position,is_active) VALUES(:id,:name,:slug,:description,:position,:is_active)",data["levels"])
            conn.executemany("INSERT INTO lessons(id,level_id,title,slug,description,position,is_active) VALUES(:id,:level_id,:title,:slug,:description,:position,:is_active)",data["lessons"])
            conn.executemany("INSERT INTO flashcards(id,lesson_id,front,back,position,is_active,created_at,updated_at) VALUES(:id,:lesson_id,:front,:back,:position,:is_active,:created_at,:updated_at)",data["flashcards"])
        flash("Backup restored.","success")
    except Exception: flash("That backup could not be restored.","error")
    return redirect(url_for("admin"))

@app.get("/health")
def health(): return jsonify(status="ok")

with app.app_context(): init_db()
if __name__=="__main__": app.run(host="0.0.0.0",port=int(os.environ.get("PORT",8000)),debug=os.environ.get("FLASK_DEBUG")=="1")
