import csv, datetime, gzip, hashlib, io, json, os, random, re, secrets, sqlite3, time, unicodedata
from functools import wraps
from pathlib import Path
import bcrypt
from flask import Flask, abort, flash, g, jsonify, make_response, redirect, render_template, request, session, url_for

app = Flask(__name__)
STATIC_ROOT = Path(__file__).parent / "static"
asset_hasher = hashlib.sha256()
for asset_name in ("style.css", "app.js", "wordle.js"):
    asset_hasher.update((STATIC_ROOT / asset_name).read_bytes())
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    DATABASE=os.environ.get("DATABASE_PATH", str(Path(__file__).parent / "data" / "longlivelatin.db")),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "false").lower() == "true",
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    ASSET_VERSION=asset_hasher.hexdigest()[:12],
)
COLORS={"burgundy":"#87283A","terracotta":"#98503B","amber":"#C18A2D","olive":"#687037","forest":"#275D45","teal":"#256B6A","deep-blue":"#285A8F","indigo":"#4B4E83","purple":"#73517F","rose":"#9B5064","slate":"#56616B"}
TEXT_COLORS={"light":"#FFFBF4","cream":"#F1E3C0","charcoal":"#1E1C1A","navy":"#142A45"}
WELCOME_COLORS={"ink":"Ink","burgundy":"Burgundy","forest":"Forest","blue":"Blue","terracotta":"Terracotta","slate":"Slate"}
WELCOME_FONTS={"serif":"Newsreader (serif)","sans":"DM Sans (sans-serif)","classic":"Georgia (classic serif)","rounded":"Trebuchet (rounded sans)"}
DEFAULT_SETTINGS={"welcome_heading":"Welcome to Mrs. Leonte's Latin class","welcome_color":"ink","welcome_font":"serif","wordle_enabled":"0","wordle_verbum":"1","wordle_anagram":"1"}

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
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '');
    CREATE TABLE IF NOT EXISTS login_attempts(ip TEXT NOT NULL, attempted_at REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_login_attempts_ip ON login_attempts(ip,attempted_at);
    CREATE TABLE IF NOT EXISTS wordle_card_choices(card_id INTEGER PRIMARY KEY REFERENCES flashcards(id) ON DELETE CASCADE, side TEXT NOT NULL DEFAULT 'auto');
    CREATE TABLE IF NOT EXISTS wordle_extra_words(id INTEGER PRIMARY KEY, word TEXT NOT NULL, meaning TEXT NOT NULL DEFAULT '', is_active INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS wordle_schedule(game TEXT NOT NULL, level_id INTEGER NOT NULL REFERENCES wordle_levels(id) ON DELETE CASCADE, day TEXT NOT NULL, word TEXT NOT NULL, PRIMARY KEY(game,level_id,day));
    CREATE TABLE IF NOT EXISTS wordle_levels(id INTEGER PRIMARY KEY, name TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0, letters INTEGER NOT NULL, tries INTEGER NOT NULL, max_course_level INTEGER, is_active INTEGER NOT NULL DEFAULT 1, points_solved INTEGER NOT NULL, points_try INTEGER NOT NULL, points_green INTEGER NOT NULL, points_yellow INTEGER NOT NULL);
    """)
    conn.executemany("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",list(DEFAULT_SETTINGS.items()))
    lesson_columns={r[1] for r in conn.execute("PRAGMA table_info(lessons)")}
    if "color" not in lesson_columns: conn.execute("ALTER TABLE lessons ADD COLUMN color TEXT NOT NULL DEFAULT 'first-blue'")
    level_columns={r[1] for r in conn.execute("PRAGMA table_info(levels)")}
    if "color" not in level_columns: conn.execute("ALTER TABLE levels ADD COLUMN color TEXT NOT NULL DEFAULT 'deep-blue'")
    if "text_color" not in level_columns: conn.execute("ALTER TABLE levels ADD COLUMN text_color TEXT NOT NULL DEFAULT 'light'")
    if "color" not in level_columns: conn.execute("UPDATE levels SET color=CASE ((position-1)%3) WHEN 0 THEN 'deep-blue' WHEN 1 THEN 'burgundy' ELSE 'forest' END")
    conn.execute("UPDATE lessons SET color=CASE color WHEN 'first-blue' THEN 'deep-blue' WHEN 'first-navy' THEN 'indigo' WHEN 'second-crimson' THEN 'burgundy' WHEN 'second-wine' THEN 'rose' WHEN 'third-green' THEN 'forest' WHEN 'third-forest' THEN 'olive' WHEN 'book-cream' THEN 'amber' WHEN 'blue' THEN 'deep-blue' ELSE color END WHERE color IN ('first-blue','first-navy','second-crimson','second-wine','third-green','third-forest','book-cream','blue')")
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
    if conn.execute("SELECT count(*) FROM wordle_levels").fetchone()[0] == 0:
        conn.executemany("INSERT INTO wordle_levels(name,position,letters,tries,max_course_level,points_solved,points_try,points_green,points_yellow) VALUES(?,?,?,?,?,?,?,?,?)",WORDLE_DEFAULT_LEVELS)
    conn.commit()

# --- Wordle easter egg -------------------------------------------------------
# name, position, letters, tries, words from the first N course levels (None = all), points: solved, per try left, green, yellow
WORDLE_DEFAULT_LEVELS=[("Facilis",1,4,6,1,50,10,5,2),("Medius",2,5,6,2,100,20,8,3),("Difficilis",3,6,5,None,150,30,10,4)]
WORDLE_EPOCH=datetime.date(2026,1,1)
LATIN_ENDINGS=("us","um","ae","is","os","as","es","or","ur","nt","re","ri","ii","am","em","im","ix","ex","ax","o","a","i")
ENGLISH_ENDINGS=("ing","ed","ly","ght","ness","ful","ls","ts","ds","ks","ck","sh","th","w","y")
ENGLISH_COMMON=set("""a an the and or but if so not no yes to of in on at by for from with without into onto about above below under over after before
between through during until since because while than then there here where when why how who whom whose which what this that these those
i me my mine you your he him his she her it its we us our they them their is are was were be been being am do does did done have has had
can could will would shall should may might must go goes went come came give gave take took make made know knew see saw say said hear
love loves loved sing sang read write wrote walk run carry call tell ask want like work play fight live die eat drink sleep stand sit
man men woman women boy boys girl girls child children father mother brother sister son daughter friend enemy king queen god goddess
water fire earth land sea sky sun moon star tree flower horse dog cat bird fish house home city town road way war peace light night day
year hour time life death name word letter book school teacher student farmer sailor soldier slave master lord lady people world body
head hand eye eyes heart mind soul voice gift money gold good bad big small great little long short new old young happy sad high low
first last all every many much more most some few other same own very also always never often today now well again only just even
faith hope glory fortune wisdom virtue praise fear anger courage forest field river island mountain wall gate door temple altar""".split())
ENGLISH_BITS=("th","sh","ck","gh","wh","ee","oo","ou","ow","aw","ay","oy","w","k","y")

def wordle_token(text):
    """First word of a card side: (letters only, macrons removed) and (display form, macrons kept)."""
    first=re.split(r"[\s,;/()]+",(text or "").strip().lower(),maxsplit=1)[0]
    display=re.sub(r"[^a-zA-Z\u00C0-\u024F]","",first)
    plain=re.sub(r"[^a-z]","",unicodedata.normalize("NFD",display))
    return plain,display

def latin_score(word):
    """Rough guess at how Latin a word looks; only used to compare the two sides of a card."""
    if not word: return -9
    score=-4 if word in ENGLISH_COMMON else 0
    if word.endswith(LATIN_ENDINGS): score+=2
    if word.endswith(ENGLISH_ENDINGS): score-=2
    score-=sum(2 for bit in ENGLISH_BITS if bit in word)
    return score

GAME_NAMES={"verbum":"Verbum","anagram":"Anagramma"}
CARD_SIDES={"auto":"Auto","front":"Front","back":"Back","none":"Not in game"}

def wordle_card_rows():
    """Every active flashcard with the word the games use from it (the admin's choice, or the side that looks Latin)."""
    rows=db().execute("SELECT f.id,f.front,f.back,l.id level_id,l.name level_name,s.title lesson_title,c.side FROM flashcards f JOIN lessons s ON s.id=f.lesson_id JOIN levels l ON l.id=s.level_id LEFT JOIN wordle_card_choices c ON c.card_id=f.id WHERE f.is_active=1 AND s.is_active=1 AND l.is_active=1 ORDER BY l.position,l.id,s.position,s.id,f.position,f.id").fetchall()
    ranks={r["id"]:i for i,r in enumerate(db().execute("SELECT id FROM levels WHERE is_active=1 ORDER BY position,id"),1)}; out=[]
    for r in rows:
        (fp,fd),(bp,bd)=wordle_token(r["front"]),wordle_token(r["back"])
        auto="back" if latin_score(bp)>=latin_score(fp) else "front"
        side=r["side"] if r["side"] in CARD_SIDES else "auto"; use=auto if side=="auto" else side
        plain,display,meaning=((bp,bd,r["front"]) if use=="back" else (fp,fd,r["back"])) if use!="none" else ("","","")
        in_game=use!="none" and 3<=len(plain)<=8 and (side!="auto" or latin_score(plain)>=0)
        out.append({"id":r["id"],"front":r["front"],"back":r["back"],"level_id":r["level_id"],"level_name":r["level_name"],"lesson_title":r["lesson_title"],"rank":ranks[r["level_id"]],
                    "side":side,"auto":auto,"plain":plain,"display":display,"meaning":meaning.strip(),"in_game":in_game,"reviewed":r["side"] is not None})
    return out

def wordle_words(max_course_level=None,cards=None):
    """Words the games can use: {plain: (display, meaning)} from flashcards (up to a course level) plus the admin's extra words."""
    words={}
    for c in cards if cards is not None else wordle_card_rows():
        if c["in_game"] and (not max_course_level or c["rank"]<=max_course_level) and c["plain"] not in words: words[c["plain"]]=(c["display"],c["meaning"])
    for r in db().execute("SELECT word,meaning FROM wordle_extra_words WHERE is_active=1 ORDER BY id"):
        plain,display=wordle_token(r["word"])
        if 3<=len(plain)<=8 and plain not in words: words[plain]=(display,r["meaning"])
    return words

def wordle_answer(level,words,day,game="verbum"):
    """Same word for everyone on a given day: a fixed shuffle of the level's words, walked one per day. Each game has its own order."""
    pool=sorted(w for w in words if len(w)==level["letters"])
    if not pool: return None
    planned=db().execute("SELECT word FROM wordle_schedule WHERE game=? AND level_id=? AND day=?",(game,level["id"],day.isoformat())).fetchone()
    if planned and planned["word"] in pool: return planned["word"]
    random.Random(f"{game}-{level['id']}").shuffle(pool)
    return pool[(day-WORDLE_EPOCH).days % len(pool)]

def wordle_colours(guess,answer):
    result=["absent"]*len(answer); left={}
    for i,(g,a) in enumerate(zip(guess,answer)):
        if g==a: result[i]="correct"
        else: left[a]=left.get(a,0)+1
    for i,g in enumerate(guess):
        if result[i]!="correct" and left.get(g):
            result[i]="present"; left[g]-=1
    return result

def wordle_score(level,rows,solved):
    if solved:
        left=level["tries"]-len(rows)
        return {"points":level["points_solved"]+left*level["points_try"],"detail":f"{level['points_solved']} for solving + {left} {'try' if left==1 else 'tries'} left × {level['points_try']}"}
    best=max(rows,key=lambda r:(r.count("correct")*level["points_green"]+r.count("present")*level["points_yellow"]))
    g,y=best.count("correct"),best.count("present")
    return {"points":g*level["points_green"]+y*level["points_yellow"],"detail":f"{g} green × {level['points_green']} + {y} yellow × {level['points_yellow']} (best guess)"}

def anagram_letters(answer,level,day):
    """The answer's letters in a fixed mixed-up order for the day, never already in the right order."""
    letters=list(answer.upper()); rng=random.Random(f"anagram-{level['id']}-{day.isoformat()}")
    for _ in range(20):
        rng.shuffle(letters)
        if "".join(letters).lower()!=answer: break
    return letters

def anagram_score(level,wrong,solved):
    if not solved: return {"points":0,"detail":"Not solved"}
    penalty=level["points_try"]//2; floor=level["points_solved"]//5
    points=max(level["points_solved"]-wrong*penalty,floor)
    return {"points":points,"detail":f"{level['points_solved']} for solving − {wrong} wrong × {penalty}" + (f" (minimum {floor})" if points==floor and wrong else "")}

def wordle_games():
    settings=get_settings()
    if settings.get("wordle_enabled")!="1": return []
    return [g for g in GAME_NAMES if settings.get(f"wordle_{g}","1")=="1"]

def wordle_levels_with_words(game=None):
    games=wordle_games()
    if not games or (game and game not in games): return [],{}
    levels=[dict(r) for r in db().execute("SELECT * FROM wordle_levels WHERE is_active=1 ORDER BY position,id")]
    cache={}; cards=wordle_card_rows()
    for lv in levels:
        key=lv["max_course_level"]
        if key not in cache: cache[key]=wordle_words(key,cards)
        lv["words"]=cache[key]
    return [lv for lv in levels if any(len(w)==lv["letters"] for w in lv["words"])],cache

def wordle_admin_summary(cards=None):
    cache={}; out=[]; cards=cards if cards is not None else wordle_card_rows()
    for lv in db().execute("SELECT * FROM wordle_levels ORDER BY position,id"):
        key=lv["max_course_level"]
        if key not in cache: cache[key]=wordle_words(key,cards)
        words=sorted((p,d,m) for p,(d,m) in cache[key].items() if len(p)==lv["letters"])
        out.append({**dict(lv),"source":"Latin Level 1" if key==1 else (f"Levels 1–{key}" if key else "All levels"),"words":words,"all_words":cache[key]})
    return out

def slugify(value):
    base=re.sub(r"[^a-z0-9]+","-",value.lower()).strip("-") or "item"
    return f"{base}-{secrets.token_hex(2)}"

def csrf_token():
    if "csrf" not in session: session["csrf"]=secrets.token_urlsafe(24)
    return session["csrf"]
app.jinja_env.globals["csrf_token"]=csrf_token
app.jinja_env.globals["lesson_colors"]=COLORS
app.jinja_env.globals["text_colors"]=TEXT_COLORS
app.jinja_env.globals["welcome_colors"]=WELCOME_COLORS
app.jinja_env.globals["welcome_fonts"]=WELCOME_FONTS

def get_settings():
    rows=db().execute("SELECT key,value FROM settings").fetchall()
    settings=dict(DEFAULT_SETTINGS); settings.update({r["key"]:r["value"] for r in rows})
    return settings

@app.context_processor
def inject_settings():
    return {"site_settings": get_settings()}
def roman(n):
    values=((1000,"M"),(900,"CM"),(500,"D"),(400,"CD"),(100,"C"),(90,"XC"),(50,"L"),(40,"XL"),(10,"X"),(9,"IX"),(5,"V"),(4,"IV"),(1,"I")); out=""
    for value,symbol in values:
        while n>=value: out+=symbol; n-=value
    return out
app.jinja_env.globals["roman"]=roman

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
    resp.headers["Cache-Control"]="no-store, max-age=0"
    return resp

@app.after_request
def compress(resp):
    """Gzip pages and JSON for browsers that accept it (the Game Center page with hundreds of cards shrinks several times)."""
    if (resp.direct_passthrough or resp.status_code!=200 or resp.headers.get("Content-Encoding") or "gzip" not in request.headers.get("Accept-Encoding","")
            or resp.mimetype not in ("text/html","application/json")): return resp
    data=resp.get_data()
    if len(data)<1500: return resp
    resp.set_data(gzip.compress(data,5)); resp.headers["Content-Encoding"]="gzip"; resp.headers["Vary"]="Accept-Encoding"
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
        ip=request.remote_addr or "unknown"; now=time.time(); conn=db(); conn.execute("DELETE FROM login_attempts WHERE attempted_at<?",(now-900,)); conn.commit()
        if conn.execute("SELECT count(*) FROM login_attempts WHERE ip=?",(ip,)).fetchone()[0]>=5: flash("Too many sign-in attempts. Try again in 15 minutes.","error"); return render_template("login.html"),429
        user=db().execute("SELECT * FROM users WHERE username=?",(request.form.get("username","").strip(),)).fetchone()
        valid=user and bcrypt.checkpw(request.form.get("password","").encode(),user["password_hash"].encode())
        if valid:
            session.clear(); session["admin"]=True; session["user_id"]=user["id"]; csrf_token(); conn.execute("DELETE FROM login_attempts WHERE ip=?",(ip,)); conn.commit(); return redirect(url_for("admin"))
        conn.execute("INSERT INTO login_attempts(ip,attempted_at) VALUES(?,?)",(ip,now)); conn.commit(); flash("Incorrect username or password.","error")
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

@app.post("/admin/settings")
@admin_required
def update_settings():
    heading=request.form.get("welcome_heading","").strip()[:120] or DEFAULT_SETTINGS["welcome_heading"]
    color=request.form.get("welcome_color","ink"); color=color if color in WELCOME_COLORS else "ink"
    font=request.form.get("welcome_font","serif"); font=font if font in WELCOME_FONTS else "serif"
    conn=db()
    conn.executemany("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",[("welcome_heading",heading),("welcome_color",color),("welcome_font",font)])
    conn.commit(); flash("Homepage welcome message updated.","success")
    return redirect(url_for("admin")+"#welcome")

@app.post("/admin/levels")
@admin_required
def add_level():
    name=request.form.get("name","").strip()
    if name:
        p=db().execute("SELECT coalesce(max(position),0)+1 FROM levels").fetchone()[0]; defaults=("deep-blue","burgundy","forest"); color=request.form.get("color",defaults[(p-1)%3]); color=color if color in COLORS else defaults[(p-1)%3]; text_color=request.form.get("text_color","light"); text_color=text_color if text_color in TEXT_COLORS else "light"; db().execute("INSERT INTO levels(name,slug,description,color,text_color,position) VALUES(?,?,?,?,?,?)",(name,slugify(name),request.form.get("description","").strip(),color,text_color,p)); db().commit()
    return redirect(url_for("admin"))

@app.post("/admin/levels/<int:lid>")
@admin_required
def edit_level(lid):
    action=request.form.get("action","save"); conn=db()
    if action=="delete": conn.execute("DELETE FROM levels WHERE id=?",(lid,))
    elif action in {"up","down"}: move_item("levels",lid,action)
    else:
        row=conn.execute("SELECT color,text_color FROM levels WHERE id=?",(lid,)).fetchone() or abort(404)
        color=request.form.get("color",row["color"]); color=color if color in COLORS else "deep-blue"; text_color=request.form.get("text_color",row["text_color"]); text_color=text_color if text_color in TEXT_COLORS else "light"; conn.execute("UPDATE levels SET name=?,description=?,color=?,text_color=?,is_active=? WHERE id=?",(request.form.get("name","").strip(),request.form.get("description","").strip(),color,text_color,1 if request.form.get("is_active") else 0,lid))
    conn.commit(); return redirect(url_for("admin"))

@app.get("/admin/levels/<int:lid>")
@admin_required
def admin_level(lid):
    level=db().execute("SELECT * FROM levels WHERE id=?",(lid,)).fetchone() or abort(404)
    lessons=db().execute("SELECT s.*,count(f.id) card_count FROM lessons s LEFT JOIN flashcards f ON f.lesson_id=s.id WHERE s.level_id=? GROUP BY s.id ORDER BY s.position,s.id",(lid,)).fetchall()
    all_levels=db().execute("SELECT id,name FROM levels ORDER BY position,id").fetchall()
    return render_template("admin_level.html",level=level,lessons=lessons,all_levels=all_levels)

def normalize_positions(table,parent=None,parent_id=None):
    where=f" WHERE {parent}=?" if parent else ""; args=(parent_id,) if parent else ()
    rows=db().execute(f"SELECT id FROM {table}{where} ORDER BY position,id",args).fetchall()
    db().executemany(f"UPDATE {table} SET position=? WHERE id=?",[(i,r["id"]) for i,r in enumerate(rows,1)])

def move_item(table,item_id,direction,parent=None):
    allowed={"levels":None,"lessons":"level_id","flashcards":"lesson_id"}
    if table not in allowed: return
    parent=allowed[table]; row=db().execute(f"SELECT * FROM {table} WHERE id=?",(item_id,)).fetchone()
    if not row:return
    clause=f"AND {parent}=?" if parent else ""; args=(row[parent],) if parent else ()
    op,pos_order=("<","DESC") if direction=="up" else (">","ASC")
    other=db().execute(f"SELECT * FROM {table} WHERE position {op} ? {clause} ORDER BY position {pos_order},id {pos_order} LIMIT 1",(row["position"],*args)).fetchone()
    if other: db().execute(f"UPDATE {table} SET position=? WHERE id=?",(other["position"],item_id)); db().execute(f"UPDATE {table} SET position=? WHERE id=?",(row["position"],other["id"]))

@app.post("/admin/reorder")
@admin_required
def reorder():
    payload=request.get_json(silent=True) or {}; kind=payload.get("kind"); ids=payload.get("ids")
    config={"levels":("levels",None),"lessons":("lessons","level_id"),"flashcards":("flashcards","lesson_id")}
    if kind not in config or not isinstance(ids,list) or not ids or not all(isinstance(x,int) for x in ids): return jsonify(error="Invalid order"),400
    table,parent=config[kind]; placeholders=','.join('?' for _ in ids); rows=db().execute(f"SELECT id{','+parent if parent else ''} FROM {table} WHERE id IN ({placeholders})",ids).fetchall()
    if len(rows)!=len(ids) or (parent and len({r[parent] for r in rows})!=1): return jsonify(error="Items must share a parent"),400
    db().executemany(f"UPDATE {table} SET position=? WHERE id=?",[(i,x) for i,x in enumerate(ids,1)]); db().commit(); return jsonify(status="saved")

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
        color=request.form.get("color","burgundy"); color=color if color in COLORS else "burgundy"; p=db().execute("SELECT coalesce(max(position),0)+1 FROM lessons WHERE level_id=?",(lid,)).fetchone()[0]; db().execute("INSERT INTO lessons(level_id,title,slug,description,color,position) VALUES(?,?,?,?,?,?)",(lid,title,slugify(title),request.form.get("description","").strip(),color,p)); db().commit()
    return redirect(url_for("admin_level",lid=lid))

@app.post("/admin/lessons/<int:sid>")
@admin_required
def edit_lesson(sid):
    conn=db(); row=conn.execute("SELECT * FROM lessons WHERE id=?",(sid,)).fetchone() or abort(404); action=request.form.get("action","save")
    if action=="delete": conn.execute("DELETE FROM lessons WHERE id=?",(sid,)); dest=row["level_id"]
    elif action in {"up","down"}: move_item("lessons",sid,action); dest=row["level_id"]
    else:
        dest=int(request.form.get("level_id",row["level_id"])); color=request.form.get("color","burgundy"); color=color if color in COLORS else "burgundy"; conn.execute("UPDATE lessons SET level_id=?,title=?,description=?,color=?,is_active=? WHERE id=?",(dest,request.form.get("title","").strip(),request.form.get("description","").strip(),color,1 if request.form.get("is_active") else 0,sid))
    conn.commit(); return redirect(url_for("admin_level",lid=dest))

@app.get("/admin/lessons/<int:sid>/flashcards")
@admin_required
def admin_cards(sid):
    lesson=db().execute("SELECT s.*,l.name level_name FROM lessons s JOIN levels l ON l.id=s.level_id WHERE s.id=?",(sid,)).fetchone() or abort(404)
    cards=db().execute("SELECT * FROM flashcards WHERE lesson_id=? ORDER BY position,id",(sid,)).fetchall(); all_lessons=db().execute("SELECT s.id,s.title,l.name level_name FROM lessons s JOIN levels l ON l.id=s.level_id ORDER BY l.position,s.position").fetchall()
    return render_template("admin_cards.html",lesson=lesson,cards=cards,all_lessons=all_lessons)

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
    elif action in {"up","down"}: move_item("flashcards",cid,action)
    elif action=="duplicate":
        p=conn.execute("SELECT coalesce(max(position),0)+1 FROM flashcards WHERE lesson_id=?",(row["lesson_id"],)).fetchone()[0]; conn.execute("INSERT INTO flashcards(lesson_id,front,back,position,is_active) VALUES(?,?,?,?,?)",(row["lesson_id"],row["front"],row["back"],p,row["is_active"]))
    else:
        dest=int(request.form.get("lesson_id",row["lesson_id"])); conn.execute("UPDATE flashcards SET lesson_id=?,front=?,back=?,is_active=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(dest,request.form.get("front","").strip(),request.form.get("back","").strip(),1 if request.form.get("is_active") else 0,cid))
    conn.commit(); return redirect(url_for("admin_cards",sid=row["lesson_id"]))

@app.post("/admin/lessons/<int:sid>/duplicate")
@admin_required
def duplicate_lesson(sid):
    conn=db(); lesson=conn.execute("SELECT * FROM lessons WHERE id=?",(sid,)).fetchone() or abort(404); p=conn.execute("SELECT coalesce(max(position),0)+1 FROM lessons WHERE level_id=?",(lesson["level_id"],)).fetchone()[0]
    conn.execute("INSERT INTO lessons(level_id,title,slug,description,color,position,is_active) VALUES(?,?,?,?,?,?,?)",(lesson["level_id"],lesson["title"]+" — Copy",slugify(lesson["title"]),lesson["description"],lesson["color"],p,lesson["is_active"])); new_id=conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute("INSERT INTO flashcards(lesson_id,front,back,position,is_active) SELECT ?,front,back,position,is_active FROM flashcards WHERE lesson_id=?",(new_id,sid)); conn.commit(); return redirect(url_for("admin_level",lid=lesson["level_id"]))

@app.post("/admin/lessons/<int:sid>/bulk")
@admin_required
def bulk_cards(sid):
    ids=[int(x) for x in request.form.getlist("card_ids") if x.isdigit()]; action=request.form.get("bulk_action"); conn=db()
    if not ids: flash("Select at least one card.","error"); return redirect(url_for("admin_cards",sid=sid))
    marks=','.join('?' for _ in ids); valid=[r[0] for r in conn.execute(f"SELECT id FROM flashcards WHERE lesson_id=? AND id IN ({marks})",[sid,*ids])]
    if action=="activate": conn.execute(f"UPDATE flashcards SET is_active=1 WHERE id IN ({marks})",valid)
    elif action=="deactivate": conn.execute(f"UPDATE flashcards SET is_active=0 WHERE id IN ({marks})",valid)
    elif action=="delete": conn.execute(f"DELETE FROM flashcards WHERE id IN ({marks})",valid)
    elif action=="move" and request.form.get("target_lesson","").isdigit(): conn.execute(f"UPDATE flashcards SET lesson_id=? WHERE id IN ({marks})",[int(request.form["target_lesson"]),*valid])
    normalize_positions("flashcards","lesson_id",sid); conn.commit(); flash(f"Updated {len(valid)} cards.","success"); return redirect(url_for("admin_cards",sid=sid))

@app.post("/admin/lessons/<int:sid>/import")
@admin_required
def bulk_import(sid):
    lines=request.form.get("bulk","").splitlines(); rows=[]
    for line in lines:
        parts=re.split(r"\s*\|\s*",line.strip(),maxsplit=1)
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
    games={"settings":{k:v for k,v in get_settings().items() if k in WORDLE_SETTING_KEYS},
           "levels":[dict(r) for r in db().execute("SELECT * FROM wordle_levels ORDER BY id")],
           "card_choices":[dict(r) for r in db().execute("SELECT * FROM wordle_card_choices ORDER BY card_id")],
           "extra_words":[dict(r) for r in db().execute("SELECT * FROM wordle_extra_words ORDER BY id")],
           "schedule":[dict(r) for r in db().execute("SELECT * FROM wordle_schedule ORDER BY day,game,level_id")]}
    resp=make_response(json.dumps({"version":2,"games":games,"exported_at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),"data":data},ensure_ascii=False,indent=2)); resp.headers["Content-Type"]="application/json"; resp.headers["Content-Disposition"]="attachment; filename=long-live-latin-backup.json"; return resp

WORDLE_SETTING_KEYS=("wordle_enabled","wordle_verbum","wordle_anagram")

def restore_games(conn,games,kept_choices):
    """Put back the word games from a backup. Older backups have no games section: keep the current card choices for cards that still exist."""
    cards={r[0] for r in conn.execute("SELECT id FROM flashcards")}
    if not games:
        conn.executemany("INSERT OR REPLACE INTO wordle_card_choices(card_id,side) VALUES(:card_id,:side)",[c for c in kept_choices if c["card_id"] in cards])
        return
    for key in WORDLE_SETTING_KEYS:
        if key in games.get("settings",{}): conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(key,"1" if str(games["settings"][key])=="1" else "0"))
    conn.execute("DELETE FROM wordle_schedule"); conn.execute("DELETE FROM wordle_extra_words"); conn.execute("DELETE FROM wordle_card_choices")
    if games.get("levels"):
        conn.execute("DELETE FROM wordle_levels")
        conn.executemany("INSERT INTO wordle_levels(id,name,position,letters,tries,max_course_level,is_active,points_solved,points_try,points_green,points_yellow) VALUES(:id,:name,:position,:letters,:tries,:max_course_level,:is_active,:points_solved,:points_try,:points_green,:points_yellow)",games["levels"])
    levels={r[0] for r in conn.execute("SELECT id FROM wordle_levels")}
    conn.executemany("INSERT INTO wordle_card_choices(card_id,side) VALUES(:card_id,:side)",[c for c in games.get("card_choices",[]) if c.get("card_id") in cards and c.get("side") in CARD_SIDES])
    conn.executemany("INSERT INTO wordle_extra_words(id,word,meaning,is_active) VALUES(:id,:word,:meaning,:is_active)",games.get("extra_words",[]))
    conn.executemany("INSERT INTO wordle_schedule(game,level_id,day,word) VALUES(:game,:level_id,:day,:word)",[x for x in games.get("schedule",[]) if x.get("game") in GAME_NAMES and x.get("level_id") in levels])

@app.post("/admin/restore")
@admin_required
def restore():
    try:
        payload=json.load(request.files["backup"]); data=payload["data"]; games=payload.get("games"); conn=db()
        with conn:
            kept_choices=[dict(r) for r in conn.execute("SELECT card_id,side FROM wordle_card_choices")]
            conn.execute("DELETE FROM flashcards"); conn.execute("DELETE FROM lessons"); conn.execute("DELETE FROM levels")
            for level in data["levels"]: level.setdefault("color","deep-blue"); level.setdefault("text_color","light")
            conn.executemany("INSERT INTO levels(id,name,slug,description,color,text_color,position,is_active) VALUES(:id,:name,:slug,:description,:color,:text_color,:position,:is_active)",data["levels"])
            for lesson in data["lessons"]: lesson.setdefault("color","burgundy")
            conn.executemany("INSERT INTO lessons(id,level_id,title,slug,description,color,position,is_active) VALUES(:id,:level_id,:title,:slug,:description,:color,:position,:is_active)",data["lessons"])
            conn.executemany("INSERT INTO flashcards(id,lesson_id,front,back,position,is_active,created_at,updated_at) VALUES(:id,:lesson_id,:front,:back,:position,:is_active,:created_at,:updated_at)",data["flashcards"])
            restore_games(conn,games,kept_choices)
        flash("Backup restored, including the word games." if games else "Backup restored.","success")
    except Exception: flash("That backup could not be restored.","error")
    return redirect(url_for("admin"))

@app.get("/api/wordle")
def wordle_config():
    levels,_=wordle_levels_with_words()
    if not levels: abort(404)
    return jsonify(games=[{"id":g,"name":GAME_NAMES[g]} for g in wordle_games()],levels=[{"id":lv["id"],"name":lv["name"],"letters":lv["letters"],"tries":lv["tries"]} for lv in levels],number=(player_day()-WORDLE_EPOCH).days+1)

def player_day():
    """The player's local date when it is sent and plausible (players are in the US), otherwise the server's UTC date."""
    utc=datetime.datetime.now(datetime.timezone.utc).date()
    try: day=datetime.date.fromisoformat(request.args.get("date",""))
    except ValueError: return utc
    return day if abs((day-utc).days)<=1 else utc

@app.get("/api/wordle/check")
def wordle_check():
    level,day,cache,err=wordle_request_level("verbum")
    if err: return err
    answer=wordle_answer(level,level["words"],day)
    allowed={w for words in cache.values() for w in words if len(w)==level["letters"]}
    guesses=[wordle_token(g)[0] for g in request.args.get("guesses","").split(",") if g.strip()][:level["tries"]]
    rows=[]
    for i,guess in enumerate(guesses):
        if len(guess)!=level["letters"]: return jsonify(error=f"Use {level['letters']} letters",index=i)
        if guess not in allowed: return jsonify(error="Not in the word list",index=i)
        rows.append(wordle_colours(guess,answer))
        if guess==answer: break
    solved=bool(guesses) and guesses[len(rows)-1]==answer
    out={"rows":rows,"used":len(rows),"solved":solved,"finished":solved or len(rows)>=level["tries"],"number":(day-WORDLE_EPOCH).days+1}
    if out["finished"]:
        display,meaning=level["words"][answer]
        out.update(answer=display,meaning=meaning,score=wordle_score(level,rows,solved))
    return jsonify(out)

def wordle_request_level(game):
    """The level and day asked for by a game request, or an error response."""
    levels,cache=wordle_levels_with_words(game)
    level=next((lv for lv in levels if str(lv["id"])==request.args.get("level")),None)
    if not level: abort(404)
    try: day=datetime.date.fromisoformat(request.args.get("date",""))
    except ValueError: return None,None,None,(jsonify(error="Invalid date"),400)
    if abs((day-datetime.datetime.now(datetime.timezone.utc).date()).days)>1: return None,None,None,(jsonify(error="Invalid date"),400)
    return level,day,cache,None

@app.get("/api/wordle/anagram")
def anagram_puzzle():
    level,day,_,err=wordle_request_level("anagram")
    if err: return err
    answer=wordle_answer(level,level["words"],day,"anagram")
    return jsonify(letters=anagram_letters(answer,level,day),tries=level["tries"],number=(day-WORDLE_EPOCH).days+1)

@app.get("/api/wordle/anagram/check")
def anagram_check():
    level,day,cache,err=wordle_request_level("anagram")
    if err: return err
    answer=wordle_answer(level,level["words"],day,"anagram")
    allowed={w for words in cache.values() for w in words if len(w)==level["letters"]}
    attempts=[wordle_token(a)[0] for a in request.args.get("attempts","").split(",") if a.strip()][:level["tries"]]
    wrong=0; solved=False
    for i,attempt in enumerate(attempts):
        if sorted(attempt)!=sorted(answer): return jsonify(error="Use the letters given",index=i)
        if attempt==answer: solved=True; break
        if attempt in allowed: return jsonify(error="A Latin word, but not today's",index=i)
        wrong+=1
    out={"wrong":wrong,"used":wrong+solved,"solved":solved,"finished":solved or wrong>=level["tries"],"tries":level["tries"],"number":(day-WORDLE_EPOCH).days+1}
    if out["finished"]:
        display,meaning=level["words"][answer]
        out.update(answer=display,meaning=meaning,score=anagram_score(level,wrong,solved))
    return jsonify(out)

@app.post("/admin/wordle/settings")
@admin_required
def wordle_settings():
    keys=("wordle_enabled","wordle_verbum","wordle_anagram") if request.form.get("games_form") else ("wordle_enabled",)
    conn=db(); conn.executemany("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",[(k,"1" if request.form.get(k) else "0") for k in keys]); conn.commit()
    return redirect(request.form.get("next") if request.form.get("next","").startswith("/admin") else url_for("admin")+"#wordle")

def int_field(name,default,low,high):
    try: value=int(request.form.get(name,default))
    except (TypeError,ValueError): value=default
    return max(low,min(high,value))

@app.get("/admin/games")
@admin_required
def admin_games():
    cards=wordle_card_rows(); summary=wordle_admin_summary(cards); today=datetime.datetime.now(datetime.timezone.utc).date()-datetime.timedelta(days=1)
    course_levels=db().execute("SELECT id,name FROM levels WHERE is_active=1 ORDER BY position,id").fetchall()
    schedule=db().execute("SELECT s.*,l.name level_name FROM wordle_schedule s JOIN wordle_levels l ON l.id=s.level_id WHERE s.day>=? ORDER BY s.day,l.position,s.game",(today.isoformat(),)).fetchall()
    extras=db().execute("SELECT * FROM wordle_extra_words ORDER BY word").fetchall()
    new_count=sum(1 for c in cards if not c["reviewed"])
    lessons={}
    cards_json={"sides":CARD_SIDES,"lessons":[],"cards":[]}
    for c in cards:   # compact rows: the page draws them in the browser, 100 at a time
        key=f"{c['level_name']} · {c['lesson_title']}"
        if key not in lessons: lessons[key]=len(lessons); cards_json["lessons"].append(key)
        cards_json["cards"].append([c["id"],c["front"],c["back"],lessons[key],c["level_id"],c["side"],c["auto"],c["display"] if c["in_game"] else "",c["meaning"] if c["in_game"] else "",int(c["in_game"]),int(c["reviewed"]),len(c["plain"]) if c["in_game"] else 0])
    return render_template("admin_games.html",cards_json=cards_json,card_total=len(cards),summary=summary,course_levels=course_levels,schedule=schedule,extras=extras,new_count=new_count,
                           games=GAME_NAMES,card_sides=CARD_SIDES,lengths=range(3,9))

@app.get("/admin/games/today")
@admin_required
def admin_games_today():
    """Each level's word for each game on the admin's own date (sent by the browser, so it follows local time)."""
    try: day=datetime.date.fromisoformat(request.args.get("date",""))
    except ValueError: day=datetime.datetime.now(datetime.timezone.utc).date()
    out={}
    for lv in wordle_admin_summary():
        out[lv["id"]]={g:(lambda w: lv["all_words"][w][0] if w else None)(wordle_answer(lv,lv["all_words"],day,g)) for g in GAME_NAMES}
    return jsonify(date=day.isoformat(),levels=out)

@app.post("/admin/games/levels/<int:wid>")
@admin_required
def admin_game_level(wid):
    db().execute("SELECT id FROM wordle_levels WHERE id=?",(wid,)).fetchone() or abort(404)
    source=request.form.get("max_course_level","")
    db().execute("UPDATE wordle_levels SET name=?,letters=?,tries=?,max_course_level=?,is_active=?,points_solved=?,points_try=?,points_green=?,points_yellow=? WHERE id=?",
        ((request.form.get("name","").strip() or "Level")[:40],int_field("letters",5,3,8),int_field("tries",6,4,8),int(source) if source.isdigit() and int(source)>0 else None,
         1 if request.form.get("is_active") else 0,int_field("points_solved",100,0,1000),int_field("points_try",20,0,1000),int_field("points_green",8,0,1000),int_field("points_yellow",3,0,1000),wid))
    db().commit(); return redirect(url_for("admin_games")+"#levels")

@app.post("/admin/games/cards/<int:cid>")
@admin_required
def admin_game_card(cid):
    side=request.form.get("side","auto"); side=side if side in CARD_SIDES else "auto"
    db().execute("SELECT id FROM flashcards WHERE id=?",(cid,)).fetchone() or abort(404)
    db().execute("INSERT INTO wordle_card_choices(card_id,side) VALUES(?,?) ON CONFLICT(card_id) DO UPDATE SET side=excluded.side",(cid,side)); db().commit()
    card=next((c for c in wordle_card_rows() if c["id"]==cid),None)
    return jsonify(status="saved",in_game=bool(card and card["in_game"]),word=card["display"] if card else "",meaning=card["meaning"] if card else "",length=len(card["plain"]) if card and card["in_game"] else 0)

@app.post("/admin/games/cards/review-all")
@admin_required
def admin_game_review_all():
    db().execute("INSERT OR IGNORE INTO wordle_card_choices(card_id,side) SELECT id,'auto' FROM flashcards"); db().commit()
    flash("All cards marked as reviewed.","success"); return redirect(url_for("admin_games")+"#words")

@app.post("/admin/games/extra")
@admin_required
def admin_game_extra():
    if request.form.get("delete","").isdigit():
        db().execute("DELETE FROM wordle_extra_words WHERE id=?",(int(request.form["delete"]),)); db().commit(); flash("Word removed.","success")
        return redirect(url_for("admin_games")+"#extra")
    word=request.form.get("word","").strip(); plain,_=wordle_token(word)
    if not 3<=len(plain)<=8 or " " in word: flash("Enter one word of 3 to 8 letters.","error")
    else: db().execute("INSERT INTO wordle_extra_words(word,meaning) VALUES(?,?)",(word[:40],request.form.get("meaning","").strip()[:120])); db().commit(); flash(f"Added {word}.","success")
    return redirect(url_for("admin_games")+"#extra")

@app.post("/admin/games/schedule")
@admin_required
def admin_game_schedule():
    game=request.form.get("game"); day=request.form.get("day","")
    if request.form.get("delete"):
        db().execute("DELETE FROM wordle_schedule WHERE game=? AND level_id=? AND day=?",(game,request.form.get("level_id"),day)); db().commit(); flash("Planned word removed.","success")
        return redirect(url_for("admin_games")+"#schedule")
    level=db().execute("SELECT * FROM wordle_levels WHERE id=?",(request.form.get("level_id"),)).fetchone()
    plain,_=wordle_token(request.form.get("word",""))
    try: datetime.date.fromisoformat(day); valid_day=True
    except ValueError: valid_day=False
    if game not in GAME_NAMES or not level or not valid_day: flash("Choose a game, a level and a date.","error")
    elif plain not in wordle_words(level["max_course_level"]) or len(plain)!=level["letters"]: flash(f"“{plain or 'That'}” is not one of {level['name']}'s {level['letters']}-letter words.","error")
    else:
        db().execute("INSERT INTO wordle_schedule(game,level_id,day,word) VALUES(?,?,?,?) ON CONFLICT(game,level_id,day) DO UPDATE SET word=excluded.word",(game,level["id"],day,plain)); db().commit()
        flash(f"{GAME_NAMES[game]} · {level['name']} will use “{plain}” on {day}.","success")
    return redirect(url_for("admin_games")+"#schedule")

@app.get("/health")
def health(): return jsonify(status="ok")

with app.app_context(): init_db()
if __name__=="__main__": app.run(host="0.0.0.0",port=int(os.environ.get("PORT",8000)),debug=os.environ.get("FLASK_DEBUG")=="1")
