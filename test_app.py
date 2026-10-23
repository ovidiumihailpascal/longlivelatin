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
        self.client.post('/admin/wordle/settings',data={'csrf_token':token})
        self.assertEqual(self.client.get('/api/wordle').status_code,404)

if __name__=='__main__': unittest.main()
