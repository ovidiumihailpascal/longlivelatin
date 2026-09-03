import os, tempfile, unittest, bcrypt

tmp=tempfile.NamedTemporaryFile(suffix='.db',delete=False); tmp.close()
os.environ['DATABASE_PATH']=tmp.name
os.environ['ADMIN_USERNAME']='admin'
os.environ['ADMIN_PASSWORD_HASH']=bcrypt.hashpw(b'test-password',bcrypt.gensalt()).decode()
os.environ['SECRET_KEY']='test-secret-key'
os.environ['COOKIE_SECURE']='false'
from app import app

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

if __name__=='__main__': unittest.main()
