import os
import io
import json
from typing import List, Dict, Any
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
- Kullanıcının 20 soruya verdiği yanıtları dikkatle inceleyip, **Eğitim Özeti** ve **Teknik & Yöntemler Özeti** bölümlerinde verilen bilgiler doğrultusunda bütünlüklü, kişiselleştirilmiş ve anlamlı bir gelişim analizi sunmak.
- Analiz yaparken **mutlaka Eğitim Özeti ve Teknik & Yöntemler Özeti'ne sadık kal**. Bu içeriklerin dışında varsayımlarda bulunma veya bağlam dışı yorum yapma.
- Çıktı TEK BİR uzun metin olacak, başlık veya madde listesi olmayacak.
- Anlatım akıcı, empatik, yargısız ve profesyonel olmalı.
- Kullanıcının yanıtlarındaki duygusal ton, ihtiyaçlar, farkındalıklar ve olası zorluklar analiz içinde doğal biçimde yer almalı.
- Analizde, eğitimde verilen bilgiler ile kullanıcının mevcut durumunu eşleştirerek yorum yap.
- Gerekiyorsa güvenlik / kriz uyarılarını metnin sonunda ekle.
- Nihai hedef, kullanıcının eğitimden aldığı değeri günlük yaşamına entegre edebilmesini kolaylaştırmaktır.
""".strip()

USER_TEMPLATE = """
# EĞİTİM ÖZETİ
{education_summary}

# TEKNİK & YÖNTEMLER ÖZETİ
{techniques_summary}

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

edu_file = st.file_uploader("Eğitim Dosyası (docx/pdf/txt/md)", type=["docx", "pdf", "txt", "md"], key="edu")
ty_file = st.file_uploader("Teknik & Yöntemler (docx/pdf/txt/md)", type=["docx", "pdf", "txt", "md"], key="ty")

questions, q_meta, answers = [], {}, []
if q_file:
    try:
        raw = json.loads(q_file.read().decode("utf-8"))
        questions = raw.get("questions", [])
        q_meta = raw.get("meta", {})
    except Exception as e:
        st.error(f"Soru JSON okunamadı: {e}")

if a_file:
    try:
        answers = json.loads(a_file.read().decode("utf-8"))
    except Exception as e:
        st.error(f"Cevaplar JSON okunamadı: {e}")

# Eğer cevap dosyası yüklenmediyse elle girme
if not a_file and questions:
    st.markdown("---")
    st.subheader("📝 Kullanıcı Yanıtları (manuel)")
    for i, q in enumerate(questions, start=1):
        qid = q.get("id", str(i))
        label = q.get("question", f"Soru {i}")
        ans = st.text_area(label, key=f"ans_{qid}", height=120)
        answers.append({"id": qid, "answer": ans})

# ------------------------------
# Önizlemeler
# ------------------------------
edu_text, tech_text = "", ""
if edu_file:
    edu_text = read_file(edu_file)
if ty_file:
    tech_text = read_file(ty_file)

# ------------------------------
# LLM Fonksiyonları
# ------------------------------
def summarize_text(client, model: str, text: str, label: str) -> str:
    prompt = f"Metni 10-12 maddeyle kısa, öz ve bilgi kaybı olmadan özetle. Başlık: {label}.\n\nMetin:\n{text[:12000]}"
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Kısa ve bilgi kaybı olmadan özetleyen bir yardımcı yazarsın."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()

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
# ------------------------------
if st.button("🧠 Analizi Üret", type="primary"):
    TEST_MODE = True  # Test modu açık/kapalı

    if not client:
        st.error("OpenAI API anahtarı gerekli")

    elif not (
        any(a.get('answer') for a in answers) and
        (TEST_MODE or (edu_text and tech_text and questions))
    ):
        if TEST_MODE:
            st.warning("⚠ Test modu aktif: Sadece cevaplar.json yüklendi.")
        else:
            st.error("Tüm gerekli dosyalar yüklenmeli ve en az bir cevap girilmeli.")

    else:
        with st.spinner("Analiz hazırlanıyor…"):
            edu_summary = summarize_text(client, model, edu_text, "Eğitim Özeti") if edu_text else ""
            ty_summary = summarize_text(client, model, tech_text, "Teknik & Yöntemler Özeti") if tech_text else ""

            user_prompt = USER_TEMPLATE.format(
                education_summary=edu_summary,
                techniques_summary=ty_summary,
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

