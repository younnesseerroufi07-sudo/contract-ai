# ================== CONTRACTAI SaaS - ALL IN ONE ==================
# التشغيل: pip install fastapi uvicorn python-multipart openai stripe pypdf python-docx passlib python-jose
# ثم: python app.py
# الموقع غادي يخدم على: http://localhost:8000

import os, io, json, stripe, openai
from datetime import datetime, timedelta
from fastapi import FastAPI, UploadFile, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr
from jose import jwt
from passlib.context import CryptContext
from pypdf import PdfReader
from docx import Document

# ========== 1. الإعدادات ==========
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

OPENAI_API_KEY = "sk-proj-HOT-KEY-DYALK" # حط المفتاح ديالك هنا
STRIPE_SECRET_KEY = "sk_test-KEY-DYALK" # حط مفتاح Stripe Test هنا
JWT_SECRET = "secret-key-123456789"

openai.api_key = OPENAI_API_KEY
stripe.api_key = STRIPE_SECRET_KEY
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
fake_db = {} # قاعدة البيانات

# ========== 2. الواجهة HTML كاملة ==========
HTML_PAGE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ContractAI - تحليل العقود</title>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;700&display=swap" rel="stylesheet">
<style>body{font-family:'Cairo',sans-serif}</style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen">
<header class="border-b border-slate-800 p-4 flex justify-between">
  <h1 class="font-bold text-indigo-400">ContractAI</h1>
  <div id="auth-btns"></div>
</header>
<main class="max-w-2xl mx-auto p-8">
  <h2 class="text-3xl font-bold text-center mb-2">حلل عقدك في 10 ثواني</h2>
  <p class="text-center text-slate-400 mb-8">30 يوم تجربة مجانية. بعدها 2000€/سنة</p>

  <div id="login-box" class="bg-slate-900 p-6 rounded-2xl mb-6">
    <h3 class="font-bold mb-3">تسجيل / دخول</h3>
    <input id="email" placeholder="email@company.com" class="w-full p-2 mb-2 bg-slate-800 rounded">
    <input id="password" type="password" placeholder="كلمة السر" class="w-full p-2 mb-2 bg-slate-800 rounded">
    <input id="company" placeholder="اسم الشركة" class="w-full p-2 mb-3 bg-slate-800 rounded">
    <button onclick="register()" class="w-full bg-indigo-600 py-2 rounded">تسجيل + بدء التجربة</button>
    <button onclick="login()" class="w-full bg-slate-700 py-2 rounded mt-2">دخول</button>
  </div>

  <div id="app-box" class="hidden bg-slate-900 p-6 rounded-2xl">
    <form id="uploadForm">
      <input type="file" id="file" accept=".pdf,.docx,.txt" class="mb-4">
      <button class="w-full bg-indigo-600 py-3 rounded">تحليل العقد</button>
    </form>
    <button onclick="pay()" class="w-full bg-green-600 py-3 rounded mt-3">اشترك 2000€/سنة</button>
    <div id="result" class="mt-6 hidden bg-slate-950 p-4 rounded"></div>
  </div>
</main>
<script>
let TOKEN = localStorage.getItem('token');
function showApp(){document.getElementById('login-box').classList.add('hidden');document.getElementById('app-box').classList.remove('hidden')}
if(TOKEN) showApp();

async function register(){
  const res = await fetch('/api/auth/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:email.value,password:password.value,company_name:company.value})});
  const data = await res.json(); TOKEN=data.access_token; localStorage.setItem('token',TOKEN); showApp();
}
async function login(){
  const res = await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:email.value,password:password.value})});
  const data = await res.json(); TOKEN=data.access_token; localStorage.setItem('token',TOKEN); showApp();
}
async function pay(){
  const res = await fetch('/api/stripe/create-checkout',{method:'POST',body:new FormData().append('email',JSON.parse(atob(TOKEN.split('.')[1])).sub)});
  const data = await res.json(); window.location.href=data.url;
}
document.getElementById('uploadForm').onsubmit=async(e)=>{
  e.preventDefault(); const fd=new FormData(); fd.append('contractFile',file.files[0]); fd.append('token',TOKEN);
  const res=await fetch('/api/contracts/analyze-contract',{method:'POST',body:fd}); const data=await res.json();
  result.innerHTML=`<b>النوع:</b>${data.analysis.contract_type}<br><b>المخاطر:</b>${data.analysis.risk_score}/100<br><b>الملخص:</b>${data.analysis.summary}`; result.classList.remove('hidden');
}
</script></body></html>
"""

# ========== 3. دوال السيرفر ==========
def create_token(email): return jwt.encode({"sub":email,"exp":datetime.utcnow()+timedelta(days=7)},JWT_SECRET)
def check_sub(user):
    if user["plan"]=="TRIAL" and datetime.utcnow()>user["trial_ends"]: raise HTTPException(402,"انتهت التجربة. ادفع 2000€")
    if user["plan"]=="FREE": raise HTTPException(402,"يجب الاشتراك")
async def get_text(f:UploadFile):
    c=await f.read()
    if f.filename.endswith('.pdf'): return "\n".join([p.extract_text() or "" for p in PdfReader(io.BytesIO(c)).pages])
    if f.filename.endswith('.docx'): return "\n".join([p.text for p in Document(io.BytesIO(c)).paragraphs])
    return c.decode()

# ========== 4. الـ Routes ==========
@app.get("/", response_class=HTMLResponse)
def home(): return HTML_PAGE

@app.post("/api/auth/register")
def register(data:dict):
    if data["email"] in fake_db: raise HTTPException(400,"موجود")
    fake_db[data["email"]]={"pw":pwd_context.hash(data["password"]),"plan":"TRIAL","trial_ends":datetime.utcnow()+timedelta(days=30)}
    return {"access_token":create_token(data["email"])}

@app.post("/api/auth/login")
def login(data:dict):
    u=fake_db.get(data["email"])
    if not u or not pwd_context.verify(data["password"],u["pw"]): raise HTTPException(401,"خطأ")
    return {"access_token":create_token(data["email"])}

@app.post("/api/stripe/create-checkout")
def checkout(email:str=Form(...)):
    fake_db[email]["plan"]="BUSINESS" # محاكاة الدفع
    return {"url":"https://checkout.stripe.com/test"}

@app.post("/api/contracts/analyze-contract")
async def analyze(contractFile:UploadFile, token:str=Form(...)):
    email=jwt.decode(token,JWT_SECRET,algorithms=["HS256"])["sub"]
    user=fake_db[email]; check_sub(user)
    text=await get_text(contractFile)
    res=openai.chat.completions.create(model="gpt-4o",response_format={"type":"json_object"},messages=[{"role":"user","content":f"حلل: {text[:4000]}"}])
    return {"analysis":json.loads(res.choices[0].message.content)}

# ========== 5. التشغيل ==========
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
