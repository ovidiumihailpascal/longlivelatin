import os, tempfile, unittest, bcrypt

tmp=tempfile.NamedTemporaryFile(suffix='.db',delete=False); tmp.close()
os.environ['DATABASE_PATH']=tmp.name
os.environ['ADMIN_USERNAME']='admin'
os.environ['ADMIN_PASSWORD_HASH']=bcrypt.hashpw(b'test-password',bcrypt.gensalt()).decode()
os.environ['SECRET_KEY']='test-secret-key'
os.environ['COOKIE_SECURE']='false'
from app import app, db

class AppTests(unittest.TestCase):
    def setUp(self): self.client=app.test_client()
    def login(self): return self.client.post('/admin/login',data={'username':'admin','password':'test-password'},follow_redirects=True)
    def csrf(self):
        with self.client.session_transaction() as s:
            s['csrf']='test-csrf'; return s['csrf']
    def test_public_flow_and_hidden_admin(self):
        self.assertEqual(self.client.get('/').status_code,200)
        self.assertIn(b'Latin Level 1',self.client.get('/').data)
        self.assertEqual(self.client.get('/level/latin-1').status_code,200)
        self.assertIn(b'\"vir\"',self.client.get('/study/1').data)
        self.assertEqual(self.client.get('/admin').status_code,302)
    def test_login_and_content_crud(self):
        self.assertEqual(self.login().status_code,200); token=self.csrf()
        res=self.client.post('/admin/levels',data={'csrf_token':token,'name':'Latin Level 4'},follow_redirects=True)
        self.assertIn(b'Latin Level 4',res.data)
        res=self.client.post('/admin/lessons',data={'csrf_token':token,'level_id':'1','title':'Verbs'},follow_redirects=True)
        self.assertIn(b'Verbs',res.data)
        res=self.client.post('/admin/lessons/1/flashcards',data={'csrf_token':token,'front':'love','back':'amo'},follow_redirects=True)
        self.assertIn(b'amo',res.data)
        self.assertEqual(self.client.get('/admin/backup').status_code,200)
        res=self.client.post('/admin/password',data={'csrf_token':token,'current_password':'test-password','new_password':'Changed123','confirm_password':'Changed123'},follow_redirects=True)
        self.assertIn(b'Password changed successfully',res.data)
    def test_csrf_rejected(self):
        self.login(); self.assertEqual(self.client.post('/admin/levels',data={'name':'Bad'}).status_code,400)
    def test_every_level_uses_same_admin_and_full_card_color(self):
        self.login(); token=self.csrf()
        for level_id in (1,2,3):
            page=self.client.get(f'/admin/levels/{level_id}')
            self.assertEqual(page.status_code,200); self.assertIn(b'Edit level',page.data); self.assertIn(b'Add lesson',page.data)
        self.client.post('/admin/levels',data={'csrf_token':token,'name':'Latin Level 4','description':'Dynamic','color':'forest','text_color':'cream'})
        with app.app_context(): level=dict(db().execute("SELECT * FROM levels WHERE name='Latin Level 4' ORDER BY id DESC LIMIT 1").fetchone())
        self.assertIn(b'Edit level',self.client.get(f"/admin/levels/{level['id']}").data)
        self.assertIn(b'color-forest text-cream',self.client.get('/').data)
        self.client.post('/admin/lessons',data={'csrf_token':token,'level_id':level['id'],'title':'Blue lesson','color':'deep-blue'})
        public=self.client.get(f"/level/{level['slug']}")
        self.assertIn(b'color-deep-blue',public.data); self.assertIn(b'Blue lesson',public.data)
        with app.app_context(): lesson=dict(db().execute("SELECT * FROM lessons WHERE level_id=?",(level['id'],)).fetchone())
        self.client.post(f"/admin/lessons/{lesson['id']}",data={'csrf_token':token,'level_id':level['id'],'title':'Blue lesson','description':'','color':'burgundy','is_active':'on'})
        self.assertIn(b'color-burgundy',self.client.get(f"/level/{level['slug']}").data)

    def test_level_row_save_keeps_tile_colours(self):
        self.login(); token=self.csrf()
        self.client.post('/admin/levels',data={'csrf_token':token,'name':'Colour Level','color':'forest','text_color':'cream'})
        with app.app_context(): lid=db().execute("SELECT id FROM levels WHERE name='Colour Level'").fetchone()[0]
        self.client.post(f'/admin/levels/{lid}',data={'csrf_token':token,'name':'Colour Level renamed','description':'','is_active':'on','action':'save'})
        with app.app_context(): row=dict(db().execute("SELECT name,color,text_color FROM levels WHERE id=?",(lid,)).fetchone())
        self.assertEqual(row,{'name':'Colour Level renamed','color':'forest','text_color':'cream'})

    def test_login_rate_limit_is_shared_and_blocks_after_five_failures(self):
        for _ in range(5): self.assertEqual(self.client.post('/admin/login',data={'username':'admin','password':'wrong'}).status_code,200)
        other=app.test_client()
        res=other.post('/admin/login',data={'username':'admin','password':'test-password'})
        self.assertEqual(res.status_code,429); self.assertIn(b'Too many sign-in attempts',res.data)
        with app.app_context(): db().execute("DELETE FROM login_attempts"); db().commit()
        self.assertEqual(self.login().status_code,200)

    def test_wordle_easter_egg(self):
        import datetime
        from app import wordle_answer, wordle_words
        self.assertEqual(self.client.get('/api/wordle').status_code,404)
        self.assertNotIn(b'id="wordle"',self.client.get('/').data)
        with app.app_context(): db().execute("UPDATE users SET password_hash=?",(os.environ['ADMIN_PASSWORD_HASH'],)); db().execute("DELETE FROM login_attempts"); db().commit()
        self.assertIn(b'Course content',self.login().data); token=self.csrf()
        for front,back in [('dog','canis'),('fides','faith'),('house','domus'),('gift','donum'),('girls','puellae')]:
            self.client.post('/admin/lessons/1/flashcards',data={'csrf_token':token,'front':front,'back':back})
        self.client.post('/admin/wordle/settings',data={'csrf_token':token,'wordle_enabled':'on'})
        self.assertIn(b'id="wordle"',self.client.get('/').data)
        config=self.client.get('/api/wordle').get_json()
        medius=next(l for l in config['levels'] if l['letters']==5)
        with app.app_context():
            words=wordle_words(2)
            self.assertIn('fides',words); self.assertEqual(words['fides'][1],'faith')
            self.assertNotIn('faith',words); self.assertNotIn('girls',words); self.assertNotIn('house',words)
            level=dict(db().execute("SELECT * FROM wordle_levels WHERE id=?",(medius['id'],)).fetchone())
            today=datetime.datetime.now(datetime.timezone.utc).date()
            answer=wordle_answer(level,words,today)
        other=next(w for w in ['canis','domus','donum','fides'] if w!=answer)
        url=f"/api/wordle/check?level={medius['id']}&date={today.isoformat()}&guesses="
        res=self.client.get(url+'zzzzz'); self.assertEqual(res.get_json()['error'],'Not in the word list'); self.assertNotIn('rows',res.get_json())
        res=self.client.get(url+other).get_json(); self.assertFalse(res['finished']); self.assertNotIn('answer',res)
        res=self.client.get(url+f"{other},{answer}").get_json()
        self.assertTrue(res['solved']); self.assertEqual(res['rows'][1],['correct']*5); self.assertEqual(res['score']['points'],100+4*20)
        res=self.client.get(url+','.join([other]*6)).get_json()
        self.assertTrue(res['finished']); self.assertFalse(res['solved']); self.assertEqual(res['answer'],words[answer][0])
        greens=res['rows'][0].count('correct'); yellows=res['rows'][0].count('present')
        self.assertEqual(res['score']['points'],greens*8+yellows*3)
        self.assertEqual(self.client.get(f"/api/wordle/check?level={medius['id']}&date=2001-01-01&guesses=").status_code,400)
        # Anagramma: same levels, its own daily word
        with app.app_context(): ana=wordle_answer(level,words,today,'anagram')
        base=f"/api/wordle/anagram?level={medius['id']}&date={today.isoformat()}"
        puzzle=self.client.get(base).get_json()
        self.assertEqual(sorted(puzzle['letters']),sorted(ana.upper())); self.assertNotEqual(''.join(puzzle['letters']).lower(),ana)
        check=f"/api/wordle/anagram/check?level={medius['id']}&date={today.isoformat()}&attempts="
        wrong=''.join(puzzle['letters']).lower()
        self.assertEqual(self.client.get(check+'zzzzz').get_json()['error'],'Use the letters given')
        res=self.client.get(check+wrong).get_json()
        if 'error' not in res:   # skip when the jumble happens to be another Latin word
            self.assertEqual(res['wrong'],1); self.assertFalse(res['finished']); self.assertNotIn('answer',res)
            res=self.client.get(check+f"{wrong},{ana}").get_json()
            self.assertTrue(res['solved']); self.assertEqual(res['used'],2); self.assertEqual(res['score']['points'],100-10)
            res=self.client.get(check+','.join([wrong]*6)).get_json()
            self.assertTrue(res['finished']); self.assertFalse(res['solved']); self.assertEqual(res['score']['points'],0); self.assertEqual(res['answer'],words[ana][0])
        res=self.client.get(check+ana).get_json(); self.assertTrue(res['solved']); self.assertEqual(res['score']['points'],100)
        self.client.post('/admin/wordle/settings',data={'csrf_token':token})
        self.assertEqual(self.client.get('/api/wordle').status_code,404)
        self.assertEqual(self.client.get(base).status_code,404)

    def test_game_center(self):
        import datetime
        from app import wordle_words
        with app.app_context(): db().execute("UPDATE users SET password_hash=?",(os.environ['ADMIN_PASSWORD_HASH'],)); db().execute("DELETE FROM login_attempts"); db().commit()
        self.assertIn(b'Course content',self.login().data); token=self.csrf()
        self.client.post('/admin/wordle/settings',data={'csrf_token':token,'games_form':'1','wordle_enabled':'on','wordle_verbum':'on','wordle_anagram':'on'})
        page=self.client.get('/admin/games'); self.assertEqual(page.status_code,200)
        for text in (b'Game Center',b'Words from your cards',b'Extra words',b'Plan a word',b'Facilis'): self.assertIn(text,page.data)
        self.client.post('/admin/lessons/1/flashcards',data={'csrf_token':token,'front':'stella','back':'star'})
        with app.app_context():
            cid=db().execute("SELECT id FROM flashcards WHERE front='stella'").fetchone()[0]
            medius=dict(db().execute("SELECT * FROM wordle_levels WHERE name='Medius'").fetchone())
            self.assertIn('stella',wordle_words())   # Auto picks the Latin side
        # the admin can force the other side, then take the card out
        res=self.client.post(f'/admin/games/cards/{cid}',data={'side':'back'},headers={'X-CSRF-Token':token}).get_json()
        self.assertTrue(res['in_game']); self.assertEqual(res['word'],'star'); self.assertEqual(res['meaning'],'stella')
        with app.app_context(): words=wordle_words(); self.assertIn('star',words); self.assertNotIn('stella',words)
        self.client.post(f'/admin/games/cards/{cid}',data={'side':'none'},headers={'X-CSRF-Token':token})
        with app.app_context(): words=wordle_words(); self.assertNotIn('stella',words); self.assertNotIn('star',words)
        # level settings: grid size, source, points; values are kept in range
        self.client.post(f"/admin/games/levels/{medius['id']}",data={'csrf_token':token,'name':'Medius','letters':'99','tries':'7','max_course_level':'','is_active':'on','points_solved':'120','points_try':'15','points_green':'9','points_yellow':'4'})
        with app.app_context(): lv=dict(db().execute("SELECT * FROM wordle_levels WHERE id=?",(medius['id'],)).fetchone())
        self.assertEqual((lv['letters'],lv['tries'],lv['max_course_level'],lv['points_solved']),(8,7,None,120))
        self.client.post(f"/admin/games/levels/{medius['id']}",data={'csrf_token':token,'name':'Medius','letters':'5','tries':'6','max_course_level':'2','is_active':'on','points_solved':'100','points_try':'20','points_green':'8','points_yellow':'3'})
        # extra word, then plan it for today
        self.client.post('/admin/games/extra',data={'csrf_token':token,'word':'lūmen','meaning':'light'})
        with app.app_context(): self.assertEqual(wordle_words(2)['lumen'],('lūmen','light'))
        today=datetime.datetime.now(datetime.timezone.utc).date().isoformat()
        self.client.post('/admin/games/schedule',data={'csrf_token':token,'day':today,'game':'verbum','level_id':medius['id'],'word':'lumen'})
        res=self.client.get(f"/api/wordle/check?level={medius['id']}&date={today}&guesses=lumen").get_json()
        self.assertTrue(res['solved']); self.assertEqual(res['answer'],'lūmen'); self.assertEqual(res['meaning'],'light')
        bad=self.client.post('/admin/games/schedule',data={'csrf_token':token,'day':today,'game':'verbum','level_id':medius['id'],'word':'zzzzz'},follow_redirects=True)
        self.assertIn(b'is not one of',bad.data)
        # turning one game off hides only that game
        self.client.post('/admin/wordle/settings',data={'csrf_token':token,'games_form':'1','wordle_enabled':'on','wordle_verbum':'on'})
        self.assertEqual([g['id'] for g in self.client.get('/api/wordle').get_json()['games']],['verbum'])
        self.assertEqual(self.client.get(f"/api/wordle/anagram?level={medius['id']}&date={today}").status_code,404)
        # review all clears the "new" marks
        self.client.post('/admin/games/cards/review-all',data={'csrf_token':token})
        with app.app_context(): self.assertEqual(db().execute("SELECT count(*) FROM flashcards f LEFT JOIN wordle_card_choices c ON c.card_id=f.id WHERE c.card_id IS NULL").fetchone()[0],0)
        self.client.post('/admin/wordle/settings',data={'csrf_token':token,'games_form':'1','wordle_verbum':'on','wordle_anagram':'on'})
        self.assertEqual(self.client.get('/api/wordle').status_code,404)

    def test_backup_includes_games_and_local_dates_and_gzip(self):
        import datetime, gzip, io, json as js
        with app.app_context(): db().execute("UPDATE users SET password_hash=?",(os.environ['ADMIN_PASSWORD_HASH'],)); db().execute("DELETE FROM login_attempts"); db().commit()
        self.assertIn(b'Course content',self.login().data); token=self.csrf()
        self.client.post('/admin/wordle/settings',data={'csrf_token':token,'games_form':'1','wordle_enabled':'on','wordle_verbum':'on'})
        with app.app_context(): cid=db().execute("SELECT id FROM flashcards ORDER BY id LIMIT 1").fetchone()[0]; lid=db().execute("SELECT id FROM wordle_levels WHERE name='Facilis'").fetchone()[0]
        self.client.post(f'/admin/games/cards/{cid}',data={'side':'none'},headers={'X-CSRF-Token':token})
        self.client.post('/admin/games/extra',data={'csrf_token':token,'word':'nox','meaning':'night'})
        self.client.post(f'/admin/games/levels/{lid}',data={'csrf_token':token,'name':'Facilis','letters':'3','tries':'5','max_course_level':'1','is_active':'on','points_solved':'40','points_try':'10','points_green':'5','points_yellow':'2'})
        self.client.post('/admin/games/schedule',data={'csrf_token':token,'day':'2099-01-01','game':'verbum','level_id':lid,'word':'nox'})
        backup=js.loads(self.client.get('/admin/backup').data)
        self.assertEqual(backup['version'],2); g=backup['games']
        self.assertEqual(g['settings'],{'wordle_enabled':'1','wordle_verbum':'1','wordle_anagram':'0'})
        self.assertIn({'card_id':cid,'side':'none'},g['card_choices']); self.assertEqual(g['extra_words'][-1]['word'],'nox'); self.assertEqual(g['schedule'][-1]['word'],'nox')
        # change everything, then restore the backup: it all comes back
        self.client.post('/admin/wordle/settings',data={'csrf_token':token,'games_form':'1','wordle_verbum':'on','wordle_anagram':'on'})
        self.client.post(f'/admin/games/cards/{cid}',data={'side':'front'},headers={'X-CSRF-Token':token})
        self.client.post(f'/admin/games/levels/{lid}',data={'csrf_token':token,'name':'Changed','letters':'4','tries':'6','max_course_level':'1','is_active':'on','points_solved':'50','points_try':'10','points_green':'5','points_yellow':'2'})
        res=self.client.post('/admin/restore',data={'csrf_token':token,'backup':(io.BytesIO(js.dumps(backup).encode()),'b.json')},content_type='multipart/form-data',follow_redirects=True)
        self.assertIn(b'including the word games',res.data)
        with app.app_context():
            self.assertEqual(db().execute("SELECT side FROM wordle_card_choices WHERE card_id=?",(cid,)).fetchone()[0],'none')
            self.assertEqual(tuple(db().execute("SELECT name,letters,tries,points_solved FROM wordle_levels WHERE id=?",(lid,)).fetchone()),('Facilis',3,5,40))
            self.assertEqual(db().execute("SELECT word FROM wordle_schedule WHERE day='2099-01-01'").fetchone()[0],'nox')
            self.assertEqual(db().execute("SELECT value FROM settings WHERE key='wordle_anagram'").fetchone()[0],'0')
        # an older backup without games keeps the current card choices
        old=dict(backup); old.pop('games'); old['version']=1
        self.client.post(f'/admin/games/cards/{cid}',data={'side':'back'},headers={'X-CSRF-Token':token})
        self.client.post('/admin/restore',data={'csrf_token':token,'backup':(io.BytesIO(js.dumps(old).encode()),'b.json')},content_type='multipart/form-data')
        with app.app_context(): self.assertEqual(db().execute("SELECT side FROM wordle_card_choices WHERE card_id=?",(cid,)).fetchone()[0],'back')
        # dates follow the browser: today's words for a given day, and the puzzle number for the player's day
        today=datetime.datetime.now(datetime.timezone.utc).date(); yesterday=today-datetime.timedelta(days=1)
        words=self.client.get(f'/admin/games/today?date=2099-01-01').get_json()
        self.assertEqual(words['levels'][str(lid)]['verbum'],'nox')
        n1=self.client.get(f'/api/wordle?date={today}').get_json()['number']; n0=self.client.get(f'/api/wordle?date={yesterday}').get_json()['number']
        self.assertEqual(n1-n0,1)
        # pages are gzipped for browsers that accept it
        page=self.client.get('/admin/games',headers={'Accept-Encoding':'gzip'})
        self.assertEqual(page.headers.get('Content-Encoding'),'gzip'); self.assertIn(b'Game Center',gzip.decompress(page.data))
        self.assertIsNone(self.client.get('/admin/games').headers.get('Content-Encoding'))
        self.client.post(f'/admin/games/levels/{lid}',data={'csrf_token':token,'name':'Facilis','letters':'4','tries':'6','max_course_level':'1','is_active':'on','points_solved':'50','points_try':'10','points_green':'5','points_yellow':'2'})
        self.client.post('/admin/wordle/settings',data={'csrf_token':token,'games_form':'1','wordle_verbum':'on','wordle_anagram':'on'})

    def test_login_limit_per_visitor_behind_a_proxy(self):
        from werkzeug.middleware.proxy_fix import ProxyFix
        with app.app_context(): db().execute("DELETE FROM login_attempts"); db().commit()
        bad={'username':'admin','password':'wrong'}
        # without TRUSTED_PROXIES the forwarded header is ignored: faking it does not get round the limit
        for i in range(5): self.client.post('/admin/login',data=bad,headers={'X-Forwarded-For':f'9.9.9.{i}'})
        self.assertEqual(self.client.post('/admin/login',data=bad,headers={'X-Forwarded-For':'8.8.8.8'}).status_code,429)
        with app.app_context(): db().execute("DELETE FROM login_attempts"); db().commit()
        original=app.wsgi_app; app.wsgi_app=ProxyFix(original,x_for=1,x_proto=1)
        try:
            for _ in range(5): self.client.post('/admin/login',data=bad,headers={'X-Forwarded-For':'1.1.1.1'})
            self.assertEqual(self.client.post('/admin/login',data=bad,headers={'X-Forwarded-For':'1.1.1.1'}).status_code,429)
            self.assertEqual(self.client.post('/admin/login',data=bad,headers={'X-Forwarded-For':'2.2.2.2'}).status_code,200)
        finally:
            app.wsgi_app=original
            with app.app_context(): db().execute("DELETE FROM login_attempts"); db().commit()

if __name__=='__main__': unittest.main()
