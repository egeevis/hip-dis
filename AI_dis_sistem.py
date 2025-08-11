import os
import io
import json
import streamlit as st

# ------------------------------
# API Key Ayarı
# ------------------------------
openai_key = st.sidebar.text_input(
    "OpenAI API Key",
    type="password",
    value=os.getenv("OPENAI_API_KEY", st.secrets.get("OPENAI_API_KEY", "")),
    key="openai_api_key_input"
)

try:
    from docx import Document
except Exception:
    Document = None

try:
    import PyPDF2
except Exception:
    PyPDF2 = None

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

st.set_page_config(page_title="Hiperaktivist – Kullanıcı Analiz Sistemi", page_icon="🧩", layout="wide")
st.title("Hiperaktivist • Dış Sistem: Kullanıcı Analiz Motoru")
st.caption("20 soruya verilen yanıtları, Eğitim içeriği + Teknik & Yöntemler'e sadık kalarak analiz eder.")

# ------------------------------
# Yardımcı Fonksiyonlar
# ------------------------------
def read_file(file) -> str:
    """Dosya formatına göre oku"""
    name = file.name.lower()
    if name.endswith(".txt") or name.endswith(".md"):
        return file.read().decode("utf-8", errors="ignore")
    if name.endswith(".docx"):
        if not Document:
            return "(python-docx eksik)"
        buf = io.BytesIO(file.read())
        doc = Document(buf)
        return "\n".join([p.text for p in doc.paragraphs])
    if name.endswith(".pdf"):
        if not PyPDF2:
            return "(PyPDF2 eksik)"
        buf = io.BytesIO(file.read())
        reader = PyPDF2.PdfReader(buf)
        return "\n".join([p.extract_text() or "" for p in reader.pages])
    try:
        return file.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""

SYSTEM_PROMPT = """
Sen, Hiperaktivist markasının sunduğu kişisel gelişim eğitimleri için özel olarak geliştirilmiş bir "Kullanıcı Yanıtları Analiz Uzmanı"sın.

Görevin:
- Kullanıcının verdiği cevapları analiz ederken sadece yukarıda verilen "Eğitim Dosyası" ve "Teknik & Yöntemler" içeriğini bilgi kaynağı olarak kullan.
- Eğitim dosyasındaki bilgilerden beslenerek yorum yap.
- Analizi oluştururken, Teknik & Yöntemler dosyasındaki yaklaşımları temel al.
- Eğitim veya teknik/yöntemler dosyasında geçmeyen kavramlar, yöntemler veya çıkarımlar ekleme.
- Çıktı tek bir akıcı metin olacak; başlık, madde listesi veya numaralandırma olmayacak.
- Anlatım empatik, yargısız, profesyonel ve kullanıcıya özel olacak.
""".strip()

USER_TEMPLATE = """
# EĞİTİM DOSYASI
{education_full}

# TEKNİK & YÖNTEMLER
{techniques_full}

# SORULAR
{questions_json}

# KULLANICI YANITLARI
{answers_json}
""".strip()

# ------------------------------
# Sidebar Ayarları
# ------------------------------
st.sidebar.header("Ayarlar")
model = st.sidebar.text_input("Model", value="gpt-4o-mini")
language = st.sidebar.selectbox("Dil", ["Türkçe", "English"], index=0)
temperature = st.sidebar.slider("Temperature", 0.0, 1.0, 0.3, 0.05)

client = None
if openai_key and OpenAI:
    try:
        client = OpenAI(api_key=openai_key)
    except Exception as e:
        st.sidebar.error(f"OpenAI istemcisi başlatılamadı: {e}")

# ------------------------------
# Dosya Yüklemeler
# ------------------------------
left, right = st.columns(2)
with left:
    q_file = st.file_uploader("Soru Seti (JSON)", type=["json"], key="qjson")
with right:
    a_file = st.file_uploader("Kullanıcı Yanıtları (JSON)", type=["json"], key="ajson")

edu_file = st.file_uploader("Eğitim Dosyası", type=["docx", "pdf", "txt", "md"], key="edu")
ty_file = st.file_uploader("Teknik & Yöntemler", type=["docx", "pdf", "txt", "md"], key="ty")

questions, answers = [], []
if q_file:
    try:
        raw = json.loads(q_file.read().decode("utf-8"))
        questions = raw.get("questions", [])
    except Exception as e:
        st.error(f"Soru JSON okunamadı: {e}")

if a_file:
    try:
        answers = json.loads(a_file.read().decode("utf-8"))
    except Exception as e:
        st.error(f"Cevaplar JSON okunamadı: {e}")

# Elle giriş
if not a_file and questions:
    st.markdown("---")
    st.subheader("📝 Kullanıcı Yanıtları (manuel)")
    for i, q in enumerate(questions, start=1):
        qid = q.get("id", str(i))
        label = q.get("question", f"Soru {i}")
        ans = st.text_area(label, key=f"ans_{qid}", height=120)
        answers.append({"id": qid, "answer": ans})

# ------------------------------
# Eğitim ve Teknik metinleri oku
# ------------------------------
edu_text, tech_text = "", ""
if edu_file:
    edu_text = read_file(edu_file)
if ty_file:
    tech_text = read_file(ty_file)

# DEBUG: Yüklenen dosyaların ilk 500 karakterini göster
if edu_text:
    st.info(f"📘 Eğitim Dosyası (ilk 500 karakter):\n{edu_text[:500]}")
if tech_text:
    st.info(f"🛠 Teknik & Yöntemler Dosyası (ilk 500 karakter):\n{tech_text[:500]}")

# ------------------------------
# LLM Fonksiyonları
# ------------------------------
def generate_analysis(client, model: str, system_prompt: str, user_prompt: str, temperature: float = 0.3) -> str:
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
    )
    return resp.choices[0].message.content.strip()

# ------------------------------
# Analiz Üret
# ------------------------------
if st.button("🧠 Analizi Üret", type="primary"):
    if not client:
        st.error("OpenAI API anahtarı gerekli")
    elif not (edu_text and tech_text and any(a.get('answer') for a in answers)):
        st.error("Eğitim + Teknik & Yöntemler dosyaları ve en az bir cevap gerekli")
    else:
        with st.spinner("Analiz hazırlanıyor…"):
            user_prompt = USER_TEMPLATE.format(
                education_full=edu_text,
                techniques_full=tech_text,
                questions_json=json.dumps(questions, ensure_ascii=False),
                answers_json=json.dumps(answers, ensure_ascii=False),
            )
            analysis_text = generate_analysis(client, model, SYSTEM_PROMPT, user_prompt, temperature)
            st.session_state["analysis_text"] = analysis_text

# ------------------------------
# Çıktı
# ------------------------------
if st.session_state.get("analysis_text"):
    st.markdown("---")
    st.subheader("📎 Analiz Sonucu")
    st.text_area("Analiz Metni", value=st.session_state["analysis_text"], height=500)
    st.download_button("📥 analysis.txt", data=st.session_state["analysis_text"], file_name="analysis.txt", mime="text/plain")
