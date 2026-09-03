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

if __name__=='__main__': unittest.main()
