import os
import io
import json
from typing import List, Dict, Any

import streamlit as st

# ------------------------------
# API Key
# ------------------------------
openai_key = st.sidebar.text_input(
    "OpenAI API Key",
    type="password",
    value=os.getenv("OPENAI_API_KEY", st.secrets.get("OPENAI_API_KEY", "")),
    key="openai_api_key_input"
)

# Optional deps
try:
    from docx import Document
except Exception:
    Document = None

try:
    import PyPDF2
except Exception:
    PyPDF2 = None

try:
    from jsonschema import validate as jsonschema_validate
except Exception:
    def jsonschema_validate(instance, schema):
        return True

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

# ------------------------------
# Streamlit UI Config
# ------------------------------
st.set_page_config(page_title="Hiperaktivist – Kullanıcı Analiz Sistemi", page_icon="🧩", layout="wide")
st.title("Hiperaktivist • Dış Sistem: Kullanıcı Analiz Motoru")
st.caption("20 soruya verilen yanıtları, Eğitim içeriği + Teknik & Yöntemler'e sadık kalarak tek parça sistem analizi üretir.")

# ------------------------------
# Helpers
# ------------------------------
def read_file(file) -> str:
    name = file.name.lower()
    if name.endswith(".txt") or name.endswith(".md"):
        return file.read().decode("utf-8", errors="ignore")
    if name.endswith(".docx"):
        if not Document:
            return "(python-docx yok – requirements'e ekleyin)"
        buf = io.BytesIO(file.read())
        doc = Document(buf)
        return "\n".join([p.text for p in doc.paragraphs])
    if name.endswith(".pdf"):
        if not PyPDF2:
            return "(PyPDF2 yok – requirements'e ekleyin)"
        buf = io.BytesIO(file.read())
        reader = PyPDF2.PdfReader(buf)
        pages = []
        for p in reader.pages:
            try:
                pages.append(p.extract_text() or "")
            except Exception:
                pages.append("")
        return "\n".join(pages)
    try:
        return file.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""

# ------------------------------
# JSON Schema (Simplified)
# ------------------------------
ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "meta": {
            "type": "object",
            "properties": {
                "education_title": {"type": "string"},
                "num_answers": {"type": "integer"},
                "language": {"type": "string"},
            },
            "required": ["education_title", "num_answers", "language"],
        },
        "ga_style_narrative": {"type": "string"},
        "safety_notes": {"type": "string"},
    },
    "required": ["meta", "ga_style_narrative"],
}

# ------------------------------
# Prompts
# ------------------------------
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

# JSON ŞEMA
{json_schema}
""".strip()

# ------------------------------
# Sidebar
# ------------------------------
st.sidebar.header("Ayarlar")
openai_key = st.sidebar.text_input(
    "OpenAI API Key",
    type="password",
    value=os.getenv("OPENAI_API_KEY", st.secrets.get("OPENAI_API_KEY", "")),
    key="openai_api_key_sidebar"
)
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
# Inputs
# ------------------------------
left, right = st.columns(2)
with left:
    q_file = st.file_uploader("Soru Seti (JSON)", type=["json"], key="qjson")
with right:
    edu_file = st.file_uploader("Eğitim Dosyası (docx/pdf/txt/md)", type=["docx", "pdf", "txt", "md"], key="edu")

ty_file = st.file_uploader("Teknik & Yöntemler (docx/pdf/txt/md)", type=["docx", "pdf", "txt", "md"], key="ty")

questions = []
q_meta = {}
if q_file:
    try:
        raw = json.loads(q_file.read().decode("utf-8"))
        questions = raw.get("questions", [])
        q_meta = raw.get("meta", {})
    except Exception as e:
        st.error(f"Soru JSON okunamadı: {e}")

# ------------------------------
# User Answers
# ------------------------------
st.markdown("---")
st.subheader("📝 Kullanıcı Yanıtları")
answers: List[Dict[str, Any]] = []
if questions:
    for i, q in enumerate(questions, start=1):
        qid = q.get("id", str(i))
        label = q.get("question", f"Soru {i}")
        ans = st.text_area(label, key=f"ans_{qid}", height=120)
        answers.append({"id": qid, "answer": ans})
else:
    st.info("Lütfen soru seti JSON'unu yükleyin.")

# ------------------------------
# Context Docs Preview
# ------------------------------
edu_text = ""
tech_text = ""
if edu_file:
    edu_text = read_file(edu_file)
if ty_file:
    tech_text = read_file(ty_file)

# ------------------------------
# LLM Helpers
# ------------------------------
def summarize_text(client, model: str, text: str, label: str) -> str:
    prompt = f"Metni 10-12 maddeyle kısa, öz ve bilgi kaybı olmadan özetle. Başlık: {label}.\n\nMetin:\n{text[:12000]}"
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Kısa ve bilgi kaybı olmadan özetleyen bir yardımcı yazarsın."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"(Özetlenemedi: {e})"

def generate_analysis(client, model: str, system_prompt: str, user_prompt: str, temperature: float = 0.3) -> Dict[str, Any]:
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    content = resp.choices[0].message.content
    try:
        data = json.loads(content)
    except Exception:
        data = {"raw": content}
    return data

# ------------------------------
# Generate
# ------------------------------
if st.button("🧠 Analizi Üret", type="primary"):
    if client and questions and any(a.get("answer") for a in answers) and (edu_text and tech_text):
        with st.spinner("Analiz hazırlanıyor…"):
            edu_summary = summarize_text(client, model, edu_text, "Eğitim Özeti")
            ty_summary = summarize_text(client, model, tech_text, "Teknik & Yöntemler Özeti")

            schema = ANALYSIS_SCHEMA.copy()

            system_prompt = SYSTEM_PROMPT
            user_prompt = USER_TEMPLATE.format(
                education_summary=edu_summary,
                techniques_summary=ty_summary,
                questions_json=json.dumps(questions, ensure_ascii=False),
                answers_json=json.dumps(answers, ensure_ascii=False),
                json_schema=json.dumps(schema, ensure_ascii=False),
            )

            data = generate_analysis(client, model, system_prompt, user_prompt, temperature)

            data.setdefault("meta", {})
            data["meta"].setdefault("education_title", q_meta.get("education_title", "Eğitim"))
            data["meta"]["num_answers"] = len([a for a in answers if a.get("answer")])
            data["meta"]["language"] = language

            st.session_state["analysis_data"] = data
    else:
        st.warning("Lütfen tüm dosyaları ve yanıtları girin.")

# ------------------------------
# Show Output
# ------------------------------
if st.session_state.get("analysis_data"):
    st.markdown("---")
    st.subheader("📎 Analiz Sonucu")
    data = st.session_state["analysis_data"]

    try:
        jsonschema_validate(data, ANALYSIS_SCHEMA)
    except Exception as e:
        st.warning(f"Şema doğrulaması uyarısı: {e}")

    meta = data.get("meta", {})
    st.write(f"**Eğitim:** {meta.get('education_title', 'Eğitim')} · **Yanıt sayısı:** {meta.get('num_answers', 0)}")

    st.text_area("GA Üslubunda Sistem Analizi", value=data.get("ga_style_narrative", ""), height=500)

    if data.get("safety_notes"):
        st.info(data.get("safety_notes"))

    pretty = json.dumps(data, ensure_ascii=False, indent=2)
    st.download_button("📥 analysis.json", data=pretty, file_name="analysis.json", mime="application/json")
