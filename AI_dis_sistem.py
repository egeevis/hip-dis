import os
import io
import json
from typing import List, Dict, Any

import streamlit as st

openai_key = st.sidebar.text_input(
    "OpenAI API Key",
    type="password",
    value=os.getenv("OPENAI_API_KEY", st.secrets.get("OPENAI_API_KEY", "")),
    key="openai_api_key_input"
)



# Optional deps (add to requirements.txt):
# streamlit
# python-docx
# PyPDF2
# openai>=1.30.0
# jsonschema

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

st.set_page_config(page_title="Hiperaktivist – Kullanıcı Analiz Sistemi", page_icon="🧩", layout="wide")
st.title("Hiperaktivist • Dış Sistem: Kullanıcı Analiz Motoru")
st.caption("20 soruya verilen yanıtları, Eğitim içeriği + Teknik & Yöntemler'e sadık kalarak analiz eder.")

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

ANALYSIS_SCHEMA: Dict[str, Any] = {
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
        "themes": {"type": "array", "items": {"type": "string"}},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "growth_areas": {"type": "array", "items": {"type": "string"}},
        "micro_actions": {"type": "array", "items": {"type": "string"}},
        "ga_style_narrative": {"type": "string"},
        "safety_notes": {"type": "string"},
    },
    "required": ["meta", "themes", "strengths", "growth_areas", "micro_actions", "ga_style_narrative"],
}

SYSTEM_PROMPT = """
Sen, Hiperaktivist markasının sunduğu kişisel gelişim eğitimleri için özel olarak geliştirilmiş Dış Sistem analiz yapay zekâsısın.

Amacın:
- Kullanıcının 20 soruya verdiği yanıtları, ilgili eğitim içeriği ve GA'nın Teknik & Yöntemleri doğrultusunda işleyerek derin, kişisel ve anlamlı bir gelişim analizi sunmak.
- Çıktı tek parça, akıcı ve zengin bir metin olmalı. Madde listeleri yerine, bütünlüklü bir anlatım içinde kişisel gözlemler, duygusal farkındalık, eğitimden gelen ana fikirler ve uygulanabilir öneriler harmanlanmalı.
- Metin GA metodolojisine sadık, yargısız, empatik, güvenli ve profesyonel bir üslupta olmalı.
- Nihai hedef, kullanıcının eğitimden aldığı değeri günlük yaşamına entegre edebilmesini kolaylaştırmaktır.

Kurallar:
- Kesinlikle “temalar, güçlü alanlar, gelişim alanları” gibi başlıklar verme.
- Metin, kullanıcı yanıtlarındaki ipuçlarını doğrudan yansıtsın, kişiselleştirilmiş hissettirsin.
- Uygulanabilir öneriler metnin içine doğal biçimde yedirilsin.
- Gerekiyorsa güvenlik / kriz uyarılarını metnin sonunda ekle.
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
# Sidebar settings
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
max_actions = st.sidebar.slider("Mikro eylem sayısı", 3, 10, 5)
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

# Render dynamic form
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
    st.info("Lütfen soru seti JSON'unu yükleyin (ör. sorular_1.json).")

# Show previews for context docs
edu_text = ""
tech_text = ""
if edu_file:
    edu_text = read_file(edu_file)
    with st.expander("Eğitim Metni (önizleme)", expanded=False):
        st.text_area("Eğitim metni önizleme", value=edu_text[:6000], height=200, label_visibility="collapsed")
if ty_file:
    tech_text = read_file(ty_file)
    with st.expander("Teknik & Yöntemler (önizleme)", expanded=False):
        st.text_area("Teknik & Yöntemler önizleme", value=tech_text[:6000], height=200, label_visibility="collapsed")

# ------------------------------
# LLM helpers
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
c1, c2, c3 = st.columns([1.2,1,1])
with c1:
    can_generate = client and questions and any(a.get("answer") for a in answers) and (edu_text and tech_text)
    if st.button("🧠 Analizi Üret", type="primary", use_container_width=True, disabled=not can_generate):
        with st.spinner("Analiz hazırlanıyor…"):
            edu_summary = summarize_text(client, model, edu_text, "Eğitim Özeti")
            ty_summary = summarize_text(client, model, tech_text, "Teknik & Yöntemler Özeti")

            # Trim micro action count in schema hint (model uses it in narrative)
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

            # Attach meta
            data.setdefault("meta", {})
            data["meta"].setdefault("education_title", q_meta.get("education_title", "Eğitim"))
            data["meta"]["num_answers"] = len([a for a in answers if a.get("answer")])
            data["meta"]["language"] = language

            st.session_state["analysis_data"] = data
            st.session_state["analysis_text"] = None

with c2:
    if st.session_state.get("analysis_data"):
        if st.button("⬇️ JSON indir", use_container_width=True):
            st.download_button(
                "İndir (analysis.json)",
                data=json.dumps(st.session_state["analysis_data"], ensure_ascii=False, indent=2),
                file_name="analysis.json",
                mime="application/json",
            )
with c3:
    pass

# ------------------------------
# Show output
# ------------------------------
if st.session_state.get("analysis_data"):
    st.markdown("---")
    st.subheader("📎 Analiz Sonucu")
    data = st.session_state["analysis_data"]

    # Validate (best-effort)
    try:
        jsonschema_validate(data, ANALYSIS_SCHEMA)
    except Exception as e:
        st.warning(f"Şema doğrulaması uyarısı: {e}")

    # Render
    meta = data.get("meta", {})
    st.write(f"**Eğitim:** {meta.get('education_title', 'Eğitim')} · **Yanıt sayısı:** {meta.get('num_answers', 0)}")

    cols = st.columns(3)
    with cols[0]:
        st.markdown("**Temalar**")
        for t in data.get("themes", []):
            st.write("•", t)
    with cols[1]:
        st.markdown("**Güçlü Alanlar**")
        for t in data.get("strengths", []):
            st.write("•", t)
    with cols[2]:
        st.markdown("**Gelişim Alanları**")
        for t in data.get("growth_areas", []):
            st.write("•", t)

    st.markdown("**Mikro Eylemler (öneri)**")
    for i, a in enumerate(data.get("micro_actions", []), start=1):
        st.write(f"{i}. {a}")

    st.markdown("**GA Üslubunda Anlatı**")
    st.text_area("Anlatı", value=data.get("ga_style_narrative", ""), height=300)

    if data.get("safety_notes"):
        st.info(data.get("safety_notes"))

    # Exports
    export_cols = st.columns(2)
    with export_cols[0]:
        pretty = json.dumps(data, ensure_ascii=False, indent=2)
        st.download_button("📥 analysis.json", data=pretty, file_name="analysis.json", mime="application/json")
    with export_cols[1]:
        md = [
            f"# {meta.get('education_title','Eğitim')} – Kişisel Analiz",
            "## Temalar",
            *[f"- {t}" for t in data.get("themes", [])],
            "\n## Güçlü Alanlar",
            *[f"- {t}" for t in data.get("strengths", [])],
            "\n## Gelişim Alanları",
            *[f"- {t}" for t in data.get("growth_areas", [])],
            "\n## Mikro Eylemler",
            *[f"- {t}" for t in data.get("micro_actions", [])],
            "\n## GA Üslubunda Anlatı\n",
            data.get("ga_style_narrative", ""),
            "\n\n---\nOtomatik üretildi: Hiperaktivist Analiz Sistemi",
        ]
        md_text = "\n".join(md)
        st.download_button("📝 Markdown indir", data=md_text, file_name="analysis.md", mime="text/markdown")

# ------------------------------
# Footer
# ------------------------------
st.markdown(
    """
---
**Kullanım Akışı:**  
1) İç sistemden ürettiğiniz `sorular_*.json` dosyasını yükleyin.  
2) Eğitime ait `Eğitim` ve `Teknik & Yöntemler` dosyalarını yükleyin.  
3) Kullanıcı yanıtlarını girin / yapıştırın.  
4) **Analizi Üret** düğmesine tıklayın; JSON ve Markdown çıktıları indirin.

**Notlar**  
• Çıktı GA üslubuna ve dokümanlarınıza sadık kalarak üretilir.  
• JSON şeması sayesinde raporlarınız tutarlı yapıdadır.  
• Gerekirse `analysis.json` içinden müşteri raporu PDF’leri üretebilirsiniz (ayrı bir adımda).
"""
)
